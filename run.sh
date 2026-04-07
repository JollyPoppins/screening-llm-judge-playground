#!/usr/bin/env bash
# Mac/Linux: same idea as run.bat — starts Streamlit from the project folder.
set -euo pipefail
cd "$(dirname "$0")"
if [[ -d .venv ]]; then
  exec .venv/bin/python -m streamlit run app.py
fi
echo "No .venv in this folder. Using system python3."
echo "Tip: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
exec python3 -m streamlit run app.py
