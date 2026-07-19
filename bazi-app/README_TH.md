# BaZi App ด่าน 0 — ถอดดวงปาจื่อ (Prototype พิสูจน์คุณภาพ)

แอปนี้ทำอะไร: **กรอกวันเกิด → ได้คำตีความปาจื่อภาษาไทย 1 หน้า**
เป้าหมายของด่าน 0 คือพิสูจน์ว่าคุณภาพคำตีความของเราดีกว่าคู่แข่ง ก่อนลงทุนทำระบบเต็ม
(ยังไม่มี LINE / ระบบจ่ายเงิน / หน้าเว็บสวยงาม — มีเฉพาะแกนคำนวณ + ตีความ + วิธีทดสอบ)

## หลักการทำงาน (2 ชั้น แยกกันเด็ดขาด)

1. **ชั้นคำนวณ** (`app/engine/`) — โค้ดคณิตศาสตร์ล้วน ไม่มี AI
   คำนวณสี่เสา สิบเทพ ธาตุแฝง นายิน วัยจร สมดุลธาตุ ด้วยไลบรารี `lunar-python`
   พร้อม **ปรับเวลาสุริยคติ** (จุดที่ทำให้แม่นกว่าคู่แข่ง) และ **ดักเคสก้ำกึ่ง**
   (เวลาเกิดใกล้เส้นแบ่งยาม/เดือน/ปี จะคำนวณทั้งสองฝั่งแล้วเตือน ไม่เลือกเงียบๆ)
2. **ชั้นตีความ** (`app/interpret/`) — เรียก Claude API ตีความจากตัวเลขใน JSON เท่านั้น
   ห้าม AI คำนวณเลขเอง (เพราะ AI คำนวณปฏิทินไม่แม่น แต่ตีความเก่ง)
   มีชั้น QA ให้ Claude รุ่นเล็กตรวจคำตีความอีกรอบ แล้วบันทึกผลใน log

## ไฟล์ไหนทำหน้าที่อะไร

| ไฟล์ | หน้าที่ |
|---|---|
| `app/engine/calculator.py` | คำนวณปาจื่อทั้งหมด (เรียก lunar-python) คืนเป็น JSON |
| `app/engine/solar_time.py` | แปลงเวลานาฬิกา → เวลาสุริยคติ (แก้ลองจิจูด + สมการเวลา) |
| `app/engine/boundary.py` | ดักเคสเวลาเกิดก้ำกึ่ง (ยาม/ยามจื่อ/เสาเดือน/เสาปี 立春) |
| `app/interpret/system_prompt.py` | **หัวใจของแอป** — กรอบตีความที่คุมคุณภาพ Claude |
| `app/interpret/interpreter.py` | เรียก Claude API ตีความ (โมเดล claude-sonnet-5) |
| `app/interpret/qa.py` | ให้ Claude Haiku ตรวจคำตีความ (ขัดตัวเลข/ฟันธงเกิน/Barnum) |
| `app/cache.py` | เก็บผลใน SQLite — ดวงซ้ำไม่เรียก AI ใหม่ (ประหยัดเงิน) |
| `app/logging_config.py` | ตั้งค่า log ให้อ่านรู้เรื่อง เขียนลงไฟล์บน NAS |
| `app/main.py` | หน้าเว็บฟอร์ม + API (FastAPI) |
| `app/cli.py` | สั่งถอดดวงจาก command line ไว้เทสต์เร็วๆ |
| `tests/test_engine.py` | เทสต์กับดวงที่รู้คำตอบแล้ว — เครื่องมือตรวจว่าระบบคำนวณถูก |

## วิธี deploy บน Synology (Container Manager) — ทีละคลิก

เตรียมก่อน: NAS ต้องติดตั้งแพ็กเกจ **Container Manager** จาก Package Center แล้ว

