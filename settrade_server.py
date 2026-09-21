#!/usr/bin/env python3
"""
เว็บแอป "พอร์ต + ราคาสด + กราฟ" สไตล์ TradingView จาก Settrade Open API
- backend (Flask) ถือ key ตอบ quote/candles/portfolio — ดึงข้อมูลอย่างเดียว ไม่มีคำสั่งซื้อขาย
- frontend: ค้นหุ้นได้ทุกตัว + กราฟแท่งเทียน (Lightweight Charts) + พอร์ต + watchlist
รัน: python settrade_server.py  (อ่าน settrade_config.json ในโฟลเดอร์เดียวกัน)
"""
import argparse
import threading
import time
from datetime import datetime, timezone, timedelta

from flask import Flask, jsonify, Response, request
from settrade_client import SettradeData, load_config

VALID_TF = ("1m", "5m", "15m", "30m", "60m", "1d", "1w", "1M")

app = Flask(__name__)
_D = None


def data():
    global _D
    if _D is None:
        _D = SettradeData()
    return _D


# ---------- cache: ลดการยิง Settrade (โควตา 5/วิ · 60/นาที ต่อบัญชี) ----------
QUOTE_TTL = 8        # cache ราคา ~8 วินาที
CANDLE_TTL = 20      # cache กราฟ ~20 วินาที
BKK = timezone(timedelta(hours=7))
_cache = {}
_clock = threading.Lock()


def _cached(key, ttl, fn):
    now = time.time()
    with _clock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    val = fn()
    with _clock:
        _cache[key] = (now, val)
    return val


def cq(sym):
    """quote แบบ cache"""
    return _cached("q:" + sym, QUOTE_TTL, lambda: data().quote(sym))


def _candles(sym, interval, limit, normalized=False, iso=False):
    """candles แบบ cache · iso=True -> time เป็น ISO 8601 +07:00 · normalized -> ปรับ corporate action"""
    key = f"c:{sym}:{interval}:{limit}:{int(bool(normalized))}:{int(bool(iso))}"

    def build():
        c = data().candles(sym, interval=interval, limit=limit, normalized=normalized or None)
        ts, o, h, l, cl = c["time"], c["open"], c["high"], c["low"], c["close"]
        vol = c.get("volume", [])
        daily = interval in ("1d", "1w", "1M")
        out = []
        for i in range(len(ts)):
            t = ts[i]
            if iso:
                tv = datetime.fromtimestamp(t, tz=BKK).isoformat()          # 2026-09-21T16:00:00+07:00
            elif daily:
                tv = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
            else:
                tv = int(t)
            out.append({"time": tv, "open": o[i], "high": h[i], "low": l[i], "close": cl[i],
                        "volume": vol[i] if i < len(vol) else 0})
        return out
    return _cached(key, CANDLE_TTL, build)


@app.route("/api/symbol/<sym>")
def api_symbol(sym):
    sym = sym.upper().strip()
    iv = request.args.get("interval", "1d")
    if iv not in VALID_TF:
        iv = "1d"
    try:
        q = cq(sym)
        lim = 1000 if iv in ("1d", "1w", "1M") else 400
        cand = _candles(sym, iv, lim)
        return jsonify({"ok": True, "symbol": sym, "interval": iv, "quote": q, "candles": cand})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 404


@app.route("/api/watch")
def api_watch():
    # ราคาสด watchlist เท่านั้น (ไม่มีพอร์ต/เงิน — ตามที่ผู้ใช้ขอซ่อน) · ใช้ cache รายตัว
    try:
        out = {}
        for s in WATCH:
            try:
                out[s] = cq(s)
            except Exception as e:
                out[s] = {"error": str(e)[:80]}
        return jsonify({"ok": True, "watch": WATCH, "quotes": out})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


# ===== Public Data API (ข้อมูลตลาดเท่านั้น · ต้องมี API key ที่เจ้าของอนุญาต) =====
def _api_keys():
    return set(load_config().get("api_keys", []) or [])


def _check_key():
    keys = _api_keys()
    if not keys:
        return False
    k = request.args.get("key") or request.headers.get("X-API-Key", "")
    return k in keys


def _deny():
    return jsonify({"ok": False, "error": "ต้องมี API key ที่ได้รับอนุญาต — ใส่ ?key=... หรือ header X-API-Key"}), 401


