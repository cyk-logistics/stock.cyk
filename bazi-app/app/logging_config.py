# -*- coding: utf-8 -*-
"""ตั้งค่า log ให้อ่านรู้เรื่อง — เวลาพัง เจ้าของก๊อป log ส่วนท้ายไปให้ Claude Code อ่านต่อได้เลย

log เขียน 2 ที่:
1. หน้าจอ (ดูใน Container Manager ของ DSM ได้ที่แท็บ Log)
2. ไฟล์ BAZI_LOG_DIR/bazi.log (ค่าเริ่มต้น ./logs) หมุนไฟล์อัตโนมัติไม่ให้เต็มดิสก์
"""
import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.environ.get("BAZI_LOG_DIR", "./logs")

_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging():
    """เรียกครั้งเดียวตอนแอปเริ่ม — ตั้ง logger ชื่อ 'bazi' ให้ทุกไฟล์ใช้ร่วมกัน"""
    logger = logging.getLogger("bazi")
    if logger.handlers:  # กันตั้งซ้ำ
        return logger
    logger.setLevel(logging.INFO)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_FORMAT, _DATEFMT))
    logger.addHandler(console)

    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(LOG_DIR, "bazi.log"),
            maxBytes=5 * 1024 * 1024,  # 5MB ต่อไฟล์
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(_FORMAT, _DATEFMT))
        logger.addHandler(file_handler)
    except OSError as e:
        logger.warning("เขียน log ลงไฟล์ไม่ได้ (ใช้หน้าจออย่างเดียว): %s", e)

    return logger
