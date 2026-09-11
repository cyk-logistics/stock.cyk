#!/usr/bin/env python3
"""
Settrade Open API client (ผ่าน InnovestX) — ดึงข้อมูลอย่างเดียว (DATA ONLY)

เจตนา/ความปลอดภัย:
  • มีเฉพาะฟังก์ชัน "อ่าน" — ราคาสด, แท่งเทียน, บัญชี, พอร์ต, คำสั่ง/ดีลที่เกิดแล้ว
  • ตั้งใจ "ไม่" ห่อ place_order/cancel_order — การส่งคำสั่งซื้อขายต้องทำโดยคนเท่านั้น (ต้องใช้ PIN)
  • credentials อ่านจาก env หรือ settrade_config.json — ห้าม commit ไฟล์จริง (อยู่ใน .gitignore)

ค่าที่ต้องมี: app_id, app_secret, app_code, broker_id  (+ account_no ถ้าจะดูพอร์ต)
Sandbox: is_sandbox=true (broker_id ทดสอบ = 098) · Live InnovestX: broker_id = 023
"""
import json
import os
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "settrade_config.json"


def load_config():
    cfg = {}
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            raise SystemExit(f"อ่าน settrade_config.json ไม่ได้: {e}")
    # env override (ใช้บน server/CI ได้โดยไม่ต้องมีไฟล์)
    for k in ("app_id", "app_secret", "app_code", "broker_id", "account_no"):
        v = os.environ.get("SETTRADE_" + k.upper())
        if v:
            cfg[k] = v
    if "is_sandbox" not in cfg:
        cfg["is_sandbox"] = os.environ.get("SETTRADE_SANDBOX", "1") not in ("0", "false", "False")
    return cfg


class SettradeData:
    """ตัวเชื่อม Settrade แบบอ่านอย่างเดียว"""

    def __init__(self, cfg=None):
        cfg = cfg or load_config()
        missing = [k for k in ("app_id", "app_secret", "app_code", "broker_id") if not cfg.get(k)]
        if missing:
            raise SystemExit("ยังไม่ได้ตั้งค่า: " + ", ".join(missing)
                             + "\n→ เติมใน settrade_config.json (ดู settrade_config.example.json)")
        import settrade_v2
        # เลือก sandbox (uat) หรือ live (prod) ก่อนสร้าง Investor
        settrade_v2.config.config["environment"] = "uat" if cfg.get("is_sandbox") else "prod"
        from settrade_v2 import Investor
        self._inv = Investor(app_id=cfg["app_id"], app_secret=cfg["app_secret"],
                             app_code=cfg["app_code"], broker_id=str(cfg["broker_id"]))
        self.sandbox = bool(cfg.get("is_sandbox"))
        self.account_no = cfg.get("account_no")
        self._md = self._inv.MarketData()
        self._eq = self._inv.Equity(account_no=self.account_no) if self.account_no else None

    # ---------- ราคา / ตลาด ----------
    def quote(self, symbol):
        """ราคาสดของหุ้น 1 ตัว (dict) — เช่น last, change, volume, bid/offer"""
        return self._md.get_quote_symbol(symbol)

    def quotes(self, symbols):
        """ราคาสดหลายตัว → {symbol: quote|{'error':...}}"""
        out = {}
        for s in symbols:
            try:
                out[s] = self._md.get_quote_symbol(s)
            except Exception as e:
                out[s] = {"error": str(e)[:120]}
        return out

    def candles(self, symbol, interval="1d", limit=250):
        """แท่งเทียนย้อนหลัง (ไว้คำนวณ RSI/EMA แทน yfinance ได้)"""
        return self._md.get_candlestick(symbol, interval=interval, limit=limit)

    # ---------- บัญชี / พอร์ต (ต้องมี account_no) ----------
    def account(self):
        self._need_acct()
        return self._eq.get_account_info()

    def portfolio(self):
        self._need_acct()
        return self._eq.get_portfolios()

    def trades(self):
        self._need_acct()
        return self._eq.get_trades()

    def _need_acct(self):
        if not self._eq:
            raise SystemExit("ต้องใส่ account_no ใน config ก่อนถึงจะดูบัญชี/พอร์ตได้")


if __name__ == "__main__":
    # smoke test เบาๆ: เชื่อมต่อ + ดึงราคา AOT
    d = SettradeData()
    print("เชื่อมต่อสำเร็จ ·", "SANDBOX" if d.sandbox else "LIVE")
    print("AOT:", d.quote("AOT"))
