"""
SPX jobs service API (job details).
POST with jobSeqNo and refNum → returns job details.
"""
from typing import Any

from config import SPX_JOBS_BASE_URL
from src.api_clients.base import post


def fetch_job_details(job_seq_no: str, ref_num: str) -> dict[str, Any]:
    """
    POST to service/v1/job with jobSeqNo and common.refNum.
    """
    body = {
        "jobSeqNo": job_seq_no,
        "common": {
            "refNum": ref_num,
            "locale": "en_us",
            "siteType": "external",
        },
    }
    return post(SPX_JOBS_BASE_URL, "service/v1/job", json_body=body)


def job_details_to_text(data: dict[str, Any]) -> str:
    """Format job response as string for display or KB."""
    if not data:
        return ""
    if isinstance(data.get("description"), str):
        desc = data["description"]
    else:
        desc = str(data.get("description", ""))
    title = data.get("title") or data.get("jobTitle") or ""
    if title:
        return f"Job: {title}\n\n{desc}".strip()
    return desc or str(data)


class JobClient:
    def fetch(self, job_seq_no: str, ref_num: str) -> dict[str, Any]:
        return fetch_job_details(job_seq_no, ref_num)


job_client = JobClient()