@app.route("/api")
def api_docs():
    return jsonify({
        "service": "stock.cyk Market Data API (Settrade/SET)",
        "note": "ข้อมูลตลาด SET เท่านั้น · ไม่มีข้อมูลพอร์ต/บัญชี · ต้องมี API key ที่เจ้าของอนุญาต",
        "auth": "ใส่ ?key=YOUR_KEY หรือ header X-API-Key: YOUR_KEY",
        "endpoints": {
            "GET /api/quote/<symbol>": "ราคาสด 1 ตัว เช่น /api/quote/PTT?key=...",
            "GET /api/quotes?symbols=A,B,C": "ราคาสดหลายตัว (batch, สูงสุด 30 ตัว)",
            "GET /api/candles/<symbol>?interval=1d&limit=250&normalized=0": "แท่งเทียน (interval: 1m,5m,15m,30m,60m,1d,1w,1M · normalized=1 ปรับ corporate action)",
        },
        "conventions": {
            "time": "ISO 8601 +07:00 (Asia/Bangkok) = เวลาเปิดแท่ง",
            "candle.volume": "วอลุ่มต่อแท่ง · quote.totalVolume = สะสมทั้งวัน",
            "candle.complete": "true=แท่งปิดสมบูรณ์ · false=แท่งกำลังก่อตัว (ระหว่างตลาดเปิด)",
            "cache": "ราคา ~8 วินาที · กราฟ ~20 วินาที (ข้อมูลอาจช้ากว่าจริงเล็กน้อยตาม cache)",
            "rate_limit": "~5 คำขอ/วินาที · ~60 คำขอ/นาที (แชร์รวมทุกผู้ใช้)",
        },
        "disclaimer": "เพื่อผู้ที่ได้รับอนุญาตเท่านั้น · ห้าม redistribute ต่อสาธารณะ (สิทธิ์ข้อมูลตลาด)",
    })


