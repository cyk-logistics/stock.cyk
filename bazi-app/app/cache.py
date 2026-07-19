# -*- coding: utf-8 -*-
"""Cache ด้วย SQLite ไฟล์เดียว: ดวงซ้ำไม่เรียก Claude ใหม่ (ดวงเดียวผลเดียวตลอด = ประหยัดเงินมาก)

key = hash(วันเกิด + เวลา + เพศ + ลองจิจูด + โซนเวลา + คำถาม + เวอร์ชัน prompt)
ถ้าแก้ system prompt (PROMPT_VERSION เปลี่ยน) ดวงเดิมจะถูกตีความใหม่อัตโนมัติ

ตำแหน่งไฟล์ DB: env BAZI_DATA_DIR (ค่าเริ่มต้น ./data) — บน Synology ให้ mount volume มาที่นี่
"""
import hashlib
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone

log = logging.getLogger("bazi")

DATA_DIR = os.environ.get("BAZI_DATA_DIR", "./data")
DB_PATH = os.path.join(DATA_DIR, "bazi_cache.sqlite3")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    key            TEXT PRIMARY KEY,
    engine_json    TEXT NOT NULL,
    interpretation TEXT NOT NULL,
    qa_json        TEXT,
    model          TEXT,
    prompt_version TEXT,
    created_at     TEXT
)
"""


def _connect() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(_SCHEMA)
    return conn


def make_key(birth_date: str, birth_time: str, gender: str, longitude: float,
             tz_offset: float, time_known: bool, question: str, prompt_version: str) -> str:
    """สร้าง key จากข้อมูลดวง + เวอร์ชัน prompt (sha256)"""
    raw = json.dumps(
        [birth_date, birth_time, gender, longitude, tz_offset, time_known,
         question or "", prompt_version],
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get(key: str):
    """หา cache: เจอคืน dict {engine_json, interpretation, qa, model, created_at} / ไม่เจอคืน None"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT engine_json, interpretation, qa_json, model, created_at "
            "FROM readings WHERE key = ?", (key,)
        ).fetchone()
    if row is None:
        return None
    log.info("ใช้ผลจาก cache (ไม่เรียก Claude ใหม่) | key=%s...", key[:12])
    return {
        "engine_json": json.loads(row[0]),
        "interpretation": row[1],
        "qa": json.loads(row[2]) if row[2] else None,
        "model": row[3],
        "created_at": row[4],
    }


def put(key: str, engine_json: dict, interpretation: str, qa: dict,
        model: str, prompt_version: str):
    """บันทึกผลลง cache (เขียนทับได้ กรณีบังคับ regenerate)"""
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO readings "
            "(key, engine_json, interpretation, qa_json, model, prompt_version, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                key,
                json.dumps(engine_json, ensure_ascii=False),
                interpretation,
                json.dumps(qa, ensure_ascii=False) if qa else None,
                model,
                prompt_version,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    log.info("บันทึกผลลง cache | key=%s...", key[:12])
