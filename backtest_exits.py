#!/usr/bin/env python3
"""
Backtest "จังหวะออก" ของหุ้นที่เมลแนะนำ ย้อน 10 ปี — หาว่ากฎออกแบบไหนดีกว่าถือเฉยๆ 120 วัน
จุดเข้า = กฎเดียวกับเมลรายวัน: ราคา>EMA200 และ (ปิด <= 90% ของไฮ 60 วันก่อนหน้า หรือ RSI<40)
         นับเฉพาะวันแรกที่สัญญาณเกิด (เมลส่งซ้ำทุกวันระหว่างค้างสัญญาณ) · เข้าที่ราคาปิดวันนั้น
ออก = วันแรกที่กฎทำงาน (ราคาปิด) ไม่งั้นครบ 120 วันทำการ

⚠️ ข้อจำกัด: yfinance (auto_adjust รวมปันผล) · รายชื่อปัจจุบัน (survivorship bias) · ไม่รวมค่าคอม
รัน: python backtest_exits.py  → พิมพ์ตาราง + เขียน backtest_exits.json
"""
import json
import warnings
from pathlib import Path

import numpy as np
import yfinance as yf

from signal_email import UNIVERSE

warnings.filterwarnings("ignore")
HOLD = 120
OUT = Path(__file__).parent / "backtest_exits.json"


def ema(a, p):
    k = 2 / (p + 1); out = np.empty_like(a); out[0] = a[0]
    for i in range(1, len(a)):
        out[i] = a[i] * k + out[i - 1] * (1 - k)
    return out


def rsi(c, p=14):
    d = np.diff(c, prepend=c[0]); up = np.clip(d, 0, None); dn = np.clip(-d, 0, None)
    au = np.zeros_like(c); ad = np.zeros_like(c)
    au[p] = up[1:p + 1].mean(); ad[p] = dn[1:p + 1].mean()
    for i in range(p + 1, len(c)):
        au[i] = (au[i - 1] * (p - 1) + up[i]) / p; ad[i] = (ad[i - 1] * (p - 1) + dn[i]) / p
    rs = np.divide(au, ad, out=np.full_like(au, np.inf), where=ad > 0)
    r = 100 - 100 / (1 + rs); r[:p] = 50
    return r


def load(sym):
    df = yf.Ticker(sym + ".BK").history(period="10y", auto_adjust=True)
    if df is None or len(df) < 400:
        return None
    df = df[["High", "Low", "Close"]].dropna()
    return df["High"].values.astype(float), df["Low"].values.astype(float), df["Close"].values.astype(float)


def rules():
    """ชื่อกฎ → ฟังก์ชัน(ctx, j) คืน True = ออกที่ราคาปิดวัน j"""
    R = {}
    R["ถือ 120 วัน (ฐาน)"] = lambda x, j: False
    for s in (8, 10, 15):
        R["ตัดขาดทุน -%d%%" % s] = (lambda s: lambda x, j: x["c"][j] <= x["entry"] * (1 - s / 100))(s)
    R["หลุด EMA200"] = lambda x, j: x["c"][j] < x["e200"][j]
    R["หลุด EMA200 เกิน 3%"] = lambda x, j: x["c"][j] < x["e200"][j] * 0.97
    R["หลุด EMA200 เกิน 5%"] = lambda x, j: x["c"][j] < x["e200"][j] * 0.95
    R["ถึงไฮเดิม (เป้า)"] = lambda x, j: x["c"][j] >= x["target"]
    R["RSI ตัดลงจาก 70"] = lambda x, j: x["r"][j - 1] >= 70 > x["r"][j]
    for t in (10, 15):
        R["ย่อจากยอด %d%% (trailing)" % t] = (lambda t: lambda x, j: x["c"][j] <= x["peak"][j] * (1 - t / 100)
                                            and x["peak"][j] >= x["entry"] * 1.05)(t)
    combos = {
        "ถึงไฮเดิม หรือ ตัดขาดทุน -15%": ("ถึงไฮเดิม (เป้า)", "ตัดขาดทุน -15%"),
        "ถึงไฮเดิม หรือ ตัดขาดทุน -10%": ("ถึงไฮเดิม (เป้า)", "ตัดขาดทุน -10%"),
        "RSI ตัดลงจาก 70 หรือ ตัดขาดทุน -15%": ("RSI ตัดลงจาก 70", "ตัดขาดทุน -15%"),
        "trailing 15% หรือ ตัดขาดทุน -15%": ("ย่อจากยอด 15% (trailing)", "ตัดขาดทุน -15%"),
        "trailing 10% หรือ ตัดขาดทุน -10%": ("ย่อจากยอด 10% (trailing)", "ตัดขาดทุน -10%"),
        "หลุด EMA200 เกิน 5% หรือ ถึงไฮเดิม": ("หลุด EMA200 เกิน 5%", "ถึงไฮเดิม (เป้า)"),
        "RSI ลงจาก 70 / trailing 15% / ตัดขาดทุน -15%": ("RSI ตัดลงจาก 70", "ย่อจากยอด 15% (trailing)", "ตัดขาดทุน -15%"),
        "ถึงไฮเดิม (เดิม: ระบบ backtest ก่อนหน้า) + หลุด EMA200": ("ถึงไฮเดิม (เป้า)", "หลุด EMA200"),
    }
    for name, parts in combos.items():
        R[name] = (lambda parts: lambda x, j: any(R[p](x, j) for p in parts))(parts)
    return R


