# -*- coding: utf-8 -*-
"""ชั้นที่ 1: เครื่องคำนวณปาจื่อ (deterministic ล้วน)

ห้ามมี AI ในไฟล์นี้เด็ดขาด — ทุกตัวเลขมาจาก lunar-python + คณิตศาสตร์ล้วน
ผลลัพธ์เป็น JSON (dict) ตามโครงสร้างใน APPENDIX A ของสเปค
"""
from datetime import date, datetime

from lunar_python import Solar

from app.engine import boundary
from app.engine.solar_time import to_apparent_solar

# ---------- ตารางอ้างอิงมาตรฐาน (ไม่มีวันเปลี่ยน) ----------

# ก้านฟ้า 10 ตัว -> (ธาตุ, หยิน/หยาง)
STEM_INFO = {
    "甲": ("wood", "yang"), "乙": ("wood", "yin"),
    "丙": ("fire", "yang"), "丁": ("fire", "yin"),
    "戊": ("earth", "yang"), "己": ("earth", "yin"),
    "庚": ("metal", "yang"), "辛": ("metal", "yin"),
    "壬": ("water", "yang"), "癸": ("water", "yin"),
}

# กิ่งดิน 12 ตัว -> ธาตุหลัก
BRANCH_ELEMENT = {
    "子": "water", "丑": "earth", "寅": "wood", "卯": "wood",
    "辰": "earth", "巳": "fire", "午": "fire", "未": "earth",
    "申": "metal", "酉": "metal", "戌": "earth", "亥": "water",
}

# lunar-python คืนชื่อสิบเทพเป็นจีนตัวย่อ -> แปลงเป็นตัวเต็ม (ตามสเปค)
TEN_GOD_TRADITIONAL = {
    "比肩": "比肩", "劫财": "劫財", "食神": "食神", "伤官": "傷官",
    "偏财": "偏財", "正财": "正財", "七杀": "七殺", "正官": "正官",
    "偏印": "偏印", "正印": "正印",
}

# น้ำหนักธาตุแฝงในกิ่ง: ธาตุหลักเต็ม ธาตุรองลดหลั่น
HIDDEN_WEIGHTS = [1.0, 0.5, 0.3]


def _trad(ten_god: str) -> str:
    """แปลงชื่อสิบเทพจากตัวย่อเป็นตัวเต็ม (ถ้าไม่รู้จักก็คืนค่าเดิม)"""
    return TEN_GOD_TRADITIONAL.get(ten_god, ten_god)


def _build_pillar(stem, branch, ten_god_stem, hidden_stems, hidden_ten_gods, nayin,
                  is_day_master=False):
    """ประกอบข้อมูลหนึ่งเสาเป็น dict"""
    element, yinyang = STEM_INFO[stem]
    pillar = {
        "stem": stem,
        "branch": branch,
        "stem_element": element,
        "stem_yinyang": yinyang,
        "branch_element": BRANCH_ELEMENT[branch],
        # สิบเทพของก้านบน (เสาวันคือตัวเราเอง จึงไม่มีสิบเทพ)
        "ten_god_stem": None if is_day_master else _trad(ten_god_stem),
        # ธาตุแฝงในกิ่ง พร้อมสิบเทพของแต่ละธาตุแฝง
        "hidden": [
            {"stem": hs, "element": STEM_INFO[hs][0], "ten_god": _trad(tg)}
            for hs, tg in zip(hidden_stems, hidden_ten_gods)
        ],
        "nayin": nayin,
    }
    if is_day_master:
        pillar["day_master"] = True
    return pillar


def _five_elements_score(pillars: list) -> dict:
    """นับสมดุลธาตุทั้ง 5 จากก้านบน (น้ำหนัก 1.0) + ธาตุแฝงในกิ่ง (1.0/0.5/0.3)

    ใช้ธาตุแฝงแทนธาตุหลักของกิ่งตรงๆ เพราะธาตุแฝงหลักตัวแรกคือธาตุหลักของกิ่งอยู่แล้ว
    และธาตุรองสะท้อนพลังแฝงตามตำรา
    """
    score = {"wood": 0.0, "fire": 0.0, "earth": 0.0, "metal": 0.0, "water": 0.0}
    for p in pillars:
        if p is None:
            continue
        score[p["stem_element"]] += 1.0
        for i, h in enumerate(p["hidden"]):
            w = HIDDEN_WEIGHTS[i] if i < len(HIDDEN_WEIGHTS) else 0.3
            score[h["element"]] += w
    return {k: round(v, 1) for k, v in score.items()}


def _luck_cycles(eight_char, gender: str, birth_year: int) -> dict:
    """ดึงวัยจร (大運) จาก lunar-python

    หมายเหตุ signature จริงของไลบรารี (ตรวจแล้ว):
      - getYun(1) = ชาย, getYun(0) = หญิง
      - yun.getStartYear/Month/Day = "ระยะเวลา" ก่อนเริ่มเดินวัยจร (ปี/เดือน/วัน)
      - getDaYun() คืน 10 รอบ โดยรอบแรก (index 0) คือช่วงวัยเด็กก่อนเข้าวัยจร
        (ganzhi ว่าง) เราจึงข้ามรอบนั้น
    """
    yun = eight_char.getYun(1 if gender == "male" else 0)
    start_age = round(
        yun.getStartYear() + yun.getStartMonth() / 12 + yun.getStartDay() / 365, 1
    )
    cycles = []
    for dy in yun.getDaYun():
        if not dy.getGanZhi():
            continue  # ข้ามช่วงวัยเด็กก่อนเข้าวัยจร
        cycles.append({
            "start_age": dy.getStartAge(),
            "start_year": dy.getStartYear(),
            "ganzhi": dy.getGanZhi(),
            "stem_element": STEM_INFO[dy.getGanZhi()[0]][0],
            "branch_element": BRANCH_ELEMENT[dy.getGanZhi()[1]],
        })
        if len(cycles) >= 9:
            break

    # หาวัยจรรอบปัจจุบัน (เทียบกับปีปัจจุบันจริง)
    current_year = date.today().year
    current = None
    for c in cycles:
        if c["start_year"] <= current_year < c["start_year"] + 10:
            current = c
            break

    return {
        "start_age": start_age,
        "direction": "forward" if yun.isForward() else "backward",
        "cycles": cycles,
        "current_cycle": current,
        "current_age": current_year - birth_year,
    }


