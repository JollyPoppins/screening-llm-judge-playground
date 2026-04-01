"""
SPX get-document API (knowledge base).
POST with refNum → returns KB content for screening.
"""
from typing import Any

import requests

from config import SPX_TRANSFORMS_BASE_URL
from src.api_clients.base import post


def fetch_knowledge_base(ref_num: str) -> str:
    """
    POST to get-document with CRM-SCREENING / getAgentKBDetails.
    Returns empty string on 404 (no document for this refNum) so the rest of the fetch can succeed.
    """
    body = {
        "source_type": "CRM-SCREENING",
        "entity": ["company", "screening"],
        "refNum": ref_num,
        "childRefnums": [ref_num],
        "ddoKey": "getAgentKBDetails",
    }
    try:
        data = post(SPX_TRANSFORMS_BASE_URL, "get-document", json_body=body)
        return _extract_kb_text(data)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return ""
        raise


def _extract_kb_text(data: Any) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        for key in ("knowledgeBase", "content", "kbContent", "text"):
            out = data.get(key)
            if out:
                if isinstance(out, str):
                    return out
                if isinstance(out, dict):
                    return _extract_kb_text(out)
                return str(out)
        for key in ("result", "response", "body", "data"):
            if key in data and data[key]:
                return _extract_kb_text(data[key])
    return str(data)


class KBClient:
    def fetch_kb(self, ref_num: str) -> str:
        return fetch_knowledge_base(ref_num)


kb_client = KBClient()
