#!/usr/bin/env python3
"""
Signal Edge — วัด "ความแม่นจริง" ของสัญญาณแต่ละแบบย้อนหลัง 5 ปี (SET + MAI)
สำหรับทุกครั้งที่สัญญาณเกิดในอดีต → วัดผลตอบแทนล่วงหน้า 10/20 วันทำการ
ผลรวม: hit-rate (% ที่บวก) + ผลตอบแทนเฉลี่ย/มัธยฐาน + max gain/drawdown ต่อชนิดสัญญาณ
เขียนผลลง signal_edge.json → screener.py อ่านไปติดกำกับสัญญาณสด + โชว์ตารางบนเว็บ

⚠️ ข้อจำกัด (อ่านก่อนเชื่อ): ใช้รายชื่อ *ปัจจุบัน* = survivorship bias, ไม่รวมค่าคอม/slippage,
เข้าที่ราคาปิด, ผลตอบแทนวัดจากราคาล้วน (ไม่รวมปันผล), yfinance อาจคลาดเคลื่อน
รันหนัก → ตั้งใจให้รันสัปดาห์ละครั้ง (cron แยก) ไม่ใช่ทุกวัน
"""
import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import yfinance as yf

from screener import rsi, ema, macd, bollinger, TICKERS, MAI_TICKERS

LBL = LBR = 5
OS, OB = 40, 60          # เกณฑ์ divergence (ตรงกับ screener)
CONFIRM = 8              # รอยืนยันข้าม EMA20 ภายใน N แท่ง
HORIZONS = [10, 20]      # วัดผลล่วงหน้ากี่วันทำการ

EDGE_FILE = Path(__file__).parent / "signal_edge.json"

SIG_LABELS = {
    "bull_confirm": "🟢 เข้าได้ (Bull Div ยืนยันเหนือ EMA20)",
    "dip_buy":      "🟢 ย่อซื้อในขาขึ้น (โซน EMA50 + MACD ตัดขึ้น)",
    "oversold":     "🔵 Oversold (RSI ตัดลงใต้ 35)",
    "near800":      "🟣 ที่แนวรับใหญ่ (เข้าโซน EMA800 ±3%)",
    "bear_avoid":   "🔴 เลี่ยง (Bear Div ยืนยันใต้ EMA20)",
}


def detect_events(df):
    """คืน dict: signal_type -> list ของ index แท่งที่สัญญาณเกิด (ในอดีต)"""
    close = df["Close"].values.astype(float)
    low = df["Low"].values.astype(float)
    high = df["High"].values.astype(float)
    n = len(close)
    r = rsi(df["Close"]).values
    e20 = ema(df["Close"], 20).values
    e50 = ema(df["Close"], 50).values
    e200 = ema(df["Close"], 200).values
    e800 = ema(df["Close"], 800).values
    ml, ms, _ = macd(df["Close"])
    ml, ms = ml.values, ms.values
    _, _, bbl = bollinger(df["Close"])
    bbl = bbl.values

    ev = {k: [] for k in SIG_LABELS}

    # ----- pivots -----
    piv_lo = [i for i in range(LBL, n - LBR) if low[i] == np.min(low[i - LBL:i + LBR + 1])]
    piv_hi = [i for i in range(LBL, n - LBR) if high[i] == np.max(high[i - LBL:i + LBR + 1])]

    # ----- bull divergence -> armed -> ยืนยันข้าม EMA20 ขึ้น -----
    bull_known = set()
    for k in range(1, len(piv_lo)):
        pp, p = piv_lo[k - 1], piv_lo[k]
        if low[p] < low[pp] and r[p] > r[pp] and r[p] <= OS and p + LBR < n:
            bull_known.add(p + LBR)
    armed = 0
    for i in range(1, n):
        if i in bull_known:
            armed = CONFIRM
        if armed > 0 and close[i] > e20[i] and close[i - 1] <= e20[i - 1]:
            ev["bull_confirm"].append(i); armed = 0
        elif armed > 0:
            armed -= 1

    # ----- bear divergence -> armed -> ยืนยันข้าม EMA20 ลง -----
    bear_known = set()
    for k in range(1, len(piv_hi)):
        pp, p = piv_hi[k - 1], piv_hi[k]
        if high[p] > high[pp] and r[p] < r[pp] and r[p] >= OB and p + LBR < n:
            bear_known.add(p + LBR)
    armedS = 0
    for i in range(1, n):
        if i in bear_known:
            armedS = CONFIRM
        if armedS > 0 and close[i] < e20[i] and close[i - 1] >= e20[i - 1]:
            ev["bear_avoid"].append(i); armedS = 0
        elif armedS > 0:
            armedS -= 1

    # ----- dip-buy / oversold / near800 (event-based) -----
    for i in range(1, n):
        if not np.isfinite(e200[i]) or not np.isfinite(e50[i]):
            continue
        up = close[i] > e200[i]
        pull = e50[i] * 0.95 <= close[i] <= e50[i] * 1.03
        macd_x = ml[i] > ms[i] and ml[i - 1] <= ms[i - 1]
        if up and pull and macd_x:
            ev["dip_buy"].append(i)
        if r[i] < 35 and r[i - 1] >= 35:
            ev["oversold"].append(i)
        if np.isfinite(e800[i]):
            near = abs(close[i] - e800[i]) / e800[i] <= 0.03
            near_prev = np.isfinite(e800[i - 1]) and abs(close[i - 1] - e800[i - 1]) / e800[i - 1] <= 0.03
            if near and not near_prev:
                ev["near800"].append(i)
    return ev, close, high, low


