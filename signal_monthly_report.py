#!/usr/bin/env python3
"""
สรุปผล "หุ้นที่เมลแนะนำ" ประจำเดือน — ส่งเมลวันทำการสุดท้ายของเดือน (หลังตลาดปิด)
- อ่านประวัติ history/signals_1d.jsonl + signals_4h.jsonl (signal_history.py) ของเดือนนั้น
- หุ้นแต่ละตัวนับจาก "ครั้งแรกที่แนะนำในเดือน": ราคาตอนแนะนำ → ราคาปิดสิ้นเดือน · สูงสุด/ต่ำสุดหลังแนะนำ
  · เทียบดัชนี SET ช่วงเดียวกัน (ชนะตลาดไหม)
- ราคาจาก live.atlog.asia (ถ้าล่ม ใช้ yfinance สำรอง) · ตัดแท่งที่เลยสิ้นเดือนทิ้ง (รันต้นเดือนถัดไปก็ได้ราคาสิ้นเดือนจริง)
- ส่งแล้วเก็บผลลง history/report_YYYY-MM.json (มีไฟล์แล้ว = ไม่ส่งซ้ำ ยกเว้น --force)

env: STOCK_API_KEY · RESEND_API_KEY · MAIL_TO · MAIL_FROM · SCAN_API_BASE
รัน: python signal_monthly_report.py [--month 2026-09] [--dry] [--force]
  ไม่ใส่ --month: วันทำการสุดท้ายของเดือน → สรุปเดือนนี้ · วันที่ 1-3 → สรุปเดือนก่อนถ้ายังไม่ได้ส่ง
  (กัน cron ของ GitHub ดีเลย์ข้ามเที่ยงคืน — เคยช้าถึง 4 ชม.)
"""
import argparse
import json
import statistics
from datetime import date, datetime, timedelta

import signal_history
from signal_email import BASE, BKK, KEY, MAIL_TO, _get, send_resend

TH_MONTH = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]


def last_weekday(y, m):
    d = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def month_end(ym):
    y, m = map(int, ym.split("-"))
    return date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)


