#!/usr/bin/env python3
"""
SET Dividend + Technical + Fundamental Screener
หาหุ้นปันผลคุณภาพในตลาดไทย จับจังหวะเข้าด้วยสัญญาณเทคนิค และกรองด้วยงบการเงิน

ดึงข้อมูล: yfinance (ราคา/ปันผล/งบ) | อินดิเคเตอร์: คำนวณเอง
สัญญาณ: RSI bullish & bearish divergence, oversold, ย่อในขาขึ้น, แนวรับ, MACD
งบ: payout ratio, ROE, D/E, margin, การเติบโตกำไร -> เกรดสุขภาพ + เตือน dividend trap
ผลลัพธ์: dashboard (กราฟแบบ TradingView) + ตารางในเทอร์มินัล
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

TICKERS = [
    "PTT", "PTTEP", "PTTGC", "TOP", "IRPC", "BCP", "OR", "BANPU",
    "EGCO", "RATCH", "GULF", "GPSC", "BGRIM", "EA",
    "ADVANC", "TRUE", "KBANK", "SCB", "BBL", "KTB", "TTB", "KKP", "TISCO",
    "KTC", "SAWAD", "MTC", "AOT", "BEM", "BTS", "BDMS", "BH",
    "CPALL", "CPAXT", "CPF", "CPN", "CRC", "HMPRO", "GLOBAL", "COM7", "BJC",
    "MINT", "CENTEL", "OSP", "CBG", "TU", "SCC", "SCGP", "IVL", "DELTA",
    "KCE", "HANA", "WHA", "AWC", "LH", "AP", "SPALI",
]


# ---------- อินดิเคเตอร์ ----------
def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def macd(close, fast=12, slow=26, signal=9):
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig, line - sig


def bollinger(close, n=20, k=2):
    ma = close.rolling(n).mean()
    sd = close.rolling(n).std()
    return ma, ma + k * sd, ma - k * sd


# ---------- divergence (ทั้งกระทิงและหมี) ----------
def _pivots(vals, left, right, kind):
    out = []
    n = len(vals)
    for i in range(left, n - right):
        seg = vals[i - left:i + right + 1]
        if (kind == "low" and vals[i] == seg.min()) or (kind == "high" and vals[i] == seg.max()):
            out.append(i)
    return out


def detect_bull_div(low, r, left=5, right=5, lookback=70):
    lows, rsis = low.values, r.values
    idx = [i for i in _pivots(lows, left, right, "low") if i >= len(lows) - lookback]
    if len(idx) < 2:
        return False, None
    i1, i2 = idx[-2], idx[-1]
    if lows[i2] < lows[i1] and rsis[i2] > rsis[i1]:   # ราคา Lower Low, RSI Higher Low
        return True, i2
    return False, None


def detect_bear_div(high, r, left=5, right=5, lookback=70):
    highs, rsis = high.values, r.values
    idx = [i for i in _pivots(highs, left, right, "high") if i >= len(highs) - lookback]
    if len(idx) < 2:
        return False, None
    i1, i2 = idx[-2], idx[-1]
    if highs[i2] > highs[i1] and rsis[i2] < rsis[i1]:  # ราคา Higher High, RSI Lower High
        return True, i2
    return False, None


# ---------- งบการเงิน ----------
FUND_FIELDS = ["payoutRatio", "returnOnEquity", "debtToEquity", "profitMargins",
               "trailingPE", "priceToBook", "earningsGrowth", "revenueGrowth"]


def _one_fund(tq):
    try:
        info = yf.Ticker(tq).info
        return tq, {f: info.get(f) for f in FUND_FIELDS}
    except Exception:
        return tq, {}


def fetch_fundamentals(yq):
    out = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for tq, d in ex.map(_one_fund, yq):
            out[tq] = d
    return out


def grade_financials(f):
    """คืน (label, สี, เหตุผล[], คะแนนงบ) — None ถ้าไม่มีข้อมูล"""
    payout, roe = f.get("payoutRatio"), f.get("returnOnEquity")
    margin, epsg = f.get("profitMargins"), f.get("earningsGrowth")
    pts, have, reasons = 0, 0, []
    if payout is not None:
        have += 1
        if payout < 0:
            pts -= 1; reasons.append("payout ติดลบ")
        elif payout <= 0.7:
            pts += 1
        elif payout > 1.0:
            pts -= 2; reasons.append(f"จ่ายปันผล {payout*100:.0f}% เกินกำไร")
    if roe is not None:
        have += 1
        if roe >= 0.12:
            pts += 1
        elif roe < 0.05:
            pts -= 1
    if margin is not None:
        have += 1
        if margin < 0:
            pts -= 2; reasons.append("ขาดทุน (margin ติดลบ)")
        elif margin >= 0.10:
            pts += 1
    if epsg is not None:
        have += 1
        if epsg <= -0.15:
            pts -= 2; reasons.append(f"กำไรหด {epsg*100:.0f}%")
        elif epsg > 0:
            pts += 1
    if have == 0:
        return ("n/a", "#3a3f4b", [], None)
    if pts >= 2:
        return ("แข็งแรง", "#0b6e4f", reasons, pts)
    if pts >= 0:
        return ("พอใช้", "#5a4a1f", reasons, pts)
    return ("อ่อนแอ", "#7a2e2e", reasons, pts)


def pct(v, mul=100):
    return None if v is None else round(v * mul, 1)


# ---------- วิเคราะห์หุ้น 1 ตัว ----------
def analyze(ticker, df, fund):
    df = df.dropna(how="all")
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    if len(df) < 60:
        return None

    close, low, high = df["Close"].astype(float), df["Low"].astype(float), df["High"].astype(float)
    price = float(close.iloc[-1])
    if not np.isfinite(price) or price <= 0:
        return None

    div = df["Dividends"].fillna(0) if "Dividends" in df else pd.Series(0, index=df.index)
    cutoff = df.index[-1] - pd.Timedelta(days=365)
    div_1y = float(div[div.index >= cutoff].sum())
    dyield = div_1y / price * 100

    r = rsi(close)
    rsi_now = float(r.iloc[-1])
    ema50, ema200 = ema(close, 50), ema(close, 200)
    _, _, bb_low = bollinger(close)
    macd_line, macd_sig, _ = macd(close)
    e50, e200 = float(ema50.iloc[-1]), float(ema200.iloc[-1])
    bbl = float(bb_low.iloc[-1]) if np.isfinite(bb_low.iloc[-1]) else price
    uptrend = price > e200
    low52 = float(low.tail(252).min())
    bull_div, bull_idx = detect_bull_div(low, r)
    bear_div, bear_idx = detect_bear_div(high, r)

    fg_label, fg_color, fg_reasons, fg_pts = grade_financials(fund)
    payout = fund.get("payoutRatio")
    epsg = fund.get("earningsGrowth")
    margin = fund.get("profitMargins")
    trap = dyield >= 4 and ((payout or 0) > 1.0 or (epsg is not None and epsg <= -0.2)
                            or (margin is not None and margin < 0))

    # ---------- คะแนนจังหวะเข้า ----------
    score, reasons = 0.0, []
    if 3 <= dyield <= 12:
        score += min(20, dyield * 2); reasons.append(f"ปันผล {dyield:.1f}%")
    elif dyield > 12:
        reasons.append(f"⚠ ปันผล {dyield:.1f}% สูงผิดปกติ")
    elif dyield > 0:
        reasons.append(f"ปันผล {dyield:.1f}%")
    if rsi_now < 35:
        score += 20; reasons.append(f"RSI oversold ({rsi_now:.0f})")
    if bull_div:
        score += 30; reasons.append("🟢 Bullish Divergence")
    if price < bbl:
        score += 15; reasons.append("หลุดกรอบล่าง BB")
    if uptrend and price <= e50 * 1.02:
        score += 20; reasons.append("ย่อในขาขึ้น (EMA50)")
    if price <= low52 * 1.10:
        score += 15; reasons.append("ใกล้ Low 52 สัปดาห์")
    if bool(macd_line.iloc[-1] > macd_sig.iloc[-1] and macd_line.iloc[-2] <= macd_sig.iloc[-2]):
        score += 10; reasons.append("MACD ตัดขึ้น")
    # ตัวหักลบ / เตือน
    if bear_div:
        score -= 20; reasons.append("🔴 Bearish Divergence (ระวังกลับหัว)")
    if trap:
        score -= 15; reasons.append("⚠ เสี่ยง dividend trap")
    if fg_pts is not None and fg_pts < 0:
        score -= 10
        for x in fg_reasons:
            reasons.append("⚠ " + x)
    score = round(max(0, min(score, 100)), 0)

    # ---------- ข้อมูลกราฟ ----------
    tail = df.tail(300)
    e50t, e200t = ema50.tail(300), ema200.tail(300)
    candles, l50, l200 = [], [], []
    for ts, row in tail.iterrows():
        o, h, lo, c = row["Open"], row["High"], row["Low"], row["Close"]
        if all(np.isfinite([o, h, lo, c])):
            candles.append({"time": ts.strftime("%Y-%m-%d"), "open": round(float(o), 2),
                            "high": round(float(h), 2), "low": round(float(lo), 2), "close": round(float(c), 2)})
    for ts, v in e50t.items():
        if np.isfinite(v):
            l50.append({"time": ts.strftime("%Y-%m-%d"), "value": round(float(v), 2)})
    for ts, v in e200t.items():
        if np.isfinite(v):
            l200.append({"time": ts.strftime("%Y-%m-%d"), "value": round(float(v), 2)})
    markers = []
    if bull_div and bull_idx is not None:
        markers.append({"time": df.index[bull_idx].strftime("%Y-%m-%d"), "position": "belowBar",
                        "color": "#26a69a", "shape": "arrowUp", "text": "BULL"})
    if bear_div and bear_idx is not None:
        markers.append({"time": df.index[bear_idx].strftime("%Y-%m-%d"), "position": "aboveBar",
                        "color": "#ef5350", "shape": "arrowDown", "text": "BEAR"})

    return {
        "ticker": ticker, "id": ticker.replace(".", "_"),
        "price": round(price, 2), "yield": round(dyield, 2),
        "rsi": round(rsi_now, 1), "trend": "ขาขึ้น" if uptrend else "ขาลง/ออกข้าง",
        "payout": pct(payout), "roe": pct(fund.get("returnOnEquity")),
        "de": None if fund.get("debtToEquity") is None else round(fund["debtToEquity"] / 100, 2),
        "epsg": pct(epsg), "pe": None if fund.get("trailingPE") is None else round(fund["trailingPE"], 1),
        "health": fg_label, "health_color": fg_color,
        "bull_div": bull_div, "bear_div": bear_div, "trap": trap,
        "score": score, "reasons": reasons,
        "chart": {"candles": candles, "ema50": l50, "ema200": l200, "markers": markers},
    }


def run(tickers):
    yq = [t + ".BK" for t in tickers]
    print(f"⬇  ราคา/ปันผล {len(yq)} ตัว ...")
    raw = yf.download(yq, period="2y", interval="1d", group_by="ticker",
                      auto_adjust=False, actions=True, progress=False, threads=True)
    print(f"⬇  งบการเงิน {len(yq)} ตัว ...")
    funds = fetch_fundamentals(yq)

    results = []
    for t, tq in zip(tickers, yq):
        try:
            df = raw[tq]
        except KeyError:
            continue
        try:
            res = analyze(t, df, funds.get(tq, {}))
        except Exception as e:
            print(f"   ! {t}: {e}")
            continue
        if res:
            results.append(res)
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def build_dashboard(results, out_path):
    keys = ("ticker", "price", "yield", "payout", "roe", "de", "epsg", "pe",
            "health", "health_color", "rsi", "trend", "score", "reasons", "id", "bear_div", "trap")
    table = [{k: r[k] for k in keys} for r in results]
    charts = [{"id": r["id"], "ticker": r["ticker"], **r["chart"]} for r in results if r["chart"]["candles"]][:8]
    n_buy = sum(1 for r in results if r["score"] >= 50)
    n_warn = sum(1 for r in results if r["bear_div"] or r["trap"])

    html = HTML_TEMPLATE
    html = html.replace("/*__ROWS__*/", json.dumps(table, ensure_ascii=False))
    html = html.replace("/*__CHARTS__*/", json.dumps(charts, ensure_ascii=False))
    html = html.replace("__SCANNED__", str(len(results)))
    html = html.replace("__NBUY__", str(n_buy))
    html = html.replace("__NWARN__", str(n_warn))
    Path(out_path).write_text(html, encoding="utf-8")


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SET Dividend Screener</title>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>
  :root{--bg:#0e1117;--card:#161b22;--bd:#222a35;--tx:#d1d4dc;--mut:#7d8590;--grn:#26a69a;--red:#ef5350;--amb:#f0a000;}
  *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--tx);font-family:-apple-system,"Segoe UI",Roboto,sans-serif}
  .wrap{max-width:1280px;margin:0 auto;padding:24px}
  h1{font-size:20px;margin:0 0 4px} .sub{color:var(--mut);font-size:13px;margin-bottom:18px}
  .stats{display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap}
  .stat{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:12px 16px;min-width:110px}
  .stat b{display:block;font-size:22px} .stat span{color:var(--mut);font-size:12px}
  table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--bd);border-radius:10px;overflow:hidden;font-size:12.5px}
  th,td{padding:9px 10px;text-align:left;border-bottom:1px solid var(--bd)}
  th{color:var(--mut);font-weight:600;cursor:pointer;user-select:none;white-space:nowrap} th:hover{color:var(--tx)}
  tr:last-child td{border-bottom:none}
  td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
  .score{font-weight:700;padding:2px 8px;border-radius:6px;display:inline-block;min-width:30px;text-align:center}
  .pill{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;color:#fff;white-space:nowrap}
  .badge{display:inline-block;background:#1f2630;border:1px solid var(--bd);color:var(--tx);border-radius:20px;padding:2px 8px;font-size:11px;margin:2px 3px 0 0;white-space:nowrap}
  .badge.warn{border-color:#5a3a00;color:#ffcf66} .badge.bull{border-color:#1c5a4f;color:#5fe0c8} .badge.bear{border-color:#5a2222;color:#ff8a8a}
  .up{color:var(--grn)} .down{color:var(--red)}
  h2{font-size:16px;margin:30px 0 12px}
  .grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px} @media(max-width:860px){.grid{grid-template-columns:1fr}}
  .chart-card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:12px}
  .chart-head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px;gap:8px;flex-wrap:wrap}
  .chart-head b{font-size:15px} .chart-head .meta{color:var(--mut);font-size:11.5px}
  .chart{height:300px} .foot{color:var(--mut);font-size:11px;margin-top:24px;line-height:1.7}
</style>
</head>
<body>
<div class="wrap">
  <h1>📈 SET Dividend + Technical + Fundamental Screener</h1>
  <div class="sub">หุ้นปันผลคุณภาพ + จังหวะเข้า + กรองงบการเงิน • ข้อมูล: yfinance • อินดิเคเตอร์คำนวณเอง</div>
  <div class="stats">
    <div class="stat"><b>__SCANNED__</b><span>หุ้นที่สแกน</span></div>
    <div class="stat"><b class="up">__NBUY__</b><span>มีสัญญาณเข้า (คะแนน ≥ 50)</span></div>
    <div class="stat"><b class="down">__NWARN__</b><span>ติดธงเตือน (bear/trap)</span></div>
  </div>

  <table id="tbl"><thead><tr>
    <th data-k="ticker">หุ้น</th>
    <th class="num" data-k="price">ราคา</th>
    <th class="num" data-k="yield">ปันผล%</th>
    <th class="num" data-k="payout">Payout%</th>
    <th class="num" data-k="roe">ROE%</th>
    <th class="num" data-k="epsg">กำไรโต%</th>
    <th data-k="health">สุขภาพงบ</th>
    <th class="num" data-k="rsi">RSI</th>
    <th class="num" data-k="score">คะแนน</th>
    <th data-k="reasons">สัญญาณ</th>
  </tr></thead><tbody></tbody></table>

  <h2>กราฟหุ้นน่าสนใจ (เรียงตามคะแนน)</h2>
  <div class="grid" id="charts"></div>

  <div class="foot">
    ⚠ <b>คำเตือน:</b> เป็น "สัญญาณ" ไม่ใช่คำแนะนำซื้อขาย • ควร backtest + ศึกษางบจริงก่อนลงเงิน • ข้อมูล yfinance ไม่ใช่ realtime<br>
    🟢 <b>Bullish Divergence</b> = ราคาลงแต่แรงขายอ่อน → ลุ้นเด้ง (เข้า) • 🔴 <b>Bearish Divergence</b> = ราคาขึ้นแต่แรงซื้ออ่อน → ระวังกลับหัว (เลี่ยง/ขาย)<br>
    💰 <b>สุขภาพงบ</b> ดูจาก payout ratio, ROE, margin, การเติบโตกำไร • <b>dividend trap</b> = ปันผลสูงแต่งบทรุด (อาจกำลังจะลดปันผล)
  </div>
</div>

<script>
const ROWS = /*__ROWS__*/;
const CHARTS = /*__CHARTS__*/;
const f1 = (v)=> v===null||v===undefined ? '—' : (+v).toFixed(1);
function scoreColor(s){ if(s>=70) return '#0b6e4f'; if(s>=50) return '#1f7a4d'; if(s>=30) return '#5a4a1f'; return '#3a3f4b'; }
function badge(r){ let c='badge'; if(r.includes('🔴'))c='badge bear'; else if(r.includes('🟢'))c='badge bull'; else if(r.includes('⚠'))c='badge warn'; return `<span class="${c}">${r}</span>`; }

const tb = document.querySelector('#tbl tbody');
function render(rows){
  tb.innerHTML = rows.map(r=>`<tr style="${r.bear_div||r.trap?'background:rgba(239,83,80,.05)':''}">
    <td><b>${r.ticker}</b></td>
    <td class="num">${r.price.toFixed(2)}</td>
    <td class="num ${r.yield>=4?'up':''}">${r.yield.toFixed(2)}</td>
    <td class="num ${r.payout>100?'down':''}">${f1(r.payout)}</td>
    <td class="num">${f1(r.roe)}</td>
    <td class="num ${r.epsg<0?'down':r.epsg>0?'up':''}">${f1(r.epsg)}</td>
    <td><span class="pill" style="background:${r.health_color}">${r.health}</span></td>
    <td class="num ${r.rsi<35?'up':r.rsi>70?'down':''}">${r.rsi.toFixed(0)}</td>
    <td class="num"><span class="score" style="background:${scoreColor(r.score)}">${r.score}</span></td>
    <td>${r.reasons.map(badge).join('')}</td>
  </tr>`).join('');
}
render(ROWS);

let asc = {};
document.querySelectorAll('#tbl th').forEach(th=>{
  th.onclick = ()=>{ const k=th.dataset.k; asc[k]=!asc[k];
    const s=[...ROWS].sort((a,b)=>{ let x=a[k],y=b[k];
      if(k==='reasons'){x=a[k].length;y=b[k].length;}
      if(x===null||x===undefined)x=-Infinity; if(y===null||y===undefined)y=-Infinity;
      if(typeof x==='string') return asc[k]?x.localeCompare(y):y.localeCompare(x);
      return asc[k]?x-y:y-x; });
    render(s); };
});

const host = document.getElementById('charts');
CHARTS.forEach(c=>{
  const row = ROWS.find(r=>r.id===c.id) || {};
  const card=document.createElement('div'); card.className='chart-card';
  card.innerHTML = `<div class="chart-head"><b>${c.ticker}</b>
     <span class="meta">ปันผล ${(row.yield||0).toFixed(2)}% · งบ ${row.health||'—'} · Payout ${f1(row.payout)}% · คะแนน ${row.score||0}</span></div>
     <div class="chart" id="c_${c.id}"></div>`;
  host.appendChild(card);
  const el = card.querySelector('.chart');
  const chart = LightweightCharts.createChart(el,{ width:el.clientWidth, height:300,
    layout:{background:{color:'#161b22'},textColor:'#d1d4dc'},
    grid:{vertLines:{color:'#1c2230'},horzLines:{color:'#1c2230'}},
    timeScale:{borderColor:'#2a2e39'}, rightPriceScale:{borderColor:'#2a2e39'} });
  const cs=chart.addCandlestickSeries({upColor:'#26a69a',downColor:'#ef5350',borderVisible:false,wickUpColor:'#26a69a',wickDownColor:'#ef5350'});
  cs.setData(c.candles);
  const e50=chart.addLineSeries({color:'#f0a000',lineWidth:1,priceLineVisible:false,lastValueVisible:false}); e50.setData(c.ema50);
  const e200=chart.addLineSeries({color:'#2962ff',lineWidth:1,priceLineVisible:false,lastValueVisible:false}); e200.setData(c.ema200);
  if(c.markers&&c.markers.length) cs.setMarkers(c.markers);
  chart.timeScale().fitContent();
  let _lw=el.clientWidth; new ResizeObserver(()=>{const w=el.clientWidth; if(w&&w!==_lw){_lw=w; chart.applyOptions({width:w});}}).observe(el);
});
</script>
</body>
</html>"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="dashboard.html")
    args = ap.parse_args()

    tk = TICKERS[:args.limit] if args.limit else TICKERS
    res = run(tk)
    if not res:
        print("❌ ไม่ได้ข้อมูล — เช็คอินเทอร์เน็ต/ชื่อหุ้น")
        raise SystemExit(1)

    print(f"\n{'หุ้น':<8}{'ราคา':>8}{'ปผ%':>6}{'Pay%':>6}{'กำไรโต%':>8}{'งบ':>10}{'คะแนน':>7}  สัญญาณ")
    print("-" * 86)
    for r in res[:20]:
        pay = "—" if r["payout"] is None else f"{r['payout']:.0f}"
        eg = "—" if r["epsg"] is None else f"{r['epsg']:.0f}"
        sig = ", ".join(x for x in r["reasons"] if "Diverg" in x or "trap" in x or "oversold" in x)[:40]
        print(f"{r['ticker']:<8}{r['price']:>8.2f}{r['yield']:>6.1f}{pay:>6}{eg:>8}{r['health']:>10}{r['score']:>7.0f}  {sig}")

    build_dashboard(res, args.out)
    print(f"\n✅ สร้าง {args.out} แล้ว ({len(res)} หุ้น)")