@app.route("/api/quote/<sym>")
def api_quote(sym):
    if not _check_key():
        return _deny()
    sym = sym.upper().strip()
    try:
        return jsonify({"ok": True, "symbol": sym, "quote": cq(sym)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 404


@app.route("/api/quotes")
def api_quotes():
    if not _check_key():
        return _deny()
    syms = [s.strip().upper() for s in request.args.get("symbols", "").split(",") if s.strip()][:30]
    if not syms:
        return jsonify({"ok": False, "error": "ต้องระบุ ?symbols=PTT,KBANK,..."}), 400
    out = {}
    for s in syms:
        try:
            out[s] = cq(s)
        except Exception as e:
            out[s] = {"error": str(e)[:80]}
    return jsonify({"ok": True, "quotes": out})


@app.route("/api/candles/<sym>")
def api_candles(sym):
    if not _check_key():
        return _deny()
    sym = sym.upper().strip()
    iv = request.args.get("interval", "1d")
    if iv not in VALID_TF:
        iv = "1d"
    try:
        lim = int(request.args.get("limit", 250))
    except (TypeError, ValueError):
        lim = 250
    lim = max(1, min(lim, 1000))
    norm = request.args.get("normalized", "") in ("1", "true", "yes")
    try:
        cand = [dict(c, complete=True) for c in _candles(sym, iv, lim, normalized=norm, iso=True)]
        if cand:   # แท่งล่าสุดยังไม่ปิดถ้าตลาดเปิดอยู่
            mopen = "Open" in (cq(sym).get("marketStatus") or "")
            cand[-1]["complete"] = not mopen
        return jsonify({"ok": True, "symbol": sym, "interval": iv, "normalized": norm, "candles": cand})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 404


WATCH = ["KTB", "KBANK", "KKP", "BBL", "SCB", "TISCO", "PTT", "AP", "PTTEP", "ADVANC"]


@app.route("/")
def index():
    return Response(PAGE, mimetype="text/html")


PAGE = r"""<!DOCTYPE html><html lang="th"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Live Port · Settrade</title>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>
 :root{--bg:#0e1117;--pan:#161b22;--bd:#2a2e39;--tx:#e6e9ef;--mut:#8b95a3;--grn:#26c281;--red:#ff5a5a;--ac:#2962ff;}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--tx);font-family:-apple-system,"Segoe UI",Roboto,sans-serif;font-size:16px}
 .top{display:flex;align-items:center;gap:12px;padding:12px 16px;background:var(--pan);border-bottom:1px solid var(--bd);position:sticky;top:0;z-index:5;flex-wrap:wrap}
 .top b{font-size:18px;color:#5f8cff}
 #q{flex:1;min-width:150px;max-width:300px;background:#0e1117;border:1px solid var(--bd);color:var(--tx);border-radius:9px;padding:10px 14px;font-size:16px}
 #go{background:var(--ac);color:#fff;border:none;border-radius:9px;padding:10px 18px;font-size:16px;font-weight:700;cursor:pointer}
 #legend{display:flex;gap:14px;flex-wrap:wrap;padding:4px 16px 8px;font-size:13px}
 #legend span{display:inline-flex;align-items:center;gap:5px;color:var(--mut)}
 #legend i{width:16px;height:3px;border-radius:2px;display:inline-block}
 #tfbar{display:flex;gap:6px;flex-wrap:wrap;padding:6px 16px 0}
 #tfbar button{background:#0e1117;border:1px solid var(--bd);color:var(--mut);border-radius:8px;padding:7px 13px;font-size:14px;cursor:pointer}
 #tfbar button.on{background:var(--ac);color:#fff;border-color:var(--ac);font-weight:700}
 .hd{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;padding:14px 16px}
 .hd .sym{font-size:26px;font-weight:800} .hd .last{font-size:26px;font-weight:800}
 .hd .chg{font-size:17px;font-weight:700} .hd .meta{color:var(--mut);font-size:14px}
 .up{color:var(--grn)} .down{color:var(--red)}
 #chart{height:60vh;min-height:340px;margin:0 8px}
 .wrap{max-width:1200px;margin:0 auto}
 h2{font-size:18px;margin:22px 16px 10px}
 table{width:calc(100% - 32px);margin:0 16px;border-collapse:collapse;background:var(--pan);border:1px solid var(--bd);border-radius:12px;overflow:hidden;font-size:15px}
 th,td{padding:11px 12px;text-align:left;border-bottom:1px solid var(--bd)} th{color:var(--mut);font-size:13px;font-weight:600}
 td.num,th.num{text-align:right;font-variant-numeric:tabular-nums} tr:last-child td{border-bottom:none}
 tbody tr{cursor:pointer} tbody tr:hover{background:#1c2230}
 .cards{display:flex;gap:12px;flex-wrap:wrap;padding:0 16px}
 .card{background:var(--pan);border:1px solid var(--bd);border-radius:12px;padding:12px 16px;flex:1;min-width:150px}
 .card b{display:block;font-size:22px} .card span{color:var(--mut);font-size:13px}
 .foot{color:var(--mut);font-size:13px;margin:22px 16px;line-height:1.7}
</style></head><body><div class="wrap">
 <div class="top"><b>📈 Live Port</b>
   <input id="q" placeholder="ค้นหุ้น เช่น PTT, KBANK, DELTA…" autocomplete="off">
   <button id="go">ค้นหา</button>
   <span id="mkt" class="meta" style="color:var(--mut);font-size:13px"></span></div>
 <div id="tfbar"></div>
 <div class="hd"><span id="sym" class="sym">—</span><span id="last" class="last">—</span>
   <span id="chg" class="chg"></span>
   <span id="meta" class="meta"></span></div>
 <div id="legend"></div>
 <div id="chart"></div>

 <h2>👀 ราคาสด — เฝ้าดู <span style="color:var(--mut);font-size:13px">(แตะเพื่อดูกราฟ)</span></h2>
 <table id="wl"><thead><tr><th>หุ้น</th><th class="num">ล่าสุด</th><th class="num">เปลี่ยน%</th><th class="num">ปันผล%</th><th class="num">PE</th><th class="num">PBV</th></tr></thead><tbody></tbody></table>
 <div class="foot">ราคาสดจาก Settrade (InnovestX) · อ่านอย่างเดียว ไม่มีคำสั่งซื้อขาย · ไม่ใช่คำแนะนำลงทุน · รีเฟรชอัตโนมัติทุก 30 วินาที</div>
</div>
<script>
const $=s=>document.querySelector(s);
let chart, series, volSeries, cur="PTT", curTf="1d", emaSeries=[];
const EMAS=[[5,"#ffd93d"],[7,"#ff9f1c"],[14,"#4dd0e1"],[20,"#5f8cff"],[200,"#b06cff"],[800,"#ff5aa9"]];
function fmt(v,d=2){return v==null||isNaN(v)?"—":(+v).toLocaleString("th-TH",{minimumFractionDigits:d,maximumFractionDigits:d});}
function emaCalc(data,period){const k=2/(period+1);let prev;const out=[];for(let i=0;i<data.length;i++){const c=data[i].close;prev=i===0?c:c*k+prev*(1-k);if(i>=period-1)out.push({time:data[i].time,value:+prev.toFixed(2)});}return out;}
function initChart(){
 const el=$("#chart");
 chart=LightweightCharts.createChart(el,{width:el.clientWidth,height:el.clientHeight,
   layout:{background:{color:"#0e1117"},textColor:"#c9d1d9"},grid:{vertLines:{color:"#1c2230"},horzLines:{color:"#1c2230"}},
   timeScale:{borderColor:"#2a2e39"},rightPriceScale:{borderColor:"#2a2e39"}});
 series=chart.addCandlestickSeries({upColor:"#26c281",downColor:"#ff5a5a",borderVisible:false,wickUpColor:"#26c281",wickDownColor:"#ff5a5a"});
 volSeries=chart.addHistogramSeries({priceFormat:{type:"volume"},priceScaleId:"vol"});
 chart.priceScale("vol").applyOptions({scaleMargins:{top:0.82,bottom:0}});
 emaSeries=EMAS.map(([p,c])=>chart.addLineSeries({color:c,lineWidth:p>=200?2:1,priceLineVisible:false,lastValueVisible:false}));
 $("#legend").innerHTML=EMAS.map(([p,c])=>`<span><i style="background:${c}"></i>EMA${p}</span>`).join("");
 new ResizeObserver(()=>chart.applyOptions({width:el.clientWidth,height:el.clientHeight})).observe(el);
}
const TFS=[["1m","1m"],["5m","5m"],["15m","15m"],["30m","30m"],["60m","1H"],["1d","D"],["1w","W"],["1M","M"]];
function initTf(){
 $("#tfbar").innerHTML=TFS.map(([v,l])=>`<button data-tf="${v}"${v===curTf?' class="on"':''}>${l}</button>`).join("");
 $("#tfbar").querySelectorAll("button").forEach(b=>b.onclick=()=>{curTf=b.dataset.tf;
   $("#tfbar").querySelectorAll("button").forEach(x=>x.classList.toggle("on",x.dataset.tf===curTf));load(cur);});
}
async function load(sym){
 sym=(sym||"").toUpperCase().trim(); if(!sym)return;
 const r=await fetch("/api/symbol/"+encodeURIComponent(sym)+"?interval="+curTf); const j=await r.json();
 if(!j.ok){$("#sym").textContent=sym;$("#last").textContent="ไม่พบ";$("#chg").textContent="";$("#meta").textContent=j.error||"";return;}
 cur=sym; series.setData(j.candles);
 volSeries.setData(j.candles.map(c=>({time:c.time,value:c.volume,color:c.close>=c.open?"#26c28166":"#ff5a5a66"})));
 EMAS.forEach(([p,_],i)=>emaSeries[i].setData(j.candles.length>=p?emaCalc(j.candles,p):[]));
 chart.timeScale().fitContent();
 const q=j.quote, ch=+q.percentChange||0, col=ch>=0?"up":"down";
 $("#sym").textContent=sym; $("#last").textContent=fmt(q.last);
 $("#chg").className="chg "+col; $("#chg").textContent=(ch>=0?"▲ +":"▼ ")+fmt(q.change)+" ("+(ch>=0?"+":"")+fmt(ch)+"%)";
 $("#meta").textContent="ปันผล "+fmt(q.percentYield)+"% · PE "+fmt(q.pe,1)+" · PBV "+fmt(q.pbv)+" · สูง "+fmt(q.high)+" ต่ำ "+fmt(q.low);
 $("#mkt").textContent=(q.marketStatus||"").includes("Open")?"🟢 ตลาดเปิด":"🔴 ตลาดปิด";
}
async function loadWatch(){
 const j=await (await fetch("/api/watch")).json(); if(!j.ok)return;
 $("#wl tbody").innerHTML=j.watch.map(s=>{const q=j.quotes[s]||{};const ch=+q.percentChange||0,c=ch>=0?"up":"down";
   return q.last==null?`<tr onclick="load('${s}')"><td><b>${s}</b></td><td colspan="5" style="color:var(--mut)">—</td></tr>`:
   `<tr onclick="load('${s}')"><td><b>${s}</b></td><td class="num">${fmt(q.last)}</td><td class="num ${c}">${ch>=0?"+":""}${fmt(ch)}%</td><td class="num">${fmt(q.percentYield)}%</td><td class="num">${fmt(q.pe,1)}</td><td class="num">${fmt(q.pbv)}</td></tr>`;}).join("");
}
$("#q").addEventListener("keydown",e=>{if(e.key==="Enter")load(e.target.value);});
$("#go").addEventListener("click",()=>load($("#q").value));
initChart(); initTf(); load(cur); loadWatch();
setInterval(()=>{load(cur);loadWatch();},30000);
</script></body></html>"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8095)
    a = ap.parse_args()
    print(f"เริ่มเซิร์ฟเวอร์ที่ http://{a.host}:{a.port}")
    app.run(host=a.host, port=a.port, debug=False)
