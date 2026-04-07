"""
Conversational Intelligence Transcript API.
POST with callId, refNum → returns transcript and optional recording URL.
"""
from typing import Any, Optional

from config import TRANSCRIPT_SELECTED_ENV
from src.api_clients.base import post


def fetch_transcript(
    call_id: str,
    ref_num: str,
    selected_env: str = "",
    *,
    base_url: Optional[str] = None,
) -> dict[str, Any]:
    """
    POST to conversationalIntelligenceTranscript.
    Body: callId, refNum, childRefnums: [refNum], common: { refNum, selectedEnv? }
    """
    env_token = (selected_env or "").strip() or (TRANSCRIPT_SELECTED_ENV or "").strip()
    common: dict[str, Any] = {"refNum": ref_num}
    if env_token:
        common["selectedEnv"] = env_token
    body: dict[str, Any] = {
        "callId": call_id,
        "refNum": ref_num,
        "childRefnums": [ref_num],
        "common": common,
    }
    url = (base_url or "").strip().rstrip("/")
    if not url:
        from src.region_routing import resolve_api_bases

        bases = resolve_api_bases(selected_env, TRANSCRIPT_SELECTED_ENV)
        url = bases.transcript
    data = post(
        url,
        "conversationalIntelligenceTranscript",
        json_body=body,
    )
    # HTTP 200 with application-level failure (e.g. conversation missing in this env)
    if isinstance(data, dict):
        status = str(data.get("status") or "").lower()
        err_msg = data.get("errorMsg") or data.get("message")
        if status == "failure" or err_msg:
            msg = (str(err_msg).strip() if err_msg else None) or "Transcript API returned an error"
            return {"transcript": "", "recordingUrl": "", "error": msg}
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
    def fetch(
        self,
        call_id: str,
        ref_num: str,
        selected_env: str = "",
        *,
        base_url: Optional[str] = None,
    ) -> dict[str, Any]:
        return fetch_transcript(call_id, ref_num, selected_env=selected_env, base_url=base_url)


transcript_client = TranscriptClient()
