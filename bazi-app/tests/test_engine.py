# -*- coding: utf-8 -*-
"""เทสต์ engine กับดวงที่ยืนยันคำตอบแล้ว — เครื่องมือตรวจงานของเจ้าของโปรเจกต์

วิธีรัน (จากโฟลเดอร์ bazi-app):
    pytest tests/ -v

เกณฑ์ผ่าน: ตัวเลขตรงทุกตัว + เคสก้ำกึ่งมี warning ครบ
เทสต์ทั้งหมดไม่เรียก Claude API (ฟรี ไม่ต้องมี API key)
"""
import pytest

from app.engine.calculator import compute_bazi
from app.engine.solar_time import longitude_correction_min


def _pillar_str(p):
    return p["stem"] + p["branch"]


def _warning_types(result):
    return [w["type"] for w in result["boundary_warnings"]]


# ---------- เทสต์ค่าแก้เวลาสุริยคติ ----------

def test_bangkok_longitude_correction():
    """กรุงเทพ 100.5017°E โซน UTC+7 -> ค่าแก้ ≈ -17.99 นาที"""
    corr = longitude_correction_min(100.5017, 7)
    assert corr == pytest.approx(-17.99, abs=0.01)


# ---------- เคส 1: 27 มิ.ย. 1966, 05:00, ชาย, กรุงเทพ ----------

@pytest.fixture(scope="module")
def case1():
    return compute_bazi("1966-06-27", "05:00", "male")


def test_case1_pillars(case1):
    """เสาปี 丙午, เสาเดือน 甲午, เสาวัน 丁巳, day master 丁"""
    assert _pillar_str(case1["pillars"]["year"]) == "丙午"
    assert _pillar_str(case1["pillars"]["month"]) == "甲午"
    assert _pillar_str(case1["pillars"]["day"]) == "丁巳"
    assert case1["day_master"]["stem"] == "丁"
    assert case1["day_master"]["element"] == "fire"
    assert case1["day_master"]["yinyang"] == "yin"


def test_case1_hour_boundary_warning(case1):
    """ต้องมี boundary_warning ยาม: สุริยคติ ~04:39 ให้ 壬寅 / นาฬิกา 05:00 ให้ 癸卯"""
    # เสาชั่วโมงหลัก (ตามเวลาสุริยคติ) ต้องเป็น 壬寅
    assert _pillar_str(case1["pillars"]["hour"]) == "壬寅"
    hour_warnings = [w for w in case1["boundary_warnings"] if w["type"] == "hour_branch"]
    assert hour_warnings, "ต้องมี warning เส้นแบ่งยาม"
    alts = hour_warnings[0]["alternatives"]
    assert alts["before"] == {"hour_stem": "壬", "hour_branch": "寅"}
    assert alts["after"] == {"hour_stem": "癸", "hour_branch": "卯"}


def test_case1_solar_time(case1):
    """เวลาสุริยคติ ~04:39-04:42 (ค่าแก้ลองจิจูด -17.99 + EoT ~ -2.7)"""
    assert case1["solar_time"]["lon_correction_min"] == pytest.approx(-17.99, abs=0.01)
    assert case1["solar_time"]["apparent_solar_time"].endswith(("04:39", "04:40", "04:41", "04:42"))


def test_case1_luck_cycles(case1):
    """วัยจรชายเริ่ม ~อายุ 3.5 เดินหน้า รอบปัจจุบัน (ปี 2026) คือ 庚子"""
    luck = case1["luck_cycles"]
    assert 3.3 <= luck["start_age"] <= 3.8
    assert luck["direction"] == "forward"
    assert luck["current_cycle"] is not None
    assert luck["current_cycle"]["ganzhi"] == "庚子"
    assert len(luck["cycles"]) >= 8


def test_case1_five_elements_score(case1):
    """สมดุลธาตุ: ดวงนี้ไฟต้องเด่นสุด (เกิดกลางหน้าร้อน เสาปี/เดือน/วันล้วนธาตุไฟแรง)"""
    score = case1["five_elements_score"]
    assert set(score.keys()) == {"wood", "fire", "earth", "metal", "water"}
    assert score["fire"] == max(score.values())
    assert sum(score.values()) > 0


# ---------- เคส 2: 27 พ.ค. 1973, 17:41, ชาย, กรุงเทพ ----------

@pytest.fixture(scope="module")
def case2():
    return compute_bazi("1973-05-27", "17:41", "male")


