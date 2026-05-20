"""
LLM Judge: run user-editable prompt with placeholders {TS}, {KB}, {JD};
optionally attach audio from recording URL (or {AUDIO} in custom prompts). Uses Google Gemini or an internal
Gemini-compatible gateway (REST :generateContent).
"""
import base64
import time
import uuid
from io import BytesIO
from dataclasses import dataclass
from typing import Any, Optional

import requests

from src.data_aggregation import AssembledRow


# Transient gateway / upstream failures worth retrying
_GATEWAY_RETRY_HTTP_STATUSES = frozenset({429, 502, 503, 504})


def _gateway_request_exc_retryable(exc: BaseException) -> bool:
    if isinstance(exc, requests.exceptions.Timeout):
        return True
    if isinstance(exc, requests.exceptions.ConnectionError):
        return True
    if isinstance(exc, requests.exceptions.ChunkedEncodingError):
        return True
    return False


# Default template; user can edit in UI. Placeholders: {TS}, {KB}, {JD}
DEFAULT_JUDGE_TEMPLATE = """You are an expert evaluator for screening calls. Use the transcript (and optionally the attached audio) plus the knowledge base and job description to assess the call.

## Knowledge base (screening requirements)
{KB}

## Job description
{JD}

## Call transcript
{TS}

Evaluate this screening call. Provide: (1) Issue category (short label), (2) Brief comments on strengths and issues, (3) Pass/Fail or severity. Be concise and consistent with human reviewer style."""


def fill_prompt(
    template: str,
    transcript: str,
    knowledge_base: str,
    job_description: str,
    include_transcript: bool = True,
    include_kb: bool = True,
    include_jd: bool = True,
    *,
    recording_url: str = "",
    include_audio_placeholder: bool = False,
) -> str:
    """Replace {TS}, {KB}, {JD}, and optionally {AUDIO} when present in the template."""
    ts = (transcript or "(No transcript)") if include_transcript else "(not included)"
    kb = (knowledge_base or "(No knowledge base)") if include_kb else "(not included)"
    jd = (job_description or "(No job description)") if include_jd else "(not included)"
    out = (
        template.replace("{TS}", ts)
        .replace("{KB}", kb)
        .replace("{JD}", jd)
    )
    if "{AUDIO}" in template:
        if not include_audio_placeholder:
            au = "(not included)"
        elif (recording_url or "").strip():
            au = (recording_url or "").strip()
        else:
            au = "(recording URL not available)"
        out = out.replace("{AUDIO}", au)
    return out


def fetch_audio_bytes(recording_url: str, timeout: int = 60) -> Optional[bytes]:
    """Fetch audio from recording URL; return bytes or None."""
    if not recording_url or not recording_url.strip():
        return None
    try:
        r = requests.get(recording_url, timeout=timeout)
        r.raise_for_status()
        return r.content
    except Exception:
        return None


@dataclass
class JudgeResult:
    row_number: int
    call_id: str
    raw_output: str
    error: Optional[str] = None


def judge_skip_reason(
    assembled: AssembledRow,
    *,
    include_transcript: bool,
    include_kb: bool,
    include_jd: bool,
    include_audio: bool,
) -> Optional[str]:
    """
    Skip the judge only when **every** included context dimension has no usable data.
    If at least one included checkbox has retrieved data, the judge runs (partial fetch is OK).
    """
    checks: list[tuple[str, bool]] = []
    if include_transcript:
        checks.append(("transcript", bool((assembled.transcript or "").strip())))
    if include_kb:
        checks.append(("knowledge base", bool((assembled.knowledge_base or "").strip())))
    if include_jd:
        checks.append(("job description", bool((assembled.job_details_text or "").strip())))
    if include_audio:
        checks.append(("audio (recording URL)", bool((assembled.recording_url or "").strip())))

    if not checks:
        return None

    if any(ok for _, ok in checks):
        return None

    labels = ", ".join(label for label, _ in checks)
    msg = (
        f"Judge skipped — every included source was empty ({labels}). "
        "Include at least one source that returned data, or turn off unused includes."
    )
    if assembled.error:
        msg = f"{msg} Fetch details: {assembled.error}"
    return msg


