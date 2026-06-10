#!/usr/bin/env python3
"""
SET Dividend + Technical Screener
หาหุ้นปันผลคุณภาพในตลาดไทย แล้วจับจังหวะเข้าตอนราคาย่อด้วยสัญญาณเทคนิค
(RSI bullish divergence, oversold, ย่อในขาขึ้น, ใกล้แนวรับ)

ดึงข้อมูล: yfinance (ฟรี) | อินดิเคเตอร์: คำนวณเอง (pandas/numpy)
ผลลัพธ์: dashboard.html (กราฟแบบ TradingView ด้วย Lightweight Charts) + ตารางในเทอร์มินัล
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

# ---------- รายชื่อหุ้น (SET50-ish, ปรับ/เพิ่มได้) ----------
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


# ---------- ตรวจ divergence ----------
def pivot_low_idx(vals, left=5, right=5):
    out = []
    n = len(vals)
    for i in range(left, n - right):
        seg = vals[i - left:i + right + 1]
        if vals[i] == seg.min():
            out.append(i)
    return out


def detect_bull_div(low, rsi_series, left=5, right=5, lookback=70):
    lows = low.values
    rsis = rsi_series.values
    idx = [i for i in pivot_low_idx(lows, left, right) if i >= len(lows) - lookback]
    if len(idx) < 2:
        return False, None
    i1, i2 = idx[-2], idx[-1]
    price_ll = lows[i2] < lows[i1]
    rsi_hl = rsis[i2] > rsis[i1]
    if price_ll and rsi_hl:
        return True, i2  # index ของ pivot ล่าสุด (ไว้ปักหมุดบนกราฟ)
    return False, None


# ---------- วิเคราะห์หุ้น 1 ตัว ----------
def analyze(ticker, df):
    df = df.dropna(how="all")
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    if len(df) < 60:
        return None

    close = df["Close"].astype(float)
    low = df["Low"].astype(float)
    price = float(close.iloc[-1])
    if not np.isfinite(price) or price <= 0:
        return None

    # ปันผลย้อนหลัง 12 เดือน
    div = df["Dividends"].fillna(0) if "Dividends" in df else pd.Series(0, index=df.index)
    cutoff = df.index[-1] - pd.Timedelta(days=365)
    div_1y = float(div[div.index >= cutoff].sum())
    dyield = div_1y / price * 100

    r = rsi(close)
    rsi_now = float(r.iloc[-1])
    ema50 = ema(close, 50)
    ema200 = ema(close, 200)
    _, _, bb_low = bollinger(close)
    macd_line, macd_sig, _ = macd(close)

    e50 = float(ema50.iloc[-1])
    e200 = float(ema200.iloc[-1])
    bbl = float(bb_low.iloc[-1]) if np.isfinite(bb_low.iloc[-1]) else price
    uptrend = price > e200
    low52 = float(low.tail(252).min())
    bull_div, div_idx = detect_bull_div(low, r)

    # ---------- ให้คะแนน + เหตุผล ----------
    score = 0.0
    reasons = []

    if 3 <= dyield <= 12:
        score += min(20, dyield * 2)
        reasons.append(f"ปันผล {dyield:.1f}%")
    elif dyield > 12:
        reasons.append(f"⚠ ปันผล {dyield:.1f}% สูงผิดปกติ (เช็ค trap)")
    elif dyield > 0:
        reasons.append(f"ปันผล {dyield:.1f}%")

    if rsi_now < 35:
        score += 20
        reasons.append(f"RSI oversold ({rsi_now:.0f})")
    if bull_div:
        score += 30
        reasons.append("Bullish Divergence")
    if price < bbl:
        score += 15
        reasons.append("หลุดกรอบล่าง BB")
    if uptrend and price <= e50 * 1.02:
        score += 20
        reasons.append("ย่อในขาขึ้น (แตะ EMA50)")
    if price <= low52 * 1.10:
        score += 15
        reasons.append("ใกล้ Low 52 สัปดาห์")

    macd_cross = bool(macd_line.iloc[-1] > macd_sig.iloc[-1] and macd_line.iloc[-2] <= macd_sig.iloc[-2])
    if macd_cross:
        score += 10
        reasons.append("MACD ตัดขึ้น")

    score = round(min(score, 100), 0)

    # ---------- ข้อมูลกราฟ (300 แท่งล่าสุด) ----------
    tail = df.tail(300)
    e50t = ema50.tail(300)
    e200t = ema200.tail(300)
    candles, l50, l200 = [], [], []
    for ts, row in tail.iterrows():
        t = ts.strftime("%Y-%m-%d")
        o, h, lo, c = row["Open"], row["High"], row["Low"], row["Close"]
        if not all(np.isfinite([o, h, lo, c])):
            continue
        candles.append({"time": t, "open": round(float(o), 2), "high": round(float(h), 2),
                        "low": round(float(lo), 2), "close": round(float(c), 2)})
    for ts, v in e50t.items():
        if np.isfinite(v):
            l50.append({"time": ts.strftime("%Y-%m-%d"), "value": round(float(v), 2)})
    for ts, v in e200t.items():
        if np.isfinite(v):
            l200.append({"time": ts.strftime("%Y-%m-%d"), "value": round(float(v), 2)})

    markers = []
    if bull_div and div_idx is not None:
        mt = df.index[div_idx].strftime("%Y-%m-%d")
        markers.append({"time": mt, "position": "belowBar", "color": "#26a69a",
                        "shape": "arrowUp", "text": "DIV"})

    return {
        "ticker": ticker,
        "id": ticker.replace(".", "_"),
        "price": round(price, 2),
        "yield": round(dyield, 2),
        "div_1y": round(div_1y, 2),
        "rsi": round(rsi_now, 1),
        "trend": "ขาขึ้น" if uptrend else "ขาลง/ออกข้าง",
        "score": score,
        "reasons": reasons,
        "bull_div": bull_div,
        "chart": {"candles": candles, "ema50": l50, "ema200": l200, "markers": markers},
    }


# ---------- ดึงข้อมูล + ประมวลผล ----------
def run(tickers):
    yq = [t + ".BK" for t in tickers]
    print(f"⬇  ดึงข้อมูล {len(yq)} ตัวจาก yfinance ...")
    raw = yf.download(yq, period="2y", interval="1d", group_by="ticker",
                      auto_adjust=False, actions=True, progress=False, threads=True)

    results = []
    for t, tq in zip(tickers, yq):
        try:
            df = raw[tq]
        except KeyError:
            continue
        try:
            res = analyze(t, df)
        except Exception as e:
            print(f"   ! {t}: {e}")
            continue
        if res:
            results.append(res)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


# ---------- สร้าง dashboard ----------
def build_dashboard(results, out_path):
    table_rows = [{k: r[k] for k in ("ticker", "price", "yield", "rsi", "trend", "score", "reasons", "id")}
                  for r in results]
    charts = [{"id": r["id"], "ticker": r["ticker"], **r["chart"]}
              for r in results if r["score"] > 0][:8]

    n_buy = sum(1 for r in results if r["score"] >= 50)
    html = HTML_TEMPLATE
    html = html.replace("/*__ROWS__*/", json.dumps(table_rows, ensure_ascii=False))
    html = html.replace("/*__CHARTS__*/", json.dumps(charts, ensure_ascii=False))
    html = html.replace("__SCANNED__", str(len(results)))
    html = html.replace("__NBUY__", str(n_buy))
    Path(out_path).write_text(html, encoding="utf-8")


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SET Dividend Screener</title>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>
  :root{--bg:#0e1117;--card:#161b22;--bd:#222a35;--tx:#d1d4dc;--mut:#7d8590;--grn:#26a69a;--red:#ef5350;--amb:#f0a000;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--tx);font-family:-apple-system,"Segoe UI",Roboto,"Helvetica Neue",sans-serif}
  .wrap{max-width:1200px;margin:0 auto;padding:24px}
  h1{font-size:20px;margin:0 0 4px} .sub{color:var(--mut);font-size:13px;margin-bottom:18px}
  .stats{display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap}
  .stat{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:12px 16px;min-width:120px}
  .stat b{display:block;font-size:22px} .stat span{color:var(--mut);font-size:12px}
  table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--bd);border-radius:10px;overflow:hidden;font-size:13px}
  th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--bd)}
  th{color:var(--mut);font-weight:600;cursor:pointer;user-select:none;white-space:nowrap}
  th:hover{color:var(--tx)} tr:last-child td{border-bottom:none}
  td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
  .score{font-weight:700;padding:2px 8px;border-radius:6px;display:inline-block;min-width:34px;text-align:center}
  .badge{display:inline-block;background:#1f2630;border:1px solid var(--bd);color:var(--tx);
         border-radius:20px;padding:2px 9px;font-size:11px;margin:2px 3px 0 0;white-space:nowrap}
  .badge.warn{border-color:#5a3a00;color:#ffcf66} .badge.div{border-color:#1c5a4f;color:#5fe0c8}
  .up{color:var(--grn)} .down{color:var(--red)}
  h2{font-size:16px;margin:30px 0 12px}
  .grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}
  @media(max-width:820px){.grid{grid-template-columns:1fr}}
  .chart-card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:12px}
  .chart-head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px}
  .chart-head b{font-size:15px} .chart-head .y{color:var(--amb);font-size:12px}
  .chart{height:300px} .foot{color:var(--mut);font-size:11px;margin-top:24px;line-height:1.6}
  a{color:#58a6ff;text-decoration:none}
</style>
</head>
<body>
<div class="wrap">
  <h1>📈 SET Dividend + Technical Screener</h1>
  <div class="sub">หุ้นปันผลคุณภาพ + จังหวะเข้าตอนราคาย่อ • ข้อมูล: yfinance • อินดิเคเตอร์คำนวณเอง</div>
  <div class="stats">
    <div class="stat"><b>__SCANNED__</b><span>หุ้นที่สแกน</span></div>
    <div class="stat"><b class="up">__NBUY__</b><span>มีสัญญาณเข้า (คะแนน ≥ 50)</span></div>
  </div>

  <table id="tbl">
    <thead><tr>
      <th data-k="ticker">หุ้น</th>
      <th class="num" data-k="price">ราคา</th>
      <th class="num" data-k="yield">ปันผล %</th>
      <th class="num" data-k="rsi">RSI</th>
      <th data-k="trend">เทรนด์</th>
      <th class="num" data-k="score">คะแนน</th>
      <th data-k="reasons">สัญญาณ</th>
    </tr></thead>
    <tbody></tbody>
  </table>

  <h2>กราฟหุ้นน่าสนใจ (เรียงตามคะแนน)</h2>
  <div class="grid" id="charts"></div>

  <div class="foot">
    ⚠ <b>คำเตือน:</b> นี่คือ "สัญญาณ" ไม่ใช่คำแนะนำซื้อขาย • ปันผลสูงผิดปกติอาจเป็นกับดัก (ราคาดิ่งเพราะกำลังลดปันผล) •
    divergence มีสัญญาณหลอกได้ • ควร backtest และศึกษาพื้นฐานก่อนลงเงินจริงเสมอ<br>
    คะแนน = ผลรวมสัญญาณ (ปันผล/oversold/divergence/ย่อในขาขึ้น/ใกล้แนวรับ/MACD)
  </div>
</div>

<script>
const ROWS = /*__ROWS__*/;
const CHARTS = /*__CHARTS__*/;

function scoreColor(s){ if(s>=70) return '#0b6e4f'; if(s>=50) return '#1f7a4d'; if(s>=30) return '#5a4a1f'; return '#3a3f4b'; }
function badge(r){ const c = r.includes('⚠')?'badge warn' : r.includes('Divergence')?'badge div':'badge'; return `<span class="${c}">${r}</span>`; }

const tb = document.querySelector('#tbl tbody');
function render(rows){
  tb.innerHTML = rows.map(r=>`<tr>
    <td><b>${r.ticker}</b></td>
    <td class="num">${r.price.toFixed(2)}</td>
    <td class="num ${r.yield>=4?'up':''}">${r.yield.toFixed(2)}</td>
    <td class="num ${r.rsi<35?'up':r.rsi>70?'down':''}">${r.rsi.toFixed(0)}</td>
    <td class="${r.trend==='ขาขึ้น'?'up':'down'}">${r.trend}</td>
    <td class="num"><span class="score" style="background:${scoreColor(r.score)}">${r.score}</span></td>
    <td>${r.reasons.map(badge).join('')}</td>
  </tr>`).join('');
}
render(ROWS);

// sort
let asc = {};
document.querySelectorAll('#tbl th').forEach(th=>{
  th.onclick = ()=>{ const k = th.dataset.k; asc[k]=!asc[k];
    const s=[...ROWS].sort((a,b)=>{ let x=a[k],y=b[k];
      if(k==='reasons'){x=a[k].length;y=b[k].length;}
      if(typeof x==='string') return asc[k]?x.localeCompare(y):y.localeCompare(x);
      return asc[k]?x-y:y-x; });
    render(s);
  };
});

// charts
const host = document.getElementById('charts');
CHARTS.forEach(c=>{
  const card=document.createElement('div'); card.className='chart-card';
  const row = ROWS.find(r=>r.id===c.id) || {};
  card.innerHTML = `<div class="chart-head"><b>${c.ticker}</b>
     <span class="y">ปันผล ${(row.yield||0).toFixed(2)}% · คะแนน ${row.score||0}</span></div>
     <div class="chart" id="c_${c.id}"></div>`;
  host.appendChild(card);
  const el = card.querySelector('.chart');
  const chart = LightweightCharts.createChart(el,{
    width:el.clientWidth, height:300,
    layout:{background:{color:'#161b22'},textColor:'#d1d4dc'},
    grid:{vertLines:{color:'#1c2230'},horzLines:{color:'#1c2230'}},
    timeScale:{borderColor:'#2a2e39'}, rightPriceScale:{borderColor:'#2a2e39'},
  });
  const cs=chart.addCandlestickSeries({upColor:'#26a69a',downColor:'#ef5350',borderVisible:false,wickUpColor:'#26a69a',wickDownColor:'#ef5350'});
  cs.setData(c.candles);
  const e50=chart.addLineSeries({color:'#f0a000',lineWidth:1,priceLineVisible:false,lastValueVisible:false}); e50.setData(c.ema50);
  const e200=chart.addLineSeries({color:'#2962ff',lineWidth:1,priceLineVisible:false,lastValueVisible:false}); e200.setData(c.ema200);
  if(c.markers&&c.markers.length) cs.setMarkers(c.markers);
  chart.timeScale().fitContent();
  new ResizeObserver(()=>chart.applyOptions({width:el.clientWidth})).observe(el);
});
</script>
</body>
</html>"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="จำกัดจำนวนหุ้น (ทดสอบเร็ว)")
    ap.add_argument("--out", default="dashboard.html")
    args = ap.parse_args()

    tk = TICKERS[:args.limit] if args.limit else TICKERS
    res = run(tk)

    if not res:
        print("❌ ไม่ได้ข้อมูล — เช็คอินเทอร์เน็ต/ชื่อหุ้น")
        raise SystemExit(1)

    print(f"\n{'หุ้น':<9}{'ราคา':>9}{'ปันผล%':>8}{'RSI':>6}{'คะแนน':>7}  สัญญาณ")
    print("-" * 70)
    for r in res[:20]:
        print(f"{r['ticker']:<9}{r['price']:>9.2f}{r['yield']:>8.2f}{r['rsi']:>6.0f}{r['score']:>7.0f}  "
              + ", ".join(r["reasons"][:3]))

    build_dashboard(res, args.out)
    print(f"\n✅ สร้าง {args.out} แล้ว ({len(res)} หุ้น) — เปิดไฟล์นี้ในเบราว์เซอร์ได้เลย")
