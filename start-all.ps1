# TrueNest: start webapp + bot in one command
# Usage: .\start-all.ps1
# Token doc 1 lan: tao file token.txt cung folder, paste token vao (file nay ko push len GitHub)
# Chay lai bao nhieu lan cung chi con dung 1 bot + 1 webapp: ban cu bi tat truoc khi bat ban moi.

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

# Duong dan tuyet doi: dong lenh cua tien trinh chua duong dan nay, nen chi tat dung
# bot/webapp cua thu muc nay, khong dung bot.py cua du an khac.
$botScript = Join-Path $PSScriptRoot "bot.py"
$webScript = Join-Path $PSScriptRoot "webapp\server.py"

function Get-TrueNestProcs {
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -and ($_.CommandLine.Contains($botScript) -or $_.CommandLine.Contains($webScript)) }
}

$old = @(Get-TrueNestProcs)
if ($old.Count -gt 0) {
    Write-Host "Tat $($old.Count) ban dang chay..." -ForegroundColor Yellow
    foreach ($p in $old) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
    $left = @(Get-TrueNestProcs)
    if ($left.Count -gt 0) {
        Write-Host "Khong tat duoc $($left.Count) ban cu (PID $($left.ProcessId -join ', ')). Dung lai, khong bat them." -ForegroundColor Red
        exit 1
    }
}

Write-Host "Starting webapp..." -ForegroundColor Green
Start-Process pythonw -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -ArgumentList "`"$webScript`""

Start-Sleep -Seconds 2

Write-Host "Starting bot..." -ForegroundColor Green
Start-Process pythonw -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -ArgumentList "`"$botScript`""

Start-Sleep -Seconds 5
$now = @(Get-TrueNestProcs)
$bots = @($now | Where-Object { $_.CommandLine.Contains($botScript) }).Count
$webs = @($now | Where-Object { $_.CommandLine.Contains($webScript) }).Count
if ($bots -eq 1 -and $webs -eq 1) {
    Write-Host "Done! 1 bot + 1 webapp dang chay ngam." -ForegroundColor Green
} else {
    Write-Host "Canh bao: dang co $bots bot va $webs webapp (mong doi 1 + 1)." -ForegroundColor Red
    exit 1
}
