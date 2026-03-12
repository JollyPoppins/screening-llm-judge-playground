"""Load configuration from environment."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

# Transcript API (conversational intelligence)
TRANSCRIPT_API_BASE_URL = os.getenv(
    "TRANSCRIPT_API_BASE_URL",
    "http://mcs-campaign-execution-admin.prod.phenom.local",
).rstrip("/")

# SPX get-document (knowledge base)
SPX_TRANSFORMS_BASE_URL = os.getenv(
    "SPX_TRANSFORMS_BASE_URL",
    "http://spx-enterprise-search-transforms.prod.phenom.local",
).rstrip("/")

# SPX jobs (job details)
SPX_JOBS_BASE_URL = os.getenv(
    "SPX_JOBS_BASE_URL",
    "http://spx-jobs-service.prod.phenom.local",
).rstrip("/")

# LLM Judge (Gemini)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_JUDGE_MODEL = os.getenv("GEMINI_JUDGE_MODEL", "gemini-1.5-flash")
