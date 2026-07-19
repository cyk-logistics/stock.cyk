# -*- coding: utf-8 -*-
"""เรียก Claude API เพื่อตีความดวง (ชั้นตีความ — ห้ามคำนวณตัวเลขเอง)

- โมเดลหลัก: claude-sonnet-5 (คุณภาพสูง เหมาะกับคำตีความพรีเมียม)
  เปลี่ยนได้ผ่าน env: BAZI_INTERPRET_MODEL (เช่นอยากใช้ claude-opus-4-8 ให้ลึกสุด)
- เปิด prompt caching ที่ system prompt (กรอบตีความยาวและซ้ำทุก request จึงลดต้นทุนมาก)
- API key อ่านจาก env: ANTHROPIC_API_KEY เท่านั้น (SDK อ่านให้อัตโนมัติ ห้าม hardcode)
"""
import json
import logging
import os

from anthropic import Anthropic

from app.interpret.system_prompt import PROMPT_VERSION, SYSTEM_PROMPT

log = logging.getLogger("bazi")

# ราคา/ชื่อโมเดลยืนยันจาก docs ณ ก.ค. 2026 — ถ้าเปลี่ยนให้แก้ผ่าน env ได้เลย
DEFAULT_MODEL = os.environ.get("BAZI_INTERPRET_MODEL", "claude-sonnet-5")
MAX_TOKENS = int(os.environ.get("BAZI_INTERPRET_MAX_TOKENS", "6000"))

_client = None


def get_client() -> Anthropic:
    """สร้าง client ครั้งเดียวแล้วใช้ซ้ำ (SDK อ่าน ANTHROPIC_API_KEY จาก env เอง)"""
    global _client
    if _client is None:
        _client = Anthropic()
    return _client


def build_user_message(engine_json: dict, question: str = None) -> str:
    """ประกอบข้อความที่ส่งให้ Claude: JSON จาก engine + คำถามเพิ่มเติม (ถ้ามี)"""
    parts = [
        "นี่คือผลคำนวณปาจื่อ (JSON) จากเครื่องคำนวณ deterministic "
        "กรุณาตีความตามกรอบใน system prompt:",
        "```json",
        json.dumps(engine_json, ensure_ascii=False, indent=2),
        "```",
    ]
    if question:
        parts.append(f"คำถามเพิ่มเติมจากเจ้าของดวง: {question}")
    return "\n".join(parts)


def interpret(engine_json: dict, question: str = None, model: str = None) -> dict:
    """เรียก Claude ตีความดวง คืน dict: {text, model, usage}

    system prompt ใส่ cache_control เพื่อให้ request ถัดๆ ไปอ่านจาก cache
    (ประหยัด ~90% ของค่า input ในส่วน system prompt)
    """
    model = model or DEFAULT_MODEL
    client = get_client()

    log.info("เรียก Claude ตีความดวง | โมเดล=%s | prompt_version=%s", model, PROMPT_VERSION)

    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": build_user_message(engine_json, question)}],
    )

    if response.stop_reason == "refusal":
        # โมเดลปฏิเสธ (เกิดได้ยากมากกับงานนี้) — แจ้งตรงๆ ดีกว่าเงียบ
        log.warning("Claude ปฏิเสธการตีความ (stop_reason=refusal)")
        return {
            "text": "ขออภัย ระบบไม่สามารถตีความดวงนี้ได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง",
            "model": model,
            "usage": None,
        }

    text = "".join(b.text for b in response.content if b.type == "text")
    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0),
        "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0),
    }
    log.info(
        "ตีความสำเร็จ | input=%s output=%s cache_read=%s",
        usage["input_tokens"], usage["output_tokens"], usage["cache_read_input_tokens"],
    )
    return {"text": text, "model": model, "usage": usage}
