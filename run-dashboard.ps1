$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Virtual environment is missing. Run .\setup.ps1 first."
}

if (-not $env:LEADPULSE_DEV_MODE) {
    $env:LEADPULSE_DEV_MODE = "true"
}

& ".\.venv\Scripts\python.exe" -m uvicorn dashboard.app:app --host 127.0.0.1 --port 8000
