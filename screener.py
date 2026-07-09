#!/usr/bin/env python3
"""
SET Dividend + Technical + Fundamental Screener
หาหุ้นปันผลคุณภาพในตลาดไทย จับจังหวะเข้าด้วยสัญญาณเทคนิค และกรองด้วยงบการเงิน

ดึงข้อมูล: yfinance (ราคา/ปันผล/งบ) | อินดิเคเตอร์: คำนวณเอง
สัญญาณ: RSI bullish & bearish divergence, oversold, ย่อในขาขึ้น, แนวรับ, MACD
งบ: payout ratio, ROE, D/E, margin, การเติบโตกำไร -> เกรดสุขภาพ + เตือน dividend trap
ผลลัพธ์: dashboard (กราฟแบบ TradingView) + ตารางในเทอร์มินัล
"""
import argparse
import json
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

TICKERS = [
    "PTT", "PTTEP", "PTTGC", "TOP", "IRPC", "BCP", "OR", "BANPU",
    "EGCO", "RATCH", "GULF", "GPSC", "BGRIM", "EA",
    "ADVANC", "TRUE", "KBANK", "SCB", "BBL", "KTB", "TTB", "KKP", "TISCO",
    "KTC", "SAWAD", "MTC", "AOT", "BEM", "BTS", "BDMS", "BH",
    "CPALL", "CPAXT", "CPF", "CPN", "CRC", "HMPRO", "GLOBAL", "COM7", "BJC",
    "MINT", "CENTEL", "OSP", "CBG", "TU", "SCC", "SCGP", "IVL", "DELTA",
    "KCE", "HANA", "WHA", "AWC", "LH", "AP", "SPALI",
]

# กลุ่ม MAI — รายชื่อคัดมือ (~95 ตัวที่เป็นที่รู้จัก; SET API กัน bot ดึงรายชื่อทางการอัตโนมัติไม่ได้)
# หมายเหตุ: บริษัทย้ายกระดาน MAI↔SET ได้ — ถ้าเจอตัวผิดกระดาน/ตกหล่น แก้ list นี้ตรงๆ
MAI_TICKERS = [
    "AU", "XO", "TACC", "TQR", "KUMWEL", "SICT", "IIG", "PROS", "ETC",
    "ADD", "INSET", "CAZ", "PROEN", "TPS", "ARIP", "ATP30", "COLOR", "CMO",
    "DOD", "ECF", "HARN", "KASET", "KIAT", "MBAX", "MGT", "NDR", "PIMO",
    "QLT", "SAAM", "SALEE", "SE", "SONIC", "VL", "WINNER", "YGG", "ZIGA", "TMILL",
    "SELIC", "STC", "STI", "NCAP", "MOONG", "ABM", "AF", "AKP", "APP", "AUCT",
    "BGT", "BM", "BOL", "CHOW", "COMAN", "CPANEL", "DPAINT", "FLOYD", "FVC",
    "HL", "ICN", "IMH", "K", "KJL", "KWM", "LDC", "LIT", "MASTER", "MITSIB",
    "PHOL", "PLANET", "PPS", "PRAPAT", "SANKO", "TITLE", "TRT", "TRV", "UKEM", "VCOM",
    "WARRIX", "WINMED", "CHIC", "CRD", "POLY", "JDF", "NV", "TAN", "BLESS", "DEXON",
    "PLT", "SCM", "ADB", "SFT", "MENA", "PJW", "SECURE", "CIG",
]


# ---------- อินดิเคเตอร์ ----------
def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def macd(close, fast=12, slow=26, signal=9):
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig, line - sig


def bollinger(close, n=20, k=2):
    ma = close.rolling(n).mean()
    sd = close.rolling(n).std()
    return ma, ma + k * sd, ma - k * sd


# ---------- divergence (ทั้งกระทิงและหมี) ----------
def _pivots(vals, left, right, kind):
    out = []
    n = len(vals)
    for i in range(left, n - right):
        seg = vals[i - left:i + right + 1]
        if (kind == "low" and vals[i] == seg.min()) or (kind == "high" and vals[i] == seg.max()):
            out.append(i)
    return out


def detect_bull_div(low, r, left=5, right=5, lookback=70):
    lows, rsis = low.values, r.values
    idx = [i for i in _pivots(lows, left, right, "low") if i >= len(lows) - lookback]
    if len(idx) < 2:
        return False, None
    i1, i2 = idx[-2], idx[-1]
    if lows[i2] < lows[i1] and rsis[i2] > rsis[i1]:   # ราคา Lower Low, RSI Higher Low
        return True, i2
    return False, None


def detect_bear_div(high, r, left=5, right=5, lookback=70):
    highs, rsis = high.values, r.values
    idx = [i for i in _pivots(highs, left, right, "high") if i >= len(highs) - lookback]
    if len(idx) < 2:
        return False, None
    i1, i2 = idx[-2], idx[-1]
    if highs[i2] > highs[i1] and rsis[i2] < rsis[i1]:  # ราคา Higher High, RSI Lower High
        return True, i2
    return False, None


# ---------- งบการเงิน ----------
FUND_FIELDS = ["payoutRatio", "returnOnEquity", "debtToEquity", "profitMargins",
               "trailingPE", "priceToBook", "earningsGrowth", "revenueGrowth", "exDividendDate"]

TH_MON = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
          "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]


def _fmt_xd(dt):
    return f"{dt.day} {TH_MON[dt.month]}{str(dt.year)[2:]}"


def _one_fund(tq):
    try:
        tk = yf.Ticker(tq)
        info = tk.info
        d = {}
        for f in FUND_FIELDS:
            v = info.get(f)
            if f != "exDividendDate" and v is not None:
                try:   # yfinance บางตัวส่งเป็น string เช่น priceToBook='Infinity' (เจอกับหุ้น MAI) → ทิ้ง
                    v = float(v)
                    if not np.isfinite(v):
                        v = None
                except (TypeError, ValueError):
                    v = None
            d[f] = v
        try:  # กำไรสุทธิรายปี ล่าสุด > ปีก่อน = ฟื้นจริงระดับทั้งปี (ไม่ใช่แค่ไตรมาส)
            ni = tk.income_stmt.loc["Net Income"]
            vals = [float(v) for _, v in ni.items() if v == v]   # newest first, ตัด NaN
            d["ni_recovering"] = len(vals) >= 2 and vals[0] > vals[1]
        except Exception:
            d["ni_recovering"] = None
        return tq, d
    except Exception:
        return tq, {}


def fetch_fundamentals(yq):
    out = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for tq, d in ex.map(_one_fund, yq):
            out[tq] = d
    return out


def grade_financials(f):
    """คืน (label, สี, เหตุผล[], คะแนนงบ) — None ถ้าไม่มีข้อมูล"""
    payout, roe = f.get("payoutRatio"), f.get("returnOnEquity")
    margin, epsg = f.get("profitMargins"), f.get("earningsGrowth")
    pts, have, reasons = 0, 0, []
    if payout is not None:
        have += 1
        if payout < 0:
            pts -= 1; reasons.append("payout ติดลบ")
        elif payout <= 0.7:
            pts += 1
        elif payout > 1.0:
            pts -= 2; reasons.append(f"จ่ายปันผล {payout*100:.0f}% เกินกำไร")
    if roe is not None:
        have += 1
        if roe >= 0.12:
            pts += 1
        elif roe < 0.05:
            pts -= 1
    if margin is not None:
        have += 1
        if margin < 0:
            pts -= 2; reasons.append("ขาดทุน (margin ติดลบ)")
        elif margin >= 0.10:
            pts += 1
    if epsg is not None:
        have += 1
        if epsg <= -0.15:
            pts -= 2; reasons.append(f"กำไรหด {epsg*100:.0f}%")
        elif epsg > 0:
            pts += 1
    if have == 0:
        return ("n/a", "#3a3f4b", [], None)
    if pts >= 2:
        return ("แข็งแรง", "#0b6e4f", reasons, pts)
    if pts >= 0:
        return ("พอใช้", "#5a4a1f", reasons, pts)
    return ("อ่อนแอ", "#7a2e2e", reasons, pts)


def pct(v, mul=100):
    return None if v is None else round(v * mul, 1)


