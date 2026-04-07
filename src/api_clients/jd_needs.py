"""
JD_API_Needs: getMongoDocument (videoScreenId → jobSeqNo, locale, siteType).
Must be called before the Job Description API to get required parameters.
"""
from dataclasses import dataclass
from typing import Any, Optional

from src.api_clients.base import post


@dataclass
class JDNeedsResult:
    """Result from getMongoDocument for use in Job Description API."""
    job_seq_no: str
    locale: str
    site_type: str


def fetch_jd_needs(video_screen_id: str, *, base_url: Optional[str] = None) -> JDNeedsResult:
    """
    Call getMongoDocument with videoScreenId; return jobSeqNo, locale, siteType.
    API returns Job ID which is the same as jobSeqNo.
    """
    body = {
        "query": {"videoScreenId": video_screen_id},
        "collectionName": "videoScreens",
    }
    if not (base_url or "").strip():
        raise ValueError("fetch_jd_needs requires base_url (caller must resolve region)")
    data = post(base_url.strip().rstrip("/"), "getMongoDocument", json_body=body)
    return _parse_jd_needs_response(data)


def _parse_jd_needs_response(data: dict[str, Any]) -> JDNeedsResult:
    """Extract jobSeqNo (or jobId), locale, siteType from response (top-level or nested)."""
    def from_obj(obj: Any) -> Optional[JDNeedsResult]:
        if isinstance(obj, dict):
            return _extract_from_flat(obj)
        if isinstance(obj, list) and len(obj) > 0 and isinstance(obj[0], dict):
            return _extract_from_flat(obj[0])
        return None

    for key in ("data", "result", "response"):
        val = data.get(key)
        if val is not None:
            out = from_obj(val)
            if out:
                return out
    out = _extract_from_flat(data)
    if out:
        return out
    return JDNeedsResult(job_seq_no="", locale="en_us", site_type="external")


def _extract_from_flat(obj: dict[str, Any]) -> Optional[JDNeedsResult]:
    job_seq_no = (
        obj.get("jobSeqNo") or obj.get("jobId") or obj.get("job_id") or ""
    )
    job_seq_no = str(job_seq_no).strip() if job_seq_no else ""
    locale = str(obj.get("locale") or "en_us").strip() or "en_us"
    site_type = str(obj.get("siteType") or obj.get("site_type") or "external").strip() or "external"
    if job_seq_no:
        return JDNeedsResult(job_seq_no=job_seq_no, locale=locale, site_type=site_type)
    return None
