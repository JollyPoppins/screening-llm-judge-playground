"""
LLM Judge: run user-editable prompt with placeholders {TS}, {KB}, {JD};
optionally attach audio from recording URL. Uses Google Gemini.
"""
from io import BytesIO
from dataclasses import dataclass
from typing import Optional

import requests

from src.data_aggregation import AssembledRow


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
) -> str:
    """Replace {TS}, {KB}, {JD} only when corresponding include_* is True; else (not included)."""
    ts = (transcript or "(No transcript)") if include_transcript else "(not included)"
    kb = (knowledge_base or "(No knowledge base)") if include_kb else "(not included)"
    jd = (job_description or "(No job description)") if include_jd else "(not included)"
    return (
        template.replace("{TS}", ts)
        .replace("{KB}", kb)
        .replace("{JD}", jd)
    )


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
    try:
        import google.generativeai as genai
        from config import get_gemini_api_key, GEMINI_JUDGE_MODEL

        api_key = get_gemini_api_key()
        if not api_key:
            return JudgeResult(
                row_number=assembled.row_number,
                call_id=assembled.call_id,
                raw_output="",
                error="GEMINI_API_KEY not set. Add it to .env in the project folder and restart the app.",
            )

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(GEMINI_JUDGE_MODEL)

        prompt_text = fill_prompt(
            prompt_template,
            assembled.transcript,
            assembled.knowledge_base,
            assembled.job_details_text,
            include_transcript=include_transcript,
            include_kb=include_kb,
            include_jd=include_jd,
        )

        parts = [prompt_text]

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
        return JudgeResult(
            row_number=assembled.row_number,
            call_id=assembled.call_id,
            raw_output="",
            error=str(e),
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
