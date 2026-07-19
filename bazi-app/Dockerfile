# Docker image สำหรับรันบน Synology NAS (Container Manager)
FROM python:3.11-slim

WORKDIR /srv/bazi

# ติดตั้ง dependencies ก่อน (แยก layer เพื่อให้ build ซ้ำเร็ว)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY tests ./tests

# โฟลเดอร์ข้อมูล (SQLite) และ log — mount volume มาทับสองที่นี้
ENV BAZI_DATA_DIR=/srv/bazi/data \
    BAZI_LOG_DIR=/srv/bazi/logs
RUN mkdir -p /srv/bazi/data /srv/bazi/logs

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
