"""Load configuration from environment."""
import os
from pathlib import Path
from dotenv import load_dotenv

_env_dir = Path(__file__).resolve().parent
load_dotenv(_env_dir / ".env")
load_dotenv(Path.cwd() / ".env")  # also from current working directory (e.g. when run via streamlit)
# Fallback: if you put your key in .env.example instead of .env, we load it here
if not (os.getenv("GEMINI_API_KEY") or "").strip():
    load_dotenv(_env_dir / ".env.example")
    load_dotenv(Path.cwd() / ".env.example")

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

# JD_API_Needs: getMongoDocument (videoScreenId → jobSeqNo, locale, siteType for Job Description API)
JD_NEEDS_API_BASE_URL = os.getenv(
    "JD_NEEDS_API_BASE_URL",
    "http://mcs-campaign-execution-admin.stg.phenom.local",
).rstrip("/")

# X+ API (get jobId / jobSeqNo from callId for job details API)
XPLUS_API_BASE_URL = (os.getenv("XPLUS_API_BASE_URL") or "").strip().rstrip("/")
XPLUS_API_KEY = (os.getenv("XPLUS_API_KEY") or "").strip()

# LLM Judge (Gemini) — strip so " KEY" or "KEY " in .env still works
GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
GEMINI_JUDGE_MODEL = (os.getenv("GEMINI_JUDGE_MODEL") or "gemini-2.5-flash").strip()


def get_gemini_api_key() -> str:
    """Read API key at runtime so .env is respected even if config was imported early."""
    return (os.getenv("GEMINI_API_KEY") or "").strip()
