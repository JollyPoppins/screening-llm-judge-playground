"""
Assemble per-row payload: callId, refNum, knowledgeBase, transcript, recordingUrl,
job details, comments (HITL), issueCategory (HITL).
Uses: transcript API, get-document (KB), jobs service.
"""
from dataclasses import dataclass
from typing import Optional

import requests

from src.csv_processor import RowInput, extract_video_screen_id_from_call_id
from src.api_clients import (
    transcript_client,
    kb_client,
    job_client,
    job_details_to_text,
    fetch_jd_needs,
)


@dataclass
class AssembledRow:
    """Full assembled data for one row (for judge + display)."""
    row_number: int
    call_id: str
    ref_number: str
    knowledge_base: str
    transcript: str
    recording_url: str
    job_details_text: str
    hitl_comments: str
    hitl_issue_category: str
    error: Optional[str] = None
    # CSV display fields
    candidate_name: str = ""
    ai_rating: str = ""
    candidate_rating: str = ""
    annotator: str = ""
    reviewed_by: str = ""
    date: str = ""
    week_num: str = ""
    month: str = ""
    screening_date: str = ""


def _user_friendly_fetch_error(exc: Exception) -> str:
    """Turn connection/DNS errors into a message that suggests VPN and .env."""
    msg = str(exc).lower()
    if "failed to resolve" in msg or "getaddrinfo failed" in msg or "name resolution" in msg:
        return (
            "Could not reach the API host (DNS failed). "
            "The transcript/KB/jobs URLs in .env point to internal hosts (.phenom.local). "
            "Connect to your organization VPN or update TRANSCRIPT_API_BASE_URL, "
            "SPX_TRANSFORMS_BASE_URL, and SPX_JOBS_BASE_URL in .env for your network."
        )
    if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return (
            "Could not connect to the API (connection failed or timed out). "
            "If you use internal hosts, connect to VPN or check base URLs in .env."
        )
    return str(exc)


def assemble_row(row_input: RowInput) -> AssembledRow:
    """
    For one row: transcript API (callId + refNum), get-document (refNum),
    then job description via JD_API_Needs → Job API.
    Each step is resilient: one API failure does not wipe the rest (e.g. KB 404 → empty KB, rest still returned).
    """
    errors: list[str] = []
    transcript = ""
    recording_url = ""
    kb = ""
    job_details_text = ""

    # 1. Transcript (and recording URL)
    try:
        transcript_resp = transcript_client.fetch(row_input.call_id, row_input.ref_num)
        api_err = transcript_resp.get("error")
        if api_err:
            errors.append(f"Transcript: {api_err}")
        transcript = transcript_resp.get("transcript", "")
        if isinstance(transcript, list):
            transcript = "\n".join(str(s) for s in transcript)
        recording_url = transcript_resp.get("recordingUrl", "")
    except Exception as e:
        errors.append(f"Transcript: {_user_friendly_fetch_error(e)}")

    # 2. Knowledge base (get-document; 404 is handled in kb_client and returns "")
    try:
        kb = kb_client.fetch_kb(row_input.ref_num)
        kb = (kb or "").strip()
    except Exception as e:
        errors.append(f"Knowledge base: {_user_friendly_fetch_error(e)}")

    # 3. Job description: JD_API_Needs → Job API
    video_screen_id = extract_video_screen_id_from_call_id(row_input.call_id)
    if video_screen_id:
        try:
            jd_needs = fetch_jd_needs(video_screen_id)
            if jd_needs.job_seq_no:
                job_data = job_client.fetch(
                    jd_needs.job_seq_no,
                    row_input.ref_num,
                    locale=jd_needs.locale,
                    site_type=jd_needs.site_type,
                )
                job_details_text = job_details_to_text(job_data)
        except Exception:
            job_details_text = ""

    return AssembledRow(
        row_number=row_input.row_number,
        call_id=row_input.call_id,
        ref_number=row_input.ref_num,
        knowledge_base=kb,
        transcript=transcript,
        recording_url=recording_url,
        job_details_text=job_details_text,
        hitl_comments=row_input.comments,
        hitl_issue_category=row_input.issue_categories,
        error="; ".join(errors) if errors else None,
        candidate_name=row_input.candidate_name,
        ai_rating=row_input.ai_rating,
        candidate_rating=row_input.candidate_rating,
        annotator=row_input.annotator_name,
        reviewed_by=row_input.reviewed_by,
        date=row_input.date,
        week_num=row_input.week_num,
        month=row_input.month,
        screening_date=row_input.screening_date,
    )


def assemble_all(row_inputs: list[RowInput]) -> list[AssembledRow]:
    """Assemble data for every selected row."""
    return [assemble_row(r) for r in row_inputs]
