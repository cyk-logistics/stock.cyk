#!/usr/bin/env python3
"""
Backtest ระบบ "จังหวะเข้าซื้อ" ย้อน 10 ปี — หาว่าเข้าแบบไหน "ชนะตลาด"
เฉพาะหุ้นปันผลดี (trailing yield >= DIV_MIN) ใน TICKERS ของ screener

เทียบแต่ละกลยุทธ์กับ: (1) ซื้อถือหุ้นตัวนั้น (2) ซื้อถือดัชนี SET
ผลตอบแทน = total return (auto_adjust=True รวมปันผล) · เข้าที่ราคาปิดวันถัดจากสัญญาณ

⚠️ ข้อจำกัด: ใช้รายชื่อปัจจุบัน (survivorship bias) · ไม่รวมค่าคอม/slippage/ภาษี ·
   yfinance อาจคลาดเคลื่อน · อดีตไม่รับประกันอนาคต

รัน: python backtest_entries.py   (เขียนผล backtest_results.json + พิมพ์สรุป)
"""
import argparse
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from screener import TICKERS, ema, rsi, macd

warnings.filterwarnings("ignore")
YEARS = 10
DIV_MIN = 3.0            # ยีลด์ขั้นต่ำ (%) ที่ถือว่า "ปันผลดีพอ"
OUT = Path(__file__).parent / "backtest_results.json"


# ---------- โหลดข้อมูล ----------
def load(sym):
    df = yf.Ticker(sym + ".BK").history(period="%dy" % YEARS, auto_adjust=True)
    if df is None or len(df) < 500:
        return None
    df = df[["Open", "High", "Low", "Close"]].dropna()
    return df


def trailing_yield(sym, price):
    try:
        d = yf.Ticker(sym + ".BK").dividends
        if d is None or len(d) == 0:
            return 0.0
        cut = d.index.max() - pd.Timedelta(days=365)
        return float(d[d.index >= cut].sum() / price * 100) if price else 0.0
    except Exception:
        return 0.0


# ---------- อินดิเคเตอร์ประกอบ ----------
def indicators(df):
    c = df["Close"]
    return {
        "close": c.values.astype(float),
        "e20": ema(c, 20).values, "e50": ema(c, 50).values,
        "e200": ema(c, 200).values, "rsi": rsi(c).values,
        "macd": macd(c)[0].values, "sig": macd(c)[1].values,
        "hi60": c.rolling(60).max().values, "hi200": c.rolling(200).max().values,
        "ret": c.pct_change().fillna(0).values,
    }


# ---------- นิยามกลยุทธ์เข้า → คืน position array (1=ถืออยู่) ----------
def positions(ind):
    c, e20, e50, e200 = ind["close"], ind["e20"], ind["e50"], ind["e200"]
    r, ml, ms = ind["rsi"], ind["macd"], ind["sig"]
    hi60, hi200 = ind["hi60"], ind["hi200"]
    n = len(c)
    P = {}

    # กลยุทธ์แบบ mask (ถือเมื่อเงื่อนไขจริง)
    P["ซื้อถือ (Buy&Hold)"] = np.ones(n)
    P["ถือเมื่อ EMA50>EMA200"] = (e50 > e200).astype(float)
    P["ถือเมื่อราคา>EMA200"] = (c > e200).astype(float)

    def statemachine(entry, exit_):
        pos = np.zeros(n); inpos = False
        for i in range(n):
            if not inpos and entry[i]:
                inpos = True
            elif inpos and exit_[i]:
                inpos = False
            pos[i] = 1.0 if inpos else 0.0
        return pos

    up = c > e200                                  # ตัวกรองขาขึ้นระยะยาว
    xdn_e50 = c < e50                              # หลุด EMA50 = ออก
    # RSI ย่อในขาขึ้น
    rsi_cross_up = np.concatenate([[False], (r[:-1] < 35) & (r[1:] >= 35)])
    P["ย่อ RSI<35 เด้ง (ขาขึ้น)"] = statemachine(up & rsi_cross_up, (r > 70) | xdn_e50)
    # MACD ตัดขึ้นในขาขึ้น
    macd_up = np.concatenate([[False], (ml[:-1] <= ms[:-1]) & (ml[1:] > ms[1:])])
    macd_dn = np.concatenate([[False], (ml[:-1] >= ms[:-1]) & (ml[1:] < ms[1:])])
    P["MACD ตัดขึ้น (ขาขึ้น)"] = statemachine(up & macd_up, macd_dn | xdn_e50)
    # ย่อแตะ EMA50 แล้วยืน (ขาขึ้น)
    reclaim = np.concatenate([[False], (c[:-1] < e50[:-1]) & (c[1:] >= e50[1:])])
    P["ย่อแตะ EMA50 แล้วยืน"] = statemachine(up & reclaim, xdn_e50)
    # ย่อ 10% จากไฮ 60 วัน ในขาขึ้น
    dip = c <= 0.90 * hi60
    P["ย่อ 10% จากไฮ (ขาขึ้น)"] = statemachine(up & dip, (c >= hi60) | (c < e200))
    # เบรกไฮ 200 วัน
    newhi = c >= hi200
    P["เบรกไฮ 200 วัน"] = statemachine(newhi, xdn_e50)
    return P


