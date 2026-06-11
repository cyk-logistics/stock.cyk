#!/usr/bin/env python3
"""
Backtest กลยุทธ์ "เข้าตอนยืนยัน" เทียบ Buy & Hold (ใช้ logic เดียวกับ screener)

เข้า : bull divergence (ราคา Lower Low + RSI Higher Low + oversold) แล้วราคาปิดตัดขึ้นเหนือ EMA20
ออก : +12% (TP) / -8% (SL) / ถือครบ 60 วันทำการ  — รวมปันผลที่ได้ระหว่างถือ

⚠️ ข้อจำกัด (อ่านก่อนเชื่อผล): ใช้ SET50 *ปัจจุบัน* = survivorship bias (รอดมาถึงวันนี้),
ไม่รวมค่าคอม/slippage, เติมคำสั่งที่ราคาปิด, ข้อมูล yfinance อาจคลาดเคลื่อน, กลุ่มตัวอย่างจำกัด
"""
import numpy as np
import yfinance as yf
from collections import Counter
from screener import rsi, ema, TICKERS

LBL = LBR = 5
OS = 40
CONFIRM = 8
TP, SL, MAXHOLD = 0.12, -0.08, 60


def entries_for(df):
    low = df["Low"].values
    r = rsi(df["Close"]).values
    e20 = ema(df["Close"], 20).values
    close = df["Close"].values
    n = len(df)
    piv = [i for i in range(LBL, n - LBR) if low[i] == np.min(low[i - LBL:i + LBR + 1])]
    known = set()
    for k in range(1, len(piv)):
        pp, p = piv[k - 1], piv[k]
        if low[p] < low[pp] and r[p] > r[pp] and r[p] <= OS and p + LBR < n:
            known.add(p + LBR)
    ents, armed = [], 0
    for i in range(1, n):
        if i in known:
            armed = CONFIRM
        if armed > 0 and close[i] > e20[i] and close[i - 1] <= e20[i - 1]:
            ents.append(i); armed = 0
        elif armed > 0:
            armed -= 1
    return ents


def sim(close, div, e):
    entry, accum = close[e], 0.0
    end = min(e + MAXHOLD, len(close) - 1)
    for j in range(e + 1, end + 1):
        accum += div[j]
        ret = (close[j] - entry + accum) / entry
        if ret >= TP:
            return ret, j - e, "TP"
        if ret <= SL:
            return ret, j - e, "SL"
    return (close[end] - entry + accum) / entry, end - e, "TIME"


def main():
    yq = [t + ".BK" for t in TICKERS]
    print(f"ดึงข้อมูล 5 ปี {len(yq)} ตัว ...")
    raw = yf.download(yq, period="5y", interval="1d", group_by="ticker",
                      auto_adjust=False, actions=True, progress=False, threads=True)
    trades, strat_tot, bh_tot, nstock = [], [], [], 0
    for t, tq in zip(TICKERS, yq):
        try:
            df = raw[tq].dropna(how="all")
        except KeyError:
            continue
        if len(df) < 150:
            continue
        nstock += 1
        close = df["Close"].values
        div = df["Dividends"].fillna(0).values if "Dividends" in df else np.zeros(len(df))
        eq, last = 1.0, -1
        for e in entries_for(df):
            if e <= last:
                continue
            ret, days, out = sim(close, div, e)
            trades.append((ret, days, out))
            eq *= (1 + ret); last = e + days
        strat_tot.append(eq - 1)
        bh_tot.append((close[-1] - close[0] + div.sum()) / close[0])

    if not trades:
        print("ไม่มีสัญญาณ"); return
    rets = np.array([x[0] for x in trades])
    days = np.array([x[1] for x in trades])
    wins = int((rets > 0).sum())
    c = Counter(x[2] for x in trades)
    win_r, loss_r = rets[rets > 0], rets[rets <= 0]
    print(f"\n===== ผล BACKTEST (5 ปี · {nstock} หุ้น SET50) =====")
    print(f"เข้า: bull div + ปิดเหนือ EMA20 | ออก: +{TP*100:.0f}%/{SL*100:.0f}%/{MAXHOLD}วัน (รวมปันผล)")
    print(f"จำนวนเทรด     : {len(trades)}")
    print(f"อัตราชนะ      : {wins/len(trades)*100:.0f}%  ({wins} ชนะ / {len(trades)-wins} แพ้)")
    print(f"กำไรเฉลี่ย/เทรด: {rets.mean()*100:+.2f}%  (มัธยฐาน {np.median(rets)*100:+.2f}%)")
    print(f"   ชนะเฉลี่ย   : {win_r.mean()*100:+.2f}%   |   แพ้เฉลี่ย: {loss_r.mean()*100:+.2f}%")
    print(f"ถือเฉลี่ย     : {days.mean():.0f} วันทำการ")
    print(f"ออกเพราะ      : TP {c.get('TP',0)} · SL {c.get('SL',0)} · หมดเวลา {c.get('TIME',0)}")
    print(f"\n----- ผลตอบแทนรวม 5 ปี (เฉลี่ยต่อหุ้น) -----")
    print(f"กลยุทธ์ (ทบต้น): {np.mean(strat_tot)*100:+.1f}%")
    print(f"Buy & Hold    : {np.mean(bh_tot)*100:+.1f}%")
    print("(กลยุทธ์อยู่ในตลาดแค่บางช่วง—ถือเงินสดระหว่างรอ = รับความเสี่ยงน้อยกว่า)")


if __name__ == "__main__":
    main()
