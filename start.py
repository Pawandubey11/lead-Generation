#!/usr/bin/env python3
"""
LeadPulse — Zero-configuration one-command launcher.

Usage:
    python start.py           # auto-setup + start dashboard
    python start.py --setup   # setup only (no server launch)

What this does automatically:
    1. Creates a Python virtual environment (.venv)
    2. Installs all required packages from requirements.txt
    3. Downloads Playwright Chromium browser (~150 MB, one-time only)
    4. Copies .env.example → .env if .env is missing
    5. Creates output/ and logs/ directories
    6. Starts the LeadPulse dashboard at http://127.0.0.1:8000
"""

import sys
import os
import subprocess
import shutil
import platform

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
VENV_DIR     = os.path.join(PROJECT_ROOT, ".venv")
IS_WIN       = platform.system() == "Windows"
BIN_DIR      = "Scripts" if IS_WIN else "bin"

PYTHON  = os.path.join(VENV_DIR, BIN_DIR, "python" + (".exe" if IS_WIN else ""))
PIP     = os.path.join(VENV_DIR, BIN_DIR, "pip"    + (".exe" if IS_WIN else ""))
UVICORN = os.path.join(VENV_DIR, BIN_DIR, "uvicorn" + (".exe" if IS_WIN else ""))

REQ_ROOT = os.path.join(PROJECT_ROOT, "requirements.txt")
REQ_DASH = os.path.join(PROJECT_ROOT, "dashboard", "requirements.txt")
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")
ENV_EXAMPLE = os.path.join(PROJECT_ROOT, ".env.example")


def step(msg: str) -> None:
    print(f"\n\033[1;36m➤  {msg}\033[0m")


def ok(msg: str) -> None:
    print(f"   \033[1;32m✔  {msg}\033[0m")


def warn(msg: str) -> None:
    print(f"   \033[1;33m⚠  {msg}\033[0m")


# ---------------------------------------------------------------------------
# Step 1 — Virtual environment
# ---------------------------------------------------------------------------
step("Checking virtual environment …")
if not os.path.isfile(PYTHON):
    print("   Creating .venv …")
    subprocess.check_call([sys.executable, "-m", "venv", VENV_DIR])
    ok("Virtual environment created")
else:
    ok(".venv already exists — skipped")


# ---------------------------------------------------------------------------
# Step 2 — Install / upgrade dependencies
# ---------------------------------------------------------------------------
step("Installing Python dependencies …")
subprocess.check_call(
    [PYTHON, "-m", "pip", "install", "--quiet", "--upgrade", "pip"],
    stdout=subprocess.DEVNULL,
)
req_args = ["-r", REQ_ROOT]
if os.path.isfile(REQ_DASH):
    req_args += ["-r", REQ_DASH]
subprocess.check_call(
    [PYTHON, "-m", "pip", "install", "--quiet"] + req_args,
)
ok("All packages installed / up-to-date")


# ---------------------------------------------------------------------------
# Step 3 — Playwright Chromium
# ---------------------------------------------------------------------------
step("Checking Playwright Chromium browser …")
# playwright install --dry-run exits non-zero when browsers are missing
result = subprocess.run(
    [PYTHON, "-m", "playwright", "install", "--dry-run"],
    capture_output=True, text=True,
)
chromium_missing = (
    result.returncode != 0
    or "chromium" in result.stdout.lower()
    or "chromium" in result.stderr.lower()
)
if chromium_missing:
    print("   Downloading Playwright Chromium (~150 MB, one-time only) …")
    install_args = [PYTHON, "-m", "playwright", "install", "chromium"]
    if platform.system() == "Linux":
        # Install OS-level deps too on Linux
        install_args.append("--with-deps")
    subprocess.check_call(install_args)
    ok("Chromium downloaded")
else:
    ok("Playwright Chromium already installed — skipped")


# ---------------------------------------------------------------------------
# Step 4 — .env file
# ---------------------------------------------------------------------------
step("Checking .env configuration …")
if not os.path.isfile(ENV_FILE):
    if os.path.isfile(ENV_EXAMPLE):
        shutil.copy(ENV_EXAMPLE, ENV_FILE)
        warn(".env created from .env.example")
        warn("All features work without an API key.")
        warn("To enable AI lead scoring, add GEMINI_API_KEY (or OPENAI_API_KEY) to .env")
    else:
        warn(".env.example not found — skipping .env creation")
else:
    ok(".env already exists — skipped")


# ---------------------------------------------------------------------------
# Step 5 — Output / logs directories
# ---------------------------------------------------------------------------
step("Ensuring output/ and logs/ directories exist …")
os.makedirs(os.path.join(PROJECT_ROOT, "output"), exist_ok=True)
os.makedirs(os.path.join(PROJECT_ROOT, "logs"),   exist_ok=True)
ok("Directories ready")


# ---------------------------------------------------------------------------
# Step 6 — Launch dashboard (unless --setup only)
# ---------------------------------------------------------------------------
if "--setup" in sys.argv:
    print("\n\033[1;32m✅  Setup complete!\033[0m")
    print("   Run  python start.py  to start the dashboard.\n")
    sys.exit(0)

print("\n\033[1;32m✅  Setup complete! Launching LeadPulse …\033[0m")
print("   Dashboard → \033[1;4mhttp://127.0.0.1:8000\033[0m")
print("   Press Ctrl+C to stop.\n")

os.chdir(PROJECT_ROOT)

# Use os.execv to replace this process with uvicorn (clean, no extra wrapper)
if IS_WIN:
    # Windows: execv doesn't propagate console cleanly; use subprocess instead
    try:
        subprocess.run(
            [PYTHON, "-m", "uvicorn", "dashboard.app:app",
             "--host", "127.0.0.1", "--port", "8000"],
            check=True,
        )
    except KeyboardInterrupt:
        print("\nLeadPulse stopped.")
else:
    os.execv(PYTHON, [PYTHON, "-m", "uvicorn", "dashboard.app:app",
                      "--host", "127.0.0.1", "--port", "8000"])
