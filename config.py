"""Load configuration from environment."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

# API
XPLUS_API_BASE_URL = os.getenv("XPLUS_API_BASE_URL", "").rstrip("/")
XPLUS_API_KEY = os.getenv("XPLUS_API_KEY", "")
SPX_KB_API_BASE_URL = os.getenv("SPX_KB_API_BASE_URL", "").rstrip("/")
SPX_API_KEY = os.getenv("SPX_API_KEY", "")
SCREENING_API_BASE_URL = os.getenv("SCREENING_API_BASE_URL", "").rstrip("/")
SCREENING_API_KEY = os.getenv("SCREENING_API_KEY", "")

# LLM Judge
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
LLM_JUDGE_MODEL = os.getenv("LLM_JUDGE_MODEL", "gpt-4o-mini")