def fwd_stats(close, high, low, i, h):
    """ผลตอบแทนล่วงหน้า h วัน + max gain/drawdown ในช่วงนั้น (ราคาล้วน)"""
    j = i + h
    if j >= len(close):
        return None
    entry = close[i]
    fwd = (close[j] - entry) / entry * 100
    seg_hi = np.max(high[i + 1:j + 1])
    seg_lo = np.min(low[i + 1:j + 1])
    return fwd, (seg_hi - entry) / entry * 100, (seg_lo - entry) / entry * 100


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    tickers = (TICKERS + MAI_TICKERS)
    if args.limit:
        tickers = tickers[:args.limit]
    yq = [t + ".BK" for t in tickers]
    print(f"⬇  ดึงข้อมูล 5 ปี {len(yq)} ตัว (SET+MAI) ...")
    raw = yf.download(yq, period="5y", interval="1d", group_by="ticker",
                      auto_adjust=False, actions=True, progress=False, threads=True)

    # เก็บผลต่อชนิดสัญญาณ: list ของ (fwd20, maxgain, maxdd, fwd10)
    acc = {k: [] for k in SIG_LABELS}
    base = []            # baseline: ผลตอบแทน 20 วันของ "ทุกแท่ง" = สุ่มซื้อถือ 20 วัน
    n_stock = 0
    for t, tq in zip(tickers, yq):
        try:
            df = raw[tq].dropna(how="all")
        except KeyError:
            continue
        if len(df) < 250:
            continue
        n_stock += 1
        ev, close, high, low = detect_events(df)
        for i in range(len(close) - 20):    # baseline ทุกแท่งที่มีอนาคต 20 วัน
            base.append((close[i + 20] - close[i]) / close[i] * 100)
        for sig, idxs in ev.items():
            for i in idxs:
                s20 = fwd_stats(close, high, low, i, 20)
                s10 = fwd_stats(close, high, low, i, 10)
                if s20 is None:
                    continue
                acc[sig].append((s20[0], s20[1], s20[2], s10[0] if s10 else None))

    base = np.array(base)
    base_hit = round(float((base > 0).mean() * 100), 1)
    base_avg = round(float(base.mean()), 2)

    def summarize(rows):
        if not rows:
            return {"n": 0}
        f20 = np.array([x[0] for x in rows])
        mg = np.array([x[1] for x in rows])
        dd = np.array([x[2] for x in rows])
        f10 = np.array([x[3] for x in rows if x[3] is not None])
        hit20 = round(float((f20 > 0).mean() * 100), 1)
        avg20 = round(float(f20.mean()), 2)
        return {
            "n": len(rows),
            "hit20": hit20,
            "avg20": avg20,
            "med20": round(float(np.median(f20)), 2),
            "hit10": round(float((f10 > 0).mean() * 100), 1) if len(f10) else None,
            "avg10": round(float(f10.mean()), 2) if len(f10) else None,
            "maxgain": round(float(mg.mean()), 2),
            "maxdd": round(float(dd.mean()), 2),
            "edge_hit": round(hit20 - base_hit, 1),      # เทียบ baseline สุ่มซื้อ
            "edge_avg": round(avg20 - base_avg, 2),
        }

    out = {
        "as_of": (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%Y-%m-%d"),
        "years": 5, "n_stocks": n_stock, "horizon_days": 20,
        "baseline_hit": base_hit, "baseline_avg": base_avg,
        "labels": SIG_LABELS,
        "signals": {k: summarize(acc[k]) for k in SIG_LABELS},
    }
    EDGE_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nหุ้นที่ใช้ได้ {n_stock} ตัว · วัดผลล่วงหน้า 20 วันทำการ")
    print(f"BASELINE (สุ่มซื้อถือ 20 วัน): แม่น {base_hit}% · เฉลี่ย {base_avg:+.2f}%\n")
    print(f"{'สัญญาณ':<40}{'N':>6}{'แม่น%':>7}{'เฉลี่ย%':>8}{'edge±':>8}{'maxDD%':>8}")
    print("-" * 78)
    for k in SIG_LABELS:
        s = out["signals"][k]
        if s["n"] == 0:
            continue
        print(f"{SIG_LABELS[k]:<40}{s['n']:>6}{s['hit20']:>7}{s['avg20']:>8}{s['edge_avg']:>+8}{s['maxdd']:>8}")
    print(f"\n✅ เขียน {EDGE_FILE.name} แล้ว")


if __name__ == "__main__":
    main()
