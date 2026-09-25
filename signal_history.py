#!/usr/bin/env python3
"""
ประวัติหุ้นที่เมลแนะนำ (สัญญาณซื้อ) — เก็บเป็น JSONL ใน history/
1 บรรทัด = หุ้น 1 ตัวในเมล 1 ฉบับ · แยกไฟล์ตามแหล่ง (1D รายวัน / 4H ทันที) กัน 2 workflow commit ชนกัน
signal_monthly_report.py อ่านไปสรุปผลสิ้นเดือน

ฟิลด์: sent_at (เวลาส่งเมล ไทย) · source (1D/4H) · bar (แท่งที่เกิดสัญญาณ: วันที่ หรือเวลาปิดแท่ง 4H)
       sym · price (ราคาในเมล — null = ย้อนเติมจากล็อก รอดึงราคาปิดแท่งตอนสรุป) · rsi · pct · vr · vstat · reason · email_id
"""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

BKK = timezone(timedelta(hours=7))
DIR = Path(__file__).parent / "history"
FILES = {"1D": DIR / "signals_1d.jsonl", "4H": DIR / "signals_4h.jsonl"}


def append(source, rows, email_id=""):
    """บันทึกหุ้นที่เพิ่งส่งเมล (เรียกหลังส่งสำเร็จเท่านั้น)"""
    if not rows:
        return
    DIR.mkdir(exist_ok=True)
    now = datetime.now(BKK).isoformat(timespec="seconds")
    with FILES[source].open("a", encoding="utf-8") as f:
        for r in rows:
            rec = {"sent_at": now, "source": source}
            rec.update(r)
            rec["email_id"] = email_id
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load(month=None):
    """คืนรายการทั้งหมด (หรือเฉพาะเดือน 'YYYY-MM' ตามวันที่ส่งเมล) เรียงตามเวลา"""
    out = []
    for p in FILES.values():
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if month and not str(r.get("sent_at", "")).startswith(month):
                continue
            out.append(r)
    out.sort(key=lambda r: r.get("sent_at", ""))
    return out
