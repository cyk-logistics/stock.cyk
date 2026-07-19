# -*- coding: utf-8 -*-
"""หน้าเว็บและ API ของแอปถอดดวง (ด่าน 0)

- GET  /        : ฟอร์มกรอกวันเกิด (HTML ง่ายๆ)
- POST /reading : คำนวณ + ตีความ (ผ่าน cache) แล้วแสดงผลหน้าเดียวกัน
- GET  /raw     : คืน JSON ดิบจาก engine (ไว้ตรวจว่าคำนวณถูก ไม่เรียก Claude)
- GET  /docs    : เอกสาร API อัตโนมัติของ FastAPI

รัน dev: uvicorn app.main:app --reload
"""
import html
import json
import logging

from fastapi import FastAPI, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse

from app import cache
from app.engine.calculator import compute_bazi
from app.interpret import qa as qa_module
from app.interpret.interpreter import interpret
from app.interpret.system_prompt import PROMPT_VERSION
from app.logging_config import setup_logging

log = setup_logging()
app = FastAPI(title="BaZi App ด่าน 0", description="ถอดดวงปาจื่อ — prototype พิสูจน์คุณภาพ")

_FORM_HTML = """<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ถอดดวงปาจื่อ (ด่าน 0)</title>
<style>
  body {{ font-family: sans-serif; max-width: 760px; margin: 2rem auto; padding: 0 1rem; line-height: 1.7; }}
  label {{ display: block; margin-top: .8rem; font-weight: bold; }}
  input, select {{ padding: .4rem; font-size: 1rem; }}
  button {{ margin-top: 1.2rem; padding: .6rem 1.6rem; font-size: 1.1rem; cursor: pointer; }}
  .reading {{ white-space: pre-wrap; background: #f8f7f2; border: 1px solid #ddd;
             border-radius: 8px; padding: 1.2rem; margin-top: 1.5rem; }}
  .warn {{ background: #fff6e0; border: 1px solid #e0c060; border-radius: 8px;
          padding: .8rem 1.2rem; margin-top: 1rem; }}
  .meta {{ color: #888; font-size: .85rem; margin-top: 1rem; }}
</style>
</head>
<body>
<h1>ถอดดวงปาจื่อ</h1>
<p>กรอกวันเกิดตามปฏิทินสากล (ค.ศ.) และเวลาเกิดตามนาฬิกาท้องถิ่น ระบบจะปรับเป็นเวลาสุริยคติให้อัตโนมัติ</p>
<form method="post" action="/reading">
  <label>ชื่อ (ไม่บังคับ)</label>
  <input type="text" name="name" value="{name}">
  <label>วันเกิด (ค.ศ.)</label>
  <input type="date" name="birth_date" required value="{birth_date}">
  <label>เวลาเกิด</label>
  <input type="time" name="birth_time" value="{birth_time}">
  <label><input type="checkbox" name="time_unknown" value="1" {time_unknown_checked}> ไม่ทราบเวลาเกิด</label>
  <label>เพศ</label>
  <select name="gender">
    <option value="male" {male_sel}>ชาย</option>
    <option value="female" {female_sel}>หญิง</option>
  </select>
  <label>ลองจิจูดสถานที่เกิด (ค่าเริ่มต้น = กรุงเทพ)</label>
  <input type="number" step="0.0001" name="longitude" value="{longitude}">
  <label><input type="checkbox" name="force" value="1"> บังคับตีความใหม่ (ไม่ใช้ cache)</label>
  <button type="submit">ถอดดวง</button>
</form>
{result}
</body>
</html>"""


def _render(result_html: str = "", name: str = "", birth_date: str = "", birth_time: str = "12:00",
            gender: str = "male", longitude: str = "100.5017", time_unknown: bool = False) -> str:
    return _FORM_HTML.format(
        result=result_html,
        name=html.escape(name),
        birth_date=html.escape(birth_date),
        birth_time=html.escape(birth_time),
        longitude=html.escape(longitude),
        male_sel="selected" if gender == "male" else "",
        female_sel="selected" if gender == "female" else "",
        time_unknown_checked="checked" if time_unknown else "",
    )


