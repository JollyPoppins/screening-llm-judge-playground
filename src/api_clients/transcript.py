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
    """Try common response shapes: transcript, segments, transcriptText, etc.; also check nested data/result."""
    if not data:
        return ""
    # Prefer nested payload if present (e.g. API returns { "data": { "transcript": "..." } })
    for nest in ("data", "result", "response"):
        nested = data.get(nest)
        if isinstance(nested, dict):
            out = _transcript_from_flat(nested)
            if out:
                return out
    return _transcript_from_flat(data)


def _transcript_from_flat(obj: dict[str, Any]) -> str:
    """Extract transcript text from a flat dict."""
    if not obj:
        return ""
    if isinstance(obj.get("transcript"), str):
        return obj["transcript"]
    if isinstance(obj.get("transcriptText"), str):
        return obj["transcriptText"]
    segments = obj.get("segments") or obj.get("transcriptSegments")
    if isinstance(segments, list):
        parts = []
        for seg in segments:
            if isinstance(seg, dict):
                parts.append(seg.get("sentence") or seg.get("text") or str(seg))
            else:
                parts.append(str(seg))
        return "\n".join(parts)
    if isinstance(obj.get("content"), str):
        return obj["content"]
    return str(obj) if obj else ""


def _extract_recording_url(data: dict[str, Any]) -> str:
    """Extract recording URL from top-level or nested response (e.g. data.recordingUrl, data.data.recordingUrl)."""
    if not data:
        return ""
    for key in ("recordingUrl", "recording_url", "recordingLocation", "recordingURL"):
        val = data.get(key)
        if val and isinstance(val, str) and val.strip():
            return val.strip()
    # Nested: data.data, data.result, data.response
    for nest in ("data", "result", "response"):
        nested = data.get(nest)
        if isinstance(nested, dict):
            for key in ("recordingUrl", "recording_url", "recordingLocation", "recordingURL"):
                val = nested.get(key)
                if val and isinstance(val, str) and val.strip():
                    return val.strip()
    return ""


class TranscriptClient:
    def fetch(self, call_id: str, ref_num: str) -> dict[str, Any]:
        return fetch_transcript(call_id, ref_num)


transcript_client = TranscriptClient()
