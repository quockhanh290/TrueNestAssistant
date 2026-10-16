# TrueNest: start webapp + bot in one command
# Usage: .\start-all.ps1
# Token: set $env:TELEGRAM_BOT_TOKEN before running, or edit TOKEN below (local only, don't commit)

param(
    [string]$Token = ""
)

# Priority: -Token param > existing env > value below
if ($Token) { $env:TELEGRAM_BOT_TOKEN = $Token }
if (-not $env:TELEGRAM_BOT_TOKEN -or $env:TELEGRAM_BOT_TOKEN -like "*PASTE*") {
    # Edit this line locally with your token (don't push the real token)
    $env:TELEGRAM_BOT_TOKEN = "<PASTE_TOKEN_HERE>"
}
if ($env:TELEGRAM_BOT_TOKEN -like "*PASTE*") {
    Write-Host "Chua co token! Chay: `$env:TELEGRAM_BOT_TOKEN='<token>'; .\start-all.ps1" -ForegroundColor Red
    exit 1
}

$env:WEBAPP_URL = "https://celebration-workers-knowledgestorm-yard.trycloudflare.com"

Write-Host "Starting webapp..." -ForegroundColor Green
Start-Process powershell -WindowStyle Hidden -ArgumentList "-Command", "cd '$PSScriptRoot'; `$env:TELEGRAM_BOT_TOKEN='$env:TELEGRAM_BOT_TOKEN'; `$env:WEBAPP_URL='$env:WEBAPP_URL'; pythonw webapp/server.py"

Start-Sleep -Seconds 2

Write-Host "Starting bot..." -ForegroundColor Green
Start-Process powershell -WindowStyle Hidden -ArgumentList "-Command", "cd '$PSScriptRoot'; `$env:TELEGRAM_BOT_TOKEN='$env:TELEGRAM_BOT_TOKEN'; `$env:WEBAPP_URL='$env:WEBAPP_URL'; pythonw bot.py"

Write-Host "Done! webapp + bot dang chay ngam." -ForegroundColor Green
