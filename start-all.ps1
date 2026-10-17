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
$oldWebScript = Join-Path $PSScriptRoot "webapp\server.py"

# Webapp chay tu ban sao sach cua main (git worktree) canh repo. Webapp doc tep tinh tu dia
# moi request, nen chay ngay trong repo thi phien nao dang sua v2 la mini app that hong theo.
$prodDir = Join-Path (Split-Path $PSScriptRoot -Parent) "TrueNestProd"
$webScript = Join-Path $prodDir "webapp\server.py"
$env:BOT_DB_PATH = Join-Path $PSScriptRoot "broker_bot.db"

# Bot nap code luc khoi dong: restart khi repo con tep .py sua do = chay code do dang.
$dirty = @(git -C $PSScriptRoot status --porcelain --untracked-files=no -- "*.py" | Where-Object { $_ })
if ($dirty.Count -gt 0 -and -not $env:TRUENEST_FORCE) {
    Write-Host "Repo co $($dirty.Count) tep .py chua commit - khong restart (dat TRUENEST_FORCE=1 neu chac):" -ForegroundColor Red
    $dirty | ForEach-Object { Write-Host "  $_" }
    exit 1
}

if (-not (Test-Path $prodDir)) {
    git -C $PSScriptRoot worktree add --detach $prodDir main
}
git -C $prodDir checkout -q --detach main
if ($LASTEXITCODE -ne 0) {
    Write-Host "Khong cap nhat duoc $prodDir ve main. Dung lai." -ForegroundColor Red
    exit 1
}

function Get-TrueNestProcs {
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -and ($_.CommandLine.Contains($botScript) -or
                       $_.CommandLine.Contains($webScript) -or $_.CommandLine.Contains($oldWebScript)) }
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
Start-Process pythonw -WorkingDirectory $prodDir -WindowStyle Hidden -ArgumentList "`"$webScript`""

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
