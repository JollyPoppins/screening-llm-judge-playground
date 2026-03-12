"""
Assemble per-row payload: callId, refNum, knowledgeBase, transcript, recordingUrl,
job details, comments (HITL), issueCategory (HITL).
Uses: transcript API, get-document (KB), jobs service.
"""
from dataclasses import dataclass
from typing import Optional

from src.csv_processor import RowInput
from src.api_clients import transcript_client, kb_client, job_client, job_details_to_text


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


def assemble_row(row_input: RowInput) -> AssembledRow:
    """
    For one row: transcript API (callId + refNum), get-document (refNum), jobs (jobSeqNo + refNum).
    Merge with HITL from CSV.
    """
    try:
        transcript_resp = transcript_client.fetch(row_input.call_id, row_input.ref_num)
        transcript = transcript_resp.get("transcript", "")
        if isinstance(transcript, list):
            transcript = "\n".join(str(s) for s in transcript)
        recording_url = transcript_resp.get("recordingUrl", "")

        kb = kb_client.fetch_kb(row_input.ref_num)

        job_details_text = ""
        if row_input.job_seq_no:
            job_data = job_client.fetch(row_input.job_seq_no, row_input.ref_num)
            job_details_text = job_details_to_text(job_data)

        # Combine KB and job details for judge context
        knowledge_base = kb.strip()
        if job_details_text:
            knowledge_base = (knowledge_base + "\n\n--- Job details ---\n\n" + job_details_text).strip()

        return AssembledRow(
            row_number=row_input.row_number,
            call_id=row_input.call_id,
            ref_number=row_input.ref_num,
            knowledge_base=knowledge_base,
            transcript=transcript,
            recording_url=recording_url,
            job_details_text=job_details_text,
            hitl_comments=row_input.comments,
            hitl_issue_category=row_input.issue_categories,
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
    except Exception as e:
        return AssembledRow(
            row_number=row_input.row_number,
            call_id=row_input.call_id,
            ref_number=row_input.ref_num,
            knowledge_base="",
            transcript="",
            recording_url="",
            job_details_text="",
            hitl_comments=row_input.comments,
            hitl_issue_category=row_input.issue_categories,
            error=str(e),
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
