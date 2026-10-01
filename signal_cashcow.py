#!/usr/bin/env python3
"""
ระบบ 2 🐄 Cash Cow — แยกจากระบบ 1 (ย่อซื้อ 56 ตัว) ทั้งเมล ประวัติ และสัญญาณออก
กลุ่มหุ้น: ผ่านเกณฑ์ลงทุนแมน >= 3/4 ข้อ (cashcow.json — cashcow_screen.py อัปเดตรายเดือน)
  FCF บวกและโต · ROE >= 15% ทุกปี · จ่ายปันผล 50-80% ของกำไร · หนี้มีดอกเบี้ย/ทุน <= 1.5 เท่า
จังหวะเข้า: กฎเดียวกับระบบ 1 (ราคา>EMA200 + ย่อ >=10% จากไฮ 60 วัน หรือ RSI<40)
  backtest 10 ปีบนกลุ่มนี้ (backtest_cashcow.py): ถือ 250 วัน +19.4% ชนะ 54% · ซื้อวันไหนก็ได้ +13.8%
  ย่อลึกโดยไม่ดูเทรนด์ แย่กว่าซื้อวันไหนก็ได้ (ย่อ >=20% จากไฮ 1 ปี +5.6%)
ออก: ตัดขาดทุน -15% · ถือครบ 250 วันทำการ (signal_track.HOLD_BY_SOURCE)
ส่งเมลเมื่อ: มีสัญญาณใหม่ (🆕) หรือมีตัวควรออก — ไม่ส่งซ้ำทุกวันถ้าไม่มีอะไรใหม่ (SEND_EMPTY=1 = ส่งเสมอ)
รัน: python signal_cashcow.py [--dry]
"""
import json
import os
import sys
from pathlib import Path

import signal_email as se
import push_notify
import signal_history
import signal_track

CC_FILE = Path(__file__).parent / "cashcow.json"
LAB = {"fcf": "FCF", "roe": "ROE", "payout": "ปันผล50-80%", "ibde": "หนี้"}


def universe():
    cc = json.loads(CC_FILE.read_text(encoding="utf-8"))
    U = {r["sym"]: r for r in cc.get("rows", []) if not r.get("fin") and r.get("passed", 0) >= 3}
    return U, str(cc.get("updated", ""))[:10]


def scan(U):
    """คืน (หุ้น Cash Cow ที่อยู่ในจังหวะซื้อ, วันที่แท่งล่าสุด, แท่งรายวัน, สภาพตลาด)"""
    _, last_date, cmap, market = se.scan()             # แท่ง 56 ตัว + สภาพตลาด (ใช้ร่วมกับระบบ 1)
    extra = [s for s in U if s not in cmap]
    for i in range(0, len(extra), 20):
        chunk = ",".join(extra[i:i + 20])
        try:
            d = se._get("%s/api/candles?symbols=%s&interval=1d&limit=250&final=0&key=%s"
                        % (se.BASE, chunk, se.KEY))["data"]
        except Exception as e:
            print("chunk error:", str(e)[:80]); continue
        for s, v in d.items():
            cs = v.get("candles") if isinstance(v, dict) else None
            if cs and "error" not in v:
                cmap[s] = cs
    sigs = []
    for s, r in U.items():
        cs = cmap.get(s)
        if not cs or len(cs) < 210:
            continue
        cl = [c["close"] for c in cs]; hi = [c["high"] for c in cs]
        if not se._is_signal(cl, hi):
            continue
        last = cl[-1]; hi60 = max(hi[-61:-1]); pct = (last / hi60 - 1) * 100; rs = se._rsi(cl)
        risk = (["⚠️ ร่วงเร็ว"] if len(cl) > 11 and (last / cl[-11] - 1) * 100 < -10 else []) + \
               (["⚠️ ย่อลึก>20%"] if pct < -20 else [])          # เหมือนระบบ 1 (analyze_stops.py: โดนตัดขาดทุน ~50%)
        sigs.append({"sym": s, "last": last, "rsi": rs, "pct": pct, "cc": r, "risk": risk,
                     "reason": ("ย่อ %.0f%% จากไฮ 60 วัน" % pct) if last <= 0.9 * hi60 else ("RSI ต่ำ %.0f" % rs),
                     "new": not se._is_signal(cl[:-1], hi[:-1])})
    sigs.sort(key=lambda b: (b["new"], b["cc"].get("passed", 0), b["cc"].get("roe_avg") or 0), reverse=True)
    return sigs, last_date, cmap, market