def pick_month(arg_month, today):
    """คืน (เดือนที่จะสรุป, ส่งได้ไหมแม้มีรายงานแล้ว)"""
    if arg_month:
        return arg_month
    if today == last_weekday(today.year, today.month):
        return today.strftime("%Y-%m")
    if today.day <= 3:
        return (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    return None


# ---------- ราคา ----------
def api_candles(syms, interval, limit):
    out = {}
    for i in range(0, len(syms), 20):
        chunk = ",".join(syms[i:i + 20])
        try:
            d = _get("%s/api/candles?symbols=%s&interval=%s&limit=%d&final=0&key=%s"
                     % (BASE, chunk, interval, limit, KEY))["data"]
        except Exception as e:
            print("API %s ไม่ตอบ:" % interval, str(e)[:80])
            continue
        for s, v in d.items():
            cs = v.get("candles") if isinstance(v, dict) else None
            if cs and "error" not in v:
                out[s] = cs
    return out


def yf_daily(syms, start):
    """สำรองตอน live.atlog.asia ล่ม — ราคาจาก Yahoo (หุ้นไทย .BK · ดัชนี ^SET.BK)"""
    try:
        import yfinance as yf
    except ImportError:
        return {}
    out = {}
    for s in syms:
        try:
            df = yf.Ticker("^SET.BK" if s == "SET" else s + ".BK").history(start=start, auto_adjust=False)
        except Exception:
            continue
        if df is None or df.empty:
            continue
        out[s] = [{"bar_time": idx.strftime("%Y-%m-%d"), "open": float(r.Open), "high": float(r.High),
                   "low": float(r.Low), "close": float(r.Close)} for idx, r in df.iterrows()]
    return out


def daily_by_date(cs, end):
    """{วันที่: แท่ง} เฉพาะไม่เกินสิ้นเดือน"""
    out = {}
    for c in cs:
        d = str(c.get("bar_time", ""))[:10]
        if d and d <= end.isoformat():
            out[d] = c
    return out


# ---------- สรุป ----------
def build(month, recs):
    end = month_end(month)
    syms = sorted({r["sym"] for r in recs})
    first_day = min(str(r.get("bar", r["sent_at"]))[:10] for r in recs)
    daily = api_candles(syms + ["SET"], "1d", 80)
    src = "live.atlog.asia"
    miss = [s for s in syms + ["SET"] if s not in daily]
    if miss:
        fb = yf_daily(miss, (date.fromisoformat(first_day) - timedelta(days=10)).isoformat())
        daily.update(fb)
        if fb:
            src = "live.atlog.asia + Yahoo (สำรอง %d ตัว)" % len(fb) if len(miss) < len(syms) + 1 else "Yahoo (live.atlog.asia ไม่ตอบ)"
    need4h = sorted({r["sym"] for r in recs if r.get("price") is None and r.get("source") == "4H"})
    h4 = api_candles(need4h, "240m", 300) if need4h else {}
    days = {s: daily_by_date(cs, end) for s, cs in daily.items()}
    setd = days.get("SET", {})

    groups = {}
    for r in recs:
        groups.setdefault(r["sym"], []).append(r)
    rows = []
    for sym, rs in groups.items():
        first = rs[0]
        ed = str(first.get("bar", first["sent_at"]))[:10]
        dd = days.get(sym, {})
        entry = first.get("price")
        if entry is None and first.get("source") == "4H":   # ย้อนเติม: ราคาปิดแท่ง 4H ที่เกิดสัญญาณ
            for c in h4.get(sym, []):
                if str(c.get("bar_close_time", ""))[:16] == str(first.get("bar", ""))[:16]:
                    entry = c["close"]
                    break
        if entry is None and ed in dd:                         # ย้อนเติม 1D (หรือหาแท่ง 4H ไม่เจอ) = ราคาปิดวันนั้น
            entry = dd[ed]["close"]
        row = {"sym": sym, "first_sent": first["sent_at"], "entry_date": ed, "source": first.get("source", ""),
               "sources": sorted({x.get("source", "") for x in rs}), "times": len(rs),
               "reason": first.get("reason", ""), "vstat": first.get("vstat", ""), "entry": entry,
               "last": None, "last_date": None, "chg": None, "max_up": None, "max_dn": None, "set_chg": None}
        after = [dd[d] for d in sorted(dd) if d > ed]
        if entry and dd:
            last_d = max(dd)
            row.update(last=dd[last_d]["close"], last_date=last_d, chg=(dd[last_d]["close"] / entry - 1) * 100)
            if after:
                row["max_up"] = (max(c["high"] for c in after) / entry - 1) * 100
                row["max_dn"] = (min(c["low"] for c in after) / entry - 1) * 100
            base = setd.get(ed) or next((setd[d] for d in sorted(setd, reverse=True) if d <= ed), None)
            if base and setd:
                row["set_chg"] = (setd[max(setd)]["close"] / base["close"] - 1) * 100
        rows.append(row)
    rows.sort(key=lambda x: (x["chg"] is None, -(x["chg"] or 0)))

    ok = [x for x in rows if x["chg"] is not None]
    summ = {"month": month, "n": len(rows), "n_priced": len(ok), "source": src,
            "win": sum(1 for x in ok if x["chg"] > 0),
            "beat": sum(1 for x in ok if x["set_chg"] is not None and x["chg"] > x["set_chg"]),
            "n_set": sum(1 for x in ok if x["set_chg"] is not None),     # เทียบ SET ได้กี่ตัว (Yahoo สำรองมักไม่มีดัชนี)
            "avg": statistics.mean([x["chg"] for x in ok]) if ok else None,
            "median": statistics.median([x["chg"] for x in ok]) if ok else None,
            "set_avg": statistics.mean([x["set_chg"] for x in ok if x["set_chg"] is not None])
            if any(x["set_chg"] is not None for x in ok) else None,
            "last_date": max((x["last_date"] for x in ok if x["last_date"]), default=None),
            "emails": len({(r.get("source"), r.get("sent_at")) for r in recs})}
    return summ, rows


def _p(v, d=1):
    if v is None:
        return "—"
    return "%+.*f%%" % (d, 0.0 if round(v, d) == 0 else v)   # กัน "-0.0%"


def _col(v):
    return "#5a6472" if v is None else ("#0a8f5a" if v > 0 else ("#c62828" if v < 0 else "#5a6472"))


def build_email(summ, rows):
    y, m = map(int, summ["month"].split("-"))
    mname = "%s %d" % (TH_MONTH[m - 1], y)
    head = ("ชนะ %d/%d ตัว · เฉลี่ย %s (SET %s)" % (summ["win"], summ["n_priced"], _p(summ["avg"]), _p(summ["set_avg"]))
            if summ["n_priced"] else "ยังดึงราคาไม่ได้")
    subj = "📊 สรุปหุ้นที่แนะนำ เดือน %s — %s" % (mname, head)
    td = 'style="border:1px solid #dbe3ee;padding:6px 8px;%s"'
    th = '<th style="border:1px solid #dbe3ee;padding:6px 8px;text-align:%s">%s</th>'
    trs, tl = "", ["สรุปหุ้นที่เมลแนะนำ เดือน %s (ราคาถึง %s · จาก %s)" % (mname, summ["last_date"] or "—", summ["source"]),
                   head, ""]
    for x in rows:
        when = "%s/%s %s" % (x["entry_date"][8:10], x["entry_date"][5:7], "·".join(x["sources"]))
        trs += ("<tr><td %s><b>%s</b></td><td %s>%s%s</td><td %s>%s</td><td %s>%s</td>"
                "<td %s><b>%s</b></td><td %s>%s</td><td %s>%s</td><td %s>%s</td></tr>"
                % (td % "", x["sym"],
                   td % "white-space:nowrap", when, (" ×%d" % x["times"]) if x["times"] > 1 else "",
                   td % "text-align:right", "—" if x["entry"] is None else "%.2f" % x["entry"],
                   td % "text-align:right", "—" if x["last"] is None else "%.2f" % x["last"],
                   td % ("text-align:right;color:%s" % _col(x["chg"])), _p(x["chg"]),
                   td % "text-align:right;color:#0a8f5a", _p(x["max_up"]),
                   td % "text-align:right;color:#c62828", _p(x["max_dn"]),
                   td % ("text-align:right;color:%s" % _col(x["set_chg"])), _p(x["set_chg"])))
        tl.append("- %-7s แนะนำ %s  %s → %s  %s  (สูงสุด %s · ต่ำสุด %s · SET %s)"
                  % (x["sym"], when, "—" if x["entry"] is None else "%.2f" % x["entry"],
                     "—" if x["last"] is None else "%.2f" % x["last"], _p(x["chg"]),
                     _p(x["max_up"]), _p(x["max_dn"]), _p(x["set_chg"])))
    note = ("ราคาแนะนำ = ราคาปิดแท่งที่เกิดสัญญาณ (ตัวเลขในเมล) · นับจากครั้งแรกที่แนะนำในเดือน (×n = แนะนำซ้ำ) · "
            "สูงสุด/ต่ำสุด = ช่วงหลังวันแนะนำถึงสิ้นเดือน · SET = ดัชนีช่วงเดียวกัน · ไม่รวมปันผล/ค่าคอม")
    beat = "%d/%d" % (summ["beat"], summ["n_set"]) if summ["n_set"] else "— (ไม่มีข้อมูลดัชนี)"
    tl += ["", "ชนะตลาด (ดีกว่า SET) %s ตัว · มัธยฐาน %s · จากเมล %d ฉบับ"
           % (beat, _p(summ["median"]), summ["emails"]),
           note, "ไม่ใช่คำแนะนำมีใบอนุญาต — ตัดสินใจ+คุมความเสี่ยงเอง"]
    card = ('<td style="padding:10px 14px;background:#f4f7fb;border-radius:10px;text-align:center">'
            '<div style="font-size:12px;color:#5a6472">%s</div><div style="font-size:20px;font-weight:800;color:%s">%s</div></td>')
    cards = ('<table style="border-collapse:separate;border-spacing:8px 0;margin:4px -8px 14px"><tr>%s%s%s%s</tr></table>'
             % (card % ("ชนะ (บวก)", "#1a1f2b", "%d/%d" % (summ["win"], summ["n_priced"])),
                card % ("เฉลี่ย", _col(summ["avg"]), _p(summ["avg"])),
                card % ("SET ช่วงเดียวกัน", _col(summ["set_avg"]), _p(summ["set_avg"])),
                card % ("ชนะตลาด", "#1a1f2b", beat.split(" ")[0])))
    html = ('<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#1a1f2b;max-width:720px">'
            '<h2 style="color:#0e3a6e;margin:0 0 2px">📊 สรุปหุ้นที่แนะนำ — เดือน %s</h2>'
            '<div style="color:#5a6472;font-size:13px;margin-bottom:10px">ราคาถึง %s · จาก %s · เมลแนะนำ %d ฉบับ · หุ้น %d ตัว</div>%s'
            '<table style="border-collapse:collapse;font-size:14px"><tr style="background:#eef3f9">%s%s%s%s%s%s%s%s</tr>%s</table>'
            '<p style="font-size:12px;color:#555;line-height:1.6;margin-top:12px">%s<br>มัธยฐาน %s</p>'
            '<p style="font-size:12px;color:#7a8494">ไม่ใช่คำแนะนำมีใบอนุญาต — ตัดสินใจและคุมความเสี่ยงเอง</p></div>'
            % (mname, summ["last_date"] or "—", summ["source"], summ["emails"], summ["n"], cards,
               th % ("left", "หุ้น"), th % ("left", "แนะนำ"), th % ("right", "ราคาแนะนำ"), th % ("right", "ราคาล่าสุด"),
               th % ("right", "เปลี่ยน"), th % ("right", "สูงสุด"), th % ("right", "ต่ำสุด"), th % ("right", "SET"),
               trs, note, _p(summ["median"])))
    return subj, "\n".join(tl), html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", help="YYYY-MM (ไม่ใส่ = ตัดสินจากวันนี้)")
    ap.add_argument("--dry", action="store_true", help="พิมพ์ผลเฉยๆ ไม่ส่งเมล/ไม่บันทึก")
    ap.add_argument("--force", action="store_true", help="ส่งแม้ไม่ใช่สิ้นเดือน/ส่งไปแล้ว")
    a = ap.parse_args()
    today = datetime.now(BKK).date()
    month = pick_month(a.month, today)
    if not month:
        print("วันนี้ (%s) ไม่ใช่วันทำการสุดท้ายของเดือน — ยังไม่สรุป" % today)
        return
    out = signal_history.DIR / ("report_%s.json" % month)
    if out.exists() and not (a.force or a.dry):
        print("สรุปเดือน %s ส่งไปแล้ว (%s) — ข้าม" % (month, out.name))
        return
    if not a.month and today.day <= 3 and not (a.force or a.dry) and month != today.strftime("%Y-%m"):
        print("ต้นเดือน: สรุปย้อนเดือน %s ที่ยังไม่ได้ส่ง" % month)
    recs = signal_history.load(month)
    if not recs:
        print("เดือน %s ไม่มีหุ้นที่เมลแนะนำ — ไม่ส่ง" % month)
        return
    summ, rows = build(month, recs)
    subj, text, html = build_email(summ, rows)
    print(subj)
    print(text)
    if a.dry:
        return
    if summ["n_priced"] == 0:
        raise SystemExit("ดึงราคาไม่ได้เลย — ยังไม่ส่ง (รอบหน้าลองใหม่)")
    r = send_resend(subj, text, html)
    print("ส่งเมลแล้ว:", r.get("id", r) if isinstance(r, dict) else r)
    out.write_text(json.dumps({"summary": summ, "rows": rows, "sent_at": datetime.now(BKK).isoformat(timespec="seconds"),
                               "email_id": r.get("id", "") if isinstance(r, dict) else "", "to": MAIL_TO},
                              ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
