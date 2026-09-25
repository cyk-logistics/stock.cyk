#!/usr/bin/env python3
"""
เมลเตือนหุ้นสัญญาณซื้อรายวัน (ย่อในขาขึ้น) — ส่งผ่าน Resend (เมลระบบของ LifeBazi)
- สแกน universe หุ้นปันผลจาก live.atlog.asia (แท่งรายวัน)
- สัญญาณ = ราคา>EMA200 (ขาขึ้น) และ (ย่อ >=10% จากไฮ 60 วัน  หรือ RSI<40)  = จุดเข้าที่ backtest 10 ปีดีสุด
- รันหลังตลาดปิด (แท่งวันนี้ปิดแล้ว = ไม่ repaint)

env: STOCK_API_KEY (จำเป็น) · RESEND_API_KEY (จำเป็น) · MAIL_TO (ดีฟอลต์ info@atls.co.th)
     MAIL_FROM (ต้องเป็นโดเมนที่ verify กับ Resend เช่น @send.lifebazi.com)
     SCAN_API_BASE (ดีฟอลต์ https://live.atlog.asia) · SEND_EMPTY=1 เพื่อส่งแม้ไม่มีสัญญาณ
รัน: python signal_email.py [--dry]
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

import signal_history
import signal_track

BASE = os.environ.get("SCAN_API_BASE", "https://live.atlog.asia").rstrip("/")
KEY = os.environ.get("STOCK_API_KEY", "").strip()
MAIL_TO = os.environ.get("MAIL_TO", "info@atls.co.th").strip()
MAIL_FROM = os.environ.get("MAIL_FROM", "SET Buy Signals <no-reply@lifebazi.com>").strip()
BKK = timezone(timedelta(hours=7))
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/128 Safari/537.36"}

UNIVERSE = ("PTT,PTTEP,PTTGC,TOP,IRPC,BCP,OR,BANPU,EGCO,RATCH,GULF,GPSC,BGRIM,EA,ADVANC,TRUE,"
            "KBANK,SCB,BBL,KTB,TTB,KKP,TISCO,KTC,SAWAD,MTC,AOT,BEM,BTS,BDMS,BH,CPALL,CPAXT,CPF,"
            "CPN,CRC,HMPRO,GLOBAL,COM7,BJC,MINT,CENTEL,OSP,CBG,TU,SCC,SCGP,IVL,DELTA,KCE,HANA,"
            "WHA,AWC,LH,AP,SPALI").split(",")


def _get(url):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=50).read())


def _ema(vals, p):
    k = 2 / (p + 1)
    e = vals[0]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
    return e


def _rsi(vals, p=14):
    if len(vals) <= p:
        return 50.0
    ag = al = 0.0
    for i in range(1, p + 1):
        d = vals[i] - vals[i - 1]
        ag += max(d, 0); al += max(-d, 0)
    ag /= p; al /= p
    for i in range(p + 1, len(vals)):
        d = vals[i] - vals[i - 1]
        ag = (ag * (p - 1) + max(d, 0)) / p
        al = (al * (p - 1) + max(-d, 0)) / p
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def _is_signal(cl, hi):
    """กฎเข้า: ราคา>EMA200 และ (ปิด <= 90% ของไฮ 60 แท่งก่อนหน้า หรือ RSI<40)"""
    if len(cl) < 210:
        return False
    last = cl[-1]
    return last > _ema(cl, 200) and (last <= 0.90 * max(hi[-61:-1]) or _rsi(cl) < 40)


def scan():
    """คืน (สัญญาณซื้อ, วันที่แท่งล่าสุด, {หุ้น: แท่งรายวัน} ไว้ติดตามหุ้นที่แนะนำ)"""
    buys = []
    last_date = ""
    cmap = {}
    for i in range(0, len(UNIVERSE), 20):
        chunk = ",".join(UNIVERSE[i:i + 20])
        try:
            d = _get("%s/api/candles?symbols=%s&interval=1d&limit=250&final=0&key=%s" % (BASE, chunk, KEY))["data"]
        except Exception as e:
            print("chunk error:", str(e)[:80]); continue
        for s, v in d.items():
            cs = v.get("candles") if isinstance(v, dict) else None
            if not cs or len(cs) < 210 or "error" in v:
                continue
            last_date = cs[-1]["bar_time"][:10]
            cmap[s] = cs
            cl = [c["close"] for c in cs]; hi = [c["high"] for c in cs]; vol = [c["volume"] for c in cs]
            last = cl[-1]; e200 = _ema(cl, 200); e50 = _ema(cl, 50); r = _rsi(cl)
            hi60 = max(hi[-61:-1])
            up = last > e200; dip = last <= 0.90 * hi60
            if up and (dip or r < 40):
                pct = (last / hi60 - 1) * 100
                reason = "ย่อ %.0f%% จากไฮ 60 วัน" % pct if dip else "RSI ต่ำ %.0f" % r
                v20 = sum(vol[-21:-1]) / 20 if len(vol) >= 21 else (sum(vol) / max(len(vol), 1))
                vr = vol[-1] / v20 if v20 else 0.0
                chg = (last / cl[-2] - 1) * 100 if len(cl) >= 2 else 0.0
                conf_vol = vr >= 1.3 and chg >= 0
                vstat = "✅ หนุน" if conf_vol else ("🟡 ปกติ" if vr >= 0.8 else "🔴 บาง")
                new = not _is_signal(cl[:-1], hi[:-1])          # เมื่อวานยังไม่เข้า = สัญญาณเพิ่งเกิด
                buys.append({"sym": s, "last": last, "rsi": r, "pct": pct, "reason": reason,
                             "vr": vr, "vstat": vstat, "conf_vol": conf_vol, "new": new})
    buys.sort(key=lambda x: (x["new"], x["conf_vol"], x["vr"]), reverse=True)   # ใหม่ก่อน แล้ววอลลุ่มหนุน
    return buys, last_date, cmap


TD = 'style="border:1px solid #dbe3ee;padding:6px 9px;%s"'
TH = '<th style="border:1px solid #dbe3ee;padding:6px 9px;text-align:%s">%s</th>'


def _pc(v):
    return "%+.1f%%" % (0.0 if round(v, 1) == 0 else v)


def _clr(v):
    return "#0a8f5a" if v > 0 else ("#c62828" if v < 0 else "#5a6472")


def _dm(d):
    return "%s/%s" % (d[8:10], d[5:7])


def build_email(buys, last_date, held=(), exits=()):
    """เมลรายวัน: 🟢 สัญญาณซื้อ · 🔴 ควรออก (หุ้นที่เคยแนะนำเกิดสัญญาณออก) · 📌 ติดตามหุ้นที่แนะนำที่ยังถืออยู่"""
    nb, nx = len(buys), len(exits)
    if nb and nx:
        subj = "🟢 ซื้อ %d · 🔴 ควรออก %d — หุ้นปันผล %s" % (nb, nx, last_date)
    elif nx:
        subj = "🔴 สัญญาณควรออก %d ตัว — หุ้นที่เคยแนะนำ %s" % (nx, last_date)
    else:
        subj = "🟢 สัญญาณซื้อหุ้น (ย่อในขาขึ้น) %s — %d ตัว" % (last_date, nb)
    tl = ["หุ้นปันผล — แท่งล่าสุด %s · จาก live.atlog.asia" % last_date, ""]
    parts = []
    if exits:
        tl.append("🔴 ควรออก (หุ้นที่เคยแนะนำ)")
        rows = ""
        for p in exits:
            e = p["exit"]; r = (e["exit_price"] / p["entry"] - 1) * 100
            tl.append("- %-7s แนะนำ %s @%.2f → ออก %s @%.2f  %s  · %s"
                      % (p["sym"], _dm(p["entry_date"]), p["entry"], _dm(e["exit_date"]), e["exit_price"], _pc(r), e["reason"]))
            rows += ("<tr><td %s><b>%s</b></td><td %s>%s</td><td %s>%.2f</td><td %s>%.2f</td><td %s><b>%s</b></td><td %s>%s</td></tr>"
                     % (TD % "", p["sym"], TD % "", _dm(p["entry_date"]), TD % "text-align:right", p["entry"],
                        TD % "text-align:right", e["exit_price"], TD % ("text-align:right;color:%s" % _clr(r)), _pc(r),
                        TD % "", e["reason"]))
        parts.append('<h3 style="color:#c62828;margin:18px 0 6px">🔴 ควรออก — หุ้นที่เคยแนะนำ</h3>'
                     '<table style="border-collapse:collapse;font-size:14px"><tr style="background:#fdeeee">%s%s%s%s%s%s</tr>%s</table>'
                     % (TH % ("left", "หุ้น"), TH % ("left", "แนะนำ"), TH % ("right", "ราคาแนะนำ"), TH % ("right", "ราคาออก"),
                        TH % ("right", "ผล"), TH % ("left", "สัญญาณ"), rows))
        tl.append("")
    if buys:
        tl.append("🟢 สัญญาณซื้อ (ย่อในขาขึ้น)")
        rows = ""
        for b in buys:
            tag = "🆕 " if b.get("new") else ""
            tl.append("- %s%-7s %8.2f  RSI %3.0f  วอลลุ่ม %.1fx %s  · %s"
                      % (tag, b["sym"], b["last"], b["rsi"], b["vr"], b["vstat"], b["reason"]))
            rows += ("<tr><td %s><b>%s</b>%s</td><td %s>%.2f</td><td %s>%.0f</td><td %s>%.1fx %s</td><td %s>%s</td></tr>"
                     % (TD % "", b["sym"], ' <span style="color:#0a8f5a;font-size:12px">🆕 ใหม่</span>' if b.get("new") else "",
                        TD % "text-align:right", b["last"], TD % "text-align:right", b["rsi"],
                        TD % "text-align:right", b["vr"], b["vstat"], TD % "", b["reason"]))
        parts.append('<h3 style="color:#0a8f5a;margin:18px 0 6px">🟢 สัญญาณซื้อ — ย่อในขาขึ้น</h3>'
                     '<table style="border-collapse:collapse;font-size:14px"><tr style="background:#eef3f9">%s%s%s%s%s</tr>%s</table>'
                     '<p style="font-size:12px;color:#555;margin:6px 0 0">🆕 = สัญญาณเพิ่งเกิดวันนี้ · ไม่มีป้าย = ยังอยู่ในโซนซื้อต่อจากวันก่อน</p>'
                     % (TH % ("left", "หุ้น"), TH % ("right", "ราคา"), TH % ("right", "RSI"), TH % ("right", "วอลลุ่ม"),
                        TH % ("left", "เหตุผล"), rows))
        tl.append("")
    if held:
        tl.append("📌 หุ้นที่แนะนำ — ยังถืออยู่ (จุดตัดขาดทุน -%d%% · ครบรอบ %d วัน)" % (signal_track.STOP, signal_track.HOLD))
        rows = ""
        for p in held:
            st = " · ".join(p["tags"]) if p["tags"] else "ถือต่อ"
            tl.append("- %-7s แนะนำ %s @%.2f → %.2f  %s  ถือ %d/%d วัน  ตัดขาดทุน %.2f (ห่าง %.0f%%)  %s"
                      % (p["sym"], _dm(p["entry_date"]), p["entry"], p["last"], _pc(p["chg"]), p["days"],
                         signal_track.HOLD, p["stop"], p["to_stop"], st))
            rows += ("<tr><td %s><b>%s</b></td><td %s>%s%s</td><td %s>%.2f</td><td %s>%.2f</td><td %s><b>%s</b></td>"
                     "<td %s>%d/%d</td><td %s>%.2f <span style=\"color:#7a8494\">(ห่าง %.0f%%)</span></td><td %s>%s</td></tr>"
                     % (TD % "", p["sym"], TD % "white-space:nowrap", _dm(p["entry_date"]),
                        (" ×%d" % p["times"]) if p["times"] > 1 else "", TD % "text-align:right", p["entry"],
                        TD % "text-align:right", p["last"], TD % ("text-align:right;color:%s" % _clr(p["chg"])), _pc(p["chg"]),
                        TD % "text-align:right", p["days"], signal_track.HOLD, TD % "text-align:right;white-space:nowrap",
                        p["stop"], p["to_stop"], TD % "", st))
        parts.append('<h3 style="color:#0e3a6e;margin:18px 0 6px">📌 หุ้นที่แนะนำ — ยังถืออยู่ (%d ตัว)</h3>'
                     '<table style="border-collapse:collapse;font-size:14px"><tr style="background:#eef3f9">%s%s%s%s%s%s%s%s</tr>%s</table>'
                     % (len(held), TH % ("left", "หุ้น"), TH % ("left", "แนะนำ"), TH % ("right", "ราคาแนะนำ"), TH % ("right", "ล่าสุด"),
                        TH % ("right", "เปลี่ยน"), TH % ("right", "ถือ (วัน)"), TH % ("right", "จุดตัดขาดทุน"), TH % ("left", "สถานะ"), rows))
        tl.append("")
    tl += [("สัญญาณซื้อ = ราคาเหนือ EMA200 (ขาขึ้น) และย่อ >=10% จากไฮ 60 วัน หรือ RSI ต่ำ = จังหวะย่อซื้อในขาขึ้น "
            "(backtest 10 ปี +5%/120วัน ชนะ 57%)"),
           "วอลลุ่ม: ✅ หนุน (>=1.3x + เขียว) · 🟡 ปกติ · 🔴 บาง = ยังไม่ยืนยัน (รอวันวอลลุ่มพุ่งก่อนหนักมือ)",
           "ควรออก: 🔴 ต่ำกว่าราคาแนะนำ %d%% (ตัดขาดทุน) · ⏰ ถือครบ %d วันทำการ" % (signal_track.STOP, signal_track.HOLD),
           signal_track.STAT_NOTE,
           "หมายเหตุ: ใช้แท่งที่ปิดแล้ว · ไม่ใช่การันตี · ไม่ใช่คำแนะนำมีใบอนุญาต ตัดสินใจ+คุมความเสี่ยงเอง"]
    html = ('<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#1a1f2b;max-width:720px">'
            '<h2 style="color:#0e3a6e;margin:0 0 2px">หุ้นปันผล — ย่อซื้อในขาขึ้น</h2>'
            '<div style="color:#5a6472;font-size:13px">แท่งล่าสุด %s · จาก live.atlog.asia · ซื้อ %d · ควรออก %d · ถืออยู่ %d</div>%s'
            '<p style="font-size:13px;color:#333;margin-top:16px;line-height:1.6"><b>สัญญาณซื้อ:</b> ราคาเหนือ EMA200 (ขาขึ้น) '
            'และย่อ ≥10%% จากไฮ 60 วัน (หรือ RSI ต่ำ) = จังหวะ "ย่อซื้อในขาขึ้น" ที่ backtest 10 ปีให้ผลดีสุด (+5%%/120วัน ชนะ 57%%)<br>'
            '<b>ควรออก:</b> 🔴 ราคาต่ำกว่าราคาแนะนำ %d%% (ตัดขาดทุน) · ⏰ ถือครบ %d วันทำการ (~6 เดือน)</p>'
            '<p style="font-size:12px;color:#555;line-height:1.6">%s</p>'
            '<p style="font-size:12px;color:#555;line-height:1.6"><b>วอลลุ่ม:</b> ✅ หนุน (≥1.3x + เขียว) · 🟡 ปกติ · 🔴 บาง = ยังไม่ยืนยัน</p>'
            '<p style="font-size:12px;color:#7a8494;line-height:1.6">⚠️ ใช้แท่งที่ปิดแล้ว · เป็นจังหวะทยอยเข้า ไม่ใช่การันตี<br>'
            'ไม่ใช่คำแนะนำมีใบอนุญาต — ตัดสินใจและคุมความเสี่ยงเอง</p></div>'
            % (last_date, nb, nx, len(held), "".join(parts), signal_track.STOP, signal_track.HOLD, signal_track.STAT_NOTE))
    return subj, "\n".join(tl), html


def send_resend(subj, text, html):
    payload = {"from": MAIL_FROM, "to": [MAIL_TO], "subject": subj, "text": text, "html": html}
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + os.environ["RESEND_API_KEY"],
                 "Content-Type": "application/json", "Accept": "application/json",
                 # ⚠️ ต้องมี browser UA ไม่งั้น Cloudflare หน้า Resend บล็อก (error 1010 / 403)
                 "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=25).read())
    except urllib.error.HTTPError as e:
        raise SystemExit("Resend error %s: %s" % (e.code, e.read().decode(errors="replace")[:300]))


def main():
    if not KEY:
        raise SystemExit("ต้องตั้ง STOCK_API_KEY")
    dry = "--dry" in sys.argv
    buys, last_date, cmap = scan()
    if not last_date:
        # ดึงแท่งไม่ได้สักตัว (API ล่ม/เครื่อง mini หลุด) ≠ "ไม่มีสัญญาณ" → ให้ run ขึ้นแดง ไม่เงียบหลอก
        raise SystemExit("สแกนไม่ได้ — ดึงข้อมูลจาก %s ไม่ได้เลย (ไม่ใช่ 'ไม่มีสัญญาณ')" % BASE)
    # ติดตามหุ้นที่เคยแนะนำ (ประวัติเมลรายวัน + 4H) → ยังถือ / เกิดสัญญาณควรออก
    held, exits = signal_track.track(signal_history.load(), signal_history.load_exits(), cmap)
    print("แท่งล่าสุด %s · สัญญาณซื้อ %d ตัว: %s · ควรออก %d: %s · ถืออยู่ %d"
          % (last_date, len(buys), ", ".join(("🆕" if b["new"] else "") + b["sym"] for b in buys),
             len(exits), ", ".join(p["sym"] for p in exits), len(held)))
    if not buys and not exits and os.environ.get("SEND_EMPTY", "") not in ("1", "true", "yes"):
        print("ไม่มีสัญญาณซื้อ/ออกวันนี้ — ไม่ส่งเมล (ตั้ง SEND_EMPTY=1 ถ้าอยากให้ส่งทุกวัน)")
        return
    subj, text, html = build_email(buys, last_date, held, exits)
    if dry:
        print("\n[DRY] subject:", subj, "\n", text)
        return
    if not os.environ.get("RESEND_API_KEY"):
        raise SystemExit("ต้องตั้ง RESEND_API_KEY (ยังไม่ได้ส่ง)")
    r = send_resend(subj, text, html)
    print("ส่งเมลแล้ว:", r.get("id", r))
    eid = r.get("id", "") if isinstance(r, dict) else ""
    # เก็บประวัติหุ้นที่แนะนำ → ติดตาม/สรุปสิ้นเดือน · บันทึกสัญญาณออกที่แจ้งแล้ว (ไม่แจ้งซ้ำ)
    signal_history.append("1D", [{"bar": last_date, "sym": b["sym"], "price": round(b["last"], 4), "new": b["new"],
                                  "rsi": round(b["rsi"], 1), "pct": round(b["pct"], 1), "vr": round(b["vr"], 2),
                                  "vstat": b["vstat"], "reason": b["reason"]} for b in buys], email_id=eid)
    signal_history.append_exits([signal_track.exit_record(p) for p in exits], email_id=eid)



if __name__ == "__main__":
    main()
