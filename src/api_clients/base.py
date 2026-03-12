"""Base HTTP client for API calls."""
import requests
from typing import Any, Optional


def get(
    base_url: str,
    path: str,
    params: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
    api_key: Optional[str] = None,
) -> dict[str, Any]:
    """GET request; returns JSON or raises."""
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    h = dict(headers or {})
    if api_key:
        h.setdefault("Authorization", f"Bearer {api_key}")
        h.setdefault("X-API-Key", api_key)
    r = requests.get(url, params=params, headers=h, timeout=30)
    r.raise_for_status()
    return r.json() if r.content else {}


def post(
    base_url: str,
    path: str,
    json_body: dict[str, Any],
    headers: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """POST request with JSON body; returns JSON or raises."""
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    h = dict(headers or {})
    h.setdefault("Content-Type", "application/json")
    r = requests.post(url, json=json_body, headers=h, timeout=60)
    r.raise_for_status()
    return r.json() if r.content else {}
