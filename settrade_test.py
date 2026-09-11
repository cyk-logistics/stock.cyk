#!/usr/bin/env python3
"""
ทดสอบเชื่อม Settrade Open API (ตามเดโมในคลิป) — ราคา AOT + บัญชี + พอร์ต
วิธีใช้:
  1) เติมค่าใน settrade_config.json (คัดจาก settrade_config.example.json)
  2) ติดตั้ง SDK:  pip install settrade-v2
  3) รัน:  python settrade_test.py
เริ่มบน Sandbox ก่อน (is_sandbox: true) ให้เห็นว่าต่อได้จริง แล้วค่อยสลับเป็น live
"""
from settrade_client import SettradeData


def main():
    d = SettradeData()
    print("=" * 48)
    print("โหมด:", "🧪 SANDBOX (uat)" if d.sandbox else "🔴 LIVE (prod)")
    print("=" * 48)

    print("\n① ราคาสด AOT:")
    try:
        q = d.quote("AOT")
        last = q.get("last") if isinstance(q, dict) else q
        print("   last =", last, "| ทั้งก้อน:", q)
    except Exception as e:
        print("   ✗", e)

    print("\n② ราคาหลายตัว (KTB/PTT/KBANK):")
    for s, v in d.quotes(["KTB", "PTT", "KBANK"]).items():
        last = v.get("last") if isinstance(v, dict) else v
        print(f"   {s}: {last}")

    if d.account_no:
        print("\n③ ข้อมูลบัญชี:")
        try:
            print("  ", d.account())
        except Exception as e:
            print("   ✗", e)
        print("\n④ พอร์ต (หุ้นที่ถือ):")
        try:
            for p in (d.portfolio() or []):
                print("  ", p)
        except Exception as e:
            print("   ✗", e)
    else:
        print("\n(ข้าม ③④ บัญชี/พอร์ต — ยังไม่ได้ใส่ account_no ใน config)")

    print("\n✅ จบการทดสอบ")


if __name__ == "__main__":
    main()
