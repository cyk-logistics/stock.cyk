# -*- coding: utf-8 -*-
"""CLI ไว้เทสต์เร็วๆ ไม่ต้องเปิดเว็บ

ตัวอย่าง:
    # ดู JSON engine ดิบ (ไม่เรียก Claude — ฟรี)
    python -m app.cli --date 1966-06-27 --time 05:00 --gender male

    # คำนวณ + ตีความด้วย Claude (เสียเงินตามจริง ผ่าน cache)
    python -m app.cli --date 1966-06-27 --time 05:00 --gender male --interpret
"""
import argparse
import json

from app.engine.calculator import compute_bazi
from app.logging_config import setup_logging


def main():
    parser = argparse.ArgumentParser(description="ถอดดวงปาจื่อจาก command line")
    parser.add_argument("--date", required=True, help="วันเกิด YYYY-MM-DD (ค.ศ.)")
    parser.add_argument("--time", default="12:00", help="เวลาเกิด HH:MM (เวลานาฬิกา)")
    parser.add_argument("--gender", default="male", choices=["male", "female"])
    parser.add_argument("--longitude", type=float, default=100.5017,
                        help="ลองจิจูดสถานที่เกิด (ค่าเริ่มต้น = กรุงเทพ)")
    parser.add_argument("--tz-offset", type=float, default=7, help="โซนเวลา (ค่าเริ่มต้น UTC+7)")
    parser.add_argument("--time-unknown", action="store_true", help="ไม่ทราบเวลาเกิด")
    parser.add_argument("--interpret", action="store_true",
                        help="เรียก Claude ตีความด้วย (ต้องมี ANTHROPIC_API_KEY)")
    parser.add_argument("--force", action="store_true", help="บังคับตีความใหม่ ไม่ใช้ cache")
    parser.add_argument("--question", default=None, help="คำถามเพิ่มเติมถึงผู้ตีความ")
    args = parser.parse_args()

    setup_logging()

    if args.interpret:
        # import ตรงนี้เพื่อให้โหมด engine-only ใช้ได้แม้ยังไม่ติดตั้ง/ตั้งค่า anthropic
        from app.main import get_reading
        result = get_reading(args.date, args.time, args.gender, args.longitude,
                             args.tz_offset, not args.time_unknown, args.question, args.force)
        print("=" * 60)
        print("JSON จาก engine:")
        print(json.dumps(result["engine_json"], ensure_ascii=False, indent=2))
        print("=" * 60)
        print("คำตีความ (โมเดล {} | cache: {}):".format(
            result["model"], "ใช่" if result["from_cache"] else "ไม่"))
        print(result["interpretation"])
        if result.get("qa"):
            print("=" * 60)
            print("ผลตรวจ QA:", json.dumps(result["qa"], ensure_ascii=False))
    else:
        engine_json = compute_bazi(args.date, args.time, args.gender,
                                   args.longitude, args.tz_offset, not args.time_unknown)
        print(json.dumps(engine_json, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
