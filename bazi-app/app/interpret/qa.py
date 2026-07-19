# -*- coding: utf-8 -*-
"""ชั้น QA: ให้ Claude (โมเดลถูก = Haiku) ตรวจคำตีความของ Claude อีกที

ตรวจ 3 อย่าง:
1. มีข้อความไหนขัดกับตัวเลขใน JSON ไหม (เช่น อ้างเสา/สิบเทพ/ปีที่ไม่มีจริง)
2. มีการฟันธงผลเหตุการณ์เฉพาะเกินขอบเขตไหม (ผลคดี/โรค/วันตาย ฯลฯ)
3. มีคำกว้างแบบ Barnum ที่ใครอ่านก็ใช่ไหม

ด่าน 0: แค่ log ผลตรวจไว้พอ (ไม่วนแก้อัตโนมัติ) — เจ้าของเอา log ไปดูคุณภาพได้
"""
import json
import logging
import os

from app.interpret.interpreter import get_client

log = logging.getLogger("bazi")

QA_MODEL = os.environ.get("BAZI_QA_MODEL", "claude-haiku-4-5-20251001")

QA_SYSTEM = """คุณคือผู้ตรวจสอบคุณภาพคำตีความปาจื่อ ตรวจ 3 ข้อแล้วตอบเป็น JSON เท่านั้น:
1. contradictions: ข้อความในคำตีความที่ "ขัดกับตัวเลขใน JSON" (อ้างเสา/ธาตุ/สิบเทพ/วัยจร/ปีที่ไม่มีใน JSON หรืออ้างผิด) — list ของ string, ว่างถ้าไม่มี
2. overreach: การฟันธงผลเหตุการณ์เฉพาะเกินขอบเขต (ผลคดีความ, วินิจฉัยโรค, วันเสียชีวิต, ผลตั้งครรภ์, รับประกันอนาคต) — list ของ string, ว่างถ้าไม่มี
3. barnum: ประโยคกว้างๆ ที่ใครอ่านก็ใช่ โดยไม่อ้างอิงจุดจริงในดวง — list ของ string, ว่างถ้าไม่มี

ตอบเป็น JSON รูปแบบนี้เท่านั้น (ห้ามมีข้อความอื่น):
{"passed": true/false, "contradictions": [...], "overreach": [...], "barnum": [...]}
passed = true เมื่อทั้งสาม list ว่าง"""


def review(engine_json: dict, interpretation_text: str) -> dict:
    """ตรวจคำตีความ คืน dict {passed, contradictions, overreach, barnum}

    ถ้าเรียก API ไม่สำเร็จหรือ parse ไม่ได้ จะคืน passed=None (ไม่ตัดสิน) และ log ไว้
    """
    client = get_client()
    user_msg = (
        "JSON จากเครื่องคำนวณ:\n```json\n"
        + json.dumps(engine_json, ensure_ascii=False)
        + "\n```\n\nคำตีความที่ต้องตรวจ:\n---\n"
        + interpretation_text
        + "\n---"
    )
    try:
        response = client.messages.create(
            model=QA_MODEL,
            max_tokens=2000,
            system=QA_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = "".join(b.text for b in response.content if b.type == "text").strip()
        # โมเดลอาจห่อ JSON ด้วย ```json ... ``` — ลอกออกก่อน parse
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())
    except Exception as e:  # QA พังต้องไม่ทำให้คำตีความหลักพังตาม
        log.warning("ชั้น QA ตรวจไม่สำเร็จ (ไม่กระทบคำตีความหลัก): %s", e)
        return {"passed": None, "error": str(e)}

    if result.get("passed"):
        log.info("QA ผ่าน: คำตีความไม่พบปัญหา")
    else:
        log.warning(
            "QA พบปัญหา | ขัดกับตัวเลข=%d | ฟันธงเกินขอบเขต=%d | Barnum=%d | รายละเอียด: %s",
            len(result.get("contradictions", [])),
            len(result.get("overreach", [])),
            len(result.get("barnum", [])),
            json.dumps(result, ensure_ascii=False),
        )
    return result
