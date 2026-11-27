#!/usr/bin/env bash
# LeadPulse — Linux / macOS dashboard launcher
# Usage: ./run-dashboard.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -f ".venv/bin/python" ]; then
    echo "❌  Virtual environment not found. Run ./setup.sh first."
    exit 1
fi

source .venv/bin/activate

echo ""
echo "✅  Starting LeadPulse at http://127.0.0.1:8000"
echo "   Press Ctrl+C to stop."
echo ""

python -m uvicorn dashboard.app:app --host 127.0.0.1 --port 8000
