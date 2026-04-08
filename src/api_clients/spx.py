"""
SPX API (KB) client.
Input: jobId
Response: knowledge base (job description / screening requirements)
"""
from typing import Any

from config import SPX_KB_API_BASE_URL, SPX_API_KEY
from src.api_clients.base import get


def fetch_knowledge_base(job_id: str) -> str:
    """
    Fetch knowledge base / job description for jobId.
    Replace path and response parsing when API contract is available.
    """
    if not SPX_KB_API_BASE_URL:
        return _mock_kb(job_id)
    data = get(
        SPX_KB_API_BASE_URL,
        "kb",  # placeholder path
        params={"jobId": job_id},
        api_key=SPX_API_KEY or None,
    )
    if isinstance(data, str):
        return data
    return data.get("knowledgeBase", data.get("content", str(data)))


def _mock_kb(job_id: str) -> str:
    return (
        f"[Mock KB for jobId={job_id}]\n"
        "Job description and screening requirements will appear here once SPX API is configured."
    )


class SPXClient:
    def fetch_kb(self, job_id: str) -> str:
        return fetch_knowledge_base(job_id)


spx_client = SPXClient()