# ---------- วัดผลจาก position ----------
def perf(ret, pos):
    pos = np.asarray(pos, float)
    posn = np.concatenate([[0.0], pos[:-1]])       # เข้าที่แท่งถัดไป (กัน lookahead)
    sr = ret * posn
    eq = np.cumprod(1 + sr)
    yrs = len(ret) / 252.0
    cagr = eq[-1] ** (1 / yrs) - 1 if eq[-1] > 0 else -1.0
    dd = float((eq / np.maximum.accumulate(eq) - 1).min())
    expo = float(posn.mean())
    # นับเทรด + winrate
    tr, wins, cur = 0, 0, 1.0
    trades = []
    for i in range(len(posn)):
        if posn[i] == 1:
            cur *= (1 + ret[i])
        if posn[i] == 1 and (i + 1 >= len(posn) or posn[i + 1] == 0):
            trades.append(cur - 1); cur = 1.0
    tr = len(trades)
    wins = sum(1 for t in trades if t > 0)
    winrate = (wins / tr * 100) if tr else 0.0
    avgtrade = (np.mean(trades) * 100) if trades else 0.0
    return {"cagr": cagr * 100, "maxdd": dd * 100, "expo": expo * 100,
            "trades": tr, "winrate": winrate, "avgtrade": avgtrade}


FQ_H = (60, 120)          # วัดผลตอบแทนล่วงหน้าหลังเข้า (วันทำการ)


