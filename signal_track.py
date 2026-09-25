#!/usr/bin/env python3
"""
ติดตามหุ้นที่เมลแนะนำ + สัญญาณ "ควรออก" (ใช้ในเมลรายวันและเมลสรุปสิ้นเดือน)

กฎออก — เลือกจาก backtest 10 ปี 55 หุ้น 2,137 จุดเข้า (backtest_exits.py · กฎเข้าเดียวกับเมล):
  🔴 ตัดขาดทุน : ราคาปิด <= ราคาแนะนำ -15%
  ⏰ ครบรอบ   : ถือครบ 120 วันทำการ (~6 เดือน) = รอบที่ backtest ให้ผลดีสุด
ผลทดสอบ: ถือครบ 120 วัน เฉลี่ย +7.1% ชนะ 55% (5% ที่แย่สุด -25.6%) · ใส่ตัดขาดทุน -15% เฉลี่ย +4.8% ชนะ 49%
แต่กรณีแย่สุดเหลือ -19.1% (และ backtest ใช้หุ้นที่ยังอยู่วันนี้ = ประเมินความเสี่ยงต่ำกว่าจริง จึงควรมีจุดตัดขาดทุน)
กฎอื่น (หลุด EMA200 / กลับถึงไฮเดิม / trailing stop / RSI ลงจาก 70) เฉลี่ยแย่กว่าถือทุกแบบ → ใช้เป็นแค่ "ป้ายสถานะ"

ตำแหน่ง = เปิดเมื่อแนะนำครั้งแรก · แนะนำซ้ำระหว่างถือ = นับครั้ง · ปิดเมื่อเกิดสัญญาณออก (บันทึก history/exits.jsonl)
แนะนำใหม่หลังปิดไปแล้ว = เปิดตำแหน่งใหม่
"""
STOP = 15.0
HOLD = 120
STAT_NOTE = ("สัญญาณออกทดสอบย้อนหลัง 10 ปี (55 หุ้น 2,137 ครั้ง): ถือครบ 120 วันทำการ เฉลี่ย +7.1% ชนะ 55% · "
             "ตัดขาดทุนที่ -15% ผลเฉลี่ยลดเหลือ +4.8% แต่กรณีแย่สุดเสียหายน้อยลง (-25.6% → -19.1%) · "
             "ออกตอนหลุด EMA200 / กลับถึงไฮเดิม / trailing ได้ผลเฉลี่ยแย่กว่าถือ จึงเป็นแค่ป้ายสถานะ")


def _ema(vals, p):
    k = 2 / (p + 1)
    out, e = [], None
    for v in vals:
        e = v if e is None else v * k + e * (1 - k)
        out.append(e)
    return out


def positions(recs, exits=()):
    """recs = ประวัติเรียงตามเวลา · exits = รายการที่เคยแจ้งออกแล้ว → คืนรายการตำแหน่ง (เก่า→ใหม่)"""
    closed = {(e.get("sym"), e.get("entry_sent_at")): e for e in exits}
    cur, out = {}, []
    for r in sorted(recs, key=lambda x: x.get("sent_at", "")):
        s = r["sym"]
        d = str(r.get("bar", r.get("sent_at", "")))[:10]
        p = cur.get(s)
        if p is not None and p.get("exit") and d > p["exit"]["exit_date"]:
            if r.get("source") == "1D" and r.get("new") is False:
                continue                               # สัญญาณเดิมยังค้าง (ไม่ใช่สัญญาณใหม่) หลังออก → ไม่นับเข้าใหม่ (ตรงกับ backtest)
            p = None                                   # ออกไปแล้ว + สัญญาณเกิดใหม่ = ตำแหน่งใหม่
        if p is None:
            p = {"sym": s, "entry_sent_at": r["sent_at"], "entry_date": d, "entry": r.get("price"),
                 "source": r.get("source", ""), "sources": {r.get("source", "")}, "times": 1,
                 "reason": r.get("reason", ""), "exit": closed.get((s, r["sent_at"]))}
            cur[s] = p
            out.append(p)
        else:
            p["times"] += 1
            p["sources"].add(r.get("source", ""))
            if p["entry"] is None and r.get("price") is not None:
                p["entry"] = r["price"]
    return out


def evaluate(p, candles):
    """ตำแหน่ง p กับแท่งรายวัน (เรียงเก่า→ใหม่) → สถานะ ณ แท่งล่าสุด + สัญญาณออก (ถ้ามี) · None = ข้อมูลไม่พอ"""
    if not candles:
        return None
    dates = [str(c.get("bar_time", ""))[:10] for c in candles]
    closes = [float(c["close"]) for c in candles]
    highs = [float(c.get("high", c["close"])) for c in candles]
    before = [i for i, d in enumerate(dates) if d <= p["entry_date"]]
    if not before:
        return None
    ie = before[-1]
    entry = p["entry"] if p.get("entry") else closes[ie]
    exit_ = None
    for k, j in enumerate(range(ie + 1, len(closes)), start=1):
        if closes[j] <= entry * (1 - STOP / 100):
            exit_ = {"exit_date": dates[j], "exit_price": closes[j], "kind": "stop",
                     "reason": "🔴 ตัดขาดทุน (ต่ำกว่าราคาแนะนำ %d%%)" % STOP}
            break
        if k >= HOLD:
            exit_ = {"exit_date": dates[j], "exit_price": closes[j], "kind": "time",
                     "reason": "⏰ ครบ %d วันทำการ — ขายตามรอบ/ประเมินใหม่" % HOLD}
            break
    last = closes[-1]
    e200 = _ema(closes, 200)[-1] if len(closes) >= 200 else None
    target = max(highs[max(0, ie - 60):ie]) if ie >= 20 else None       # ไฮก่อนย่อ = เป้าตามธรรมชาติของจังหวะย่อซื้อ
    tags = []
    if target and last >= target:
        tags.append("🎯 กลับถึงไฮเดิมแล้ว")
    if e200 and last < e200:
        tags.append("⚠️ ต่ำกว่า EMA200")
    stop = entry * (1 - STOP / 100)
    return {"entry": entry, "last": last, "last_date": dates[-1], "chg": (last / entry - 1) * 100,
            "days": len(closes) - 1 - ie, "stop": stop, "to_stop": (last / stop - 1) * 100,
            "target": target, "exit": exit_, "tags": tags}


def track(recs, exits, cmap):
    """คืน (ถืออยู่, สัญญาณออกใหม่) — cmap = {หุ้น: แท่งรายวัน}"""
    held, new_exits = [], []
    for p in positions(recs, exits):
        if p.get("exit"):
            continue                                   # เคยแจ้งออกไปแล้ว
        st = evaluate(p, cmap.get(p["sym"]))
        if st is None:
            continue
        p.update(st)
        (new_exits if st["exit"] else held).append(p)
    held.sort(key=lambda x: x["chg"], reverse=True)
    return held, new_exits


def exit_record(p):
    """แถวสำหรับ history/exits.jsonl"""
    e = p["exit"]
    return {"sym": p["sym"], "entry_sent_at": p["entry_sent_at"], "entry_date": p["entry_date"],
            "entry_price": round(p["entry"], 4), "exit_date": e["exit_date"], "exit_price": round(e["exit_price"], 4),
            "ret": round((e["exit_price"] / p["entry"] - 1) * 100, 2), "kind": e["kind"], "reason": e["reason"]}
