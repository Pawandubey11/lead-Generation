#!/usr/bin/env bash
# LeadPulse — Linux / macOS one-time setup script
# Usage: ./setup.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   LeadPulse — Setting up environment …  ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# -- Python version check ---------------------------------------------------
if ! command -v python3 &>/dev/null; then
    echo "❌  python3 not found. Install Python 3.10+ and re-run this script."
    exit 1
fi
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "✔  Python $PY_VER found"

# -- Virtual environment ----------------------------------------------------
if [ ! -f ".venv/bin/python" ]; then
    echo "   Creating virtual environment …"
    python3 -m venv .venv
    echo "✔  .venv created"
else
    echo "✔  .venv already exists — skipped"
fi

source .venv/bin/activate

# -- Dependencies -----------------------------------------------------------
echo "   Installing Python packages (this may take a minute) …"
pip install --upgrade pip -q
pip install -r requirements.txt -q
if [ -f "dashboard/requirements.txt" ]; then
    pip install -r dashboard/requirements.txt -q
fi
echo "✔  Packages installed"

# -- Playwright Chromium ----------------------------------------------------
echo "   Checking Playwright Chromium …"
if python -m playwright install --dry-run 2>&1 | grep -qi chromium || \
   ! python -m playwright install --dry-run &>/dev/null; then
    echo "   Downloading Playwright Chromium (~150 MB, one-time only) …"
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        python -m playwright install --with-deps chromium
    else
        python -m playwright install chromium
    fi
    echo "✔  Chromium downloaded"
else
    echo "✔  Chromium already installed — skipped"
fi

# -- .env file --------------------------------------------------------------
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "✔  .env created from .env.example"
        echo "   ℹ  All features work without an API key."
        echo "   ℹ  Add GEMINI_API_KEY (or OPENAI_API_KEY) to .env to enable AI scoring."
    fi
else
    echo "✔  .env already exists — skipped"
fi

# -- Output dirs ------------------------------------------------------------
mkdir -p output logs
echo "✔  output/ and logs/ directories ready"

echo ""
echo "✅  Setup complete!"
echo "   Run  ./run-dashboard.sh  to start LeadPulse."
echo ""