1. เปิด **File Station** สร้างโฟลเดอร์ เช่น `docker/bazi-app` แล้วอัปโหลดไฟล์ทั้งโปรเจกต์นี้เข้าไป
   (โฟลเดอร์ `app/`, `tests/`, ไฟล์ `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `.env.example`)
2. ใน File Station ก๊อปไฟล์ `.env.example` เป็นชื่อใหม่ `.env`
   แล้วคลิกขวา → เปิดด้วย Text Editor ใส่ API key จริงแทนข้อความตัวอย่าง:
   `ANTHROPIC_API_KEY=sk-ant-xxxx...` (ขอ key ได้ที่ https://platform.claude.com)
3. เปิด **Container Manager** → แท็บ **Project** → กด **Create**
4. ตั้งชื่อ project เช่น `bazi-app` → ช่อง Path ชี้ไปที่โฟลเดอร์ `docker/bazi-app`
   → ระบบจะเห็นไฟล์ `docker-compose.yml` เอง → เลือก "Use existing docker-compose.yml"
5. กด **Next** ไปเรื่อยๆ แล้วกด **Done** — ระบบจะ build image (ครั้งแรกใช้เวลา 2-5 นาที)
6. เสร็จแล้วเปิดเบราว์เซอร์ไปที่ `http://<IP ของ NAS>:8080` จะเจอหน้าฟอร์มถอดดวง
   (ถ้า port 8080 ชนกับแอปอื่น แก้เลขซ้ายของ `8080:8080` ใน docker-compose.yml เช่น `8090:8080`)

รีสตาร์ทแอป: Container Manager → Project → bazi-app → ปุ่ม Action → Restart

## วิธีใส่/เปลี่ยน API key

แก้ไฟล์ `.env` (ใน File Station) แล้ว restart project ใน Container Manager
**ห้าม** เอา key ไปเขียนในโค้ดหรือ commit ขึ้น git เด็ดขาด

## วิธีดู log

- แบบเร็ว: Container Manager → Container → `bazi-app` → แท็บ **Log**
- แบบไฟล์: โฟลเดอร์ `docker/bazi-app/logs/bazi.log` (เปิดด้วย Text Editor ได้)
  log บอกทุกครั้งว่า: รับดวงอะไร เรียกโมเดลไหน ใช้ cache ไหม ผลตรวจ QA เจออะไร และ error (ถ้ามี)

## วิธีรัน test (ตรวจว่าระบบคำนวณถูก)

เทสต์เทียบกับดวงที่ยืนยันคำตอบแล้ว ไม่เรียก Claude ไม่เสียเงิน:

```bash
# ในเครื่องที่มี Python 3.11 (จากโฟลเดอร์ bazi-app)
pip install -r requirements.txt
pytest tests/ -v
```

หรือรันในตัว container บน NAS: Container Manager → Container → bazi-app →
แท็บ Terminal → Create → bash → พิมพ์ `pytest tests/ -v`

ผ่านครบทุกข้อ = เครื่องคำนวณถูกต้อง (ถ้าข้อไหนแดง ให้ทำตามหัวข้อ "เวลาพังให้ทำยังไง")

## วิธีเทสต์เร็วๆ จาก command line

```bash
# ดูตัวเลขดิบ (ฟรี ไม่เรียก AI)
python -m app.cli --date 1966-06-27 --time 05:00 --gender male

# คำนวณ + ตีความเต็ม (เสียเงินตามจริง ครั้งถัดไปดวงเดิมจะดึงจาก cache ฟรี)
python -m app.cli --date 1966-06-27 --time 05:00 --gender male --interpret
```

หรือดู JSON ดิบผ่านเว็บ: `http://<IP NAS>:8080/raw?date=1966-06-27&time=05:00&gender=male`

## เวลาพังให้ทำยังไง

1. เปิดไฟล์ `logs/bazi.log` (หรือแท็บ Log ใน Container Manager)
2. ก๊อป **50 บรรทัดสุดท้าย** (หรือตั้งแต่บรรทัด ERROR แรกที่เจอ)
3. เอาไปวางให้ Claude Code พร้อมบอกว่า "แอป bazi-app พัง log เป็นแบบนี้ ช่วยแก้ให้หน่อย"
4. ปัญหาที่เจอบ่อย:
   - `authentication_error` / 401 → API key ผิดหรือหมดอายุ → แก้ `.env` แล้ว restart
   - `rate_limit_error` / 429 → เรียกถี่เกินโควตา → รอสักครู่แล้วลองใหม่
   - หน้าเว็บเปิดไม่ขึ้น → เช็คว่า container สถานะ Running และ port ไม่ชน

## ค่าใช้จ่ายโดยประมาณ (ก.ค. 2026)

ตีความ 1 ดวง ใช้ claude-sonnet-5 (ราคาโปรโมชัน $2/$10 ต่อล้าน token ถึง 31 ส.ค. 2026):
- input ~4,000 token (ส่วนใหญ่อ่านจาก cache เหลือ ~0.1 เท่าของราคา) + output ~2,500 token
- รวมชั้น QA (Haiku) แล้ว **~$0.03-0.04 ต่อดวงแรก** และเกือบฟรีเมื่อดวงซ้ำ (ดึงจาก SQLite cache)
- ราคาจริงดูได้จาก log (มีตัวเลข token ทุกครั้ง) และ https://platform.claude.com/docs/en/pricing

## หมายเหตุทางเทคนิค

- เสาปีเปลี่ยนที่ 立春 (~4 ก.พ.) ไม่ใช่ตรุษจีนหรือ 1 ม.ค. — ระบบจัดการให้แล้ว
- ยามจื่อ (23:00-01:00) ใช้แนวหลัก: เสาวันเปลี่ยนตอนเที่ยงคืน (ถ้าเกิดช่วงนี้ระบบจะเตือน
  พร้อมแสดงเสาวันของอีกสำนักให้เทียบ)
- เวลาที่ป้อนเข้าเครื่องคำนวณคือ "เวลาสุริยคติ" ไม่ใช่เวลานาฬิกา
  (กรุงเทพช้ากว่านาฬิกา ~18 นาที บวกลบสมการเวลาอีก ±15 นาทีตามฤดู)
