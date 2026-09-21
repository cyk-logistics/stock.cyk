#!/usr/bin/env python3
"""
สร้างหน้าเว็บ "พอร์ต + ราคาสด" จาก Settrade Open API (ดึงข้อมูลอย่างเดียว)
รันบนเครื่องที่มี settrade_config.json → เขียนไฟล์ live.html (เปิดดูได้ทุกที่)
ไม่มีคำสั่งซื้อขาย — อ่านพอร์ต/ราคา/บัญชี เท่านั้น
"""
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

from settrade_client import SettradeData

# watchlist เริ่มต้น: แบงก์/ปันผลที่เฝ้าดู (รวมกับหุ้นในพอร์ตอัตโนมัติ)
WATCH = ["KTB", "KBANK", "KKP", "BBL", "SCB", "TISCO", "PTT", "AP", "PTTEP", "ADVANC"]

TH_MON = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
          "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]


def _f(v, d=2):
    try:
        return f"{float(v):,.{d}f}"
    except Exception:
        return "—"


def build(out_path):
    d = SettradeData()
    acc = d.account()
    pf = d.portfolio()
    rows = pf.get("portfolioList", []) if isinstance(pf, dict) else (pf or [])
    tot = pf.get("totalPortfolio", {}) if isinstance(pf, dict) else {}

    held = [r.get("symbol") for r in rows if r.get("symbol")]
    watch = held + [s for s in WATCH if s not in held]
    quotes = d.quotes(watch)

    now = datetime.now(timezone.utc) + timedelta(hours=7)
    updated = f"{now.day} {TH_MON[now.month]} {now.year} {now.hour:02d}:{now.minute:02d} น."
    mstat = ""
    for q in quotes.values():
        if isinstance(q, dict) and q.get("marketStatus"):
            mstat = q["marketStatus"]; break
    mopen = "Open" in mstat
    mlabel = ("🟢 ตลาดเปิด" if mopen else "🔴 ตลาดปิด") + (f" ({mstat})" if mstat else "")

    # ----- พอร์ต -----
    pf_rows = ""
    for r in rows:
        p = float(r.get("profit") or 0)
        pc = float(r.get("percentProfit") or 0)
        col = "up" if p >= 0 else "down"
        pf_rows += (f'<tr><td><b>{r.get("symbol","")}</b></td>'
                    f'<td class="num">{_f(r.get("actualVolume") or r.get("currentVolume"),0)}</td>'
                    f'<td class="num">{_f(r.get("averagePrice"))}</td>'
                    f'<td class="num">{_f(r.get("marketPrice"))}</td>'
                    f'<td class="num">{_f(r.get("marketValue"),0)}</td>'
                    f'<td class="num {col}">{"+" if p>=0 else ""}{_f(p,0)}<br>'
                    f'<span style="font-size:13px">{"+" if pc>=0 else ""}{_f(pc,1)}%</span></td></tr>')
    if not rows:
        pf_rows = '<tr><td colspan="6" style="color:var(--mut);text-align:center">ไม่มีหุ้นในพอร์ต (ถือเงินสด)</td></tr>'
    tp_val = _f(tot.get("marketValue"), 0)
    tp_profit = float(tot.get("profit") or 0)
    tp_pc = float(tot.get("percentProfit") or 0)
    tp_col = "up" if tp_profit >= 0 else "down"

    # ----- watchlist ราคาสด -----
    wl_rows = ""
    for s in watch:
        q = quotes.get(s, {})
        if not isinstance(q, dict) or "last" not in q:
            wl_rows += f'<tr><td><b>{s}</b></td><td colspan="5" style="color:var(--mut)">—</td></tr>'
            continue
        ch = float(q.get("percentChange") or 0)
        col = "up" if ch >= 0 else "down"
        tag = " 🎒" if s in held else ""
        wl_rows += (f'<tr><td><b>{s}</b>{tag}</td>'
                    f'<td class="num">{_f(q.get("last"))}</td>'
                    f'<td class="num {col}">{"+" if ch>=0 else ""}{_f(ch,2)}%</td>'
                    f'<td class="num">{_f(q.get("percentYield"),2)}%</td>'
                    f'<td class="num">{_f(q.get("pe"),1)}</td>'
                    f'<td class="num">{_f(q.get("pbv"),2)}</td></tr>')

    html = TEMPLATE
    html = html.replace("__UPDATED__", updated)
    html = html.replace("__MARKET__", mlabel)
    html = html.replace("__CASH__", _f(acc.get("cashBalance"), 0))
    html = html.replace("__LINE__", _f(acc.get("lineAvailable"), 0))
    html = html.replace("__PFROWS__", pf_rows)
    html = html.replace("__TPVAL__", tp_val)
    html = html.replace("__TPPROFIT__", ("+" if tp_profit >= 0 else "") + _f(tp_profit, 0))
    html = html.replace("__TPPC__", ("+" if tp_pc >= 0 else "") + _f(tp_pc, 1))
    html = html.replace("__TPCOL__", tp_col)
    html = html.replace("__WLROWS__", wl_rows)
    Path(out_path).write_text(html, encoding="utf-8")
    print(f"✅ สร้าง {out_path} · พอร์ต {len(rows)} ตัว · watchlist {len(watch)} ตัว · {mlabel}")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="th"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>พอร์ต + ราคาสด (Settrade)</title>
