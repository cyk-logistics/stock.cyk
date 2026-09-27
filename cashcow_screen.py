#!/usr/bin/env python3
"""
คัดหุ้น Cash Cow ในตลาดไทย — ตามเกณฑ์บทความลงทุนแมน "วิธีหาหุ้น Cash Cow" (longtunman.com/66311)
  1) กระแสเงินสดอิสระ (FCF = เงินสดจากดำเนินงาน - รายจ่ายลงทุน) เป็นบวก และโตขึ้น
  2) ROE >= 15% ต่อเนื่อง
  3) จ่ายปันผล 50-80% ของกำไร (ต้องไม่เกิน 100%)
  4) หนี้ที่มีภาระดอกเบี้ย / ส่วนผู้ถือหุ้น (IBD/E) <= 1.5 เท่า
เสริม: ปันผลจ่ายต่อเนื่องกี่ปี · FCF พอจ่ายปันผลไหม · สัดส่วนลงทุน (capex/เงินสดดำเนินงาน) · ยีลด์ตอนนี้ · กลุ่มธุรกิจ

ข้อมูล: งบปีจาก yfinance (~4 ปีล่าสุด) · สถาบันการเงิน (แบงก์/สินเชื่อ/ประกัน) ใช้เกณฑ์ FCF/หนี้ไม่ได้ → แยกกลุ่ม
รัน: python cashcow_screen.py → พิมพ์ตาราง + เขียน cashcow.json (ใช้ติดป้าย 🐄 ในเมลสัญญาณซื้อ)
"""
import json
import warnings
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

from signal_email import UNIVERSE

warnings.filterwarnings("ignore")
OUT = Path(__file__).parent / "cashcow.json"
# นอกจาก 56 ตัวในระบบ: ธุรกิจจำเป็น/โตช้า/ผู้นำตลาดที่มักเป็น Cash Cow ในไทย
EXTRA = ("TTW,EASTW,TFMAMA,SNP,M,DCC,TOA,SCCC,STANLY,SAT,TQM,BAFS,PR9,BCH,CHG,SAPPE,ICHI,MEGA,TVO,TKN,"
         "QH,SPRC,PTG,BCPG,CKP,TISCO,TCAP,LHFG,THANI,TIDLOR,ASK,TLI,BLA,SVI,SYNEX,SIS,MAJOR,PLANB,"
         "GFPT,NER,SNNP,ERW,TASCO,SCB,INTUCH,JMT,AEONTS,KGI,BCH,TPIPL,TPIPP,III,PSL,RCL").split(",")
FIN_SECTORS = {"Financial Services"}
STAPLE_SECTORS = {"Consumer Defensive", "Utilities", "Communication Services", "Healthcare"}


def _row(df, *names):
    for n in names:
        if df is not None and n in df.index:
            s = df.loc[n].dropna()
            if len(s):
                return s.sort_index()
    return None