def test_case2_pillars(case2):
    """เสา 癸丑/丁巳/癸亥/辛酉, day master 癸"""
    assert _pillar_str(case2["pillars"]["year"]) == "癸丑"
    assert _pillar_str(case2["pillars"]["month"]) == "丁巳"
    assert _pillar_str(case2["pillars"]["day"]) == "癸亥"
    assert _pillar_str(case2["pillars"]["hour"]) == "辛酉"
    assert case2["day_master"]["stem"] == "癸"


def test_case2_luck_cycles(case2):
    """วัยจรเริ่ม ~อายุ 7 เดินถอยหลัง รอบปัจจุบัน (ปี 2026) คือ 壬子"""
    luck = case2["luck_cycles"]
    assert 6.8 <= luck["start_age"] <= 7.6
    assert luck["direction"] == "backward"
    assert luck["current_cycle"]["ganzhi"] == "壬子"


# ---------- เคส 3: early/late 子時 ----------

def test_late_zi_hour_flag():
    """เกิด ~23:30 -> ต้อง flag ยามจื่อดึก พร้อมเสาวันสองแบบ (สองสำนักไม่ตรงกัน)"""
    result = compute_bazi("1966-06-27", "23:30", "male")
    zi = [w for w in result["boundary_warnings"] if w["type"] == "zi_hour"]
    assert zi, "ต้องมี warning ยามจื่อ"
    alts = zi[0]["alternatives"]
    assert alts["before"]["day_pillar"] != alts["after"]["day_pillar"], \
        "สองสำนักต้องให้เสาวันคนละวัน"
    assert alts["before"]["day_pillar"] == "丁巳"   # แนวหลัก: ยังเป็นวันเดิม
    assert alts["after"]["day_pillar"] == "戊午"    # อีกแนว: นับเป็นวันถัดไป


def test_early_zi_hour_flag():
    """เกิด ~00:30 -> ต้อง flag ยามจื่อเช้า (เสาวันตรงกันทุกสำนัก แต่คาบเที่ยงคืน)"""
    result = compute_bazi("1966-06-28", "00:30", "male")
    zi = [w for w in result["boundary_warnings"] if w["type"] == "zi_hour"]
    assert zi, "ต้องมี warning ยามจื่อ"


# ---------- เคส 4: เกิดใกล้ 立春 (เสาปีก้ำกึ่ง) ----------

def test_lichun_year_boundary_flag():
    """เกิด 4 ก.พ. 1966 ช่วงบ่าย (立春 = 14:37 เวลาจีน) -> เสาปีต้องถูก flag"""
    result = compute_bazi("1966-02-04", "13:45", "male")
    types = _warning_types(result)
    assert "year_boundary_lichun" in types, "ต้องมี warning เสาปีใกล้ 立春"
    assert "month_boundary_jie" in types, "立春 กระทบเสาเดือนด้วย"
    lichun = [w for w in result["boundary_warnings"] if w["type"] == "year_boundary_lichun"][0]
    alts = lichun["alternatives"]
    assert alts["before"]["year_pillar"] == "乙巳"
    assert alts["after"]["year_pillar"] == "丙午"


# ---------- เคสไม่ทราบเวลาเกิด ----------

def test_time_unknown():
    """ไม่ทราบเวลา: ไม่มีเสาชั่วโมง + มี warning แจ้ง"""
    result = compute_bazi("1966-06-27", "12:00", "male", time_known=False)
    assert result["pillars"]["hour"] is None
    assert "time_unknown" in _warning_types(result)
    # สามเสาที่เหลือยังต้องถูกต้อง
    assert _pillar_str(result["pillars"]["day"]) == "丁巳"


# ---------- โครงสร้าง JSON ครบตามสเปค ----------

def test_json_structure(case1):
    """JSON ต้องมีครบทุกส่วนที่ชั้นตีความต้องใช้"""
    for key in ("input", "solar_time", "pillars", "day_master",
                "five_elements_score", "luck_cycles", "boundary_warnings"):
        assert key in case1, f"ขาด field {key}"
    year = case1["pillars"]["year"]
    for key in ("stem", "branch", "stem_element", "stem_yinyang",
                "ten_god_stem", "hidden", "nayin"):
        assert key in year, f"เสาปีขาด field {key}"
    assert year["hidden"], "ต้องมีธาตุแฝง"
    assert "ten_god" in year["hidden"][0]
    # เสาวันคือตัวเรา ไม่มีสิบเทพของก้านบน
    assert case1["pillars"]["day"]["ten_god_stem"] is None
    assert case1["pillars"]["day"]["day_master"] is True
    # สิบเทพต้องเป็นตัวเต็ม (ไม่ใช่ตัวย่อจากไลบรารี)
    assert case1["pillars"]["year"]["ten_god_stem"] == "劫財"  # ไม่ใช่ 劫财
