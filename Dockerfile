FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# source files จะ mount จาก host ทำให้ git pull แล้วรันได้ทันที
# ถ้าต้องการ image แบบ standalone ให้ uncomment บรรทัดด้านล่าง:
# COPY screener.py backtest.py signals.json ./

CMD ["python", "screener.py", "--out", "site/index.html"]