def _prepend_implicit_cache_breaker(prompt_text: str, assembled: AssembledRow) -> str:
    """
    Gemini 2.5+ enables implicit context caching on similar input prefixes within a short window
    (see https://ai.google.dev/gemini-api/docs/caching). There is no public API to disable it;
    leading each request with a unique prefix reduces cross-request prefix overlap.
    """
    nonce = uuid.uuid4().hex
    return (
        f"[One-off screening evaluation | nonce:{nonce} | csv_row:{assembled.row_number} | "
        f"call:{assembled.call_id}]\n\n"
        f"{prompt_text}"
    )


def _text_from_gemini_rest_response(data: dict[str, Any]) -> str:
    """Parse Google-style generateContent JSON body; raise ValueError on top-level API error."""
    err = data.get("error")
    if isinstance(err, dict):
        msg = err.get("message") or str(err)
        raise ValueError(msg)
    cands = data.get("candidates") or []
    if not cands:
        pf = data.get("promptFeedback")
        if isinstance(pf, dict) and pf.get("blockReason"):
            raise ValueError(f"Prompt blocked: {pf.get('blockReason')}")
        return ""
    parts = (((cands[0] or {}).get("content") or {}).get("parts")) or []
    texts: list[str] = []
    for p in parts:
        if isinstance(p, dict) and p.get("text"):
            texts.append(str(p["text"]))
    return "\n".join(t.strip() for t in texts if t).strip()


def _gateway_post_generate(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    max_retries: int,
) -> tuple[Optional[requests.Response], str]:
    """
    POST :generateContent with retries. Returns (response, "") when response.ok;
    on failure returns (last non-OK response or None, human-readable error).
    """
    last_exc: Optional[str] = None
    r: Optional[requests.Response] = None
    last_body_snip = ""
    for attempt in range(max_retries + 1):
        try:
            r = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=180,
            )
        except requests.exceptions.RequestException as e:
            last_exc = str(e)
            if attempt < max_retries and _gateway_request_exc_retryable(e):
                time.sleep(min(45.0, 1.5 * (2**attempt)))
                continue
            return None, f"Gemini gateway request failed: {last_exc} (after {attempt + 1} attempt(s))."
        if r.ok:
            return r, ""
        try:
            err_json = r.json()
        except Exception:
            err_json = {}
        err_obj = err_json.get("error") if isinstance(err_json, dict) else None
        if isinstance(err_obj, dict):
            last_body_snip = str(err_obj.get("message") or err_obj)[:2000]
        else:
            last_body_snip = (r.text[:2000] if r.text else "") or f"HTTP {r.status_code}"
        if r.status_code in _GATEWAY_RETRY_HTTP_STATUSES and attempt < max_retries:
            time.sleep(min(45.0, 1.5 * (2**attempt)))
            continue
        msg = last_body_snip or f"HTTP {r.status_code}"
        hint = ""
        if r.status_code == 502:
            hint = (
                " Internal gateways often return 502 when the JSON body is very large (e.g. base64 audio), "
                "the upstream times out, or the proxy is overloaded — switching to your org base URL does not "
                "remove those limits. The app can retry without audio (see below) or set GEMINI_GATEWAY_SEND_AUDIO=0."
            )
        err = (
            f"Gemini gateway HTTP {r.status_code}: {msg}"
            + (f" ({attempt + 1} attempts)" if attempt else "")
            + hint
        )
        return r, err
    return None, "Gemini gateway: unexpected retry loop exit."


