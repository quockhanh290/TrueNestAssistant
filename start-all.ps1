# TrueNest: start webapp + bot in one command
# Usage: .\start-all.ps1
# First time: edit the two values below

$env:TELEGRAM_BOT_TOKEN="<PASTE_TOKEN_HERE>"
$env:WEBAPP_URL="https://celebration-workers-knowledgestorm-yard.trycloudflare.com"

if ($env:TELEGRAM_BOT_TOKEN -eq "<PASTE_TOKEN_HERE>") {
    Write-Host "Chua set token! Mo file start-all.ps1 va paste token vao." -ForegroundColor Red
    exit 1
}

Write-Host "Starting webapp..." -ForegroundColor Green
Start-Process powershell -WindowStyle Hidden -ArgumentList "-Command", "cd '$PSScriptRoot'; `$env:TELEGRAM_BOT_TOKEN='$env:TELEGRAM_BOT_TOKEN'; `$env:WEBAPP_URL='$env:WEBAPP_URL'; python webapp/server.py"

Start-Sleep -Seconds 2

Write-Host "Starting bot..." -ForegroundColor Green
Start-Process powershell -WindowStyle Hidden -ArgumentList "-Command", "cd '$PSScriptRoot'; `$env:TELEGRAM_BOT_TOKEN='$env:TELEGRAM_BOT_TOKEN'; `$env:WEBAPP_URL='$env:WEBAPP_URL'; python bot.py"

Write-Host "Done! webapp + bot dang chay ngam (Task Manager > python de dung)." -ForegroundColor Green
