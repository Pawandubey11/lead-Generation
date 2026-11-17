param(
    [Parameter(Mandatory = $true)]
    [string]$BusinessType,

    [Parameter(Mandatory = $true)]
    [string]$Country,

    [int]$MaxCities = 30
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Virtual environment is missing. Run .\setup.ps1 first."
}

& ".\.venv\Scripts\python.exe" main.py $BusinessType $Country $MaxCities