def _judge_result_from_ok_gateway_response(
    assembled: AssembledRow,
    r: requests.Response,
    *,
    raw_prefix: str = "",
) -> JudgeResult:
    try:
        data = r.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        return JudgeResult(
            row_number=assembled.row_number,
            call_id=assembled.call_id,
            raw_output="",
            error="Gemini gateway returned a non-JSON response.",
        )
    try:
        raw = _text_from_gemini_rest_response(data)
    except ValueError as e:
        return JudgeResult(
            row_number=assembled.row_number,
            call_id=assembled.call_id,
            raw_output="",
            error=str(e),
        )
    out = (raw_prefix + raw).strip()
    return JudgeResult(
        row_number=assembled.row_number,
        call_id=assembled.call_id,
        raw_output=out,
    )


def _gateway_file_data_audio_part(mime: str, rec_url: str, *, camel_case: bool) -> dict[str, Any]:
    """Gemini REST uses snake_case; some internal gateways expect camelCase."""
    if camel_case:
        return {"fileData": {"mimeType": mime, "fileUri": rec_url}}
    return {"file_data": {"mime_type": mime, "file_uri": rec_url}}


def _mime_for_gateway_recording_url(url: str) -> str:
    """Guess mime type for file_data from URL path."""
    u = (url or "").split("?", 1)[0].lower()
    if u.endswith(".mp4") or ".mp4" in u:
        return "video/mp4"
    if u.endswith(".webm"):
        return "video/webm"
    if u.endswith(".wav"):
        return "audio/wav"
    if u.endswith(".ogg") or u.endswith(".opus"):
        return "audio/ogg"
    if u.endswith(".m4a"):
        return "audio/mp4"
    if "mp4" in u:
        return "video/mp4"
    return "audio/ogg"


def _run_judge_via_gateway(
    assembled: AssembledRow,
    prompt_text: str,
    include_audio: bool,
) -> JudgeResult:
    from config import (
        gemini_gateway_audio_inline_payload,
        gemini_gateway_audio_mime_override,
        gemini_gateway_configured,
        gemini_gateway_file_data_camel_case,
        gemini_gateway_max_retries,
        gemini_gateway_send_audio,
        gemini_generate_content_url,
        get_gemini_gateway_api_key,
        gemini_judge_temperature,
    )

    if not gemini_gateway_configured():
        return JudgeResult(
            row_number=assembled.row_number,
            call_id=assembled.call_id,
            raw_output="",
            error="GEMINI_GATEWAY_BASE_URL and GEMINI_GATEWAY_API_KEY must both be set.",
        )

    url = gemini_generate_content_url()
    parts: list[dict[str, Any]] = [{"text": prompt_text}]
    audio_attached = False
    file_uri_mime: Optional[str] = None
    file_uri_rec: Optional[str] = None
    use_camel_file_data = gemini_gateway_file_data_camel_case()
    if (
        include_audio
        and assembled.recording_url
        and gemini_gateway_send_audio()
    ):
        rec_url = (assembled.recording_url or "").strip()
        if gemini_gateway_audio_inline_payload():
            audio_bytes = fetch_audio_bytes(rec_url)
            if audio_bytes:
                parts.append(
                    {
                        "inline_data": {
                            "mime_type": "audio/ogg",
                            "data": base64.standard_b64encode(audio_bytes).decode("ascii"),
                        }
                    }
                )
                audio_attached = True
        else:
            mime_ov = gemini_gateway_audio_mime_override()
            mime = mime_ov if mime_ov else _mime_for_gateway_recording_url(rec_url)
            parts.append(_gateway_file_data_audio_part(mime, rec_url, camel_case=use_camel_file_data))
            audio_attached = True
            file_uri_mime = mime
            file_uri_rec = rec_url

    gen_cfg = {"temperature": gemini_judge_temperature()}
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": gen_cfg,
    }
    headers = {
        "Authorization": f"Bearer {get_gemini_gateway_api_key()}",
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
    }
    max_retries = gemini_gateway_max_retries()

    r, err = _gateway_post_generate(url, headers, payload, max_retries)
    if r is not None and r.ok:
        return _judge_result_from_ok_gateway_response(assembled, r)

    # LiteLLM/Gemini often expects snake_case file_data; retry once with the other casing on 400.
    if (
        audio_attached
        and file_uri_mime
        and file_uri_rec
        and not gemini_gateway_audio_inline_payload()
        and r is not None
        and r.status_code == 400
    ):
        parts_alt: list[dict[str, Any]] = [
            {"text": prompt_text},
            _gateway_file_data_audio_part(
                file_uri_mime, file_uri_rec, camel_case=not use_camel_file_data
            ),
        ]
        pay_alt: dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts_alt}],
            "generationConfig": gen_cfg,
        }
        r_alt, err_alt = _gateway_post_generate(url, headers, pay_alt, min(3, max_retries + 1))
        if r_alt is not None and r_alt.ok:
            return _judge_result_from_ok_gateway_response(assembled, r_alt)
        err = f"{err} Retried with alternate file_data JSON casing: {err_alt}"

    try_text_only = False
    if audio_attached:
        if r is None:
            try_text_only = True
        elif r.status_code in (400, 502, 503, 504):
            try_text_only = True

    if try_text_only:
        payload_text = {
            "contents": [{"role": "user", "parts": [{"text": prompt_text}]}],
            "generationConfig": gen_cfg,
        }
        retry_n = min(max_retries, 3)
        r2, err2 = _gateway_post_generate(url, headers, payload_text, retry_n)
        if r2 is not None and r2.ok:
            note = (
                "[Note: The gateway failed on the request that included call media "
                "(invalid file URI/mime, casing, payload size, or upstream errors). "
                "This answer used a text-only retry — transcript/KB/JD as sent; audio/video part omitted.]\n\n"
            )
            return _judge_result_from_ok_gateway_response(assembled, r2, raw_prefix=note)
        combined = f"{err} Text-only retry also failed: {err2}"
        return JudgeResult(
            row_number=assembled.row_number,
            call_id=assembled.call_id,
            raw_output="",
            error=combined,
        )

    return JudgeResult(
        row_number=assembled.row_number,
        call_id=assembled.call_id,
        raw_output="",
        error=err,
    )


