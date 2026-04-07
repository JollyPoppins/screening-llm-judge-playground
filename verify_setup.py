#!/usr/bin/env python3
"""Check that .env / config are present for local runs (does not print secret values)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example")

import config as app_config


def mask(name: str, value: str) -> str:
    if not value:
        return "(empty)"
    if "KEY" in name.upper() or "SECRET" in name.upper() or "TOKEN" in name.upper():
        return f"set ({len(value)} chars)"
    return value[:80] + ("..." if len(value) > 80 else "")


def main() -> int:
    env_path = ROOT / ".env"
    print(f"Project: {ROOT}")
    print(f".env file: {'found' if env_path.is_file() else 'MISSING — copy .env.example to .env and edit'}")
    print()

    # Values as the running app sees them (config.py defaults apply)
    resolved = [
        ("TRANSCRIPT_API_BASE_URL", app_config.TRANSCRIPT_API_BASE_URL, True, "Transcript API"),
        ("SPX_TRANSFORMS_BASE_URL", app_config.SPX_TRANSFORMS_BASE_URL, True, "Knowledge base (SPX)"),
        ("SPX_JOBS_BASE_URL", app_config.SPX_JOBS_BASE_URL, True, "Job details (SPX jobs)"),
        ("JD_NEEDS_API_BASE_URL", app_config.JD_NEEDS_API_BASE_URL, True, "JD needs (Mongo → job seq)"),
        ("XPLUS_API_BASE_URL", app_config.XPLUS_API_BASE_URL, False, "X+ (optional)"),
        ("XPLUS_API_KEY", app_config.XPLUS_API_KEY, False, "X+ key (optional)"),
        ("GEMINI_API_KEY", app_config.GEMINI_API_KEY, False, "Gemini (needed for Run judge)"),
        ("GEMINI_JUDGE_MODEL", app_config.GEMINI_JUDGE_MODEL, True, "Gemini model"),
    ]

    ok = True
    for var, value, required, label in resolved:
        raw = (value or "").strip()
        if required and not raw:
            print(f"  [!!] {label} ({var}): MISSING")
            ok = False
        elif not raw:
            print(f"  [ ] {label} ({var}): {mask(var, raw)}")
        else:
            print(f"  [ok] {label} ({var}): {mask(var, raw)}")

    print()
    missing = []
    for mod in ("streamlit", "pandas", "requests"):
        if importlib.util.find_spec(mod) is None:
            missing.append(mod)
    if importlib.util.find_spec("google.generativeai") is None:
        missing.append("google.generativeai")
    if missing:
        print(f"Python packages: MISSING {missing} — pip install -r requirements.txt")
        ok = False
    else:
        print("Python packages: streamlit, pandas, requests, google-generativeai — OK")

    print()
    if ok and (app_config.GEMINI_API_KEY or "").strip():
        print("Ready for Fetch (internal APIs). Ready for Run if Gemini key is valid.")
    elif ok:
        print("Ready for Fetch (internal APIs). Add GEMINI_API_KEY to .env for Run.")
    else:
        print("Fix items marked [!!] above, then run again.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
