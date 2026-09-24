#!/usr/bin/env python3
"""
เมลเตือนหุ้นสัญญาณซื้อ "ทันที" บนกราฟ 4H (240m) — ส่งเมื่อสัญญาณ "เพิ่งเกิดใหม่"
- สแกน universe บน 4H แท่งที่ปิดแล้ว (final=1 = ไม่ repaint)
- สัญญาณ = ราคา>EMA200 (ขาขึ้น) และ (ย่อ >=10% จากไฮ 60 แท่ง หรือ RSI<40)  + วอลลุ่ม
- **กันส่งซ้ำด้วย state** (signals_4h_state.json) — ส่งเฉพาะตัวที่เพิ่งเข้าสัญญาณ ไม่ส่งซ้ำระหว่างที่ยังค้างสัญญาณ
- รันถี่ช่วงตลาด (cron) → ได้ผลใกล้เรียลไทม์ต่อการปิดแท่ง 4H (13:00 / 17:00)

env: STOCK_API_KEY · RESEND_API_KEY · MAIL_TO · MAIL_FROM · SCAN_API_BASE
รัน: python signal_email_4h.py [--dry]
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = os.environ.get("SCAN_API_BASE", "https://live.atlog.asia").rstrip("/")
KEY = os.environ.get("STOCK_API_KEY", "").strip()
MAIL_TO = os.environ.get("MAIL_TO", "info@atls.co.th").strip()
MAIL_FROM = os.environ.get("MAIL_FROM", "SET Buy Signals <no-reply@lifebazi.com>").strip()
STATE = Path(__file__).parent / "signals_4h_state.json"
BKK = timezone(timedelta(hours=7))
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"}
INTERVAL = "240m"

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
    sig = {}
    bar_close = ""
    for i in range(0, len(UNIVERSE), 20):
        chunk = ",".join(UNIVERSE[i:i + 20])
        try:
            d = _get("%s/api/candles?symbols=%s&interval=%s&limit=500&final=1&key=%s"
                     % (BASE, chunk, INTERVAL, KEY))["data"]
        except Exception as e:
            print("chunk error:", str(e)[:80]); continue
        for s, v in d.items():
            cs = v.get("candles") if isinstance(v, dict) else None
            if not cs or len(cs) < 210 or "error" in v:
                continue
            bar_close = cs[-1]["bar_close_time"]
            cl = [c["close"] for c in cs]; hi = [c["high"] for c in cs]; vol = [c["volume"] for c in cs]
            last = cl[-1]; e200 = _ema(cl, 200); r = _rsi(cl); hi60 = max(hi[-61:-1])
            up = last > e200; dip = last <= 0.90 * hi60
            if up and (dip or r < 40):
                pct = (last / hi60 - 1) * 100
                v20 = sum(vol[-21:-1]) / 20 if len(vol) >= 21 else (sum(vol) / max(len(vol), 1))
                vr = vol[-1] / v20 if v20 else 0.0
                chg = (last / cl[-2] - 1) * 100 if len(cl) >= 2 else 0.0
                vstat = "✅ หนุน" if (vr >= 1.3 and chg >= 0) else ("🟡 ปกติ" if vr >= 0.8 else "🔴 บาง")
                sig[s] = {"sym": s, "last": last, "rsi": r, "pct": pct, "vr": vr, "vstat": vstat,
                          "reason": ("ย่อ %.0f%% จากไฮ" % pct) if dip else ("RSI ต่ำ %.0f" % r),
                          "bar_close": cs[-1]["bar_close_time"]}
    return sig, bar_close


def build_email(newsig, bar_close):
    ts = ""
    try:
        ts = datetime.fromisoformat(bar_close).astimezone(BKK).strftime("%d/%m %H:%M")
    except Exception:
        ts = bar_close[:16]
    syms = ", ".join(newsig.keys())
    subj = "⚡ สัญญาณซื้อใหม่ (กราฟ 4H) %s — %s" % (ts, syms)
    items = sorted(newsig.values(), key=lambda x: (x["vr"]), reverse=True)
    tl = ["สัญญาณซื้อใหม่บนกราฟ 4H (แท่งปิด %s) — ย่อในขาขึ้น · จาก live.atlog.asia" % ts, ""]
    rows = ""
    for b in items:
        tl.append("- %-7s %8.2f  RSI %3.0f  วอลลุ่ม %.1fx %s  · %s"
                  % (b["sym"], b["last"], b["rsi"], b["vr"], b["vstat"], b["reason"]))
        rows += ('<tr><td style="border:1px solid #dbe3ee;padding:6px 10px"><b>%s</b></td>'
                 '<td style="border:1px solid #dbe3ee;padding:6px 10px;text-align:right">%.2f</td>'
                 '<td style="border:1px solid #dbe3ee;padding:6px 10px;text-align:right">%.0f</td>'
                 '<td style="border:1px solid #dbe3ee;padding:6px 10px;text-align:right">%.1fx %s</td>'
                 '<td style="border:1px solid #dbe3ee;padding:6px 10px">%s</td></tr>'
                 % (b["sym"], b["last"], b["rsi"], b["vr"], b["vstat"], b["reason"]))
    tl += ["", "สัญญาณ 4H = ราคาเหนือ EMA200 + ย่อ >=10% จากไฮ หรือ RSI ต่ำ · ส่งเฉพาะตัวที่ 'เพิ่งเกิดสัญญาณ' (ไม่ส่งซ้ำ)",
           "วอลลุ่ม: ✅ หนุน(>=1.3x+เขียว) · 🟡 ปกติ · 🔴 บาง=ยังไม่ยืนยัน",
           "ไม่ใช่คำแนะนำมีใบอนุญาต — ตัดสินใจ+คุมความเสี่ยงเอง"]
    html = ('<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#1a1f2b;max-width:600px">'
            '<h2 style="color:#0e3a6e;margin:0 0 2px">⚡ สัญญาณซื้อใหม่ — กราฟ 4H</h2>'
            '<div style="color:#5a6472;font-size:13px;margin-bottom:12px">แท่ง 4H ปิด %s · จาก live.atlog.asia · เพิ่งเกิด %d ตัว</div>'
            '<table style="border-collapse:collapse;font-size:14px">'
            '<tr style="background:#eef3f9"><th style="border:1px solid #dbe3ee;padding:6px 10px;text-align:left">หุ้น</th>'
            '<th style="border:1px solid #dbe3ee;padding:6px 10px;text-align:right">ราคา</th>'
            '<th style="border:1px solid #dbe3ee;padding:6px 10px;text-align:right">RSI</th>'
            '<th style="border:1px solid #dbe3ee;padding:6px 10px;text-align:right">วอลลุ่ม</th>'
            '<th style="border:1px solid #dbe3ee;padding:6px 10px;text-align:left">เหตุผล</th></tr>%s</table>'
            '<p style="font-size:12px;color:#555;line-height:1.6">สัญญาณ 4H "ย่อในขาขึ้น" · ส่งเฉพาะตัวที่เพิ่งเกิด (ไม่ส่งซ้ำ) · '
            'วอลลุ่ม ✅ หนุน(≥1.3x+เขียว)/🟡ปกติ/🔴บาง=ยังไม่ยืนยัน<br>'
            'ไม่ใช่คำแนะนำมีใบอนุญาต — ตัดสินใจและคุมความเสี่ยงเอง</p></div>' % (ts, len(items), rows))
    return subj, "\n".join(tl), html


def send_resend(subj, text, html):
    payload = {"from": MAIL_FROM, "to": [MAIL_TO], "subject": subj, "text": text, "html": html}
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + os.environ["RESEND_API_KEY"],
                 "Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": UA["User-Agent"]})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=25).read())
    except urllib.error.HTTPError as e:
        raise SystemExit("Resend error %s: %s" % (e.code, e.read().decode(errors="replace")[:300]))


def main():
    if not KEY:
        raise SystemExit("ต้องตั้ง STOCK_API_KEY")
    dry = "--dry" in sys.argv
    cur, bar_close = scan()
    try:
        prev = set(json.loads(STATE.read_text()).get("active", []))
    except Exception:
        prev = set()
    if not bar_close:
        # สแกนไม่ได้เลย (API ล่ม/token หมด) → ห้ามแตะ state ไม่งั้นรอบหน้าจะนับทุกตัวเป็น "ใหม่" แล้วส่งซ้ำ
        raise SystemExit("สแกนไม่ได้ (API ไม่ตอบ) — ไม่แตะ state รอบหน้าลองใหม่")
    cur_syms = set(cur.keys())
    new = {s: cur[s] for s in cur_syms if s not in prev}     # เพิ่งเกิดสัญญาณ (ไม่อยู่ในรอบก่อน)
    print("แท่ง4H ปิด %s · สัญญาณตอนนี้ %d (%s) · เพิ่งเกิดใหม่ %d (%s)"
          % (bar_close[:16], len(cur_syms), ",".join(sorted(cur_syms)), len(new), ",".join(sorted(new))))
    if new:
        subj, text, html = build_email(new, bar_close)
        if dry:
            print("\n[DRY]", subj, "\n", text)
        else:
            r = send_resend(subj, text, html)   # ล้ม → SystemExit ก่อนเขียน state → รอบหน้าส่งใหม่ (ไม่หลุด)
            print("ส่งเมลแล้ว:", r.get("id", r))
    else:
        print("ไม่มีสัญญาณใหม่ — ไม่ส่งเมล")
    if not dry:   # เขียน state หลังส่งสำเร็จเท่านั้น · ไม่มี timestamp → state เดิม = ไฟล์เดิม = ไม่ commit ถี่
        STATE.write_text(json.dumps({"active": sorted(cur_syms), "bar_close": bar_close},
                                    ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