def compute_bazi(birth_date: str, birth_time: str, gender: str,
                 longitude: float = 100.5017, tz_offset: float = 7,
                 time_known: bool = True) -> dict:
    """คำนวณปาจื่อครบชุด คืนเป็น dict (JSON ได้ทันที)

    พารามิเตอร์:
        birth_date : "YYYY-MM-DD" ตามปฏิทินสากล (ค.ศ.)
        birth_time : "HH:MM" เวลานาฬิกาท้องถิ่น (ไม่ใช้ถ้า time_known=False)
        gender     : "male" หรือ "female" (มีผลต่อทิศทางวัยจร)
        longitude  : ลองจิจูดสถานที่เกิด (ค่าเริ่มต้น = กรุงเทพ 100.5017°E)
        tz_offset  : โซนเวลา (ค่าเริ่มต้น UTC+7)
        time_known : False = ไม่ทราบเวลาเกิด (ใช้เที่ยงวันคำนวณ, ไม่ให้เสาชั่วโมง)
    """
    if gender not in ("male", "female"):
        raise ValueError("gender ต้องเป็น 'male' หรือ 'female'")

    y, m, d = (int(x) for x in birth_date.split("-"))
    if time_known:
        hh, mm = (int(x) for x in birth_time.split(":"))
    else:
        hh, mm = 12, 0  # ไม่ทราบเวลา: ใช้เที่ยงวันเพื่อให้เสาวัน/เดือน/ปีนิ่งที่สุด
    clock_dt = datetime(y, m, d, hh, mm, 0)

    # ชั้นที่ 2: แปลงเป็นเวลาสุริยคติปรากฏ แล้วป้อนเวลานั้นให้ lunar-python
    apparent_dt, lon_corr, eot = to_apparent_solar(clock_dt, longitude, tz_offset)

    solar = Solar.fromYmdHms(apparent_dt.year, apparent_dt.month, apparent_dt.day,
                             apparent_dt.hour, apparent_dt.minute, apparent_dt.second)
    ba = solar.getLunar().getEightChar()
    ba.setSect(2)  # แนวหลัก: เสาวันเปลี่ยนตอนเที่ยงคืน (ดู boundary.py เรื่องยามจื่อ)

    year_pillar = _build_pillar(
        ba.getYearGan(), ba.getYearZhi(), ba.getYearShiShenGan(),
        ba.getYearHideGan(), ba.getYearShiShenZhi(), ba.getYearNaYin())
    month_pillar = _build_pillar(
        ba.getMonthGan(), ba.getMonthZhi(), ba.getMonthShiShenGan(),
        ba.getMonthHideGan(), ba.getMonthShiShenZhi(), ba.getMonthNaYin())
    day_pillar = _build_pillar(
        ba.getDayGan(), ba.getDayZhi(), None,
        ba.getDayHideGan(), ba.getDayShiShenZhi(), ba.getDayNaYin(),
        is_day_master=True)
    if time_known:
        hour_pillar = _build_pillar(
            ba.getTimeGan(), ba.getTimeZhi(), ba.getTimeShiShenGan(),
            ba.getTimeHideGan(), ba.getTimeShiShenZhi(), ba.getTimeNaYin())
    else:
        hour_pillar = None

    dm_element, dm_yinyang = STEM_INFO[ba.getDayGan()]

    warnings = []
    if time_known:
        warnings = boundary.check_all(clock_dt, apparent_dt, tz_offset)
    else:
        warnings.append({
            "type": "time_unknown",
            "message": (
                "ไม่ทราบเวลาเกิด: ไม่สามารถคำนวณเสาชั่วโมงได้ "
                "และเสาวันอาจคลาดเคลื่อนถ้าเกิดช่วงใกล้เที่ยงคืน "
                "การตีความจะอิงสามเสา (ปี/เดือน/วัน) เท่านั้น"
            ),
            "alternatives": None,
        })

    pillars_for_score = [year_pillar, month_pillar, day_pillar, hour_pillar]

    return {
        "input": {
            "birth_date": birth_date,
            "birth_time_clock": birth_time if time_known else None,
            "gender": gender,
            "longitude": longitude,
            "timezone_offset": tz_offset,
            "time_known": time_known,
        },
        "solar_time": {
            "lon_correction_min": lon_corr,
            "eot_min": eot,
            "apparent_solar_time": apparent_dt.strftime("%Y-%m-%d %H:%M"),
        } if time_known else None,
        "pillars": {
            "year": year_pillar,
            "month": month_pillar,
            "day": day_pillar,
            "hour": hour_pillar,
        },
        "day_master": {
            "stem": ba.getDayGan(),
            "element": dm_element,
            "yinyang": dm_yinyang,
        },
        "five_elements_score": _five_elements_score(pillars_for_score),
        "luck_cycles": _luck_cycles(ba, gender, y),
        "boundary_warnings": warnings,
    }
