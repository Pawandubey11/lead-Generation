param(
    [switch]$SkipBrowser
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python is not installed or not on PATH. Install Python 3.11 or 3.13, then rerun this script."
}

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt -r dashboard\requirements.txt

if (-not $SkipBrowser) {
    & ".\.venv\Scripts\python.exe" -m playwright install chromium
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}

Write-Host ""
Write-Host "Setup complete."
Write-Host "Start the dashboard: .\run-dashboard.ps1"
