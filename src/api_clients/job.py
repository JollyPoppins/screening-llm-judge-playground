"""
SPX jobs service API (job details).
POST with jobSeqNo, refNum, locale, siteType (locale and siteType from JD_API_Needs).
"""
from typing import Any

from config import SPX_JOBS_BASE_URL
from src.api_clients.base import post


def fetch_job_details(
    job_seq_no: str,
    ref_num: str,
    locale: str = "en_us",
    site_type: str = "external",
) -> dict[str, Any]:
    """
    POST to service/v1/job with jobSeqNo and common (refNum, locale, siteType).
    locale and siteType should come from JD_API_Needs (getMongoDocument).
    """
    body = {
        "jobSeqNo": job_seq_no,
        "common": {
            "refNum": ref_num,
            "locale": locale,
            "siteType": site_type,
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
    def fetch(
        self,
        job_seq_no: str,
        ref_num: str,
        locale: str = "en_us",
        site_type: str = "external",
    ) -> dict[str, Any]:
        return fetch_job_details(job_seq_no, ref_num, locale=locale, site_type=site_type)


job_client = JobClient()
