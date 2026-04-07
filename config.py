"""Load configuration from environment."""
import os
from pathlib import Path
from dotenv import load_dotenv

_env_dir = Path(__file__).resolve().parent
# override=True so .env wins over a stale GEMINI_API_KEY in the shell / IDE environment.
load_dotenv(_env_dir / ".env", override=True)
load_dotenv(Path.cwd() / ".env", override=True)
# Fallback: if you put your key in .env.example instead of .env, we load it here
if not (os.getenv("GEMINI_API_KEY") or "").strip():
    load_dotenv(_env_dir / ".env.example", override=True)
    load_dotenv(Path.cwd() / ".env.example", override=True)

# Transcript API (conversational intelligence)
TRANSCRIPT_API_BASE_URL = os.getenv(
    "TRANSCRIPT_API_BASE_URL",
    "http://mcs-campaign-execution-admin.prod.phenom.local",
).rstrip("/")
# If the CSV link has no ?selectedEnv=..., set this (e.g. produs, prodin) so transcript API can resolve the right stack.
TRANSCRIPT_SELECTED_ENV = (os.getenv("TRANSCRIPT_SELECTED_ENV") or "").strip()

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


def _normalize_gemini_api_key(raw: str) -> str:
    """Strip whitespace, optional quotes, and BOM from .env / env values."""
    s = (raw or "").strip()
    if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
        s = s[1:-1].strip()
    return s.replace("\ufeff", "").strip()


# LLM Judge (Gemini)
GEMINI_API_KEY = _normalize_gemini_api_key(os.getenv("GEMINI_API_KEY") or "")
GEMINI_JUDGE_MODEL = (os.getenv("GEMINI_JUDGE_MODEL") or "gemini-2.5-flash").strip()


def get_gemini_api_key() -> str:
    """Read API key at runtime so .env is respected even if config was imported early."""
    return _normalize_gemini_api_key(os.getenv("GEMINI_API_KEY") or "")