def run_judge(
    assembled: AssembledRow,
    prompt_template: str,
    include_transcript: bool = True,
    include_kb: bool = True,
    include_jd: bool = True,
    include_audio: bool = True,
) -> JudgeResult:
    """
    Call Gemini with filled prompt. Only placeholders for enabled sections are filled;
    disabled sections get "(not included)". Audio attached only if include_audio.
    """
    from config import (
        gemini_gateway_configured,
        get_gemini_api_key,
        get_gemini_gateway_base_url,
        GEMINI_JUDGE_MODEL,
    )

    prompt_text = fill_prompt(
        prompt_template,
        assembled.transcript,
        assembled.knowledge_base,
        assembled.job_details_text,
        include_transcript=include_transcript,
        include_kb=include_kb,
        include_jd=include_jd,
        recording_url=assembled.recording_url or "",
        include_audio_placeholder=include_audio,
    )

    skip = judge_skip_reason(
        assembled,
        include_transcript=include_transcript,
        include_kb=include_kb,
        include_jd=include_jd,
        include_audio=include_audio,
    )
    if skip:
        return JudgeResult(
            row_number=assembled.row_number,
            call_id=assembled.call_id,
            raw_output="",
            error=skip,
        )

    model_prompt = _prepend_implicit_cache_breaker(prompt_text, assembled)

    # If gateway host is set, use only the internal gateway (never fall back to Google — avoids quota hits).
    if get_gemini_gateway_base_url():
        if gemini_gateway_configured():
            return _run_judge_via_gateway(assembled, model_prompt, include_audio)
        return JudgeResult(
            row_number=assembled.row_number,
            call_id=assembled.call_id,
            raw_output="",
            error=(
                "GEMINI_GATEWAY_BASE_URL is set, so the judge uses **only** the internal gateway (Google "
                "`GEMINI_API_KEY` is not used). Add `GEMINI_GATEWAY_API_KEY` to `.env` with your Bearer token, "
                "or remove `GEMINI_GATEWAY_BASE_URL` if you really want the Google API."
            ),
        )

    try:
        import google.generativeai as genai

        api_key = get_gemini_api_key()
        if not api_key:
            return JudgeResult(
                row_number=assembled.row_number,
                call_id=assembled.call_id,
                raw_output="",
                error=(
                    "GEMINI_API_KEY not set. Add it to `.env` and restart, or set "
                    "`GEMINI_GATEWAY_BASE_URL` + `GEMINI_GATEWAY_API_KEY` for the internal gateway only."
                ),
            )

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(GEMINI_JUDGE_MODEL)

        parts: list = [model_prompt]

        if include_audio and assembled.recording_url:
            audio_bytes = fetch_audio_bytes(assembled.recording_url)
            if audio_bytes:
                try:
                    audio_file = genai.upload_file(
                        path=BytesIO(audio_bytes),
                        mime_type="audio/ogg",
                        display_name="screening_recording.ogg",
                    )
                    parts.append(audio_file)
                except Exception:
                    # If in-memory upload fails (e.g. SDK version), skip audio
                    pass

        response = model.generate_content(parts)
        raw = (response.text or "").strip()
        return JudgeResult(
            row_number=assembled.row_number,
            call_id=assembled.call_id,
            raw_output=raw,
        )
    except Exception as e:
        msg = str(e)
        low = msg.lower()
        if "403" in msg or "leaked" in low:
            msg = (
                f"{msg}\n\n"
                "Google treats this key as **compromised** (often because it appeared in GitHub, a screenshot, "
                "chat, or `.env.example`). **Create a new API key** in "
                "[Google AI Studio](https://aistudio.google.com/apikey), put it only in **`.env`** as "
                "`GEMINI_API_KEY=...`, restart the app, and **revoke** the old key in the Google Cloud console."
            )
        elif (
            "api_key_invalid" in low
            or ("400" in msg and "api key" in low)
            or ("expired" in low and "api key" in low)
        ):
            msg = (
                f"{msg}\n\n"
                "Google often labels this **API_KEY_INVALID** even when the key is new. Check:\n"
                "1. **Fully stop and restart** Streamlit (the app loads `.env` on startup; a running process keeps the old key).\n"
                "2. **Shell override:** if you ever ran `export GEMINI_API_KEY=...`, your terminal may still send the old value. "
                "Run `unset GEMINI_API_KEY` or start Streamlit from a fresh terminal. The project now forces `.env` to win over the shell.\n"
                "3. **Google Cloud Console** → APIs & Services → Credentials → your key → **Application restrictions**: "
                "use **None** for local Python (HTTP referrers / iOS/Android **block** server-side calls).\n"
                "4. **API restrictions**: allow **Generative Language API** (or *Don't restrict* for testing).\n"
                "5. Enable **Generative Language API** for the Google Cloud project that owns the key.\n"
                "6. `.env` line must be exactly: `GEMINI_API_KEY=AIza...` (no spaces around `=`; quotes optional)."
            )
        return JudgeResult(
            row_number=assembled.row_number,
            call_id=assembled.call_id,
            raw_output="",
            error=msg,
        )


def run_judge_one(
    assembled: AssembledRow,
    prompt_template: str,
    include_transcript: bool,
    include_kb: bool,
    include_jd: bool,
    include_audio: bool,
) -> JudgeResult:
    return run_judge(
        assembled,
        prompt_template,
        include_transcript=include_transcript,
        include_kb=include_kb,
        include_jd=include_jd,
        include_audio=include_audio,
    )


def run_judge_for_all(
    assembled_rows: list[AssembledRow],
    prompt_template: str,
    include_transcript: bool = True,
    include_kb: bool = True,
    include_jd: bool = True,
    include_audio: bool = True,
) -> list[JudgeResult]:
    return [
        run_judge(a, prompt_template, include_transcript, include_kb, include_jd, include_audio)
        for a in assembled_rows
    ]
