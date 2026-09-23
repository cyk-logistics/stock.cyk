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


def scan():
    buys = []
    last_date = ""
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
                buys.append({"sym": s, "last": last, "rsi": r, "pct": pct, "reason": reason,
                             "vr": vr, "vstat": vstat, "conf_vol": conf_vol})
    buys.sort(key=lambda x: (x["conf_vol"], x["vr"]), reverse=True)   # วอลลุ่มหนุนขึ้นก่อน
    return buys, last_date


def build_email(buys, last_date):
    subj = "🟢 สัญญาณซื้อหุ้น (ย่อในขาขึ้น) %s — %d ตัว" % (last_date, len(buys))
    tlines = ["สัญญาณซื้อหุ้น (ย่อในขาขึ้น) — แท่งล่าสุด %s · จาก live.atlog.asia" % last_date, ""]
    rows = ""
    for b in buys:
        tlines.append("- %-7s %8.2f  RSI %3.0f  วอลลุ่ม %.1fx %s  · %s"
                      % (b["sym"], b["last"], b["rsi"], b["vr"], b["vstat"], b["reason"]))
        rows += ('<tr><td style="border:1px solid #dbe3ee;padding:6px 10px"><b>%s</b></td>'
                 '<td style="border:1px solid #dbe3ee;padding:6px 10px;text-align:right">%.2f</td>'
                 '<td style="border:1px solid #dbe3ee;padding:6px 10px;text-align:right">%.0f</td>'
                 '<td style="border:1px solid #dbe3ee;padding:6px 10px;text-align:right">%.1fx %s</td>'
                 '<td style="border:1px solid #dbe3ee;padding:6px 10px">%s</td></tr>'
                 % (b["sym"], b["last"], b["rsi"], b["vr"], b["vstat"], b["reason"]))
    tlines += ["", ("สัญญาณ = ราคาเหนือ EMA200 (ขาขึ้น) และย่อ >=10% จากไฮ 60 วัน หรือ RSI ต่ำ = จังหวะย่อซื้อในขาขึ้น "
                    "(backtest 10 ปี +5%/120วัน ชนะ 57%)"),
               "วอลลุ่ม: ✅ หนุน (>=1.3x + เขียว) · 🟡 ปกติ · 🔴 บาง = ยังไม่ยืนยัน (รอวันวอลลุ่มพุ่งก่อนหนักมือ)",
               "หมายเหตุ: ใช้แท่งที่ปิดแล้ว · เป็นจังหวะทยอยเข้า ไม่ใช่การันตี · ไม่ใช่คำแนะนำมีใบอนุญาต ตัดสินใจ+คุมความเสี่ยงเอง"]
    html = ('<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#1a1f2b;max-width:600px">'
            '<h2 style="color:#0e3a6e;margin:0 0 2px">🟢 สัญญาณซื้อหุ้น — ย่อในขาขึ้น</h2>'
            '<div style="color:#5a6472;font-size:13px;margin-bottom:12px">แท่งล่าสุด %s · จาก live.atlog.asia · พบ %d ตัว</div>'
            '<table style="border-collapse:collapse;font-size:14px">'
            '<tr style="background:#eef3f9"><th style="border:1px solid #dbe3ee;padding:6px 10px;text-align:left">หุ้น</th>'
            '<th style="border:1px solid #dbe3ee;padding:6px 10px;text-align:right">ราคา</th>'
            '<th style="border:1px solid #dbe3ee;padding:6px 10px;text-align:right">RSI</th>'
            '<th style="border:1px solid #dbe3ee;padding:6px 10px;text-align:right">วอลลุ่ม</th>'
            '<th style="border:1px solid #dbe3ee;padding:6px 10px;text-align:left">เหตุผล</th></tr>%s</table>'
            '<p style="font-size:13px;color:#333;margin-top:14px;line-height:1.6"><b>สัญญาณนี้:</b> ราคาเหนือ EMA200 (ขาขึ้น) '
            'และย่อ ≥10%% จากไฮ 60 วัน (หรือ RSI ต่ำ) = จังหวะ "ย่อซื้อในขาขึ้น" ที่ backtest 10 ปีให้ผลดีสุด (+5%%/120วัน ชนะ 57%%)</p>'
            '<p style="font-size:12px;color:#555;line-height:1.6"><b>วอลลุ่ม:</b> ✅ หนุน (≥1.3x + เขียว) · 🟡 ปกติ · 🔴 บาง = ยังไม่ยืนยัน (รอวันวอลลุ่มพุ่งก่อนค่อยหนักมือ)</p>'
            '<p style="font-size:12px;color:#7a8494;line-height:1.6">⚠️ ใช้แท่งที่ปิดแล้ว · ควรรอวอลลุ่มยืนยัน · เป็นจังหวะทยอยเข้า ไม่ใช่การันตี<br>'
            'ไม่ใช่คำแนะนำมีใบอนุญาต — ตัดสินใจและคุมความเสี่ยงเอง</p></div>' % (last_date, len(buys), rows))
    return subj, "\n".join(tlines), html


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
    buys, last_date = scan()
    print("แท่งล่าสุด %s · พบสัญญาณซื้อ %d ตัว: %s" % (last_date, len(buys), ", ".join(b["sym"] for b in buys)))
    if not buys and os.environ.get("SEND_EMPTY", "") not in ("1", "true", "yes"):
        print("ไม่มีสัญญาณวันนี้ — ไม่ส่งเมล (ตั้ง SEND_EMPTY=1 ถ้าอยากให้ส่งทุกวัน)")
        return
    subj, text, html = build_email(buys, last_date)
    if dry:
        print("\n[DRY] subject:", subj, "\n", text)
        return
    if not os.environ.get("RESEND_API_KEY"):
        raise SystemExit("ต้องตั้ง RESEND_API_KEY (ยังไม่ได้ส่ง)")
    r = send_resend(subj, text, html)
    print("ส่งเมลแล้ว:", r.get("id", r))


if __name__ == "__main__":
    main()
