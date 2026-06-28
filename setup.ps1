# setup.ps1 — ติดตั้ง environment สำหรับ Windows
# รัน: PowerShell -ExecutionPolicy Bypass -File setup.ps1
#Requires -Version 5.1

$ErrorActionPreference = "Stop"
$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "=== stock.cyk setup ===" -ForegroundColor Cyan
Write-Host "ตำแหน่ง: $RepoDir"

# ตรวจสอบ Python
try {
    $pyVer = python --version 2>&1
    Write-Host "Python: $pyVer"
} catch {
    Write-Host "ไม่พบ python — กรุณาติดตั้ง Python 3.12+ จาก https://python.org" -ForegroundColor Red
    exit 1
}

# ติดตั้ง dependencies
Set-Location $RepoDir
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt -q
Write-Host "ติดตั้ง dependencies เรียบร้อย" -ForegroundColor Green

# สร้างโฟลเดอร์ output
New-Item -ItemType Directory -Force -Path "site" | Out-Null

# ถามว่าจะตั้ง Scheduled Task ไหม
$ans = Read-Host "ตั้ง Scheduled Task รันทุกวันธรรมดา 17:30 น. (ICT) ไหม? [y/N]"
if ($ans -match '^[Yy]$') {
    $action  = New-ScheduledTaskAction `
        -Execute "python" `
        -Argument "`"$RepoDir\screener.py`" --out `"$RepoDir\site\index.html`"" `
        -WorkingDirectory $RepoDir
    # ICT 17:30 = UTC 10:30 → ตั้งตาม local time (Windows ใช้ local time)
    $trigger = New-ScheduledTaskTrigger -Weekly `
        -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
        -At "17:30"
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
    Register-ScheduledTask `
        -TaskName "StockCyk-Screener" `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -RunLevel Highest `
        -Force | Out-Null
    Write-Host "เพิ่ม Scheduled Task 'StockCyk-Screener' แล้ว" -ForegroundColor Green
    Write-Host "ดูใน Task Scheduler > StockCyk-Screener"
}

Write-Host ""
Write-Host "=== พร้อมใช้งาน ===" -ForegroundColor Cyan
Write-Host "รันสแกน:      python screener.py --out site\index.html"
Write-Host "รัน backtest: python backtest.py"