def _cc_text(r):
    return "ROE %s%% · จ่าย %s%% · หนี้ %.2fx · ปันผล %d ปีติด%s" % (
        r.get("roe_avg"), r.get("payout_avg"), r.get("ibde") or 0, r.get("div_streak") or 0,
        (" · ยีลด์ %.1f%%" % r["yield"]) if r.get("yield") else "")


def build_email(sigs, last_date, held, exits, market, U, updated):
    TD, TH, pc, clr, dm = se.TD, se.TH, se._pc, se._clr, se._dm
    nn = sum(1 for b in sigs if b["new"])
    subj = "🐄 ระบบ Cash Cow — %s%s%s" % (
        ("ซื้อใหม่ %d" % nn) if nn else "", (" · " if nn and exits else ""), ("ควรออก %d" % len(exits)) if exits else "")
    if not nn and not exits:
        subj = "🐄 ระบบ Cash Cow — สรุปสถานะ"
    subj += " (%s)" % last_date
    mtxt, mhtml = se.market_line(market)
    tl = ["🐄 ระบบ Cash Cow — แท่งล่าสุด %s · กลุ่มหุ้นอัปเดต %s" % (last_date, updated)] + ([mtxt] if mtxt else []) + [""]
    parts = [mhtml] if mhtml else []
    if exits:
        tl.append("🔴 ควรออก")
        rows = ""
        for p in exits:
            e = p["exit"]; r = (e["exit_price"] / p["entry"] - 1) * 100
            tl.append("- %-7s แนะนำ %s @%.2f → ออก %s @%.2f  %s  · %s"
                      % (p["sym"], dm(p["entry_date"]), p["entry"], dm(e["exit_date"]), e["exit_price"], pc(r), e["reason"]))
            rows += ("<tr><td %s><b>%s</b></td><td %s>%s</td><td %s>%.2f</td><td %s>%.2f</td><td %s><b>%s</b></td><td %s>%s</td></tr>"
                     % (TD % "", p["sym"], TD % "", dm(p["entry_date"]), TD % "text-align:right", p["entry"],
                        TD % "text-align:right", e["exit_price"], TD % ("text-align:right;color:%s" % clr(r)), pc(r), TD % "", e["reason"]))
        parts.append('<h3 style="color:#c62828;margin:18px 0 6px">🔴 ควรออก</h3><table style="border-collapse:collapse;font-size:14px">'
                     '<tr style="background:#fdeeee">%s%s%s%s%s%s</tr>%s</table>'
                     % (TH % ("left", "หุ้น"), TH % ("left", "แนะนำ"), TH % ("right", "ราคาแนะนำ"), TH % ("right", "ราคาออก"),
                        TH % ("right", "ผล"), TH % ("left", "สัญญาณ"), rows))
        tl.append("")
    if sigs:
        tl.append("🟢 Cash Cow ที่อยู่ในจังหวะซื้อ (ย่อในขาขึ้น)")
        rows = ""
        for b in sigs:
            r = b["cc"]
            tier = "🐄 ครบ 4 ข้อ" if r.get("passed") == 4 else "🐄 3/4 (ขาด %s)" % ",".join(LAB[k] for k in r.get("fail", []))
            rk = " ".join(b.get("risk") or [])
            tl.append("- %s%-7s %8.2f  %s %s · %s · %s" % ("🆕 " if b["new"] else "", b["sym"], b["last"], b["reason"], rk, tier, _cc_text(r)))
            rows += ("<tr><td %s><b>%s</b>%s</td><td %s>%.2f</td><td %s>%s</td><td %s>%s</td><td %s>%s</td></tr>"
                     % (TD % "", b["sym"], ' <span style="color:#0a8f5a;font-size:12px">🆕 ใหม่</span>' if b["new"] else "",
                        TD % "text-align:right", b["last"], TD % "",
                        b["reason"] + ((' <span style="color:#b26a00">%s</span>' % rk) if rk else ""), TD % "white-space:nowrap", tier,
                        TD % "font-size:13px", _cc_text(r)))
        parts.append('<h3 style="color:#0a8f5a;margin:18px 0 6px">🟢 Cash Cow ที่อยู่ในจังหวะซื้อ</h3>'
                     '<table style="border-collapse:collapse;font-size:14px"><tr style="background:#eef3f9">%s%s%s%s%s</tr>%s</table>'
                     % (TH % ("left", "หุ้น"), TH % ("right", "ราคา"), TH % ("left", "จังหวะ"), TH % ("left", "เกณฑ์"),
                        TH % ("left", "พื้นฐาน"), rows))
        tl.append("")
    if held:
        tl.append("📌 ถืออยู่ (ตัดขาดทุน -%d%% · ครบรอบ %d วัน)" % (signal_track.STOP, signal_track.HOLD_BY_SOURCE["CC"]))
        rows = ""
        for p in held:
            st = " · ".join(p["tags"]) if p["tags"] else "ถือต่อ"
            tl.append("- %-7s แนะนำ %s @%.2f → %.2f  %s  ถือ %d/%d วัน  ตัดขาดทุน %.2f  %s"
                      % (p["sym"], dm(p["entry_date"]), p["entry"], p["last"], pc(p["chg"]), p["days"], p["hold"], p["stop"], st))
            rows += ("<tr><td %s><b>%s</b></td><td %s>%s</td><td %s>%.2f</td><td %s>%.2f</td><td %s><b>%s</b></td>"
                     "<td %s>%d/%d</td><td %s>%.2f</td><td %s>%s</td></tr>"
                     % (TD % "", p["sym"], TD % "", dm(p["entry_date"]), TD % "text-align:right", p["entry"],
                        TD % "text-align:right", p["last"], TD % ("text-align:right;color:%s" % clr(p["chg"])), pc(p["chg"]),
                        TD % "text-align:right", p["days"], p["hold"], TD % "text-align:right", p["stop"], TD % "", st))
        parts.append('<h3 style="color:#0e3a6e;margin:18px 0 6px">📌 ถืออยู่ (%d ตัว)</h3><table style="border-collapse:collapse;font-size:14px">'
                     '<tr style="background:#eef3f9">%s%s%s%s%s%s%s%s</tr>%s</table>'
                     % (len(held), TH % ("left", "หุ้น"), TH % ("left", "แนะนำ"), TH % ("right", "ราคาแนะนำ"), TH % ("right", "ล่าสุด"),
                        TH % ("right", "เปลี่ยน"), TH % ("right", "ถือ (วัน)"), TH % ("right", "จุดตัดขาดทุน"), TH % ("left", "สถานะ"), rows))
        tl.append("")
    full = sorted(U.values(), key=lambda r: (-(r.get("passed") or 0), r["sym"]))
    lst4 = ", ".join(r["sym"] for r in full if r.get("passed") == 4)
    lst3 = ", ".join("%s (ขาด %s)" % (r["sym"], ",".join(LAB[k] for k in r.get("fail", []))) for r in full if r.get("passed") == 3)
    crit = ("กลุ่ม Cash Cow = ผ่านเกณฑ์ลงทุนแมน ≥3 ใน 4 ข้อ: FCF บวกและโต · ROE ≥15%% ทุกปี · จ่ายปันผล 50–80%% ของกำไร · "
            "หนี้มีดอกเบี้ย/ทุน ≤1.5 เท่า (งบปี ~4 ปี จาก Yahoo · อัปเดต %s)" % updated)
    stat = ("จังหวะเข้า = ย่อในขาขึ้น (เหมือนระบบ 1) · backtest 10 ปีบนกลุ่มนี้: ถือ 250 วัน เฉลี่ย +19.4% ชนะ 54% "
            "เทียบซื้อวันไหนก็ได้ +13.8% · ย่อลึกโดยไม่ดูเทรนด์ได้แย่กว่า · ⚠️ คัดกลุ่มด้วยงบปัจจุบัน = ผลย้อนหลังดูดีเกินจริง")
    tl += ["ครบ 4 ข้อ: " + (lst4 or "—"), "3 ข้อ: " + (lst3 or "—"), crit, stat,
           "ควรออก: ต่ำกว่าราคาแนะนำ %d%% (ตัดขาดทุน) · ถือครบ %d วันทำการ" % (signal_track.STOP, signal_track.HOLD_BY_SOURCE["CC"]),
           "ไม่ใช่คำแนะนำมีใบอนุญาต — ตัดสินใจ+คุมความเสี่ยงเอง"]
    html = ('<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#1a1f2b;max-width:760px">'
            '<h2 style="color:#6b4e00;margin:0 0 2px">🐄 ระบบ Cash Cow — หุ้นวัวเงินสด</h2>'
            '<div style="color:#5a6472;font-size:13px">แท่งล่าสุด %s · จาก live.atlog.asia · ในจังหวะซื้อ %d (ใหม่ %d) · ควรออก %d · ถืออยู่ %d</div>%s'
            '<p style="font-size:13px;color:#333;margin-top:16px;line-height:1.6"><b>กลุ่มหุ้น:</b> ครบ 4 ข้อ — %s<br><b>3 ข้อ:</b> %s</p>'
            '<p style="font-size:12px;color:#555;line-height:1.6">%s<br>%s<br><b>ควรออก:</b> ต่ำกว่าราคาแนะนำ %d%% · ถือครบ %d วันทำการ</p>'
            '<p style="font-size:12px;color:#7a8494">ไม่ใช่คำแนะนำมีใบอนุญาต — ตัดสินใจและคุมความเสี่ยงเอง</p></div>'
            % (last_date, len(sigs), nn, len(exits), len(held), "".join(parts), lst4 or "—", lst3 or "—", crit, stat,
               signal_track.STOP, signal_track.HOLD_BY_SOURCE["CC"]))
    return subj, "\n".join(tl), html


