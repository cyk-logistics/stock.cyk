# -*- coding: utf-8 -*-
"""ดักเคส "ก้ำกึ่ง" — เวลาเกิดใกล้เส้นแบ่งจนเสาอาจเป็นได้สองแบบ

หลักการ: ถ้าใกล้เส้นแบ่ง ห้ามเลือกฝั่งเงียบๆ ต้องคำนวณทั้งสองฝั่ง
แล้วใส่ warning ให้ชั้นตีความ (และผู้ใช้) รู้ว่าเสานั้นยังไม่ฟันธง

เส้นแบ่งที่ดัก 4 แบบ:
1. hour_branch      — เส้นแบ่งยาม 12 ยาม (ทุกชั่วโมงคี่: 01,03,...,23 น.)
                      รวมกรณีที่การแก้เวลาสุริยคติทำให้ "ข้าม" ยาม
                      (ยามตามนาฬิกา != ยามตามสุริยคติ)
2. zi_hour          — 早子時/晚子時 (23:00-01:00) เสาวันเปลี่ยนตอนไหน
                      สำนัก sect2 (ค่าเริ่มต้น): เสาวันเปลี่ยนตอนเที่ยงคืน
                      สำนัก sect1: เสาวันเปลี่ยนตั้งแต่ 23:00
3. month_boundary   — ใกล้จุดเปลี่ยนสุริยคติ 節 (กระทบเสาเดือน)
4. year_boundary    — ใกล้ 立春 (~4 ก.พ.) (กระทบเสาปี — เสาปีเปลี่ยนที่ 立春
                      ไม่ใช่ตรุษจีนหรือ 1 ม.ค.)

หมายเหตุเรื่องโซนเวลาของ 節氣:
    lunar-python คำนวณเวลาจุดเปลี่ยนสุริยคติในกรอบเวลาจีน (UTC+8)
    แต่เวลาเกิดของเราอยู่กรอบเวลาท้องถิ่น (เช่น UTC+7 + ค่าแก้สุริยคติ)
    เราจึงเทียบ "ทั้งสองกรอบ" — ถ้าสองกรอบให้คำตอบคนละฝั่งของ 節
    หรือฝั่งใดฝั่งหนึ่งห่าง 節 ไม่เกิน 15 นาที ให้ถือว่าก้ำกึ่งและออก warning
"""
from datetime import datetime, timedelta

from lunar_python import Solar

# ระยะ "ก้ำกึ่ง" — ห่างเส้นแบ่งไม่เกินกี่นาทีจึงต้องเตือน
BOUNDARY_WINDOW_MIN = 15