# ---------- วิเคราะห์หุ้น 1 ตัว ----------
def analyze(ticker, df, fund):
    df = df.dropna(how="all")
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    if len(df) < 60:
        return None

    close, low, high = df["Close"].astype(float), df["Low"].astype(float), df["High"].astype(float)
    price = float(close.iloc[-1])
    if not np.isfinite(price) or price <= 0:
        return None

    div = df["Dividends"].fillna(0) if "Dividends" in df else pd.Series(0, index=df.index)
    cutoff = df.index[-1] - pd.Timedelta(days=365)
    div_1y = float(div[div.index >= cutoff].sum())
    dyield = div_1y / price * 100

    # ความสม่ำเสมอปันผล (ประวัติ ~5 ปี): จับการตัดปันผลแรง >50% YoY
    dpos = div[div > 0]
    div_cut = False
    if len(dpos) > 2:
        annual = dpos.groupby(dpos.index.year).sum()
        full = annual[annual.index < annual.index.max()].values   # ตัดปีล่าสุดที่ยังไม่จบ
        div_cut = any(full[k + 1] < full[k] * 0.5 for k in range(len(full) - 1)) if len(full) > 1 else False

    # วัน XD: ล่าสุด (yfinance) + คาดถัดไป (ประมาณจากความถี่การจ่าย)
    if len(dpos):
        py = dpos.groupby(dpos.index.year).size()
        fyc = py[py.index < py.index.max()]
        freq = max(1, min(int(round(float(fyc.median()))) if len(fyc) else 1, 4))
    else:
        freq = 1
    xd_last, xd_next = "—", "—"
    xts = fund.get("exDividendDate")
    if xts:
        try:
            ld = datetime.fromtimestamp(xts, tz=timezone.utc)
            step = timedelta(days=round(365 / freq))
            nd = ld + step
            now = datetime.now(timezone.utc)
            while nd < now:
                nd += step
            xd_last, xd_next = _fmt_xd(ld), _fmt_xd(nd)
        except Exception:
            pass

    r = rsi(close)
    rsi_now = float(r.iloc[-1])
    ema20, ema50, ema200 = ema(close, 20), ema(close, 50), ema(close, 200)
    ema800 = ema(close, 800)
    _, _, bb_low = bollinger(close)
    macd_line, macd_sig, _ = macd(close)
    e20, e50, e200 = float(ema20.iloc[-1]), float(ema50.iloc[-1]), float(ema200.iloc[-1])
    above20 = price > e20   # ยืนยัน: ราคาปิดเหนือ EMA20 = โมเมนตัมกลับขึ้น (กรองมีดร่วง)
    e800 = float(ema800.iloc[-1]) if len(close) >= 800 and np.isfinite(ema800.iloc[-1]) else None
    near800 = e800 is not None and abs(price - e800) / e800 <= 0.03   # ใกล้แนวรับใหญ่ EMA800 (±3%)
    bbl = float(bb_low.iloc[-1]) if np.isfinite(bb_low.iloc[-1]) else price
    uptrend = price > e200
    low52 = float(low.tail(252).min())
    high52 = float(high.tail(252).max())
    bull_div, bull_idx = detect_bull_div(low, r)
    bear_div, bear_idx = detect_bear_div(high, r)
    macd_x = bool(macd_line.iloc[-1] > macd_sig.iloc[-1] and macd_line.iloc[-2] <= macd_sig.iloc[-2])

    # สถานะเข้า (ไฟสัญญาณ) — actionable ลดหลั่น
    if bull_div and above20:
        status, scolor, srank = "🟢 เข้าได้", "#0b6e4f", 5
    elif bull_div:
        status, scolor, srank = "🟡 รอยืนยัน", "#6e5a1f", 4
    elif bear_div:
        status, scolor, srank = "🔴 เลี่ยง", "#7a2222", 1
    elif near800:
        status, scolor, srank = "🟣 ที่แนวรับ", "#5a2d6e", 3
    elif rsi_now < 35:
        status, scolor, srank = "🔵 oversold", "#1f4e7a", 2
    else:
        status, scolor, srank = "⚪ เฝ้าดู", "#3a3f4b", 0

    fg_label, fg_color, fg_reasons, fg_pts = grade_financials(fund)
    payout = fund.get("payoutRatio")
    epsg = fund.get("earningsGrowth")
    margin = fund.get("profitMargins")
    trap = dyield >= 4 and ((payout or 0) > 1.0 or (epsg is not None and epsg <= -0.2)
                            or (margin is not None and margin < 0))
    # Turnaround: ราคาโดนทุบ ≥20% + กำไรเด้ง ≥30% + กำไรรายปีล่าสุดสูงกว่าปีก่อน (ฟื้นจริง)
    turnaround = (price <= high52 * 0.80 and epsg is not None and epsg >= 0.30
                  and fund.get("ni_recovering") is True)

    # ---------- คะแนนจังหวะเข้า ----------
    score, reasons = 0.0, []
    if 3 <= dyield <= 12:
        score += min(20, dyield * 2); reasons.append(f"ปันผล {dyield:.1f}%")
    elif dyield > 12:
        reasons.append(f"⚠ ปันผล {dyield:.1f}% สูงผิดปกติ")
    elif dyield > 0:
        reasons.append(f"ปันผล {dyield:.1f}%")
    if rsi_now < 35:
        score += 20; reasons.append(f"RSI oversold ({rsi_now:.0f})")
    if bull_div and above20:
        score += 30; reasons.append("🟢 Bull Div ✅ ยืนยัน (เหนือ EMA20)")
    elif bull_div:
        score += 10; reasons.append("🟡 Bull Div (รอยืนยัน—ยังไม่เหนือ EMA20)")
    if price < bbl:
        score += 15; reasons.append("หลุดกรอบล่าง BB")
    if uptrend and price <= e50 * 1.02:
        score += 20; reasons.append("ย่อในขาขึ้น (EMA50)")
    if price <= low52 * 1.10:
        score += 15; reasons.append("ใกล้ Low 52 สัปดาห์")
    if macd_x:
        score += 10; reasons.append("MACD ตัดขึ้น")
    # คุณภาพ + มูลค่า (ดันตัว "น่าสนใจโดยรวม" ขึ้นบน ไม่ใช่แค่ตัวที่ย่อแรง)
    if fg_pts is not None and fg_pts >= 2:
        score += 10   # งบแข็งแรง (โชว์ในคอลัมน์สุขภาพงบอยู่แล้ว)
    _pb, _pe = fund.get("priceToBook"), fund.get("trailingPE")
    if _pb is not None and 0 < _pb < 1:
        score += 8; reasons.append(f"ถูก P/B {_pb:.2f}")
    if _pe is not None and 0 < _pe < 10:
        score += 5; reasons.append(f"PE ต่ำ {_pe:.1f}")
    if near800:
        score += 8; reasons.append("🟣 ใกล้แนวรับใหญ่ (EMA800)")
    # ปันผลน่าสนใจ: ยีลด์≥5% + งบแข็งแรง + payout มีบัฟเฟอร์ (≤85%) + ไม่ติดธง
    div_good = (dyield >= 5 and fg_pts is not None and fg_pts >= 2
                and payout is not None and 0 < payout <= 0.85
                and not trap and not div_cut and not bear_div)
    if div_good:
        score += 8; reasons.append("💎 ปันผลน่าสนใจ (สูง+ยั่งยืน)")
    if turnaround:
        reasons.append("🔄 Turnaround (กำไรฟื้น ราคายังถูก)")
    if uptrend:
        score += 10   # ขาขึ้น (เหนือ EMA200) = เหมาะถือยาว — โชว์ในคอลัมน์เทรนด์
    else:
        score -= 10; reasons.append("⚠ ขาลง (ใต้ EMA200)")
    # ตัวหักลบ / เตือน
    if bear_div:
        score -= 20; reasons.append("🔴 Bearish Divergence (ระวังกลับหัว)")
    if trap:
        score -= 15; reasons.append("⚠ เสี่ยง dividend trap")
    if div_cut and dyield > 0:
        score -= 10; reasons.append("⚠ เคยตัดปันผล (ไม่สม่ำเสมอ)")
    if fg_pts is not None and fg_pts < 0:
        score -= 10
        for x in fg_reasons:
            reasons.append("⚠ " + x)
    score = round(max(0, min(score, 100)), 0)

    # ---------- คะแนนเทคนิคล้วน (หน้า "เทคนิคสวย" — ไม่สนปันผล/งบ) ----------
    rsi_rising = len(r) > 3 and rsi_now > float(r.iloc[-3])
    ema_stack = e20 > e50 > e200                                # EMA เรียงตัวขาขึ้นสวย
    pullback = uptrend and e50 * 0.95 <= price <= e50 * 1.03    # ย่อลงมาโซน EMA50 ในขาขึ้น
    vol_spike = False
    if "Volume" in df and len(df) > 21:
        _v = df["Volume"].astype(float)
        _v20 = float(_v.tail(21).iloc[:-1].mean())
        vol_spike = bool(np.isfinite(_v.iloc[-1]) and _v20 > 0 and float(_v.iloc[-1]) >= 1.5 * _v20
                         and price > float(close.iloc[-2]))
    tscore, treasons = 0.0, []
    if bull_div and above20:
        tscore += 30; treasons.append("🟢 Bull Div ยืนยัน (เหนือ EMA20)")
    elif bull_div:
        tscore += 12; treasons.append("🟡 Bull Div รอยืนยัน")
    if uptrend:
        tscore += 15; treasons.append("ขาขึ้น (เหนือ EMA200)")
    else:
        tscore -= 15; treasons.append("⚠ ขาลง (ใต้ EMA200)")
    if ema_stack:
        tscore += 10; treasons.append("EMA เรียงสวย 20>50>200")
    if pullback:
        tscore += 18; treasons.append("ย่อลงโซน EMA50 (จุดเข้าขาขึ้น)")
    if macd_x:
        tscore += 15; treasons.append("MACD ตัดขึ้น")
    if rsi_now < 35:
        tscore += 10; treasons.append(f"RSI oversold ({rsi_now:.0f})")
    elif rsi_now < 55 and rsi_rising:
        tscore += 8; treasons.append("RSI กำลังฟื้นตัว")
    if rsi_now > 70:
        tscore -= 10; treasons.append(f"⚠ RSI ร้อนเกิน ({rsi_now:.0f})")
    if near800:
        tscore += 12; treasons.append("🟣 ที่แนวรับใหญ่ EMA800")
    if price < bbl:
        tscore += 6; treasons.append("หลุดกรอบล่าง BB")
    if vol_spike:
        tscore += 8; treasons.append("วอลุ่มเข้าหนุน (≥1.5 เท่า)")
    if bear_div:
        tscore -= 25; treasons.append("🔴 Bearish Divergence")
    tscore = round(max(0, min(tscore, 100)), 0)

    if not bear_div and ((bull_div and above20) or (pullback and macd_x)):
        tstatus, tcolor, trank = "🟢 น่าเข้า", "#0b6e4f", 5
    elif not bear_div and (bull_div or pullback):
        tstatus, tcolor, trank = "🟡 ใกล้จุดเข้า", "#6e5a1f", 4
    elif bear_div:
        tstatus, tcolor, trank = "🔴 เลี่ยง", "#7a2222", 1
    elif near800:
        tstatus, tcolor, trank = "🟣 ที่แนวรับ", "#5a2d6e", 3
    elif rsi_now < 35:
        tstatus, tcolor, trank = "🔵 oversold", "#1f4e7a", 2
    else:
        tstatus, tcolor, trank = "⚪ เฝ้าดู", "#3a3f4b", 0

    # ===== คอมเมนต์งบ (สร้างอัตโนมัติเป็นภาษาคน) =====
    cm = [f"งบ{fg_label}"] if fg_label != "n/a" else ["ข้อมูลงบจำกัด"]
    _roe = fund.get("returnOnEquity")
    if _roe is not None:
        cm.append(f"ROE {_roe*100:.0f}%")
    if epsg is not None:
        cm.append(f"กำไร{'โต' if epsg >= 0 else 'หด'} {abs(epsg)*100:.0f}%")
    if payout is not None:
        if payout > 1.0:
            cm.append(f"จ่ายปันผล {payout*100:.0f}% ของกำไร (เกินกำไร—เสี่ยง)")
        elif payout >= 0.85:
            cm.append(f"payout {payout*100:.0f}% (จ่ายเกือบหมด ไม่มีบัฟเฟอร์)")
        else:
            cm.append(f"payout {payout*100:.0f}% (มีบัฟเฟอร์)")
    _pe, _pb = fund.get("trailingPE"), fund.get("priceToBook")
    if _pe is not None and _pb is not None:
        _v = "ถูก" if (_pb < 1 or 0 < _pe < 10) else ("แพง" if (_pe > 20 or _pb > 3) else "สมเหตุผล")
        cm.append(f"PE {_pe:.0f} / PB {_pb:.1f} ({_v})")
    if div_cut:
        cm.append("เคยตัดปันผล (ไม่สม่ำเสมอ)")
    cm.append("เทรนด์ขาขึ้น" if uptrend else "อยู่ขาลง")
    if trap:
        _concl = "→ ⚠ เสี่ยง dividend trap: ยีลด์สูงแต่งบ/ปันผลไม่มั่นคง อย่าหลงตัวเลข"
    elif turnaround:
        _concl = "→ 🔄 Turnaround: กำไรฟื้นแต่ราคายังถูก/ขาลง — เสี่ยงสูง รอราคายืนยันก่อน"
    elif div_good and uptrend:
        _concl = "→ 💎 หุ้นปันผลคุณภาพ: ยีลด์ดี งบแข็ง อยู่ขาขึ้น น่าถือยาว"
    elif div_good:
        _concl = "→ ปันผลน่าสนใจ งบแข็ง แต่ยังขาลง รอจังหวะกลับตัว"
    elif fg_pts is not None and fg_pts < 0:
        _concl = "→ งบอ่อนแอ ควรระวัง"
    else:
        _concl = ""
    comment = " · ".join(cm) + (("  " + _concl) if _concl else "")

    # ===== ราคาเหมาะสม (ประเมิน): มัธยฐาน 3 วิธี + ธงความเชื่อมั่น =====
    fairs = []
    if _pe is not None and _pe > 0:
        fairs.append(price / _pe * 12)      # PE 12 เท่า
    if div_1y > 0:
        fairs.append(div_1y / 0.045)        # ยีลด์เป้า 4.5%
    if _pb is not None and _pb > 0:
        fairs.append(price / _pb)           # มูลค่าทางบัญชี (PBV 1.0)
    fairs = sorted(f for f in fairs if f and f > 0)
    if len(fairs) >= 2:
        mid = fairs[len(fairs) // 2] if len(fairs) % 2 else (fairs[len(fairs) // 2 - 1] + fairs[len(fairs) // 2]) / 2
        spread = (fairs[-1] - fairs[0]) / mid if mid else 9
        upside = (mid / price - 1) * 100
        risky = (not uptrend) or (epsg is not None and epsg < 0) or trap or div_cut
        if spread <= 0.35 and not risky:
            conf = "🟢 เชื่อได้"
        elif spread <= 0.35:
            conf = "🟡 ดูถูกแต่ระวัง (ขาลง/กำไรหด อาจเป็นกับดัก)"
        else:
            conf = "⚠️ ประเมินยาก (3 วิธีต่างกันมาก)"
        fair_txt = f"~{mid:,.0f} บาท · upside {upside:+.0f}% · {conf}"
    else:
        fair_txt = "ข้อมูลไม่พอประเมิน"

    # ---------- ข้อมูลกราฟ ----------
    tail = df.tail(300)
    e20t, e50t, e200t, e800t = ema20.tail(300), ema50.tail(300), ema200.tail(300), ema800.tail(300)
    candles, l20, l50, l200, l800 = [], [], [], [], []
    for ts, row in tail.iterrows():
        o, h, lo, c = row["Open"], row["High"], row["Low"], row["Close"]
        if all(np.isfinite([o, h, lo, c])):
            candles.append({"time": ts.strftime("%Y-%m-%d"), "open": round(float(o), 2),
                            "high": round(float(h), 2), "low": round(float(lo), 2), "close": round(float(c), 2)})
    for ts, v in e20t.items():
        if np.isfinite(v):
            l20.append({"time": ts.strftime("%Y-%m-%d"), "value": round(float(v), 2)})
    for ts, v in e50t.items():
        if np.isfinite(v):
            l50.append({"time": ts.strftime("%Y-%m-%d"), "value": round(float(v), 2)})
    for ts, v in e200t.items():
        if np.isfinite(v):
            l200.append({"time": ts.strftime("%Y-%m-%d"), "value": round(float(v), 2)})
    for ts, v in e800t.items():
        if np.isfinite(v):
            l800.append({"time": ts.strftime("%Y-%m-%d"), "value": round(float(v), 2)})
    markers = []
    if bull_div and bull_idx is not None:
        markers.append({"time": df.index[bull_idx].strftime("%Y-%m-%d"), "position": "belowBar",
                        "color": "#26a69a", "shape": "arrowUp", "text": "BULL"})
    if bear_div and bear_idx is not None:
        markers.append({"time": df.index[bear_idx].strftime("%Y-%m-%d"), "position": "aboveBar",
                        "color": "#ef5350", "shape": "arrowDown", "text": "BEAR"})

    return {
        "ticker": ticker, "id": ticker.replace(".", "_"),
        "price": round(price, 2), "yield": round(dyield, 2),
        "rsi": round(rsi_now, 1), "trend": "ขาขึ้น" if uptrend else "ขาลง/ออกข้าง",
        "payout": pct(payout), "roe": pct(fund.get("returnOnEquity")),
        "de": None if fund.get("debtToEquity") is None else round(fund["debtToEquity"] / 100, 2),
        "epsg": pct(epsg), "pe": None if fund.get("trailingPE") is None else round(fund["trailingPE"], 1),
        "health": fg_label, "health_color": fg_color,
        "bull_div": bull_div, "bear_div": bear_div, "trap": trap, "div_cut": div_cut,
        "xd_last": xd_last, "xd_next": xd_next,
        "status": status, "status_color": scolor, "srank": srank, "div_good": div_good, "turnaround": turnaround,
        "comment": comment, "fair_txt": fair_txt,
        "score": score, "reasons": reasons,
        "tscore": tscore, "tstatus": tstatus, "tstatus_color": tcolor, "trank": trank, "treasons": treasons,
        "chart": {"candles": candles, "ema20": l20, "ema50": l50, "ema200": l200, "ema800": l800, "markers": markers},
    }


def run(tickers):
    yq = [t + ".BK" for t in tickers]
    print(f"⬇  ราคา/ปันผล {len(yq)} ตัว ...")
    raw = yf.download(yq, period="5y", interval="1d", group_by="ticker",
                      auto_adjust=False, actions=True, progress=False, threads=True)
    print(f"⬇  งบการเงิน {len(yq)} ตัว ...")
    funds = fetch_fundamentals(yq)

    results = []
    for t, tq in zip(tickers, yq):
        try:
            df = raw[tq]
        except KeyError:
            continue
        try:
            res = analyze(t, df, funds.get(tq, {}))
        except Exception as e:
            print(f"   ! {t}: {e}")
            continue
        if res:
            results.append(res)
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def fetch_set_index():
    try:
        h = yf.Ticker("^SET.BK").history(period="1y", auto_adjust=False)
        if len(h) < 20:
            return None
        c = h["Close"]
        last = float(c.iloc[-1])
        return {"level": last,
                "chg_1m": (last / float(c.iloc[-22]) - 1) * 100 if len(c) > 22 else None,
                "chg_1y": (last / float(c.iloc[0]) - 1) * 100,
                "from_high": (last / float(h["High"].max()) - 1) * 100}
    except Exception:
        return None


def market_banner(results, market, label="🇹🇭 ภาพรวมตลาด SET"):
    n = len(results) or 1
    up_pct = round(sum(1 for r in results if r["trend"] == "ขาขึ้น") / n * 100)
    avg_rsi = round(sum(r["rsi"] for r in results) / n)
    os_ = sum(1 for r in results if r["rsi"] < 35)
    ob = sum(1 for r in results if r["rsi"] > 70)
    bear = sum(1 for r in results if r["bear_div"])
    chg1m = market["chg_1m"] if market else None
    if chg1m is None:
        # ไม่มีดัชนี (เช่น กลุ่ม MAI — yfinance ไม่มี ^MAI) → วัดอารมณ์จาก breadth ของหุ้นที่สแกนแทน
        if up_pct >= 55:
            mood, mcol = "🐂 ขาขึ้น (จาก breadth)", "#0b6e4f"
        elif up_pct < 40:
            mood, mcol = "🐻 ขาลง (จาก breadth)", "#7a2222"
        else:
            mood, mcol = "↔ ออกข้าง/ผสม (จาก breadth)", "#5a4a1f"
    elif chg1m > 2 and up_pct >= 55:
        mood, mcol = "🐂 ขาขึ้น", "#0b6e4f"
    elif chg1m < -2 or up_pct < 40:
        mood, mcol = "🐻 ขาลง", "#7a2222"
    else:
        mood, mcol = "↔ ออกข้าง/ผสม", "#5a4a1f"
    caution = ""
    if market and market.get("from_high") is not None and market["from_high"] > -5 and bear >= 3:
        caution = " · ⚠️ ใกล้ high + เริ่มมี bear div"
    sgn = lambda v: "—" if v is None else f"{v:+.1f}%"
    if market:
        col1m = "#5fe0c8" if (market["chg_1m"] or 0) >= 0 else "#ff8a8a"
        idx = (f'<b style="font-size:22px">{market["level"]:,.0f}</b><span class="lbl"> จุด</span> · '
               f'<span style="color:{col1m}">1ด {sgn(market["chg_1m"])}</span> · 1ปี {sgn(market["chg_1y"])} · ห่าง high {sgn(market["from_high"])}')
    else:
        idx = '<span class="lbl">(ไม่มีข้อมูลดัชนีกลุ่มนี้ — ดูจาก breadth ด้านล่างแทน)</span>'
    return (f'<div class="market"><div class="mk-top"><b>{label}</b>'
            f'<span class="pill" style="background:{mcol}">{mood}</span></div>'
            f'<div class="mk-idx">{idx}</div>'
            f'<div class="mk-br">Breadth: ขาขึ้น <b>{up_pct}%</b> · RSI เฉลี่ย <b>{avg_rsi}</b> · oversold {os_} · overbought {ob} · bear div {bear}{caution}</div></div>')


SIGNALS_FILE = Path(__file__).parent / "signals.json"
SIGNALS_MAI_FILE = Path(__file__).parent / "signals_mai.json"
TRACK_DAYS = 60   # ติดตามผลสัญญาณ 60 วันปฏิทิน แล้วปิดบันทึกผล


def track_signals(results, path=SIGNALS_FILE):
    """บันทึก/อัปเดต track record ของสัญญาณ 🟢 เข้าได้ — วัดผลว่าระบบแม่นจริงไหม"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {"open": [], "closed": []}
    today = (datetime.now(timezone.utc) + timedelta(hours=7)).date()
    prices = {r["ticker"]: r["price"] for r in results}
    go_now = {r["ticker"] for r in results if "เข้าได้" in r["status"]}
    open_tickers = {s["ticker"] for s in data["open"]}

    still_open = []
    for s in data["open"]:
        p = prices.get(s["ticker"])
        if p:
            s["last"] = p
            s["ret"] = round((p / s["entry"] - 1) * 100, 2)
            s["peak"] = max(s.get("peak", 0.0), s["ret"])
        s["days"] = (today - datetime.strptime(s["date"], "%Y-%m-%d").date()).days
        if s["days"] >= TRACK_DAYS:
            s["exit_date"] = today.isoformat()
            s["win"] = s["ret"] > 0
            data["closed"].append(s)
        else:
            still_open.append(s)
    data["open"] = still_open

    for r in results:
        if r["ticker"] in go_now and r["ticker"] not in open_tickers:
            data["open"].append({"ticker": r["ticker"], "date": today.isoformat(),
                                 "entry": r["price"], "last": r["price"],
                                 "ret": 0.0, "peak": 0.0, "days": 0})

    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def tabs_html(active):
    tabs = [("div", "index.html", "💰 SET ปันผล (ถือยาว)"),
            ("tech", "technical.html", "📈 SET เทคนิค (จังหวะเทรด)"),
            ("mai", "mai.html", "🚀 MAI (หุ้นเล็กโตเร็ว)")]
    return ('<div class="tabs">'
            + "".join(f'<a class="tab{" active" if k == active else ""}" href="{h}">{t}</a>' for k, h, t in tabs)
            + "</div>")


MAI_NOTICE = ('<div style="background:#2a2014;border:1px solid #6e4a1f;border-radius:10px;'
              'padding:11px 14px;margin-bottom:16px;font-size:13px;line-height:1.7">'
              '⚠️ <b style="color:#ffcf66">MAI = หุ้นเล็ก ความเสี่ยงสูงกว่า SET มาก</b> — '
              'สภาพคล่องต่ำ สเปรดกว้าง ราคาโดนลาก/ทุบแรงได้ง่าย · งบบางตัวข้อมูลไม่ครบ (n/a) · '
              'รายชื่อคัดมือ ~95 ตัวที่เป็นที่รู้จัก อาจไม่ครบทั้งกระดาน · '
              'อย่าใส่เงินก้อนใหญ่ในหุ้น MAI ตัวเดียว</div>')


def build_dashboard(results, market, signals, out_path,
                    title="📈 SET Dividend + Technical + Fundamental Screener",
                    tabs="", notice="", mlabel="🇹🇭 ภาพรวมตลาด SET"):
    keys = ("ticker", "price", "yield", "payout", "roe", "de", "epsg", "pe",
            "health", "health_color", "rsi", "trend", "score", "reasons", "id", "bear_div", "trap", "div_cut",
            "xd_last", "xd_next", "status", "status_color", "srank", "div_good", "turnaround", "comment", "fair_txt")
    table = [{k: r[k] for k in keys} for r in results]
    charts = [{"id": r["id"], "ticker": r["ticker"], **r["chart"]} for r in results if r["chart"]["candles"]][:8]
    n_go = sum(1 for r in results if "เข้าได้" in r["status"])
    n_wait = sum(1 for r in results if "รอยืนยัน" in r["status"])
    n_div = sum(1 for r in results if r["div_good"])
    n_warn = sum(1 for r in results if r["bear_div"] or r["trap"] or r["div_cut"])

    html = HTML_TEMPLATE
    html = html.replace("/*__CSS__*/", CSS)
    html = html.replace("/*__ROWS__*/", json.dumps(table, ensure_ascii=False))
    html = html.replace("/*__CHARTS__*/", json.dumps(charts, ensure_ascii=False))
    now_ict = datetime.now(timezone.utc) + timedelta(hours=7)
    updated = f"{now_ict.day} {TH_MON[now_ict.month]} {now_ict.year} {now_ict.hour:02d}:{now_ict.minute:02d} น."
    html = html.replace("__UPDATED__", updated)
    html = html.replace("/*__SIGNALS__*/", json.dumps(signals, ensure_ascii=False))
    html = html.replace("__TITLE__", title)
    html = html.replace("__TABS__", tabs)
    html = html.replace("__NOTICE__", notice)
    html = html.replace("__MARKET__", market_banner(results, market, mlabel))
    html = html.replace("__SCANNED__", str(len(results)))
    html = html.replace("__NGO__", str(n_go))
    html = html.replace("__NWAIT__", str(n_wait))
    html = html.replace("__NDIV__", str(n_div))
    html = html.replace("__NWARN__", str(n_warn))
    Path(out_path).write_text(html, encoding="utf-8")


CSS = r"""
  :root{--bg:#0e1117;--card:#161b22;--bd:#222a35;--tx:#d1d4dc;--mut:#7d8590;--grn:#26a69a;--red:#ef5350;--amb:#f0a000;}
  *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--tx);font-family:-apple-system,"Segoe UI",Roboto,sans-serif}
  .wrap{max-width:1280px;margin:0 auto;padding:24px}
  h1{font-size:20px;margin:0 0 4px} .sub{color:var(--mut);font-size:13px;margin-bottom:18px}
  .tabs{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}
  .tab{padding:9px 16px;border-radius:10px;border:1px solid var(--bd);background:var(--card);color:var(--mut);text-decoration:none;font-size:14px;font-weight:600}
  .tab:hover{color:var(--tx)}
  .tab.active{color:#eaeef4;border-color:#3a4a63;background:#1c2436}
  .stats{display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap}
  .stat{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:12px 16px;min-width:110px}
  .stat b{display:block;font-size:22px} .stat span{color:var(--mut);font-size:12px}
  .top5{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:6px}
  @media(max-width:820px){.top5{grid-template-columns:repeat(2,1fr)}}
  .pick{background:linear-gradient(160deg,#1c2436,#161b22);border:1px solid #6a5a25;border-radius:10px;padding:12px}
  .pick .rk{color:#ffe08a;font-size:11px;font-weight:700}
  .pick .tk{font-size:18px;font-weight:700;margin:3px 0}
  .pick .big{font-size:18px;font-weight:700;color:#5fe0c8;margin:6px 0 0}
  .pick .lbl{color:var(--mut);font-size:10.5px;font-weight:400}
  .pick .meta2{color:var(--mut);font-size:11px;margin-top:6px}
  .market{background:linear-gradient(135deg,#16202e,#161b22);border:1px solid #2a3a4a;border-radius:12px;padding:14px 18px;margin-bottom:18px}
  .mk-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px} .mk-top b{font-size:15px}
  .mk-idx{font-size:13px;margin-bottom:6px} .mk-br{font-size:12px;color:var(--mut)}
  .modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.65);z-index:100;align-items:center;justify-content:center;padding:16px} .modal.show{display:flex}
  .modal-box{background:var(--card);border:1px solid var(--bd);border-radius:12px;max-width:520px;width:100%;padding:22px;position:relative;max-height:85vh;overflow:auto}
  .modal-close{position:absolute;top:10px;right:14px;cursor:pointer;color:var(--mut);font-size:18px}
  table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--bd);border-radius:10px;font-size:12.5px}
  th,td{padding:9px 10px;text-align:left;border-bottom:1px solid var(--bd)}
  th{color:var(--mut);font-weight:600;cursor:pointer;user-select:none;white-space:nowrap;position:sticky;top:0;z-index:3;background:#1a2130;box-shadow:inset 0 -1px 0 var(--bd)} th:hover{color:var(--tx)}
  tr:last-child td{border-bottom:none}
  td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
  .score{font-weight:700;padding:2px 8px;border-radius:6px;display:inline-block;min-width:30px;text-align:center}
  .pill{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;color:#fff;white-space:nowrap}
  .badge{display:inline-block;background:#1f2630;border:1px solid var(--bd);color:var(--tx);border-radius:20px;padding:2px 8px;font-size:11px;margin:2px 3px 0 0;white-space:nowrap}
  .badge.warn{border-color:#5a3a00;color:#ffcf66} .badge.bull{border-color:#1c5a4f;color:#5fe0c8} .badge.bear{border-color:#5a2222;color:#ff8a8a} .badge.gem{border-color:#7a6a1f;color:#ffe08a} .badge.turn{border-color:#5a3d6e;color:#c89aff}
  .up{color:var(--grn)} .down{color:var(--red)}
  h2{font-size:16px;margin:30px 0 12px}
  .grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px} @media(max-width:860px){.grid{grid-template-columns:1fr}}
  .chart-card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:12px}
  .chart-head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px;gap:8px;flex-wrap:wrap}
  .chart-head b{font-size:15px} .chart-head .meta{color:var(--mut);font-size:11.5px}
  .chart{height:300px} .foot{color:var(--mut);font-size:11px;margin-top:24px;line-height:1.7}
"""

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>/*__CSS__*/</style>
</head>
<body>
<div class="wrap">
  __TABS__
  <h1>__TITLE__</h1>
  <div class="sub">หุ้นปันผลคุณภาพ + จังหวะเข้า + กรองงบการเงิน • ข้อมูล: yfinance • อินดิเคเตอร์คำนวณเอง</div>
  <div style="color:var(--mut);font-size:11.5px;margin:-12px 0 16px">🕐 อัปเดตล่าสุด: <b style="color:#9aa4b0">__UPDATED__</b> (เวลาไทย) · อัปเดตอัตโนมัติทุกวันทำการหลังตลาดปิด</div>
  __MARKET__
  __NOTICE__
  <div class="stats">
    <div class="stat"><b>__SCANNED__</b><span>หุ้นที่สแกน</span></div>
    <div class="stat"><b class="up">__NGO__</b><span>🟢 เข้าได้ตอนนี้</span></div>
    <div class="stat"><b style="color:#e0b020">__NWAIT__</b><span>🟡 รอยืนยัน</span></div>
    <div class="stat"><b style="color:#ffe08a">__NDIV__</b><span>💎 ปันผลน่าสนใจ</span></div>
    <div class="stat"><b class="down">__NWARN__</b><span>ติดธงเตือน</span></div>
  </div>

  <div id="entrycall"></div>
  <div id="turncall"></div>
  <div id="modal" class="modal" onclick="if(event.target===this)closeModal()"><div class="modal-box"><span class="modal-close" onclick="closeModal()">✕</span><div id="modal-body"></div></div></div>
  <h2 style="margin-top:26px">🏆 Top 5 น่าจัด — ปันผลคุณภาพ + คะแนนสูงสุด</h2>
  <div class="sub" style="margin:-6px 0 12px">ลงทุน 1 ล้านบาท → ปันผล <b>ต่อปี</b> (สุทธิหลังหักภาษี 10%) • จ่ายจริงปีละ 1–2 ครั้งตามวัน XD ไม่ใช่รายเดือน • คัดจากหุ้น 💎 งบแข็งแรง</div>
  <div id="top5" class="top5"></div>

  <h2>📊 ผลสัญญาณที่เคยแนะนำ — วัดผลจริง</h2>
  <div id="track"></div>

  <h2>📋 ตารางทั้งหมด</h2>
  <table id="tbl"><thead><tr>
    <th data-k="ticker">หุ้น</th>
    <th data-k="srank">สถานะ</th>
    <th class="num" data-k="price">ราคา</th>
    <th class="num" data-k="yield">ปันผล%</th>
    <th class="num" data-k="yield">ปันผล/ปี (ลงล้าน)</th>
    <th data-k="xd_last">XD ล่าสุด</th>
    <th class="num" data-k="payout">Payout%</th>
    <th class="num" data-k="roe">ROE%</th>
    <th class="num" data-k="epsg">กำไรโต%</th>
    <th data-k="health">สุขภาพงบ</th>
    <th class="num" data-k="rsi">RSI</th>
    <th class="num" data-k="score">คะแนน</th>
    <th data-k="reasons">สัญญาณ</th>
  </tr></thead><tbody></tbody></table>

  <h2>กราฟหุ้นน่าสนใจ (เรียงตามคะแนน)</h2>
  <div class="grid" id="charts"></div>

  <div class="foot">
    ⚠ <b>คำเตือน:</b> เป็น "สัญญาณ" ไม่ใช่คำแนะนำซื้อขาย • ควร backtest + ศึกษางบจริงก่อนลงเงิน • ข้อมูล yfinance ไม่ใช่ realtime<br>
    🟢 <b>Bull Div ✅ ยืนยัน</b> = เจอ divergence + ราคาปิดเหนือ EMA20 (กรอง "มีดร่วง" → เข้าได้) • 🟡 <b>รอยืนยัน</b> = เจอ div แต่ราคายังไม่เหนือ EMA20 • 🔴 <b>Bearish Divergence</b> = ระวังกลับหัว<br>
    💰 <b>สุขภาพงบ</b> ดูจาก payout ratio, ROE, margin, การเติบโตกำไร • <b>dividend trap</b> = ปันผลสูงแต่งบทรุด • <b>เคยตัดปันผล</b> = ในอดีต 5 ปีเคยลดปันผลแรง >50% (ไม่สม่ำเสมอ)<br>
    📅 <b>XD ล่าสุด</b> = วันขึ้นเครื่องหมาย XD ครั้งหลังสุด (yfinance) • <b>คาดถัดไป</b> = ประมาณจากรอบเดิม ไม่ใช่วันประกาศจริง → เช็กวัน XD จริงที่ set.or.th<br>
    🟣 <b>EMA800 (เส้นม่วง)</b> = ค่าเฉลี่ยยาว = แนวรับใหญ่ระยะยาว • <b>ใกล้แนวรับใหญ่</b> = ราคาเข้าใกล้ EMA800 (±3%) = โซนเสี่ยง-ผลตอบแทนน่าสนใจ
  </div>
</div>

<script>
const ROWS = /*__ROWS__*/;
const CHARTS = /*__CHARTS__*/;
const f1 = (v)=> v===null||v===undefined ? '—' : (+v).toFixed(1);
function scoreColor(s){ if(s>=70) return '#0b6e4f'; if(s>=50) return '#1f7a4d'; if(s>=30) return '#5a4a1f'; return '#3a3f4b'; }
function badge(r){ let c='badge'; if(r.includes('🔴'))c='badge bear'; else if(r.includes('🟢'))c='badge bull'; else if(r.includes('💎'))c='badge gem'; else if(r.includes('🔄'))c='badge turn'; else if(r.includes('⚠'))c='badge warn'; return `<span class="${c}">${r}</span>`; }

const tb = document.querySelector('#tbl tbody');
function render(rows){
  tb.innerHTML = rows.map(r=>`<tr style="${r.bear_div||r.trap||r.div_cut?'background:rgba(239,83,80,.05)':''}">
    <td><b style="cursor:pointer;color:#58a6ff" onclick="openComment('${r.ticker}')">${r.ticker} 💬</b></td>
    <td><span class="pill" style="background:${r.status_color}">${r.status}</span></td>
    <td class="num">${r.price.toFixed(2)}</td>
    <td class="num ${r.yield>=4?'up':''}">${r.yield.toFixed(2)}</td>
    <td class="num">${Math.round(9000*r.yield).toLocaleString()}<br><span style="color:var(--mut);font-size:10px">≈${Math.round(750*r.yield).toLocaleString()}/ด.</span></td>
    <td style="white-space:nowrap;color:var(--mut);font-size:11px">${r.xd_last||'—'}</td>
    <td class="num ${r.payout>100?'down':''}">${f1(r.payout)}</td>
    <td class="num">${f1(r.roe)}</td>
    <td class="num ${r.epsg<0?'down':r.epsg>0?'up':''}">${f1(r.epsg)}</td>
    <td><span class="pill" style="background:${r.health_color}">${r.health}</span></td>
    <td class="num ${r.rsi<35?'up':r.rsi>70?'down':''}">${r.rsi.toFixed(0)}</td>
    <td class="num"><span class="score" style="background:${scoreColor(r.score)}">${r.score}</span></td>
    <td>${r.reasons.map(badge).join('')}</td>
  </tr>`).join('');
}
render(ROWS);
function openComment(tk){
  const r=ROWS.find(x=>x.ticker===tk); if(!r)return;
  document.getElementById('modal-body').innerHTML=`<h2 style="margin:0 0 4px">${r.ticker} <span class="pill" style="background:${r.status_color};font-size:11px">${r.status}</span></h2><div class="sub" style="margin-bottom:12px">ราคา ${r.price.toFixed(2)} · ยีลด์ ${r.yield.toFixed(1)}% · ลงล้าน ~${Math.round(9000*r.yield).toLocaleString()} ฿/ปี</div><div style="font-size:13px;background:#1a2130;border-radius:8px;padding:8px 11px;margin-bottom:12px">🎯 <b>ราคาเหมาะสม (ประเมิน):</b> ${r.fair_txt||'—'}</div><div style="font-size:13.5px;line-height:1.75">${r.comment||'—'}</div><div class="sub" style="margin-top:14px;font-size:11px">💬 คอมเมนต์สร้างอัตโนมัติจากงบ/ราคา (yfinance) • ไม่ใช่คำแนะนำลงทุน</div>`;
  document.getElementById('modal').classList.add('show');
}
function closeModal(){document.getElementById('modal').classList.remove('show');}

// 🏆 Top 5 น่าจัด (คัด div_good เรียงคะแนน)
// 🟢 ป้ายสัญญาณเข้า + คำแนะนำอัตโนมัติ (เทคนิค + พื้นฐาน)
function entryAdvice(r){
  const risks=[];
  if(r.payout!=null && r.payout>=90) risks.push('payout '+r.payout.toFixed(0)+'% แทบไม่มีบัฟเฟอร์ปันผล');
  if(r.epsg!=null && r.epsg<0) risks.push('กำไรหด '+Math.abs(r.epsg).toFixed(0)+'%');
  if(r.div_cut) risks.push('เคยตัดปันผล');
  if(r.trap) risks.push('เสี่ยง dividend trap');
  if(r.health && r.health!=='แข็งแรง' && r.health!=='n/a') risks.push('งบ'+r.health);
  if(!risks.length && r.div_good) return '✅ เทคนิคให้เข้า + พื้นฐานแข็งแรง ปันผลยั่งยืน → น่าสนใจทั้งเล่นรอบและถือยาวกินปันผล';
  if(!risks.length) return '✅ เทคนิคให้เข้า พื้นฐานโอเค → เล่นรอบได้ ตั้งจุดตัดขาดทุนเสมอ';
  return '⚠️ เทคนิคให้เข้า แต่'+risks.join(' · ')+' → เหมาะเล่นสั้น/แบ่งไม้เล็ก มากกว่าถือยาว';
}
const entries=ROWS.filter(r=>r.status.indexOf('เข้าได้')>=0);
document.getElementById('entrycall').innerHTML = entries.length ? `<div style="background:#10261b;border:1px solid #2c6e4f;border-radius:10px;padding:12px 14px;margin:6px 0;font-size:13px">🟢 <b style="color:#5fe0c8">มีสัญญาณเข้าตอนนี้ (${entries.length} ตัว)</b>${entries.map(r=>`<div style="margin-top:8px"><b style="cursor:pointer;color:#58a6ff" onclick="openComment('${r.ticker}')">${r.ticker} 💬</b> <span style="color:var(--mut)">ยีลด์ ${r.yield.toFixed(1)}% · คะแนน ${r.score} · งบ${r.health}</span><br><span style="font-size:12.5px;line-height:1.6">${entryAdvice(r)}</span></div>`).join('')}<div style="color:var(--mut);font-size:11px;margin-top:9px">สัญญาณ ≠ คำแนะนำซื้อ — กำหนดขนาดไม้ + จุดตัดขาดทุนเองเสมอ</div></div>` : '';
const turns=ROWS.filter(r=>r.turnaround);
document.getElementById('turncall').innerHTML = turns.length ? `<div style="background:#231a2e;border:1px solid #5a3d6e;border-radius:10px;padding:10px 14px;margin:6px 0;font-size:13px">🔄 <b style="color:#c89aff">หุ้น Turnaround ตอนนี้:</b> ${turns.map(r=>r.ticker+' ('+r.status+')').join(' · ')} <span style="color:var(--mut)">— กำไรฟื้นแต่ราคายังถูก/ขาลง = เสี่ยงสูง รอ confirm ก่อน</span></div>` : '';
// 📊 Track record ของสัญญาณที่เคยแนะนำ
const SIG = /*__SIGNALS__*/;
(function(){
  const el=document.getElementById('track');
  const open=SIG.open||[], closed=SIG.closed||[];
  if(!open.length && !closed.length){
    el.innerHTML='<div class="sub">ยังไม่มีสัญญาณสะสม — ระบบจะบันทึกอัตโนมัติทุกครั้งที่มีหุ้นขึ้น 🟢 เข้าได้ แล้ววัดผลให้ดูตรงนี้</div>';
    return;
  }
  const winners=open.filter(s=>s.ret>0.5);
  const winBanner=winners.length?`<div style="background:#10261b;border:1px solid #2c6e4f;border-radius:10px;padding:10px 14px;margin-bottom:10px;font-size:13px">📈 <b style="color:#5fe0c8">สัญญาณที่แนะนำไว้กำลังกำไร:</b> ${winners.map(s=>`${s.ticker} <b style="color:var(--grn)">+${s.ret.toFixed(1)}%</b> <span style="color:var(--mut)">(แนะนำ ${s.date} @${s.entry.toFixed(2)})</span>`).join(' · ')}</div>`:'';
  const row=(s)=>`<tr><td><b>${s.ticker}</b></td><td style="color:var(--mut)">${s.date}</td><td class="num">${s.entry.toFixed(2)}</td><td class="num">${(s.last??s.entry).toFixed(2)}</td><td class="num" style="font-weight:700;color:${s.ret>0?'var(--grn)':s.ret<0?'var(--red)':'var(--mut)'}">${s.ret>0?'+':''}${s.ret.toFixed(1)}%</td><td class="num" style="color:var(--mut)">${s.days}</td></tr>`;
  const wins=closed.filter(s=>s.win).length;
  const avg=closed.length?closed.reduce((a,s)=>a+s.ret,0)/closed.length:0;
  const sum=closed.length?`<div class="sub" style="margin:8px 0 0">ปิดติดตามแล้ว ${closed.length} สัญญาณ · ชนะ ${wins} (${Math.round(wins/closed.length*100)}%) · เฉลี่ย ${avg>0?'+':''}${avg.toFixed(1)}%</div>`:'';
  el.innerHTML=winBanner+`<table><thead><tr><th>หุ้น</th><th>วันแนะนำ</th><th class="num">ราคาแนะนำ</th><th class="num">ล่าสุด</th><th class="num">ผลตอบแทน</th><th class="num">ถือมา(วัน)</th></tr></thead><tbody>${open.map(row).join('')||'<tr><td colspan="6" style="color:var(--mut)">ไม่มีสัญญาณเปิดอยู่</td></tr>'}</tbody></table>`+sum+`<div class="sub" style="margin-top:6px;font-size:11px">ติดตามอัตโนมัติ 60 วันนับจากวันแนะนำ · วัดจากราคาปิด ไม่รวมปันผล/ค่าคอม · ไม่ใช่คำแนะนำซื้อขาย</div>`;
})();
const picks=[...ROWS].filter(r=>r.div_good).sort((a,b)=>b.score-a.score).slice(0,5);
document.getElementById('top5').innerHTML = picks.map((r,i)=>{
  const net=Math.round(1000000*r.yield/100*0.9);
  return `<div class="pick">
    <div class="rk">#${i+1} <span class="pill" style="background:${r.status_color};font-size:10px;padding:1px 6px">${r.status}</span></div>
    <div class="tk">${r.ticker}</div>
    <div class="big">${net.toLocaleString()} ฿<span class="lbl"> /ปี</span></div>
    <div class="lbl">≈ ${Math.round(net/12).toLocaleString()} ฿/เดือน · ลงล้าน(สุทธิ)</div>
    <div class="meta2">ยีลด์ ${r.yield.toFixed(1)}% · payout ${r.payout==null?'—':r.payout.toFixed(0)+'%'} · งบ ${r.health}</div>
  </div>`;
}).join('');

let asc = {};
document.querySelectorAll('#tbl th').forEach(th=>{
  th.onclick = ()=>{ const k=th.dataset.k; asc[k]=!asc[k];
    const s=[...ROWS].sort((a,b)=>{ let x=a[k],y=b[k];
      if(k==='reasons'){x=a[k].length;y=b[k].length;}
      if(x===null||x===undefined)x=-Infinity; if(y===null||y===undefined)y=-Infinity;
      if(typeof x==='string') return asc[k]?x.localeCompare(y):y.localeCompare(x);
      return asc[k]?x-y:y-x; });
    render(s); };
});

const host = document.getElementById('charts');
CHARTS.forEach(c=>{
  const row = ROWS.find(r=>r.id===c.id) || {};
  const card=document.createElement('div'); card.className='chart-card';
  card.innerHTML = `<div class="chart-head"><b>${c.ticker}</b>
     <span class="meta">ปันผล ${(row.yield||0).toFixed(2)}% · งบ ${row.health||'—'} · คะแนน ${row.score||0}<br>XD ล่าสุด ${row.xd_last||'—'} · คาดถัดไป ~${row.xd_next||'—'}</span></div>
     <div class="chart" id="c_${c.id}"></div>`;
  host.appendChild(card);
  const el = card.querySelector('.chart');
  const chart = LightweightCharts.createChart(el,{ width:el.clientWidth, height:300,
    layout:{background:{color:'#161b22'},textColor:'#d1d4dc'},
    grid:{vertLines:{color:'#1c2230'},horzLines:{color:'#1c2230'}},
    timeScale:{borderColor:'#2a2e39'}, rightPriceScale:{borderColor:'#2a2e39'} });
  const cs=chart.addCandlestickSeries({upColor:'#26a69a',downColor:'#ef5350',borderVisible:false,wickUpColor:'#26a69a',wickDownColor:'#ef5350'});
  cs.setData(c.candles);
  const e20=chart.addLineSeries({color:'#00bcd4',lineWidth:1,priceLineVisible:false,lastValueVisible:false}); e20.setData(c.ema20||[]);
  const e50=chart.addLineSeries({color:'#f0a000',lineWidth:1,priceLineVisible:false,lastValueVisible:false}); e50.setData(c.ema50);
  const e200=chart.addLineSeries({color:'#2962ff',lineWidth:1,priceLineVisible:false,lastValueVisible:false}); e200.setData(c.ema200);
  const e800=chart.addLineSeries({color:'#a050d0',lineWidth:2,priceLineVisible:false,lastValueVisible:false}); e800.setData(c.ema800||[]);
  if(c.markers&&c.markers.length) cs.setMarkers(c.markers);
  chart.timeScale().fitContent();
  let _lw=el.clientWidth; new ResizeObserver(()=>{const w=el.clientWidth; if(w&&w!==_lw){_lw=w; chart.applyOptions({width:w});}}).observe(el);
});
</script>
</body>
</html>"""


def build_technical(results, market, out_path):
    """หน้า 2: หุ้นเทคนิคสวย — เรียงตามคะแนนกราฟล้วนๆ (ไม่สนปันผล/งบ)"""
    res = sorted(results, key=lambda x: (x["tscore"], x["trank"]), reverse=True)
    keys = ("ticker", "id", "price", "rsi", "trend", "tscore", "tstatus", "tstatus_color", "trank",
            "treasons", "bear_div", "yield", "health", "comment", "fair_txt")
    table = [{k: r[k] for k in keys} for r in res]
    charts = [{"id": r["id"], "ticker": r["ticker"], **r["chart"]} for r in res if r["chart"]["candles"]][:8]
    n_go = sum(1 for r in res if "น่าเข้า" in r["tstatus"])
    n_near = sum(1 for r in res if "ใกล้จุดเข้า" in r["tstatus"])
    n_sup = sum(1 for r in res if "ที่แนวรับ" in r["tstatus"])
    n_avoid = sum(1 for r in res if "เลี่ยง" in r["tstatus"])

    html = TECH_TEMPLATE
    html = html.replace("/*__CSS__*/", CSS)
    html = html.replace("__TABS__", tabs_html("tech"))
    html = html.replace("/*__ROWS__*/", json.dumps(table, ensure_ascii=False))
    html = html.replace("/*__CHARTS__*/", json.dumps(charts, ensure_ascii=False))
    now_ict = datetime.now(timezone.utc) + timedelta(hours=7)
    updated = f"{now_ict.day} {TH_MON[now_ict.month]} {now_ict.year} {now_ict.hour:02d}:{now_ict.minute:02d} น."
    html = html.replace("__UPDATED__", updated)
    html = html.replace("__MARKET__", market_banner(results, market))
    html = html.replace("__SCANNED__", str(len(res)))
    html = html.replace("__NGO__", str(n_go))
    html = html.replace("__NNEAR__", str(n_near))
    html = html.replace("__NSUP__", str(n_sup))
    html = html.replace("__NAVOID__", str(n_avoid))
    Path(out_path).write_text(html, encoding="utf-8")


TECH_TEMPLATE = r"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SET Technical Screener — หุ้นเทคนิคสวย</title>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>/*__CSS__*/</style>
</head>
<body>
<div class="wrap">
  __TABS__
  <h1>📈 SET Technical Screener — หุ้นเทคนิคสวย</h1>
  <div class="sub">คัดจากกราฟล้วนๆ ไม่สนปันผล/งบ — divergence · ย่อในขาขึ้น · MACD · แนวรับ EMA800 · วอลุ่ม</div>
  <div style="color:var(--mut);font-size:11.5px;margin:-12px 0 16px">🕐 อัปเดตล่าสุด: <b style="color:#9aa4b0">__UPDATED__</b> (เวลาไทย) · อัปเดตอัตโนมัติทุกวันทำการหลังตลาดปิด</div>
  __MARKET__
  <div style="background:#2a2014;border:1px solid #6e4a1f;border-radius:10px;padding:11px 14px;margin-bottom:16px;font-size:13px;line-height:1.7">⚠️ <b style="color:#ffcf66">หน้านี้คือ "จังหวะเทรด" ไม่ใช่ลงทุนถือยาว</b> — backtest ระบบนี้ย้อนหลัง 5 ปี สัญญาณเทคนิคล้วนๆ <b>แพ้ซื้อแล้วถือเฉยๆ</b> (+2% vs +14% · ชนะ 44%) → ใช้ช่วยหาจังหวะเท่านั้น อย่าเชื่อ 100% + ตั้งจุดตัดขาดทุนทุกไม้</div>
  <div class="stats">
    <div class="stat"><b>__SCANNED__</b><span>หุ้นที่สแกน</span></div>
    <div class="stat"><b class="up">__NGO__</b><span>🟢 น่าเข้า (เทคนิค)</span></div>
    <div class="stat"><b style="color:#e0b020">__NNEAR__</b><span>🟡 ใกล้จุดเข้า</span></div>
    <div class="stat"><b style="color:#c89aff">__NSUP__</b><span>🟣 ที่แนวรับใหญ่</span></div>
    <div class="stat"><b class="down">__NAVOID__</b><span>🔴 เลี่ยง (bear div)</span></div>
  </div>
  <div id="entrycall"></div>
  <div id="modal" class="modal" onclick="if(event.target===this)closeModal()"><div class="modal-box"><span class="modal-close" onclick="closeModal()">✕</span><div id="modal-body"></div></div></div>

  <h2>📋 ตารางเทคนิค (เรียงตามความสวยของกราฟ)</h2>
  <table id="tbl"><thead><tr>
    <th data-k="ticker">หุ้น</th>
    <th data-k="trank">สถานะ</th>
    <th class="num" data-k="price">ราคา</th>
    <th class="num" data-k="rsi">RSI</th>
    <th data-k="trend">เทรนด์</th>
    <th class="num" data-k="tscore">คะแนนเทคนิค</th>
    <th data-k="treasons">สัญญาณกราฟ</th>
  </tr></thead><tbody></tbody></table>

  <h2>กราฟคะแนนเทคนิคสูงสุด (Top 8)</h2>
  <div class="grid" id="charts"></div>

  <div class="foot">
    ⚠ <b>สำคัญ:</b> หน้านี้คัดจากกราฟอย่างเดียว ไม่ได้กรองงบ/ปันผล — หุ้นกราฟสวยแต่งบแย่ก็ติดอันดับได้ → กด 💬 ดูคอมเมนต์งบก่อนตัดสินใจเสมอ<br>
    🟢 <b>น่าเข้า</b> = Bull Div ยืนยัน (เหนือ EMA20) หรือ ขาขึ้น+ย่อถึง EMA50+MACD ตัดขึ้น • 🟡 <b>ใกล้จุดเข้า</b> = เจอ setup แต่ยังไม่ครบเงื่อนไข • 🔴 <b>เลี่ยง</b> = bearish divergence<br>
    📐 เส้นบนกราฟ: <span style="color:#00bcd4">EMA20</span> · <span style="color:#f0a000">EMA50</span> · <span style="color:#2962ff">EMA200</span> · <span style="color:#a050d0">EMA800 (แนวรับใหญ่)</span><br>
    ข้อมูล yfinance ไม่ใช่ realtime • เป็นสัญญาณจากระบบ ไม่ใช่คำแนะนำลงทุน — กำหนดขนาดไม้ + จุดตัดขาดทุนเองทุกครั้ง
  </div>
</div>

<script>
const ROWS = /*__ROWS__*/;
const CHARTS = /*__CHARTS__*/;
function scoreColor(s){ if(s>=70) return '#0b6e4f'; if(s>=50) return '#1f7a4d'; if(s>=30) return '#5a4a1f'; return '#3a3f4b'; }
function badge(r){ let c='badge'; if(r.includes('🔴'))c='badge bear'; else if(r.includes('🟢'))c='badge bull'; else if(r.includes('🟣'))c='badge turn'; else if(r.includes('⚠'))c='badge warn'; return `<span class="${c}">${r}</span>`; }
const tb = document.querySelector('#tbl tbody');
function render(rows){
  tb.innerHTML = rows.map(r=>`<tr style="${r.bear_div?'background:rgba(239,83,80,.05)':''}">
    <td><b style="cursor:pointer;color:#58a6ff" onclick="openComment('${r.ticker}')">${r.ticker} 💬</b></td>
    <td><span class="pill" style="background:${r.tstatus_color}">${r.tstatus}</span></td>
    <td class="num">${r.price.toFixed(2)}</td>
    <td class="num ${r.rsi<35?'up':r.rsi>70?'down':''}">${r.rsi.toFixed(0)}</td>
    <td class="${r.trend==='ขาขึ้น'?'up':'down'}">${r.trend}</td>
    <td class="num"><span class="score" style="background:${scoreColor(r.tscore)}">${r.tscore}</span></td>
    <td>${r.treasons.map(badge).join('')}</td>
  </tr>`).join('');
}
render(ROWS);
function openComment(tk){
  const r=ROWS.find(x=>x.ticker===tk); if(!r)return;
  document.getElementById('modal-body').innerHTML=`<h2 style="margin:0 0 4px">${r.ticker} <span class="pill" style="background:${r.tstatus_color};font-size:11px">${r.tstatus}</span></h2><div class="sub" style="margin-bottom:12px">ราคา ${r.price.toFixed(2)} · RSI ${r.rsi.toFixed(0)} · ${r.trend} · ยีลด์ ${r.yield.toFixed(1)}%</div><div style="font-size:13px;background:#1a2130;border-radius:8px;padding:8px 11px;margin-bottom:12px">🎯 <b>ราคาเหมาะสม (ประเมิน):</b> ${r.fair_txt||'—'}</div><div style="font-size:13.5px;line-height:1.75">${r.comment||'—'}</div><div class="sub" style="margin-top:14px;font-size:11px">💬 คอมเมนต์สร้างอัตโนมัติจากงบ/ราคา (yfinance) • ไม่ใช่คำแนะนำลงทุน</div>`;
  document.getElementById('modal').classList.add('show');
}
function closeModal(){document.getElementById('modal').classList.remove('show');}
const entries=ROWS.filter(r=>r.tstatus.indexOf('น่าเข้า')>=0);
document.getElementById('entrycall').innerHTML = entries.length ? `<div style="background:#10261b;border:1px solid #2c6e4f;border-radius:10px;padding:12px 14px;margin:6px 0 16px;font-size:13px">🟢 <b style="color:#5fe0c8">เทคนิคน่าเข้าตอนนี้ (${entries.length} ตัว)</b>${entries.map(r=>`<div style="margin-top:8px"><b style="cursor:pointer;color:#58a6ff" onclick="openComment('${r.ticker}')">${r.ticker} 💬</b> <span style="color:var(--mut)">คะแนนเทคนิค ${r.tscore} · RSI ${r.rsi.toFixed(0)} · งบ${r.health}</span><br><span style="font-size:12.5px;line-height:1.6">${r.treasons.filter(x=>!x.includes('⚠')).slice(0,3).join(' · ')}</span></div>`).join('')}<div style="color:var(--mut);font-size:11px;margin-top:9px">สัญญาณ ≠ คำแนะนำซื้อ — ตั้งจุดตัดขาดทุนก่อนเข้าเสมอ</div></div>` : '';
let asc = {};
document.querySelectorAll('#tbl th').forEach(th=>{
  th.onclick = ()=>{ const k=th.dataset.k; asc[k]=!asc[k];
    const s=[...ROWS].sort((a,b)=>{ let x=a[k],y=b[k];
      if(k==='treasons'){x=a[k].length;y=b[k].length;}
      if(x===null||x===undefined)x=-Infinity; if(y===null||y===undefined)y=-Infinity;
      if(typeof x==='string') return asc[k]?x.localeCompare(y):y.localeCompare(x);
      return asc[k]?x-y:y-x; });
    render(s); };
});
const host = document.getElementById('charts');
CHARTS.forEach(c=>{
  const row = ROWS.find(r=>r.id===c.id) || {};
  const card=document.createElement('div'); card.className='chart-card';
  card.innerHTML = `<div class="chart-head"><b>${c.ticker}</b>
     <span class="meta">${row.tstatus||''} · RSI ${row.rsi!=null?row.rsi.toFixed(0):'—'} · ${row.trend||''} · คะแนนเทคนิค ${row.tscore||0}</span></div>
     <div class="chart" id="c_${c.id}"></div>`;
  host.appendChild(card);
  const el = card.querySelector('.chart');
  const chart = LightweightCharts.createChart(el,{ width:el.clientWidth, height:300,
    layout:{background:{color:'#161b22'},textColor:'#d1d4dc'},
    grid:{vertLines:{color:'#1c2230'},horzLines:{color:'#1c2230'}},
    timeScale:{borderColor:'#2a2e39'}, rightPriceScale:{borderColor:'#2a2e39'} });
  const cs=chart.addCandlestickSeries({upColor:'#26a69a',downColor:'#ef5350',borderVisible:false,wickUpColor:'#26a69a',wickDownColor:'#ef5350'});
  cs.setData(c.candles);
  const e20=chart.addLineSeries({color:'#00bcd4',lineWidth:1,priceLineVisible:false,lastValueVisible:false}); e20.setData(c.ema20||[]);
  const e50=chart.addLineSeries({color:'#f0a000',lineWidth:1,priceLineVisible:false,lastValueVisible:false}); e50.setData(c.ema50);
  const e200=chart.addLineSeries({color:'#2962ff',lineWidth:1,priceLineVisible:false,lastValueVisible:false}); e200.setData(c.ema200);
  const e800=chart.addLineSeries({color:'#a050d0',lineWidth:2,priceLineVisible:false,lastValueVisible:false}); e800.setData(c.ema800||[]);
  if(c.markers&&c.markers.length) cs.setMarkers(c.markers);
  chart.timeScale().fitContent();
  let _lw=el.clientWidth; new ResizeObserver(()=>{const w=el.clientWidth; if(w&&w!==_lw){_lw=w; chart.applyOptions({width:w});}}).observe(el);
});
</script>
</body>
</html>"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="dashboard.html")
    args = ap.parse_args()

    tk = TICKERS[:args.limit] if args.limit else TICKERS
    res = run(tk)
    if not res:
        print("❌ ไม่ได้ข้อมูล — เช็คอินเทอร์เน็ต/ชื่อหุ้น")
        raise SystemExit(1)

    print(f"\n{'หุ้น':<8}{'ราคา':>8}{'ปผ%':>6}{'Pay%':>6}{'กำไรโต%':>8}{'งบ':>10}{'คะแนน':>7}  สัญญาณ")
    print("-" * 86)
    for r in res[:20]:
        pay = "—" if r["payout"] is None else f"{r['payout']:.0f}"
        eg = "—" if r["epsg"] is None else f"{r['epsg']:.0f}"
        sig = ", ".join(x for x in r["reasons"] if "Div" in x or "trap" in x or "oversold" in x)[:46]
        print(f"{r['ticker']:<8}{r['price']:>8.2f}{r['yield']:>6.1f}{pay:>6}{eg:>8}{r['health']:>10}{r['score']:>7.0f}  {sig}")

    market = fetch_set_index()
    signals = track_signals(res)
    n_open = len(signals["open"])
    if n_open:
        print(f"📊 track record: เปิดติดตาม {n_open} สัญญาณ · ปิดแล้ว {len(signals['closed'])}")
    build_dashboard(res, market, signals, args.out, tabs=tabs_html("div"))
    tech_out = str(Path(args.out).with_name("technical.html"))
    build_technical(res, market, tech_out)
    print(f"\n✅ สร้าง {args.out} + {tech_out} แล้ว ({len(res)} หุ้น)")

    # ---------- หน้า 3: กลุ่ม MAI ----------
    mai_tk = MAI_TICKERS[:args.limit] if args.limit else MAI_TICKERS
    print(f"\n🚀 สแกนกลุ่ม MAI {len(mai_tk)} ตัว ...")
    res_mai = run(mai_tk)
    if res_mai:
        signals_mai = track_signals(res_mai, SIGNALS_MAI_FILE)
        mai_out = str(Path(args.out).with_name("mai.html"))
        build_dashboard(res_mai, None, signals_mai, mai_out,
                        title="🚀 MAI Dividend + Technical Screener",
                        tabs=tabs_html("mai"), notice=MAI_NOTICE,
                        mlabel="🚀 ภาพรวมกลุ่ม MAI (จากหุ้นที่สแกน)")
        print(f"✅ สร้าง {mai_out} แล้ว ({len(res_mai)} หุ้น MAI)")
    else:
        print("⚠ กลุ่ม MAI ดึงข้อมูลไม่ได้ — ข้ามหน้า mai.html รอบนี้")
