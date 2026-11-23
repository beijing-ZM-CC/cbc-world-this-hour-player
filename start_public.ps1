$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Error "Virtual environment not found at $VenvPython"
    exit 1
}

Write-Host "Starting CBC Bilingual Subtitle Player on http://127.0.0.1:8765 ..." -ForegroundColor Cyan
$serverProc = Start-Process -FilePath $VenvPython -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8765" -WorkingDirectory $ProjectDir -PassThru

Start-Sleep -Seconds 2

$localBin = Join-Path $ProjectDir "bin\cloudflared.exe"
$cloudflared = $null
if (Test-Path $localBin) {
    $cloudflared = $localBin
} else {
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) { $cloudflared = $cmd.Source }
}
if (-not $cloudflared) {
    $candidates = @(
        "C:\Program Files (x86)\cloudflared\cloudflared.exe",
        "C:\Program Files\cloudflared\cloudflared.exe",
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links\cloudflared.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $cloudflared = $c; break }
    }
}

if ($cloudflared) {
    Write-Host "Starting Cloudflare Quick Tunnel for external network access..." -ForegroundColor Green
    & $cloudflared tunnel --url http://127.0.0.1:8765
} else {
    Write-Warning "cloudflared not found in PATH. Local server is running at http://127.0.0.1:8765 (PID: $($serverProc.Id))."
    Wait-Process -Id $serverProc.Id
}
