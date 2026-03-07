"""
Screening API client.
Input: callId
Response: transcript, recordingUrl
"""
from typing import Any

from config import SCREENING_API_BASE_URL, SCREENING_API_KEY
from src.api_clients.base import get


def fetch_by_call_id(call_id: str) -> dict[str, Any]:
    """
    Fetch transcript and recording URL by callId.
    Replace path and response shape when API contract is available.
    """
    if not SCREENING_API_BASE_URL:
        return _mock_screening(call_id)
    data = get(
        SCREENING_API_BASE_URL,
        "screening/call",  # placeholder path
        params={"callId": call_id},
        api_key=SCREENING_API_KEY or None,
    )
    return {
        "transcript": data.get("transcript", data.get("transcriptText", "")),
        "recordingUrl": data.get("recordingUrl", data.get("recording_url", "")),
    }


def _mock_screening(call_id: str) -> dict[str, Any]:
    return {
        "transcript": f"[Mock transcript for callId={call_id[:20]}...]\nAgent: Hello.\nCandidate: Hi.",
        "recordingUrl": "",
    }


class ScreeningClient:
    def fetch(self, call_id: str) -> dict[str, Any]:
        return fetch_by_call_id(call_id)


screening_client = ScreeningClient()
