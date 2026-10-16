# TrueNest: start webapp + bot in one command
# Usage: .\start-all.ps1
# Token doc 1 lan: tao file token.txt cung folder, paste token vao (file nay ko push len GitHub)

$tokenFile = Join-Path $PSScriptRoot "token.txt"
if (Test-Path $tokenFile) {
    $env:TELEGRAM_BOT_TOKEN = (Get-Content $tokenFile -Raw).Trim()
}
if (-not $env:TELEGRAM_BOT_TOKEN) {
    Write-Host "Chua co token! Tao file token.txt va paste token vao." -ForegroundColor Red
    exit 1
}

# WEBAPP_URL: doc tu webapp_url.txt neu co (de doi tunnel URL khong can pull), khong thi dung default
$urlFile = Join-Path $PSScriptRoot "webapp_url.txt"
if (Test-Path $urlFile) {
    $env:WEBAPP_URL = (Get-Content $urlFile -Raw).Trim()
} else {
    $env:WEBAPP_URL = "https://celebration-workers-knowledgestorm-yard.trycloudflare.com"
}

Write-Host "Starting webapp..." -ForegroundColor Green
Start-Process powershell -WindowStyle Hidden -ArgumentList "-Command", "cd '$PSScriptRoot'; `$env:TELEGRAM_BOT_TOKEN='$env:TELEGRAM_BOT_TOKEN'; `$env:WEBAPP_URL='$env:WEBAPP_URL'; pythonw webapp/server.py"

Start-Sleep -Seconds 2

Write-Host "Starting bot..." -ForegroundColor Green
Start-Process powershell -WindowStyle Hidden -ArgumentList "-Command", "cd '$PSScriptRoot'; `$env:TELEGRAM_BOT_TOKEN='$env:TELEGRAM_BOT_TOKEN'; `$env:WEBAPP_URL='$env:WEBAPP_URL'; pythonw bot.py"

Write-Host "Done! webapp + bot dang chay ngam." -ForegroundColor Green