def main():
    R = rules()
    res = {k: [] for k in R}
    n_sym = 0
    for s in UNIVERSE:
        d = load(s)
        if d is None:
            continue
        hi, lo, c = d
        n_sym += 1
        e200 = ema(c, 200); r = rsi(c)
        hi60 = np.full_like(c, np.nan)
        for i in range(61, len(c)):
            hi60[i] = hi[i - 60:i].max()          # ไฮ 60 แท่งก่อนหน้า (ไม่รวมวันนี้) = เหมือนเมล
        sig = (c > e200) & ((c <= 0.90 * hi60) | (r < 40))
        sig[:210] = False
        for i in range(211, len(c) - 5):
            if not sig[i] or sig[i - 1]:
                continue                           # วันแรกที่สัญญาณเกิดเท่านั้น
            end = min(i + HOLD, len(c) - 1)
            peak = np.maximum.accumulate(c[i:end + 1]); pk = np.full_like(c, np.nan); pk[i:end + 1] = peak
            x = {"c": c, "e200": e200, "r": r, "entry": c[i], "target": hi60[i], "peak": pk}
            for name, fn in R.items():
                j_exit = end
                for j in range(i + 1, end + 1):
                    if fn(x, j):
                        j_exit = j
                        break
                res[name].append(((c[j_exit] / c[i] - 1) * 100, j_exit - i))
        print("  ✓", s, flush=True)
    rows = []
    for name, lst in res.items():
        if not lst:
            continue
        rets = np.array([a for a, _ in lst]); days = np.array([b for _, b in lst])
        rows.append({"rule": name, "n": len(lst), "avg": round(float(rets.mean()), 2),
                     "median": round(float(np.median(rets)), 2), "win": round(float((rets > 0).mean() * 100), 1),
                     "worst5": round(float(np.percentile(rets, 5)), 1), "days": round(float(days.mean()), 1),
                     "per100d": round(float(rets.mean() / max(days.mean(), 1) * 100), 2)})
    rows.sort(key=lambda r: r["avg"], reverse=True)
    print("\nหุ้น %d ตัว · จุดเข้า %d ครั้ง · ถือสูงสุด %d วัน" % (n_sym, rows[0]["n"], HOLD))
    print("%-48s %6s %7s %6s %7s %6s %8s" % ("กฎออก", "เฉลี่ย%", "มัธยฐาน", "ชนะ%", "แย่5%", "วันถือ", "ต่อ100วัน"))
    for r_ in rows:
        print("%-48s %6.2f %7.2f %6.1f %7.1f %6.1f %8.2f" % (r_["rule"], r_["avg"], r_["median"], r_["win"],
                                                           r_["worst5"], r_["days"], r_["per100d"]))
    OUT.write_text(json.dumps({"n_stocks": n_sym, "hold": HOLD, "rows": rows}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