@app.get("/", response_class=HTMLResponse)
def index():
    return _render()


@app.post("/reading", response_class=HTMLResponse)
def reading(
    name: str = Form(""),
    birth_date: str = Form(...),
    birth_time: str = Form("12:00"),
    gender: str = Form("male"),
    longitude: float = Form(100.5017),
    time_unknown: str = Form(""),
    force: str = Form(""),
    question: str = Form(""),
):
    time_known = not bool(time_unknown)
    log.info(
        "รับคำขอถอดดวง | เกิด=%s %s | เพศ=%s | ลองจิจูด=%s | ทราบเวลา=%s",
        birth_date, birth_time if time_known else "(ไม่ทราบเวลา)", gender, longitude, time_known,
    )

    try:
        result = get_reading(birth_date, birth_time, gender, longitude,
                             time_known=time_known, question=question or None,
                             force=bool(force))
    except Exception as e:
        log.error("ถอดดวงล้มเหลว: %s", e, exc_info=True)
        err = ('<div class="warn">เกิดข้อผิดพลาด: {} — '
               "ถ้าเกิดซ้ำ ให้เอาข้อความใน log ไปปรึกษา Claude Code</div>").format(html.escape(str(e)))
        return _render(err, name, birth_date, birth_time, gender, str(longitude), not time_known)

    warn_html = ""
    for w in result["engine_json"].get("boundary_warnings", []):
        warn_html += '<div class="warn">⚠️ {}</div>'.format(html.escape(w["message"]))

    greeting = "ดวงของคุณ{}".format(html.escape(name)) if name else "ผลการถอดดวง"
    result_html = (
        "<h2>{}</h2>{}<div class='reading'>{}</div>"
        "<div class='meta'>โมเดล: {} | จาก cache: {} | prompt v{}</div>"
    ).format(
        greeting, warn_html, html.escape(result["interpretation"]),
        html.escape(result.get("model") or "-"),
        "ใช่" if result["from_cache"] else "ไม่ (ตีความสดใหม่)",
        PROMPT_VERSION,
    )
    return _render(result_html, name, birth_date, birth_time, gender, str(longitude), not time_known)


@app.get("/raw")
def raw(
    date: str = Query(..., description="วันเกิด YYYY-MM-DD (ค.ศ.)"),
    time: str = Query("12:00", description="เวลาเกิด HH:MM"),
    gender: str = Query("male", description="male หรือ female"),
    longitude: float = Query(100.5017),
    tz_offset: float = Query(7),
    time_known: bool = Query(True),
):
    """คืน JSON ดิบจาก engine (ไม่เรียก Claude — ไว้ตรวจการคำนวณ)"""
    engine_json = compute_bazi(date, time, gender, longitude, tz_offset, time_known)
    return JSONResponse(content=engine_json)


def get_reading(birth_date: str, birth_time: str, gender: str, longitude: float = 100.5017,
                tz_offset: float = 7, time_known: bool = True, question: str = None,
                force: bool = False) -> dict:
    """ตรรกะหลัก: engine -> cache check -> interpret -> QA -> เก็บ cache

    คืน dict: {engine_json, interpretation, qa, model, from_cache}
    (ฟังก์ชันนี้ถูกใช้ทั้งจากหน้าเว็บและ CLI)
    """
    key = cache.make_key(birth_date, birth_time if time_known else "", gender,
                         longitude, tz_offset, time_known, question, PROMPT_VERSION)

    if not force:
        cached = cache.get(key)
        if cached:
            return {
                "engine_json": cached["engine_json"],
                "interpretation": cached["interpretation"],
                "qa": cached["qa"],
                "model": cached["model"],
                "from_cache": True,
            }

    engine_json = compute_bazi(birth_date, birth_time, gender, longitude, tz_offset, time_known)
    interp = interpret(engine_json, question)
    qa_result = qa_module.review(engine_json, interp["text"])
    cache.put(key, engine_json, interp["text"], qa_result, interp["model"], PROMPT_VERSION)

    return {
        "engine_json": engine_json,
        "interpretation": interp["text"],
        "qa": qa_result,
        "model": interp["model"],
        "from_cache": False,
    }
