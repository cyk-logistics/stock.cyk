#!/usr/bin/env python3
"""
ระบบ 2 "🐄 Cash Cow" — ควรซื้อหุ้นกลุ่มนี้จังหวะไหน? backtest 10 ปี (ผลตอบแทนรวมปันผล auto_adjust)
กลุ่มหุ้น = ผ่านเกณฑ์ลงทุนแมน >= 3/4 ข้อ จาก cashcow.json (⚠️ ใช้งบปัจจุบันคัด = มี look-ahead bias)
วัดผลถือ 120 และ 250 วันทำการหลังเข้า เทียบ "ซื้อวันไหนก็ได้" (ค่าเฉลี่ยทุกวัน)
กฎเข้าที่ทดสอบ (นับวันแรกที่เกิด แล้วเว้น 20 วันกันนับซ้ำ):
  A ระบบ 1 (EMA200 + ย่อ 10%/RSI<40) · B ย่อ >=10% จากไฮ 1 ปี · C ย่อ >=15% จากไฮ 1 ปี · D ย่อ >=20%
  E RSI<30 · F ยีลด์ 12 เดือน >= 1.2 เท่าของมัธยฐานยีลด์ 5 ปี (ถูกเทียบตัวเอง) · G ยีลด์สูงสุดใน 3 ปี
รัน: python backtest_cashcow.py → ตาราง + backtest_cashcow.json
"""
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from backtest_exits import ema, rsi

warnings.filterwarnings("ignore")
H = (120, 250)
GAP = 20


def load(sym):
    t = yf.Ticker(sym + ".BK")
    px = t.history(period="11y", auto_adjust=True)          # ผลตอบแทนรวมปันผล
    raw = t.history(period="11y", auto_adjust=False)          # ราคาจริง ไว้คิดยีลด์
    if px is None or len(px) < 600:
        return None
    div = raw["Dividends"] if "Dividends" in raw else pd.Series(0, index=raw.index)
    ttm = div.rolling(252, min_periods=200).sum()
    yld = (ttm / raw["Close"] * 100).reindex(px.index)
    return px["Close"].values.astype(float), px["High"].values.astype(float), yld.values.astype(float)


def main():
    cc = json.loads(Path("cashcow.json").read_text(encoding="utf-8"))
    syms = [r["sym"] for r in cc["rows"] if not r.get("fin") and r.get("passed", 0) >= 3]
    print("กลุ่มทดสอบ (ผ่าน >=3/4):", ", ".join(syms), flush=True)
    res = {k: {h: [] for h in H} for k in "ABCDEFG"}
    base = {h: [] for h in H}
    for s in syms:
        d = load(s)
        if d is None:
            print("  ✗", s); continue
        c, hi, y = d
        n = len(c)
        e200, r = ema(c, 200), rsi(c)
        hi60 = pd.Series(hi).shift(1).rolling(60).max().values
        hi250 = pd.Series(hi).shift(1).rolling(250).max().values
        ymed = pd.Series(y).rolling(1250, min_periods=750).median().values
        ymax3 = pd.Series(y).shift(1).rolling(750, min_periods=500).max().values
        dip = lambda k: c <= (1 - k) * hi250
        rules = {"A": (c > e200) & ((c <= 0.9 * hi60) | (r < 40)), "B": dip(0.10), "C": dip(0.15), "D": dip(0.20),
                 "E": r < 30, "F": y >= 1.2 * ymed, "G": y >= ymax3}
        start = 260
        for h in H:
            base[h] += [c[i + h] / c[i] - 1 for i in range(start, n - h)]
        for k, sig in rules.items():
            sig = np.nan_to_num(sig.astype(float)) > 0
            last = -999
            for i in range(start, n):
                if sig[i] and not sig[i - 1] and i - last >= GAP:
                    last = i
                    for h in H:
                        if i + h < n:
                            res[k][h].append(c[i + h] / c[i] - 1)
        print("  ✓", s, flush=True)
    names = {"A": "ระบบ 1 (EMA200 + ย่อ10%/RSI<40)", "B": "ย่อ ≥10% จากไฮ 1 ปี", "C": "ย่อ ≥15% จากไฮ 1 ปี",
             "D": "ย่อ ≥20% จากไฮ 1 ปี", "E": "RSI < 30", "F": "ยีลด์ ≥1.2× มัธยฐาน 5 ปี", "G": "ยีลด์สูงสุดรอบ 3 ปี"}
    out = {"universe": syms, "horizons": list(H), "rows": []}
    print("\n%-34s %6s %9s %7s %9s %7s" % ("จังหวะเข้า", "ครั้ง", "120วัน เฉลี่ย", "ชนะ%", "250วัน เฉลี่ย", "ชนะ%"))
    b = {h: np.array(base[h]) * 100 for h in H}
    print("%-34s %6s %8.2f%% %6.1f%% %8.2f%% %6.1f%%" % ("ซื้อวันไหนก็ได้ (ฐาน)", "-", b[120].mean(), (b[120] > 0).mean() * 100,
                                                        b[250].mean(), (b[250] > 0).mean() * 100))
    out["rows"].append({"rule": "ฐาน", "avg120": round(b[120].mean(), 2), "win120": round((b[120] > 0).mean() * 100, 1),
                        "avg250": round(b[250].mean(), 2), "win250": round((b[250] > 0).mean() * 100, 1)})
    for k in "ABCDEFG":
        a = {h: np.array(res[k][h]) * 100 for h in H}
        if len(a[120]) == 0:
            continue
        row = {"rule": names[k], "key": k, "n": len(a[120]), "avg120": round(a[120].mean(), 2),
               "win120": round((a[120] > 0).mean() * 100, 1),
               "avg250": round(a[250].mean(), 2) if len(a[250]) else None,
               "win250": round((a[250] > 0).mean() * 100, 1) if len(a[250]) else None,
               "p10_250": round(float(np.percentile(a[250], 10)), 1) if len(a[250]) else None}
        out["rows"].append(row)
        print("%-34s %6d %8.2f%% %6.1f%% %8.2f%% %6.1f%%" % (row["rule"], row["n"], row["avg120"], row["win120"],
                                                            row["avg250"] or 0, row["win250"] or 0))
    Path("backtest_cashcow.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
