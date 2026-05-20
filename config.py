"""Load configuration from environment."""
import os
from pathlib import Path
from dotenv import load_dotenv

_env_dir = Path(__file__).resolve().parent
# override=True so .env wins over a stale GEMINI_API_KEY in the shell / IDE environment.
load_dotenv(_env_dir / ".env", override=True)
load_dotenv(Path.cwd() / ".env", override=True)


def _has_gemini_direct_or_gateway() -> bool:
    if (os.getenv("GEMINI_API_KEY") or "").strip():
        return True
    # Base URL alone means gateway-only mode for Run; skip .env.example fallback so we do not clobber .env.
    if (os.getenv("GEMINI_GATEWAY_BASE_URL") or "").strip():
        return True
    return bool((os.getenv("GEMINI_GATEWAY_API_KEY") or "").strip())


# Fallback: if you put your key in .env.example instead of .env, we load it here
if not _has_gemini_direct_or_gateway():
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

# Optional: internal xplus-llm-gateway (Bearer + v1beta generateContent) instead of Google AI Studio
GEMINI_GATEWAY_BASE_URL = (os.getenv("GEMINI_GATEWAY_BASE_URL") or "").strip().rstrip("/")
GEMINI_GATEWAY_API_KEY = _normalize_gemini_api_key(os.getenv("GEMINI_GATEWAY_API_KEY") or "")
GEMINI_GATEWAY_RESOURCE_PREFIX = (
    (os.getenv("GEMINI_GATEWAY_RESOURCE_PREFIX") or "v1beta/models/gemini").strip().strip("/")
)


def get_gemini_api_key() -> str:
    """Read API key at runtime so .env is respected even if config was imported early."""
    return _normalize_gemini_api_key(os.getenv("GEMINI_API_KEY") or "")


def get_gemini_gateway_api_key() -> str:
    return _normalize_gemini_api_key(os.getenv("GEMINI_GATEWAY_API_KEY") or "")


def get_gemini_gateway_base_url() -> str:
    return (os.getenv("GEMINI_GATEWAY_BASE_URL") or "").strip().rstrip("/")


def gemini_gateway_configured() -> bool:
    return bool(get_gemini_gateway_base_url() and get_gemini_gateway_api_key())


def gemini_generate_content_url() -> str:
    """Full :generateContent URL for the gateway (matches xplus-llm-gateway layout)."""
    base = get_gemini_gateway_base_url()
    model = (os.getenv("GEMINI_JUDGE_MODEL") or GEMINI_JUDGE_MODEL).strip()
    return f"{base}/{GEMINI_GATEWAY_RESOURCE_PREFIX}/{model}:generateContent"


def gemini_judge_temperature() -> float:
    raw = (os.getenv("GEMINI_JUDGE_TEMPERATURE") or "0.2").strip()
    try:
        return float(raw)
    except ValueError:
        return 0.2


def gemini_gateway_max_retries() -> int:
    """Extra attempts after the first POST for transient 502/503/504/429 and network errors (0–12)."""
    raw = (os.getenv("GEMINI_GATEWAY_MAX_RETRIES") or "4").strip()
    try:
        return max(0, min(int(raw), 12))
    except ValueError:
        return 4


def gemini_gateway_send_audio() -> bool:
    """
    When False, gateway requests are text-only (no inline audio). Many internal gateways return 502
    on very large JSON bodies; disabling audio avoids multi‑MB base64 payloads.
    """
    raw = (os.getenv("GEMINI_GATEWAY_SEND_AUDIO") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def gemini_gateway_audio_inline_payload() -> bool:
    """
    When True, gateway sends audio as base64 inline_data (downloads the file locally).
    Default False: send fileData.fileUri so the gateway/model fetches the URL (smaller JSON).
    """
    raw = (os.getenv("GEMINI_GATEWAY_AUDIO_INLINE") or "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def gemini_gateway_audio_mime_override() -> str:
    """If set (e.g. video/mp4), used as fileData.mimeType for all recording URLs instead of inferring from the path."""
    return (os.getenv("GEMINI_GATEWAY_AUDIO_MIME") or "").strip()


def gemini_gateway_file_data_camel_case() -> bool:
    """
    JSON keys for recording URL parts: False = Google REST snake_case (file_data, file_uri, mime_type)
    which LiteLLM/Gemini backends usually expect. True = camelCase (fileData, fileUri, mimeType) for
    custom gateways that require it.
    """
    raw = (os.getenv("GEMINI_GATEWAY_FILE_DATA_CASE") or "snake").strip().lower()
    return raw in ("camel", "camelcase", "jsoncamel")
