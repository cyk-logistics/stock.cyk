#!/usr/bin/env python3
"""
สแกนหุ้นน่าสนใจรายวัน = ข่าว × กราฟ × วอลลุ่ม → ส่ง LINE
- ดึงข้อมูลจาก live.atlog.asia (SET จริง + ข่าว Kaohoon) ผ่าน API key
- ให้คะแนน 3 ชั้น: (1) ข่าวสด (2) กราฟ/เทรนด์เทียบ EMA (3) วอลลุ่มยืนยัน
- ส่งสรุป top อันดับเข้า LINE ผ่านสะพาน n8n เดิม (STOCK_LINE_HOOK)

env: STOCK_API_KEY (จำเป็น) · SCAN_API_BASE (ดีฟอลต์ https://live.atlog.asia)
     STOCK_LINE_HOOK / DISCORD_WEBHOOK (ปลายทางแจ้งเตือน) · SCAN_TOP (ดีฟอลต์ 7)
รัน: python scan_daily.py [--dry]   (--dry = พรีวิว ไม่ส่ง)
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta

BASE = os.environ.get("SCAN_API_BASE", "https://live.atlog.asia").rstrip("/")
KEY = os.environ.get("STOCK_API_KEY", "").strip()
TOP = int(os.environ.get("SCAN_TOP", "7"))
BKK = timezone(timedelta(hours=7))
UA = "scan-daily/1.0"

# watchlist แยกกลุ่ม (คัดตัวสภาพคล่องดี)
SECTORS = {
    "แบงก์": ["KBANK", "SCB", "KTB", "BBL", "KKP", "TISCO"],
    "พลังงาน": ["PTT", "PTTEP", "TOP", "BCP", "IRPC", "GULF"],
    "อิเล็ก/AI": ["DELTA", "HANA", "KCE"],
    "ค้าปลีก": ["CPALL", "CPAXT", "BJC", "HMPRO"],
    "สื่อสาร": ["ADVANC", "TRUE"],
    "ไฟแนนซ์": ["MTC", "SAWAD", "TIDLOR"],
    "ขนส่ง/ท่องเที่ยว": ["AOT", "MINT", "CENTEL"],
    "รพ.": ["BDMS", "BH"],
}
SYM2SEC = {s: sec for sec, lst in SECTORS.items() for s in lst}


def _get(path):
    url = "%s%s%skey=%s" % (BASE, path, ("&" if "?" in path else "?"), KEY)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def _ema(vals, period):
    if len(vals) < period:
        return None
    k = 2 / (period + 1)
    e = vals[0]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
    return e


def _analyze(sym):
    try:
        c = _get("/api/candles/%s?interval=1d&limit=60&final=1" % sym)
        cs = c.get("candles") or []
    except Exception:
        return None
    if len(cs) < 25:
        return None
    closes = [x["close"] for x in cs]
    highs = [x["high"] for x in cs]
    vols = [x["volume"] for x in cs]
    last = closes[-1]
    ema20, ema50 = _ema(closes, 20), _ema(closes, 50)
    vol20 = sum(vols[-21:-1]) / 20 if len(vols) >= 21 else (sum(vols) / len(vols))
    volratio = (vols[-1] / vol20) if vol20 else 0
    hi20 = max(highs[-21:-1]) if len(highs) >= 21 else max(highs[:-1] or highs)
    ret5 = (last / closes[-6] - 1) * 100 if len(closes) > 6 else 0
    # ข่าว
    try:
        news = (_get("/api/news/%s?limit=3" % sym).get("news")) or []
    except Exception:
        news = []
    fresh = _fresh_news(news)
    # คะแนน 3 ชั้น
    tech = 0
    if ema20 and last > ema20:
        tech += 2
    if ema50 and last > ema50:
        tech += 2
    if ema20 and ema50 and ema20 > ema50:
        tech += 2
    breakout = last >= hi20
    if breakout:
        tech += 2
    elif last >= 0.99 * hi20:
        tech += 1
    if ret5 > 0:
        tech += 1
    vscore = 2 if volratio >= 1.5 else (1 if volratio >= 1.2 else 0)
    nscore = 2 if fresh else (1 if news else 0)
    score = tech + vscore + nscore
    return {
        "sym": sym, "sec": SYM2SEC.get(sym, "-"), "last": last, "ret5": ret5,
        "above20": bool(ema20 and last > ema20), "above50": bool(ema50 and last > ema50),
        "uptrend": bool(ema20 and ema50 and ema20 > ema50), "breakout": breakout,
        "volratio": round(volratio, 2), "score": score, "tech": tech, "vscore": vscore,
        "nscore": nscore, "fresh": fresh, "headline": (news[0]["title"] if news else ""),
    }


def _fresh_news(news, days=3):
    """มีข่าวใหม่ภายใน N วันไหม (อ่าน pubDate RFC822)"""
    if not news:
        return False
    now = datetime.now(timezone.utc)
    for n in news:
        pd = n.get("published") or ""
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
            try:
                dt = datetime.strptime(pd, fmt)
                if (now - dt.astimezone(timezone.utc)).days <= days:
                    return True
                break
            except Exception:
                continue
    return False


def _tag(r):
    t = []
    if r["breakout"]:
        t.append("เบรกไฮ")
    if r["above20"] and r["above50"]:
        t.append("เหนือ EMA20/50")
    elif r["above20"]:
        t.append("เหนือ EMA20")
    if r["volratio"] >= 1.5:
        t.append("วอลลุ่ม %.1fx" % r["volratio"])
    return " · ".join(t) if t else "ทรงตัว"


def build_text(ranked, sec_rank, today):
    lines = ["📊 สแกนหุ้นน่าสนใจ — ข่าว×กราฟ×วอลลุ่ม (%s)" % today,
             "กลุ่มเด่น: " + ", ".join("%s(%.1f)" % (s, sc) for s, sc in sec_rank[:3]), ""]
    medal = ["🥇", "🥈", "🥉"] + ["▫️"] * 20
    for i, r in enumerate(ranked):
        head = (" · ข่าว: " + r["headline"][:52]) if r["headline"] else ""
        lines.append("%s %s %.2f (%+.1f%%) [%s] · %s%s"
                     % (medal[i], r["sym"], r["last"], r["ret5"], r["sec"], _tag(r), head))
    lines.append("")
    lines.append("คะแนน = ข่าวสด + เทรนด์/EMA + วอลลุ่มยืนยัน · ไม่ใช่คำแนะนำมีใบอนุญาต ตัดสินใจ+คุมเสี่ยงเอง")
    return "\n".join(lines)


def build_flex(ranked, sec_rank, today):
    rows = []
    medal = ["🥇", "🥈", "🥉"] + ["▫️"] * 20
    for i, r in enumerate(ranked):
        rows.append({"type": "box", "layout": "vertical", "margin": "md", "contents": [
            {"type": "box", "layout": "baseline", "contents": [
                {"type": "text", "text": "%s %s" % (medal[i], r["sym"]), "weight": "bold",
                 "size": "sm", "color": "#e6e9ef", "flex": 4},
                {"type": "text", "text": "%.2f (%+.1f%%)" % (r["last"], r["ret5"]),
                 "size": "sm", "color": ("#26c281" if r["ret5"] >= 0 else "#ff5a5a"),
                 "align": "end", "flex": 3}]},
            {"type": "text", "text": "%s · %s" % (r["sec"], _tag(r)), "size": "xxs",
             "color": "#8b95a3", "wrap": True},
        ] + ([{"type": "text", "text": "📰 " + r["headline"][:60], "size": "xxs",
               "color": "#b0b8c4", "wrap": True}] if r["headline"] else [])})
    return {"type": "flex", "altText": "สแกนหุ้นน่าสนใจ %s" % today, "contents": {
        "type": "bubble", "size": "mega",
        "header": {"type": "box", "layout": "vertical", "backgroundColor": "#0e3a6e", "contents": [
            {"type": "text", "text": "📊 หุ้นน่าสนใจวันนี้", "weight": "bold", "color": "#ffffff", "size": "md"},
            {"type": "text", "text": "ข่าว × กราฟ × วอลลุ่ม · %s" % today, "color": "#cfe0f5", "size": "xxs"},
            {"type": "text", "text": "กลุ่มเด่น: " + ", ".join(s for s, _ in sec_rank[:3]),
             "color": "#ffd93d", "size": "xxs", "margin": "sm", "wrap": True}]},
        "body": {"type": "box", "layout": "vertical", "backgroundColor": "#0e1117", "contents": rows},
        "footer": {"type": "box", "layout": "vertical", "backgroundColor": "#0e1117", "contents": [
            {"type": "text", "text": "ไม่ใช่คำแนะนำมีใบอนุญาต · ตัดสินใจ+คุมเสี่ยงเอง",
             "size": "xxs", "color": "#6b7280", "wrap": True}]}}}


def send(text, flex):
    sent = []
    dc = os.environ.get("DISCORD_WEBHOOK", "").strip()
    hook = os.environ.get("STOCK_LINE_HOOK", "").strip()
    for name, url, payload in (("discord", dc, {"content": text}),
                               ("line", hook, ({"messages": [flex]} if flex else {"text": text}))):
        if not url:
            continue
        try:
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json",
                         "Accept": "application/json",
                         "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"})
            urllib.request.urlopen(req, timeout=15).read()
            sent.append(name)
        except Exception as e:
            print("send %s failed: %s" % (name, str(e)[:120]))
    return sent


def main():
    if not KEY:
        raise SystemExit("ต้องตั้ง STOCK_API_KEY")
    dry = "--dry" in sys.argv
    results = []
    for sym in SYM2SEC:
        r = _analyze(sym)
        if r:
            results.append(r)
        time.sleep(0.15)          # กัน rate limit (5/วิ)
    if not results:
        raise SystemExit("ดึงข้อมูลไม่ได้เลย")
    ranked = sorted(results, key=lambda x: (x["score"], x["volratio"]), reverse=True)[:TOP]
    # คะแนนเฉลี่ยรายกลุ่ม
    sec_sum, sec_cnt = {}, {}
    for r in results:
        sec_sum[r["sec"]] = sec_sum.get(r["sec"], 0) + r["score"]
        sec_cnt[r["sec"]] = sec_cnt.get(r["sec"], 0) + 1
    sec_rank = sorted(((s, sec_sum[s] / sec_cnt[s]) for s in sec_sum), key=lambda x: x[1], reverse=True)
    today = datetime.now(BKK).strftime("%d/%m/%Y")
    text = build_text(ranked, sec_rank, today)
    flex = build_flex(ranked, sec_rank, today)
    print(text)
    if dry:
        print("\n[DRY] ไม่ส่ง — วิเคราะห์ %d ตัว, ส่งจริงจะขึ้น top %d" % (len(results), len(ranked)))
        return
    sent = send(text, flex)
    print("\nส่งแล้ว:", sent or "(ไม่มีปลายทางตั้งไว้)")


if __name__ == "__main__":
    main()
