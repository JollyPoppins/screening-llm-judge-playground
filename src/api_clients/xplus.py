"""
xPlus API client.
Input: callId
Response: environment, refNumber, jobId
"""
from typing import Any

from config import XPLUS_API_BASE_URL, XPLUS_API_KEY
from src.api_clients.base import get


def fetch_by_call_id(call_id: str) -> dict[str, Any]:
    """
    Fetch xPlus data by callId.
    Replace path and request shape when API contract is available.
    """
    if not XPLUS_API_BASE_URL:
        return _mock_xplus(call_id)
    data = get(
        XPLUS_API_BASE_URL,
        "call",  # placeholder path
        params={"callId": call_id},
        api_key=XPLUS_API_KEY or None,
    )
    return {
        "environment": data.get("environment", ""),
        "refNumber": data.get("refNumber", ""),
        "jobId": data.get("jobId", ""),
    }


def _mock_xplus(call_id: str) -> dict[str, Any]:
    """Return mock when no API configured."""
    return {
        "environment": "produs",
        "refNumber": "REF-MOCK",
        "jobId": "job-mock-" + call_id[:8],
    }


# Singleton for app use
class XPlusClient:
    def fetch(self, call_id: str) -> dict[str, Any]:
        return fetch_by_call_id(call_id)


xplus_client = XPlusClient()