<style>
 :root{--bg:#0e1117;--card:#161b22;--bd:#222a35;--tx:#e6e9ef;--mut:#8b95a3;--grn:#26c281;--red:#ff5a5a;}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--tx);font-family:-apple-system,"Segoe UI",Roboto,sans-serif;font-size:17px}
 .wrap{max-width:920px;margin:0 auto;padding:18px}
 h1{font-size:23px;margin:0 0 2px} h2{font-size:19px;margin:26px 0 10px}
 .sub{color:var(--mut);font-size:14px;margin-bottom:14px}
 .cards{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:6px}
 .card{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:14px 18px;flex:1;min-width:150px}
 .card b{display:block;font-size:24px} .card span{color:var(--mut);font-size:14px}
 table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--bd);border-radius:12px;overflow:hidden;font-size:16px}
 th,td{padding:11px 12px;text-align:left;border-bottom:1px solid var(--bd)}
 th{color:var(--mut);font-weight:600;font-size:14px}
 td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
 tr:last-child td{border-bottom:none}
 .up{color:var(--grn)} .down{color:var(--red)}
 .tot{background:#1a2130;font-weight:700}
 .foot{color:var(--mut);font-size:13px;margin-top:22px;line-height:1.7}
</style></head><body><div class="wrap">
 <h1>💼 พอร์ต + ราคาสด</h1>
 <div class="sub">🕐 อัปเดต: <b style="color:#aab3c0">__UPDATED__</b> · __MARKET__ · ข้อมูล: Settrade (InnovestX)</div>
 <div class="cards">
   <div class="card"><b class="up">__CASH__</b><span>เงินสดพร้อมซื้อ (บาท)</span></div>
   <div class="card"><b>__LINE__</b><span>วงเงินคงเหลือ (บาท)</span></div>
   <div class="card"><b class="__TPCOL__">__TPPROFIT__</b><span>กำไร/ขาดทุนพอร์ต (__TPPC__%)</span></div>
 </div>

 <h2>📦 พอร์ตของฉัน</h2>
 <table><thead><tr><th>หุ้น</th><th class="num">จำนวน</th><th class="num">ต้นทุนเฉลี่ย</th><th class="num">ราคาล่าสุด</th><th class="num">มูลค่า</th><th class="num">กำไร/ขาดทุน</th></tr></thead>
 <tbody>__PFROWS__<tr class="tot"><td>รวม</td><td></td><td></td><td></td><td class="num">__TPVAL__</td><td class="num __TPCOL__">__TPPROFIT__ (__TPPC__%)</td></tr></tbody></table>

 <h2>👀 ราคาสด — รายการเฝ้าดู</h2>
 <table><thead><tr><th>หุ้น</th><th class="num">ล่าสุด</th><th class="num">เปลี่ยน%</th><th class="num">ปันผล%</th><th class="num">PE</th><th class="num">PBV</th></tr></thead>
 <tbody>__WLROWS__</tbody></table>
 <div class="sub" style="margin-top:8px">🎒 = หุ้นที่ถืออยู่ในพอร์ต</div>

 <div class="foot">ราคาสดจาก Settrade Open API (InnovestX) · เป็นข้อมูล ไม่ใช่คำแนะนำลงทุน · หน้านี้อ่านอย่างเดียว ไม่มีคำสั่งซื้อขาย</div>
</div></body></html>"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="live.html")
    build(ap.parse_args().out)
