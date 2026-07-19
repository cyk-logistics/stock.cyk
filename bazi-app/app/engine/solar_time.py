# -*- coding: utf-8 -*-
"""ชั้นที่ 2: ปรับเวลานาฬิกาให้เป็น "เวลาสุริยคติปรากฏ" (Apparent Solar Time)

ทำไมต้องปรับ?
    ปาจื่อโบราณใช้ตำแหน่งดวงอาทิตย์จริงบนท้องฟ้า ไม่ใช่เวลานาฬิกา
    เวลานาฬิกา (เช่น UTC+7) เป็นเวลามาตรฐานของเส้นแวง 105°E
    แต่กรุงเทพอยู่ที่ ~100.5°E ดวงอาทิตย์จึงขึ้นสูงสุด "ช้ากว่า" นาฬิกา ~18 นาที
    บวกกับ "สมการเวลา" (Equation of Time) ที่แกว่ง ±15 นาทีตามฤดูกาล

การแก้สองขั้น:
    (ก) แก้ตามลองจิจูด:  (ลองจิจูดจริง - เส้นแวงมาตรฐานของโซนเวลา) x 4 นาที/องศา
    (ข) สมการเวลา (EoT): สูตรประมาณค่ามาตรฐาน ความคลาดเคลื่อน < 1 นาที

นี่คือจุดที่ทำให้เราแม่นกว่าคู่แข่งที่ใช้เวลานาฬิกาตรงๆ
"""
import math
from datetime import datetime, timedelta


def longitude_correction_min(longitude: float, tz_offset: float) -> float:
    """ค่าแก้ตามลองจิจูด หน่วยเป็นนาที (ติดลบ = ดวงอาทิตย์ช้ากว่านาฬิกา)

    ตัวอย่าง กรุงเทพ 100.5017°E, โซน UTC+7 (เส้นแวงมาตรฐาน 105°E):
        (100.5017 - 105) * 4 = -17.99 นาที
    """
    standard_meridian = tz_offset * 15
    return (longitude - standard_meridian) * 4


def equation_of_time_min(day_of_year: int) -> float:
    """สมการเวลา (Equation of Time) หน่วยเป็นนาที

    สูตรประมาณค่ามาตรฐาน (ใช้กันแพร่หลายในงานสุริยะ):
        B = (360/365) * (วันที่ของปี - 81) องศา
        EoT = 9.87*sin(2B) - 7.53*cos(B) - 1.5*sin(B)
    """
    B = math.radians((360 / 365) * (day_of_year - 81))
    return 9.87 * math.sin(2 * B) - 7.53 * math.cos(B) - 1.5 * math.sin(B)


def to_apparent_solar(clock_dt: datetime, longitude: float, tz_offset: float):
    """แปลงเวลานาฬิกา -> เวลาสุริยคติปรากฏ

    คืนค่า: (datetime เวลาสุริยคติ, ค่าแก้ลองจิจูดเป็นนาที, ค่าสมการเวลาเป็นนาที)

    หมายเหตุ: เวลาสุริยคติอาจข้ามวัน (เช่น เกิด 00:10 -> สุริยคติ 23:51 ของวันก่อน)
    datetime จัดการเรื่องข้ามวันให้อัตโนมัติ
    """
    lon_corr = longitude_correction_min(longitude, tz_offset)
    eot = equation_of_time_min(clock_dt.timetuple().tm_yday)
    apparent = clock_dt + timedelta(minutes=lon_corr + eot)
    return apparent, round(lon_corr, 2), round(eot, 2)
