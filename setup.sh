#!/usr/bin/env bash
# setup.sh — ติดตั้ง environment สำหรับ Linux / Ugreen NAS (UGOS)
# รัน: bash setup.sh
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON=${PYTHON:-python3}

echo "=== stock.cyk setup ==="
echo "ตำแหน่ง: $REPO_DIR"

# ตรวจสอบ Python
if ! command -v "$PYTHON" &>/dev/null; then
    echo "ไม่พบ python3 — กรุณาติดตั้ง Python 3.12+ ก่อน"
    exit 1
fi
echo "Python: $($PYTHON --version)"

# ติดตั้ง dependencies
cd "$REPO_DIR"
$PYTHON -m pip install --upgrade pip -q
$PYTHON -m pip install -r requirements.txt -q
echo "ติดตั้ง dependencies เรียบร้อย"

# สร้างโฟลเดอร์ output
mkdir -p site

# ถามว่าจะตั้ง cron ไหม
echo ""
read -rp "ตั้ง cron job รันทุกวันธรรมดา 17:30 น. (ICT) ไหม? [y/N] " ans
if [[ "$ans" =~ ^[Yy]$ ]]; then
    CRON_CMD="30 10 * * 1-5 cd $REPO_DIR && $PYTHON screener.py --out site/index.html >> $REPO_DIR/screener.log 2>&1"
    # ลบ cron เก่าถ้ามีแล้วเพิ่มใหม่
    (crontab -l 2>/dev/null | grep -v "screener.py"; echo "$CRON_CMD") | crontab -
    echo "เพิ่ม cron job แล้ว (UTC 10:30 = ICT 17:30)"
    echo "ดู cron ทั้งหมด: crontab -l"
fi

echo ""
echo "=== พร้อมใช้งาน ==="
echo "รันสแกน:      python screener.py --out site/index.html"
echo "รัน backtest: python backtest.py"
echo "ดู log cron:  tail -f $REPO_DIR/screener.log"