def main():
    if not se.KEY:
        raise SystemExit("ต้องตั้ง STOCK_API_KEY")
    dry = "--dry" in sys.argv
    U, updated = universe()
    sigs, last_date, cmap, market = scan(U)
    if not last_date:
        raise SystemExit("สแกนไม่ได้ — ดึงข้อมูลจาก %s ไม่ได้เลย (ไม่ใช่ 'ไม่มีสัญญาณ')" % se.BASE)
    held, exits = signal_track.track(signal_history.load(sources=signal_history.SYSTEM2),
                                     signal_history.load_exits(cc=True), cmap)
    new = [b for b in sigs if b["new"]]
    print("🐄 แท่งล่าสุด %s · กลุ่ม %d ตัว · ในจังหวะซื้อ %d: %s · ควรออก %d · ถืออยู่ %d"
          % (last_date, len(U), len(sigs), ", ".join(("🆕" if b["new"] else "") + b["sym"] for b in sigs),
             len(exits), len(held)))
    if not new and not exits and os.environ.get("SEND_EMPTY", "") not in ("1", "true", "yes"):
        print("ไม่มีสัญญาณใหม่/ตัวควรออก — ไม่ส่งเมล")
        return
    subj, text, html = build_email(sigs, last_date, held, exits, market, U, updated)
    if dry:
        print("\n[DRY] subject:", subj, "\n", text)
        return
    if not os.environ.get("RESEND_API_KEY"):
        raise SystemExit("ต้องตั้ง RESEND_API_KEY (ยังไม่ได้ส่ง)")
    r = se.send_resend(subj, text, html)
    print("ส่งเมลแล้ว:", r.get("id", r) if isinstance(r, dict) else r)
    first = ([b["sym"] for b in new] or [p["sym"] for p in exits] or [b["sym"] for b in sigs] or ["PTT"])[0]
    push_notify.notify(subj.split(" (")[0],
                       " · ".join(x for x in [("ซื้อใหม่: " + push_notify.short_list(b["sym"] for b in new)) if new else "",
                                              ("ออก: " + push_notify.short_list(p["sym"] for p in exits)) if exits else "",
                                              ("ในจังหวะซื้อ: " + push_notify.short_list(b["sym"] for b in sigs)) if sigs and not new else ""] if x),
                       "/#%s/1d" % first, tag="cashcow")
    eid = r.get("id", "") if isinstance(r, dict) else ""
    signal_history.append("CC", [{"bar": last_date, "sym": b["sym"], "price": round(b["last"], 4), "new": b["new"],
                                  "rsi": round(b["rsi"], 1), "pct": round(b["pct"], 1), "reason": b["reason"],
                                  "cc_passed": b["cc"].get("passed")} for b in sigs], email_id=eid)
    signal_history.append_exits([signal_track.exit_record(p) for p in exits], email_id=eid, cc=True)


if __name__ == "__main__":
    main()
