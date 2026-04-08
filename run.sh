#!/usr/bin/env bash
# Mac/Linux: same idea as run.bat — starts Streamlit from the project folder.
set -euo pipefail
cd "$(dirname "$0")"
# Non-TTY / automation: skip first-run email prompt (see streamlit check_credentials).
ST_RUN=(run app.py --server.headless true)
if [[ -x .venv/bin/python ]] && .venv/bin/python -c "import streamlit" 2>/dev/null; then
  exec .venv/bin/python -m streamlit "${ST_RUN[@]}"
fi
echo "No usable .venv (missing, broken, or no streamlit). Using system python3."
echo "Tip: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
exec python3 -m streamlit "${ST_RUN[@]}"
