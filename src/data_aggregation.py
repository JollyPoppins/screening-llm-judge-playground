"""
Assemble per-row payload: callId, environment, refNumber, jobId, knowledgeBase,
transcript, recordingUrl, comments (HITL), issueCategory (HITL).
"""
from dataclasses import dataclass, field
from typing import Optional

from src.csv_processor import RowInput
from src.api_clients.xplus import xplus_client
from src.api_clients.spx import spx_client
from src.api_clients.screening import screening_client


@dataclass
class AssembledRow:
    """Full assembled data for one row (for judge + display)."""
    row_number: int
    call_id: str
    environment: str
    ref_number: str
    job_id: str
    knowledge_base: str
    transcript: str
    recording_url: str
    hitl_comments: str
    hitl_issue_category: str
    error: Optional[str] = None


def assemble_row(row_input: RowInput) -> AssembledRow:
    """
    For one row: call xPlus(callId) -> jobId; SPX(jobId) -> KB; Screening(callId) -> transcript, recordingUrl.
    Merge with HITL from CSV (comments, issue category).
    """
    try:
        xplus = xplus_client.fetch(row_input.call_id)
        job_id = xplus.get("jobId", "")
        kb = spx_client.fetch_kb(job_id) if job_id else ""
        screening = screening_client.fetch(row_input.call_id)
        transcript = screening.get("transcript", "")
        if isinstance(transcript, list):
            transcript = "\n".join(str(s) for s in transcript)
        recording_url = screening.get("recordingUrl", "")

        return AssembledRow(
            row_number=row_input.row_number,
            call_id=row_input.call_id,
            environment=xplus.get("environment", ""),
            ref_number=xplus.get("refNumber", ""),
            job_id=job_id,
            knowledge_base=kb,
            transcript=transcript,
            recording_url=recording_url,
            hitl_comments=row_input.comments,
            hitl_issue_category=row_input.issue_category,
        )
    except Exception as e:
        return AssembledRow(
            row_number=row_input.row_number,
            call_id=row_input.call_id,
            environment="",
            ref_number="",
            job_id="",
            knowledge_base="",
            transcript="",
            recording_url="",
            hitl_comments=row_input.comments,
            hitl_issue_category=row_input.issue_category,
            error=str(e),
        )


def assemble_all(row_inputs: list[RowInput]) -> list[AssembledRow]:
    """Assemble data for every selected row."""
    return [assemble_row(r) for r in row_inputs]
