#!/usr/bin/env bash
# setup.sh — ติดตั้ง Docker + Portainer + stock screener บน Linux VM
# รัน: bash setup.sh
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== stock.cyk setup ==="
echo "ตำแหน่ง: $REPO_DIR"
echo ""

# ── 1. ติดตั้ง Docker ──────────────────────────────────────────────────────────
if command -v docker &>/dev/null; then
    echo "[✓] Docker พบแล้ว: $(docker --version)"
else
    echo "[→] กำลังติดตั้ง Docker..."
    curl -fsSL https://get.docker.com | sh
    # เพิ่ม user ปัจจุบันเข้ากลุ่ม docker เพื่อไม่ต้องพิมพ์ sudo ทุกครั้ง
    sudo usermod -aG docker "$USER"
    echo "[✓] ติดตั้ง Docker เรียบร้อย"
    echo "    ** หมายเหตุ: ต้อง logout แล้ว login ใหม่ถึงจะใช้ docker โดยไม่ต้อง sudo"
fi

# ── 2. ติดตั้ง Portainer (Docker GUI บน browser) ──────────────────────────────
if docker ps --filter "name=portainer" --format '{{.Names}}' 2>/dev/null | grep -q portainer; then
    echo "[✓] Portainer รันอยู่แล้ว"
else
    echo "[→] กำลังติดตั้ง Portainer..."
    docker volume create portainer_data 2>/dev/null || true
    docker run -d \
        --name portainer \
        --restart unless-stopped \
        -p 9000:9000 \
        -v /var/run/docker.sock:/var/run/docker.sock \
        -v portainer_data:/data \
        portainer/portainer-ce:latest
    echo "[✓] Portainer พร้อมใช้งาน"
    echo "    เปิด browser ไปที่: http://localhost:9000"
    echo "    (หรือใช้ IP ของ VM แทน localhost)"
fi

# ── 3. ตั้งค่า screener ────────────────────────────────────────────────────────
cd "$REPO_DIR"
mkdir -p site

# Build Docker image
echo ""
echo "[→] กำลัง build Docker image..."
docker build -t stock-cyk . -q
echo "[✓] Build เรียบร้อย — image ชื่อ stock-cyk"

# ── 4. ตั้ง cron รันผ่าน Docker ───────────────────────────────────────────────
echo ""
read -rp "ตั้ง cron job รันทุกวันธรรมดา 17:30 น. (ICT) ไหม? [y/N] " ans
if [[ "$ans" =~ ^[Yy]$ ]]; then
    CRON_CMD="30 10 * * 1-5 docker run --rm -v $REPO_DIR:/app stock-cyk >> $REPO_DIR/screener.log 2>&1"
    (crontab -l 2>/dev/null | grep -v "stock-cyk"; echo "$CRON_CMD") | crontab -
    echo "[✓] เพิ่ม cron job แล้ว (UTC 10:30 = ICT 17:30)"
fi

echo ""
echo "════════════════════════════════════════"
echo " พร้อมใช้งาน"
echo "════════════════════════════════════════"
echo " Portainer GUI : http://localhost:9000"
echo " รันสแกนทันที : docker run --rm -v $REPO_DIR:/app stock-cyk"
echo " รัน backtest  : docker run --rm -v $REPO_DIR:/app stock-cyk python backtest.py"
echo " ดู log        : tail -f $REPO_DIR/screener.log"
echo "════════════════════════════════════════"