def analyze(sym):
    t = yf.Ticker(sym + ".BK")
    try:
        cf, inc, bs = t.cashflow, t.financials, t.balance_sheet
    except Exception as e:
        return {"sym": sym, "error": str(e)[:60]}
    try:
        info = t.info or {}
    except Exception:
        info = {}
    sector = info.get("sector", "")
    ocf = _row(cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
    capex = _row(cf, "Capital Expenditure")
    fcf = _row(cf, "Free Cash Flow")
    if fcf is None and ocf is not None and capex is not None:
        fcf = (ocf + capex.reindex(ocf.index).fillna(0)).dropna()
    divp = _row(cf, "Cash Dividends Paid", "Common Stock Dividend Paid")
    ni = _row(inc, "Net Income Common Stockholders", "Net Income")
    eq = _row(bs, "Stockholders Equity", "Common Stock Equity")
    debt = _row(bs, "Total Debt")
    if ni is None or eq is None:
        return {"sym": sym, "error": "งบไม่ครบ"}
    yrs = sorted(set(ni.index) & set(eq.index))
    roe = [float(ni[y] / eq[y] * 100) for y in yrs if eq[y] > 0]
    payout = []
    if divp is not None:
        for y in yrs:
            if y in divp.index and ni[y] > 0:
                payout.append(float(abs(divp[y]) / ni[y] * 100))
    fcfs = [float(fcf[y]) for y in sorted(fcf.index)] if fcf is not None else []
    ibde = float(debt.iloc[-1] / eq.iloc[-1]) if debt is not None and eq.iloc[-1] > 0 else 0.0
    capex_int = (float(abs(capex.iloc[-len(ocf):].sum()) / ocf.sum() * 100)
                 if capex is not None and ocf is not None and ocf.sum() > 0 else None)
    fcf_cover = (float(sum(fcfs) / abs(divp.sum())) if divp is not None and abs(divp.sum()) > 0 and fcfs else None)
    # ปันผลจ่ายต่อเนื่องกี่ปี (ปีปฏิทินที่มีปันผล นับย้อนจากปีที่แล้ว)
    streak = 0
    try:
        d = t.dividends
        years = set(d.index.year) if d is not None and len(d) else set()
        y = datetime.now().year - 1
        while y in years:
            streak += 1; y -= 1
    except Exception:
        pass
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    dy = info.get("trailingAnnualDividendYield")
    is_fin = sector in FIN_SECTORS
    r = {"sym": sym, "name": (info.get("shortName") or "")[:28], "sector": sector, "fin": is_fin,
         "years": len(yrs), "roe": [round(x, 1) for x in roe], "roe_min": round(min(roe), 1) if roe else None,
         "roe_avg": round(sum(roe) / len(roe), 1) if roe else None,
         "payout": [round(x) for x in payout], "payout_avg": round(sum(payout) / len(payout)) if payout else None,
         "payout_max": round(max(payout)) if payout else None,
         "fcf": [round(x / 1e6) for x in fcfs], "ibde": round(ibde, 2),
         "capex_int": round(capex_int) if capex_int is not None else None,
         "fcf_cover": round(fcf_cover, 2) if fcf_cover is not None else None,
         "div_streak": streak, "yield": round(dy * 100, 2) if dy else None, "price": price}
    # ---- เกณฑ์ลงทุนแมน ----
    c = {}
    if not is_fin:
        c["fcf"] = bool(fcfs) and all(x > 0 for x in fcfs) and fcfs[-1] >= fcfs[0]
        c["fcf_every_year_up"] = bool(fcfs) and all(b >= a for a, b in zip(fcfs, fcfs[1:]))
        c["ibde"] = ibde <= 1.5
    c["roe"] = bool(roe) and min(roe) >= 15
    c["payout"] = r["payout_avg"] is not None and 50 <= r["payout_avg"] <= 80 and (r["payout_max"] or 0) < 100
    main = ["roe", "payout"] + ([] if is_fin else ["fcf", "ibde"])
    r["checks"] = c
    r["passed"] = sum(1 for k in main if c.get(k))
    r["of"] = len(main)
    r["cashcow"] = (not is_fin) and r["passed"] == 4
    r["fail"] = [k for k in main if not c.get(k)]
    return r


def main():
    syms = list(dict.fromkeys(UNIVERSE + [s for s in EXTRA if s]))
    rows = []
    for s in syms:
        try:
            r = analyze(s)
        except Exception as e:
            r = {"sym": s, "error": str(e)[:60]}
        rows.append(r)
        print("  ✓" if "error" not in r else "  ✗", s, r.get("error", ""), flush=True)
    ok = [r for r in rows if "error" not in r]
    ok.sort(key=lambda r: (r.get("cashcow", False), r.get("passed", 0) / max(r.get("of", 1), 1),
                           r.get("roe_avg") or 0), reverse=True)
    lab = {"fcf": "FCF", "roe": "ROE", "payout": "ปันผล50-80%", "ibde": "หนี้"}
    print("\n%-7s %-3s %-22s %6s %6s %7s %6s %6s %5s %6s  %s" %
          ("หุ้น", "ผ่าน", "กลุ่ม", "ROEต่ำสุด", "ROEเฉลี่ย", "จ่าย%", "IBD/E", "FCFคุ้ม", "ปีปันผล", "ยีลด์", "ไม่ผ่าน"))
    for r in ok:
        mark = "🐄" if r["cashcow"] else ("🏦" if r["fin"] else "  ")
        print("%s%-6s %d/%d %-22s %6s %6s %7s %6s %6s %5s %6s  %s" % (
            mark, r["sym"], r["passed"], r["of"], (r["sector"] or "-")[:22], r["roe_min"], r["roe_avg"],
            r["payout_avg"], r["ibde"], r["fcf_cover"], r["div_streak"], r["yield"],
            ",".join(lab[k] for k in r["fail"])))
    OUT.write_text(json.dumps({"updated": datetime.now(timezone(timedelta(hours=7))).isoformat(timespec="seconds"),
                               "source": "yfinance งบปี ~4 ปี · เกณฑ์ลงทุนแมน longtunman.com/66311",
                               "cashcow": [r["sym"] for r in ok if r["cashcow"]],
                               "rows": ok, "errors": [r for r in rows if "error" in r]},
                              ensure_ascii=False, indent=1))
    print("\nCash Cow ครบ 4 ข้อ:", ", ".join(r["sym"] for r in ok if r["cashcow"]) or "—")


if __name__ == "__main__":
    main()