def _eightchar_at(dt: datetime, sect: int = 2):
    """คืน EightChar ของ lunar-python ณ เวลาที่กำหนด (sect2 = ค่าเริ่มต้นของไลบรารี)"""
    solar = Solar.fromYmdHms(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
    ba = solar.getLunar().getEightChar()
    ba.setSect(sect)
    return ba


def _hour_pillar_at(dt: datetime) -> dict:
    ba = _eightchar_at(dt)
    return {"hour_stem": ba.getTimeGan(), "hour_branch": ba.getTimeZhi()}


def _minutes_to_nearest_hour_boundary(dt: datetime) -> float:
    """ระยะ (นาที) จากเวลา dt ถึงเส้นแบ่งยามที่ใกล้ที่สุด (เส้นแบ่งอยู่ที่ชั่วโมงคี่ทุกชั่วโมง)"""
    minutes_of_day = dt.hour * 60 + dt.minute + dt.second / 60
    best = None
    for h in range(1, 26, 2):  # 01,03,...,25 (25 = 01 ของวันถัดไป), และเช็ค -1 ด้วยด้านล่าง
        d = abs(minutes_of_day - h * 60)
        best = d if best is None else min(best, d)
    best = min(best, abs(minutes_of_day - (-1) * 60))  # เส้น 23:00 ของวันก่อน (มุมมอง -1 ชม.)
    return best


def check_hour_boundary(clock_dt: datetime, apparent_dt: datetime):
    """ดักเส้นแบ่งยาม: (ก) ยามตามนาฬิกา != ยามตามสุริยคติ (ข) สุริยคติห่างเส้นแบ่ง <= 15 นาที"""
    clock_p = _hour_pillar_at(clock_dt)
    app_p = _hour_pillar_at(apparent_dt)

    if clock_p["hour_branch"] != app_p["hour_branch"]:
        # การแก้เวลาสุริยคติพาข้ามยาม — สองสำนักให้เสาชั่วโมงต่างกัน
        earlier, later = sorted([(apparent_dt, app_p), (clock_dt, clock_p)], key=lambda x: x[0])
        return {
            "type": "hour_branch",
            "message": (
                "เวลาเกิดคาบเส้นแบ่งยาม: ยามตามเวลาสุริยคติ ({}) กับยามตามเวลานาฬิกา ({}) "
                "ไม่ตรงกัน เพราะค่าแก้สุริยคติพาข้ามเส้นแบ่งยาม "
                "ระบบใช้เวลาสุริยคติเป็นหลัก แต่ควรตีความเสาชั่วโมงอย่างระมัดระวัง"
            ).format(app_p["hour_stem"] + app_p["hour_branch"],
                     clock_p["hour_stem"] + clock_p["hour_branch"]),
            "alternatives": {"before": earlier[1], "after": later[1]},
        }

    dist = _minutes_to_nearest_hour_boundary(apparent_dt)
    if dist <= BOUNDARY_WINDOW_MIN:
        before_p = _hour_pillar_at(apparent_dt - timedelta(minutes=BOUNDARY_WINDOW_MIN + 5))
        after_p = _hour_pillar_at(apparent_dt + timedelta(minutes=BOUNDARY_WINDOW_MIN + 5))
        if before_p != after_p:
            return {
                "type": "hour_branch",
                "message": (
                    "เวลาสุริยคติห่างเส้นแบ่งยามเพียง {:.0f} นาที "
                    "เสาชั่วโมงจึงเป็นไปได้สองแบบ ควรตีความอย่างระมัดระวัง"
                ).format(dist),
                "alternatives": {"before": before_p, "after": after_p},
            }
    return None


def check_zi_hour(apparent_dt: datetime):
    """ดักยามจื่อ (23:00-01:00) — เสาวันเปลี่ยนตอนไหนแล้วแต่สำนัก"""
    if apparent_dt.hour == 23:
        # 晚子時 (จื่อดึก): สำนักต่างกันให้เสาวันคนละวัน
        ba_sect2 = _eightchar_at(apparent_dt, sect=2)
        ba_sect1 = _eightchar_at(apparent_dt, sect=1)
        return {
            "type": "zi_hour",
            "message": (
                "เกิดช่วงยามจื่อดึก (晚子時 23:00-24:00 ตามเวลาสุริยคติ) "
                "สำนักปาจื่อแบ่งเป็นสองแนว: แนวหลัก (ที่ระบบใช้) ถือว่าเสาวันยังเป็นวันเดิม "
                "อีกแนวถือว่าเปลี่ยนเป็นวันใหม่ตั้งแต่ 23:00 — เสาวันจึงเป็นไปได้สองแบบ"
            ),
            "alternatives": {
                "before": {"day_pillar": ba_sect2.getDay(), "note": "แนวหลัก: เสาวันยังเป็นวันเดิม"},
                "after": {"day_pillar": ba_sect1.getDay(), "note": "อีกแนว: นับเป็นวันถัดไปแล้ว"},
            },
        }
    if apparent_dt.hour == 0:
        # 早子時 (จื่อเช้า): เสาวันตรงกันทุกสำนัก แต่แจ้งไว้เพื่อความโปร่งใส
        ba = _eightchar_at(apparent_dt)
        return {
            "type": "zi_hour",
            "message": (
                "เกิดช่วงยามจื่อเช้า (早子時 00:00-01:00 ตามเวลาสุริยคติ) "
                "เสาวันเป็นวันใหม่ตรงกันทุกสำนัก แต่ยามจื่อคาบสองวัน "
                "หากเวลาเกิดคลาดเคลื่อนเกินไม่กี่นาที เสาวันอาจเปลี่ยนได้ ควรยืนยันเวลาเกิดให้แน่นอน"
            ),
            "alternatives": {
                "before": {"day_pillar": _eightchar_at(apparent_dt - timedelta(hours=1)).getDay(),
                           "note": "ถ้าจริงๆ เกิดก่อนเที่ยงคืน"},
                "after": {"day_pillar": ba.getDay(), "note": "เสาวันที่ใช้ (หลังเที่ยงคืน)"},
            },
        }
    return None


def _parse_jieqi_dt(jieqi) -> datetime:
    """แปลงเวลา 節氣 จาก lunar-python เป็น datetime (กรอบเวลาจีน UTC+8)"""
    s = jieqi.getSolar()
    return datetime(s.getYear(), s.getMonth(), s.getDay(), s.getHour(), s.getMinute(), s.getSecond())


def check_jie_boundary(clock_dt: datetime, apparent_dt: datetime, tz_offset: float):
    """ดักจุดเปลี่ยนสุริยคติ 節 (เสาเดือน) และ 立春 (เสาปี)

    เทียบสองกรอบเวลา:
      - apparent_dt: เวลาที่ป้อนให้ไลบรารี (กรอบสุริยคติท้องถิ่น)
      - cst_dt: เวลาเกิดแปลงเป็นกรอบเวลาจีน UTC+8 (กรอบเดียวกับตาราง 節氣 ของไลบรารี)
    ถ้าสองกรอบอยู่คนละฝั่งของ 節 หรือฝั่งใดห่าง 節 <= 15 นาที -> ก้ำกึ่ง
    """
    warnings = []
    cst_dt = clock_dt + timedelta(hours=8 - tz_offset)
    lunar = Solar.fromYmdHms(
        apparent_dt.year, apparent_dt.month, apparent_dt.day,
        apparent_dt.hour, apparent_dt.minute, apparent_dt.second
    ).getLunar()

    candidates = []
    for jq in (lunar.getPrevJie(True), lunar.getNextJie(True)):
        if jq is not None:
            candidates.append(jq)

    for jq in candidates:
        jie_dt = _parse_jieqi_dt(jq)
        diff_app_min = (apparent_dt - jie_dt).total_seconds() / 60
        diff_cst_min = (cst_dt - jie_dt).total_seconds() / 60

        opposite_sides = (diff_app_min < 0) != (diff_cst_min < 0)
        near = min(abs(diff_app_min), abs(diff_cst_min)) <= BOUNDARY_WINDOW_MIN
        if not (opposite_sides or near):
            continue

        # คำนวณเสาสองฝั่งของ 節 (ป้อนเวลาห่างจากจุดเปลี่ยน 1 ชั่วโมงในกรอบไลบรารี)
        ba_before = _eightchar_at(jie_dt - timedelta(hours=1))
        ba_after = _eightchar_at(jie_dt + timedelta(hours=1))
        jie_name = jq.getName()

        warnings.append({
            "type": "month_boundary_jie",
            "jie_name": jie_name,
            "jie_time_china_utc8": jie_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "message": (
                "เวลาเกิดใกล้จุดเปลี่ยนสุริยคติ {} มาก (จุดเปลี่ยนเวลาจีน {} "
                "ซึ่งใกล้เวลาเกิดเมื่อเทียบข้ามโซนเวลา) เสาเดือนจึงเป็นไปได้สองแบบ "
                "ควรตีความอย่างระมัดระวัง"
            ).format(jie_name, jie_dt.strftime("%Y-%m-%d %H:%M")),
            "alternatives": {
                "before": {"month_pillar": ba_before.getMonth()},
                "after": {"month_pillar": ba_after.getMonth()},
            },
        })

        if jie_name == "立春":
            # 立春 เปลี่ยนทั้งเสาปีและเสาเดือน
            warnings.append({
                "type": "year_boundary_lichun",
                "jie_time_china_utc8": jie_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "message": (
                    "เวลาเกิดใกล้ 立春 (จุดเปลี่ยนปีนักษัตรตามหลักปาจื่อ — "
                    "เสาปีเปลี่ยนที่ 立春 ไม่ใช่ตรุษจีนหรือ 1 ม.ค.) "
                    "เสาปีจึงเป็นไปได้สองแบบ ควรตีความอย่างระมัดระวัง"
                ),
                "alternatives": {
                    "before": {"year_pillar": ba_before.getYear()},
                    "after": {"year_pillar": ba_after.getYear()},
                },
            })

    return warnings


def check_all(clock_dt: datetime, apparent_dt: datetime, tz_offset: float) -> list:
    """รวมการดักก้ำกึ่งทุกแบบ คืน list ของ warning (ว่าง = ไม่มีเคสก้ำกึ่ง)"""
    warnings = []
    w = check_hour_boundary(clock_dt, apparent_dt)
    if w:
        warnings.append(w)
    w = check_zi_hour(apparent_dt)
    if w:
        warnings.append(w)
    warnings.extend(check_jie_boundary(clock_dt, apparent_dt, tz_offset))
    return warnings
