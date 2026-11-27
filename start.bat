@echo off
title LeadPulse — Starting…
echo.
echo  ██╗     ███████╗ █████╗ ██████╗ ██████╗ ██╗   ██╗██╗     ███████╗███████╗
echo  ██║     ██╔════╝██╔══██╗██╔══██╗██╔══██╗██║   ██║██║     ██╔════╝██╔════╝
echo  ██║     █████╗  ███████║██║  ██║██████╔╝██║   ██║██║     ███████╗█████╗
echo  ██║     ██╔══╝  ██╔══██║██║  ██║██╔═══╝ ██║   ██║██║     ╚════██║██╔══╝
echo  ███████╗███████╗██║  ██║██████╔╝██║     ╚██████╔╝███████╗███████║███████╗
echo  ╚══════╝╚══════╝╚═╝  ╚═╝╚═════╝ ╚═╝      ╚═════╝ ╚══════╝╚══════╝╚══════╝
echo.
echo  Initialising — this may take a few minutes on first run …
echo.

python start.py
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Python may not be installed or not in PATH.
    echo  Download Python 3.10+ from https://www.python.org/downloads/
    echo  Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)
pause