def entries_from_pos(pos):
    pos = np.asarray(pos)
    return [i for i in range(1, len(pos)) if pos[i] == 1 and pos[i - 1] == 0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="จำกัดจำนวนหุ้น (ทดสอบเร็ว)")
    a = ap.parse_args()
    syms = TICKERS[:a.limit] if a.limit else TICKERS

    set_cagr = None                       # yfinance ไม่มีประวัติดัชนี SET (คืนแค่แท่งวันนี้)
    try:
        sdf = yf.Ticker("^SET.BK").history(period="%dy" % YEARS, auto_adjust=True)
        if sdf is not None and len(sdf) >= 500:
            sr = sdf["Close"].pct_change().fillna(0).values
            set_cagr = ((np.cumprod(1 + sr)[-1]) ** (252 / len(sr)) - 1) * 100
    except Exception:
        set_cagr = None

    universe, agg, fq = [], {}, {}
    for s in syms:
        df = load(s)
        if df is None:
            continue
        price = float(df["Close"].iloc[-1])
        y = trailing_yield(s, price)
        if y < DIV_MIN:
            continue
        universe.append((s, y))
        ind = indicators(df)
        P = positions(ind)
        close = ind["close"]
        for name, pos in P.items():
            agg.setdefault(name, []).append(perf(ind["ret"], pos))
            if name.startswith("ซื้อถือ") or name.startswith("ถือเมื่อ"):
                continue                   # ข้ามกลยุทธ์ "อยู่ตลอด/mask" ตอนวัดคุณภาพจุดเข้า
            for e in entries_from_pos(pos):
                ex = e + 1
                for H in FQ_H:
                    if ex + H < len(close):
                        fq.setdefault(name, {}).setdefault(H, []).append(close[ex + H] / close[ex] - 1)
        print("  ✓ %s (yield %.1f%%)" % (s, y))

    bh = agg.get("ซื้อถือ (Buy&Hold)", [])
    bh_cagr = float(np.mean([x["cagr"] for x in bh])) if bh else float("nan")
    rows = []
    for name, lst in agg.items():
        cagrs = [x["cagr"] for x in lst]
        beat = sum(1 for x, b in zip(lst, bh) if x["cagr"] > b["cagr"])
        rows.append({"strategy": name, "avg_cagr": round(float(np.mean(cagrs)), 2),
                     "median_cagr": round(float(np.median(cagrs)), 2),
                     "avg_maxdd": round(float(np.mean([x["maxdd"] for x in lst])), 2),
                     "avg_exposure": round(float(np.mean([x["expo"] for x in lst])), 1),
                     "avg_winrate": round(float(np.mean([x["winrate"] for x in lst])), 1),
                     "beat_basket_pct": round(beat / len(lst) * 100, 1) if lst else 0})
    rows.sort(key=lambda r: r["avg_cagr"], reverse=True)

    eq = []
    for name, hs in fq.items():
        rec = {"entry": name}
        for H in FQ_H:
            v = hs.get(H, [])
            rec["n%d" % H] = len(v)
            rec["fwd%d_avg" % H] = round(float(np.mean(v)) * 100, 2) if v else None
            rec["fwd%d_win" % H] = round(sum(1 for x in v if x > 0) / len(v) * 100, 1) if v else None
        eq.append(rec)
    eq.sort(key=lambda r: (r.get("fwd120_avg") if r.get("fwd120_avg") is not None else -99), reverse=True)

    out = {"years": YEARS, "div_min": DIV_MIN, "n_stocks": len(universe),
           "set_cagr": (round(set_cagr, 2) if set_cagr is not None else None),
           "basket_buyhold_cagr": round(bh_cagr, 2),
           "universe": [{"sym": s, "yield": round(y, 2)} for s, y in universe],
           "strategies": rows, "entry_quality": eq}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n===== BACKTEST %d ปี · หุ้นปันผล>=%.0f%% · %d ตัว =====" % (YEARS, DIV_MIN, len(universe)))
    print("เกณฑ์ตลาด: ซื้อถือตะกร้าหุ้นปันผล CAGR %.2f%% · ดัชนี SET(ราคา) 10y: %s" %
          (bh_cagr, ("%.2f%%" % set_cagr if set_cagr is not None else "ไม่มีประวัติใน yfinance")))
    print("\n[A] ระบบสลับเข้า-ออก (ผลตอบแทนทบต้นเต็มพอร์ต) เทียบซื้อถือ:")
    print("%-26s %7s %7s %6s %6s %8s" % ("กลยุทธ์", "CAGR", "maxDD", "expo%", "win%", "ชนะถือ%"))
    for r in rows:
        print("%-26s %6.1f%% %6.1f%% %5.0f %6.1f %7.0f%%" %
              (r["strategy"][:26], r["avg_cagr"], r["avg_maxdd"], r["avg_exposure"],
               r["avg_winrate"], r["beat_basket_pct"]))
    print("\n[B] คุณภาพ 'จุดเข้า' (ผลตอบแทนล่วงหน้าหลังสัญญาณ — ใช้เลือกทำลูกศร):")
    print("%-26s %6s %9s %7s %9s" % ("สัญญาณเข้า", "N", "+120วัน", "ชนะ%", "+60วัน"))
    for r in eq:
        print("%-26s %6d %8s%% %6s%% %8s%%" % (r["entry"][:26], r.get("n120", 0),
              r.get("fwd120_avg"), r.get("fwd120_win"), r.get("fwd60_avg")))
    print("\nเขียนผลลง", OUT.name)


if __name__ == "__main__":
    main()
