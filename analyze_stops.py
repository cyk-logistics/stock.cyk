#!/usr/bin/env python3
"""
หุ้นที่โดนตัดขาดทุน (-15%) มีสัญญาณบอกล่วงหน้าไหม? — วิเคราะห์จุดเข้า 10 ปี (กฎเดียวกับเมล)
ผลลัพธ์ต่อจุดเข้า: โดนตัดขาดทุนภายใน 120 วันไหม / ผลตอบแทนตามระบบ (ตัดขาดทุน -15% หรือครบ 120 วัน)
ตัวชี้วัด ณ วันเข้า + พฤติกรรม 1-10 วันแรก → เทียบอัตราโดนตัดขาดทุน · แบ่งครึ่งเวลา (ก่อน/หลัง 2021) เช็คว่าไม่ใช่บังเอิญ
รัน: python analyze_stops.py → พิมพ์ตาราง + analyze_stops.json
"""
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from backtest_exits import ema, rsi
from signal_email import UNIVERSE

warnings.filterwarnings("ignore")
HOLD, STOP = 120, 15.0
SPLIT = "2021-01-01"


def load(sym):
    df = yf.Ticker(sym + ".BK").history(period="10y", auto_adjust=True)
    if df is None or len(df) < 400:
        return None
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna()


def main():
    data = {}
    for s in UNIVERSE:
        d = load(s)
        if d is not None:
            d.index = d.index.tz_localize(None).normalize()
            data[s] = d
    print("โหลด %d หุ้น" % len(data), flush=True)
    # ตลาดโดยรวม (Yahoo ไม่มีประวัติดัชนี SET) → breadth = % หุ้นในกลุ่มที่ปิดเหนือ EMA200
    above = pd.DataFrame({s: pd.Series(d["Close"].values > ema(d["Close"].values.astype(float), 200), index=d.index)
                          for s, d in data.items()}).sort_index()
    breadth = above.mean(axis=1) * 100
    ew = pd.DataFrame({s: d["Close"].pct_change() for s, d in data.items()}).sort_index().mean(axis=1).fillna(0)
    mkt = (1 + ew).cumprod()                                  # ดัชนีเฉลี่ยเท่ากัน (แทน SET)
    mkt_e200 = pd.Series(ema(mkt.values, 200), index=mkt.index)

    rows = []
    for s, d in data.items():
        o, h, l, c, v = (d[k].values.astype(float) for k in ("Open", "High", "Low", "Close", "Volume"))
        idx = d.index
        e200, e50, r = ema(c, 200), ema(c, 50), rsi(c)
        tr = np.maximum(h - l, np.maximum(abs(h - np.roll(c, 1)), abs(l - np.roll(c, 1))))
        atr = pd.Series(tr).rolling(14).mean().values
        hi60 = np.full_like(c, np.nan); lo60 = np.full_like(c, np.nan)
        for i in range(61, len(c)):
            hi60[i] = h[i - 60:i].max(); lo60[i] = l[i - 60:i].min()
        sig = (c > e200) & ((c <= 0.90 * hi60) | (r < 40)); sig[:230] = False
        for i in range(231, len(c) - 5):
            if not sig[i] or sig[i - 1]:
                continue
            entry = c[i]; end = min(i + HOLD, len(c) - 1)
            stop_j = next((j for j in range(i + 1, end + 1) if c[j] <= entry * (1 - STOP / 100)), None)
            exit_j = stop_j if stop_j is not None else end
            v20 = v[i - 20:i].mean() if v[i - 20:i].mean() > 0 else np.nan
            dday = pd.Timestamp(idx[i])
            hi_i = int(np.argmax(h[i - 60:i])) + i - 60           # วันที่ทำไฮ 60 วัน
            f = {
                "sym": s, "date": str(dday.date()), "stopped": stop_j is not None,
                "ret": (c[exit_j] / entry - 1) * 100, "ret120": (c[end] / entry - 1) * 100,
                "days_to_stop": (stop_j - i) if stop_j is not None else None,
                # ---- ณ วันเข้า ----
                "reason_rsi_only": bool(not (c[i] <= 0.90 * hi60[i])),     # เข้าเพราะ RSI<40 อย่างเดียว (ยังย่อไม่ถึง 10%)
                "dip": (c[i] / hi60[i] - 1) * 100,                          # ย่อจากไฮกี่ %
                "above_e200": (c[i] / e200[i] - 1) * 100,                   # เหนือ EMA200 กี่ %
                "e200_slope": (e200[i] / e200[i - 20] - 1) * 100,           # EMA200 ชัน (20 วัน)
                "e50_over_e200": (e50[i] / e200[i] - 1) * 100,
                "rsi": r[i],
                "vr": v[i] / v20 if v20 else np.nan,                        # วอลลุ่ม x เท่าของ 20 วัน
                "green": c[i] >= o[i],
                "atr_pct": atr[i] / c[i] * 100,                             # ความผันผวนรายวัน
                "drop10": (c[i] / c[i - 10] - 1) * 100,                      # ร่วงเร็วแค่ไหนใน 10 วัน
                "days_from_high": i - hi_i,                                  # ไฮเกิดมาแล้วกี่วัน
                "ret250": (c[i] / c[i - 250] - 1) * 100 if i >= 250 else np.nan,  # โมเมนตัม 1 ปี
                "breadth": float(breadth.get(dday, np.nan)),                # % หุ้นในกลุ่มเหนือ EMA200
                "mkt_up": bool(mkt.get(dday, np.nan) > mkt_e200.get(dday, np.nan)),
                "below_lo60": c[i] < lo60[i],                               # หลุดโลว์ 60 วันแล้ว
            }
            # ---- พฤติกรรมช่วงแรก (เตือนล่วงหน้าหลังเข้า) ----
            for n in (5, 10):
                k = min(i + n, len(c) - 1)
                f["dd%d" % n] = (min(c[i + 1:k + 1]) / entry - 1) * 100 if k > i else 0.0
                f["r%d" % n] = (c[k] / entry - 1) * 100
                f["lostE200_%d" % n] = bool((c[i + 1:k + 1] < e200[i + 1:k + 1]).any())
                f["newlow_%d" % n] = bool((l[i + 1:k + 1] < l[i]).any())
            rows.append(f)
    df = pd.DataFrame(rows)
    base = df["stopped"].mean() * 100
    print("\nจุดเข้า %d ครั้ง · โดนตัดขาดทุน -15%% ภายใน 120 วัน %.1f%% · ผลตามระบบเฉลี่ย %+.2f%%"
          % (len(df), base, df["ret"].mean()))
    print("โดนตัดขาดทุนเฉลี่ยหลังเข้า %.0f วัน (มัธยฐาน %.0f)" % (df["days_to_stop"].mean(), df["days_to_stop"].median()))

    early, late = df["date"] < SPLIT, df["date"] >= SPLIT
    out = {"n": len(df), "stop_rate": round(base, 1), "avg_ret": round(df["ret"].mean(), 2), "features": []}

    def report(name, mask):
        m = mask.fillna(False) if hasattr(mask, "fillna") else mask
        if m.sum() < 40 or (~m).sum() < 40:
            return
        a, b = df[m], df[~m]
        e1 = df[m & early]["stopped"].mean() * 100; e0 = df[~m & early]["stopped"].mean() * 100
        l1 = df[m & late]["stopped"].mean() * 100; l0 = df[~m & late]["stopped"].mean() * 100
        consistent = (e1 - e0) * (l1 - l0) > 0 and abs(e1 - e0) >= 4 and abs(l1 - l0) >= 4
        rec = {"feature": name, "n": int(m.sum()), "stop_yes": round(a["stopped"].mean() * 100, 1),
               "stop_no": round(b["stopped"].mean() * 100, 1), "ret_yes": round(a["ret"].mean(), 2),
               "ret_no": round(b["ret"].mean(), 2), "early": [round(e1, 1), round(e0, 1)],
               "late": [round(l1, 1), round(l0, 1)], "consistent": bool(consistent)}
        out["features"].append(rec)
        print("%-44s n=%4d  โดนตัด %5.1f%% vs %5.1f%%  ผล %+6.2f%% vs %+6.2f%%  (ก่อน21: %4.1f/%4.1f · หลัง21: %4.1f/%4.1f) %s"
              % (name, rec["n"], rec["stop_yes"], rec["stop_no"], rec["ret_yes"], rec["ret_no"],
                 e1, e0, l1, l0, "✔ คงที่" if consistent else ""))

    print("\n=== ณ วันเข้า (ใช้คัดก่อนซื้อ) ===")
    report("เข้าเพราะ RSI<40 อย่างเดียว (ยังย่อไม่ถึง10%)", df["reason_rsi_only"])
    report("ย่อลึกกว่า 20% จากไฮ", df["dip"] < -20)
    report("ย่อ 10-15% (ตื้น)", (df["dip"] >= -15) & (df["dip"] < -10))
    report("เหนือ EMA200 ไม่ถึง 3% (จ่อหลุด)", df["above_e200"] < 3)
    report("เหนือ EMA200 เกิน 10%", df["above_e200"] > 10)
    report("EMA200 เริ่มชี้ลง/แบน (20วัน < +0.5%)", df["e200_slope"] < 0.5)
    report("EMA50 ต่ำกว่า EMA200 แล้ว", df["e50_over_e200"] < 0)
    report("RSI < 30 (ขายหนัก)", df["rsi"] < 30)
    report("วอลลุ่ม >= 2 เท่า", df["vr"] >= 2)
    report("วอลลุ่มหนุน (>=1.3x + แท่งเขียว)", (df["vr"] >= 1.3) & df["green"])
    report("วอลลุ่มพุ่ง + แท่งแดง (ขายทิ้ง)", (df["vr"] >= 1.5) & ~df["green"])
    report("ผันผวนสูง (ATR > 3%/วัน)", df["atr_pct"] > 3)
    report("ร่วงเร็ว (10 วัน ร่วง > 10%)", df["drop10"] < -10)
    report("ไฮเพิ่งเกิด <= 10 วัน (ดิ่งจากยอดเร็ว)", df["days_from_high"] <= 10)
    report("โมเมนตัม 1 ปี ติดลบ", df["ret250"] < 0)
    report("โมเมนตัม 1 ปี > +40% (ขึ้นแรงมาก่อน)", df["ret250"] > 40)
    report("ตลาดอ่อน: หุ้นเหนือ EMA200 < 40%", df["breadth"] < 40)
    report("ตลาดแข็ง: หุ้นเหนือ EMA200 > 60%", df["breadth"] > 60)
    report("ดัชนีกลุ่มต่ำกว่า EMA200 (ตลาดขาลง)", ~df["mkt_up"])
    report("หลุดโลว์ 60 วันแล้วตอนเข้า", df["below_lo60"])

    print("\n=== หลังเข้า 5-10 วันแรก (เตือนก่อนถึงจุดตัดขาดทุน) ===")
    for n in (5, 10):
        report("%d วันแรก ติดลบเกิน 5%%" % n, df["dd%d" % n] < -5)
        report("%d วันแรก ติดลบเกิน 8%%" % n, df["dd%d" % n] < -8)
        report("ครบ %d วัน ยังขาดทุน (ปิดต่ำกว่าราคาเข้า)" % n, df["r%d" % n] < 0)
        report("%d วันแรก หลุด EMA200" % n, df["lostE200_%d" % n])
        report("%d วันแรก ทำโลว์ใหม่ต่ำกว่าวันเข้า" % n, df["newlow_%d" % n])

    # ถ้าออกเร็วเมื่อสัญญาณเตือนหลังเข้าเกิด (แทนรอ -15%) → ดีขึ้นหรือแย่ลง?
    print("\n=== ถ้าออกทันทีเมื่อเตือน (เทียบกับระบบ ตัดขาดทุน -15%/120 วัน) ===")
    sims = []
    for n, thr in ((5, -5), (5, -8), (10, -8), (10, -10)):
        m = df["dd%d" % n] < thr
        # ออกที่ราคาปิดวันที่ n (ประมาณ — ใช้ r_n) สำหรับตัวที่ถูกเตือน · ที่เหลือใช้ผลระบบเดิม
        alt = np.where(m, df["r%d" % n], df["ret"])
        sims.append({"rule": "ครบ %d วันยังติดลบเกิน %d%% → ออก" % (n, -thr), "flagged": int(m.sum()),
                     "flag_stop_rate": round(df[m]["stopped"].mean() * 100, 1),
                     "avg_new": round(float(alt.mean()), 2), "avg_base": round(df["ret"].mean(), 2),
                     "p5_new": round(float(np.percentile(alt, 5)), 1), "p5_base": round(float(np.percentile(df["ret"], 5)), 1)})
    for sm in sims:
        print("%-36s เตือน %4d ครั้ง (ในนี้โดนตัดจริง %4.1f%%) · ผลเฉลี่ย %+.2f%% → %+.2f%% · แย่สุด5%% %+.1f%% → %+.1f%%"
              % (sm["rule"], sm["flagged"], sm["flag_stop_rate"], sm["avg_base"], sm["avg_new"], sm["p5_base"], sm["p5_new"]))
    out["early_exit_sims"] = sims
    Path("analyze_stops.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
