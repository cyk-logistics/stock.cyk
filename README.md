# SET Dividend + Technical Screener

ระบบหาหุ้นปันผลคุณภาพในตลาดไทย (SET) แล้วจับจังหวะเข้าตอนราคาย่อด้วยสัญญาณเทคนิค
สร้าง dashboard กราฟแบบ TradingView (ใช้ Lightweight Charts ของ TradingView เอง) จากข้อมูล yfinance ฟรี

## ติดตั้ง
```bash
pip install -r requirements.txt
```

## ใช้งาน
```bash
python3 screener.py              # สแกนทั้ง SET50 → สร้าง dashboard.html
python3 screener.py --limit 12   # ทดสอบเร็ว 12 ตัวแรก
python3 screener.py --out my.html
```
เปิด `dashboard.html` ในเบราว์เซอร์ (ดับเบิลคลิกได้เลย ต้องต่อเน็ตเพื่อโหลดไลบรารีกราฟ)

## ระบบให้คะแนนยังไง
รวมสัญญาณ "พื้นฐานดี + จังหวะเข้า":
| สัญญาณ | คะแนน |
|--------|------:|
| ปันผล 3–12% | +สูงสุด 20 |
| RSI oversold (<35) | +20 |
| RSI Bullish Divergence | +30 |
| หลุดกรอบล่าง Bollinger | +15 |
| ย่อในขาขึ้น (แตะ EMA50, เหนือ EMA200) | +20 |
| ใกล้ Low 52 สัปดาห์ | +15 |
| MACD ตัดขึ้น | +10 |

ปันผล > 12% จะ**ไม่ให้คะแนน**และติดธงเตือน (เสี่ยง dividend trap)

## ปรับแต่ง
- แก้รายชื่อหุ้นที่ตัวแปร `TICKERS` ใน `screener.py` (เพิ่มหุ้นนอก SET50 ได้ ใส่ชื่อไม่ต้องมี `.BK`)
- ปรับเกณฑ์/น้ำหนักคะแนนในฟังก์ชัน `analyze()`

## ⚠️ คำเตือน
เป็น "สัญญาณ" ไม่ใช่คำแนะนำซื้อขาย — ปันผลสูงผิดปกติอาจเป็นกับดัก, divergence มีสัญญาณหลอกได้,
ข้อมูล yfinance ไม่ใช่ realtime และหุ้นไทยบางตัวอาจมีรู ควร backtest + ศึกษาพื้นฐานก่อนลงเงินจริง
