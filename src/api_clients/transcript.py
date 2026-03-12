"""
Conversational Intelligence Transcript API.
POST with callId, refNum → returns transcript and optional recording URL.
"""
from typing import Any

from config import TRANSCRIPT_API_BASE_URL
from src.api_clients.base import post


def fetch_transcript(call_id: str, ref_num: str) -> dict[str, Any]:
    """
    POST to conversationalIntelligenceTranscript.
    Body: callId, refNum, childRefnums: [refNum], common: { refNum }
    """
    body = {
        "callId": call_id,
        "refNum": ref_num,
        "childRefnums": [ref_num],
        "common": {"refNum": ref_num},
    }
    data = post(
        TRANSCRIPT_API_BASE_URL,
        "conversationalIntelligenceTranscript",
        json_body=body,
    )
    transcript_text = _extract_transcript_text(data)
    recording_url = _extract_recording_url(data)
    return {"transcript": transcript_text, "recordingUrl": recording_url}


def _extract_transcript_text(data: dict[str, Any]) -> str:
    """Try common response shapes: transcript, segments, transcriptText, etc."""
    if not data:
        return ""
    if isinstance(data.get("transcript"), str):
        return data["transcript"]
    if isinstance(data.get("transcriptText"), str):
        return data["transcriptText"]
    segments = data.get("segments") or data.get("transcriptSegments")
    if isinstance(segments, list):
        parts = []
        for seg in segments:
            if isinstance(seg, dict):
                parts.append(seg.get("sentence") or seg.get("text") or str(seg))
            else:
                parts.append(str(seg))
        return "\n".join(parts)
    if isinstance(data.get("content"), str):
        return data["content"]
    return str(data)


def _extract_recording_url(data: dict[str, Any]) -> str:
    if not data:
        return ""
    return (
        data.get("recordingUrl")
        or data.get("recording_url")
        or data.get("recordingLocation")
        or ""
    )


class TranscriptClient:
    def fetch(self, call_id: str, ref_num: str) -> dict[str, Any]:
        return fetch_transcript(call_id, ref_num)


transcript_client = TranscriptClient()
