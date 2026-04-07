"""
Pick MCS / SPX base URLs from screening Link ?selectedEnv=... (produs, prodir, stgus, stgir, etc.).
Falls back to values from config (.env) when env token is missing or unknown.

Override wrong hostnames without code changes: set PHENOM_REGION_OVERRIDES in .env to JSON, e.g.
{"prodir":{"transcript":"http://mcs-campaign-execution-admin.YOUR-IR-HOST.phenom.local"}}
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ApiBases:
    transcript: str
    spx_transforms: str
    spx_jobs: str
    jd_needs: str
    """Normalized region key used (e.g. produs, prodir) or empty if .env defaults."""
    region_key: str
    """Original selectedEnv token from URL / .env (for API body)."""
    selected_env_token: str


def _strip_urls(d: Dict[str, str]) -> Dict[str, str]:
    return {k: (v or "").strip().rstrip("/") for k, v in d.items()}


def _built_in_regions() -> Dict[str, Dict[str, str]]:
    """
    Hostname patterns — adjust via PHENOM_REGION_OVERRIDES if your DNS differs.
    produs / prodir: production US vs production IR (India) style stacks.
    stgus / stgir: staging US vs staging IR.
    """
    return {
        "produs": _strip_urls(
            {
                "transcript": "http://mcs-campaign-execution-admin.prod.phenom.local",
                "spx_transforms": "http://spx-enterprise-search-transforms.prod.phenom.local",
                "spx_jobs": "http://spx-jobs-service.prod.phenom.local",
                # Historical: JD needs often hit stg MCS even for prod US rows
                "jd_needs": "http://mcs-campaign-execution-admin.stg.phenom.local",
            }
        ),
        "prodir": _strip_urls(
            {
                "transcript": "http://mcs-campaign-execution-admin.prodir.phenom.local",
                "spx_transforms": "http://spx-enterprise-search-transforms.prodir.phenom.local",
                "spx_jobs": "http://spx-jobs-service.prodir.phenom.local",
                "jd_needs": "http://mcs-campaign-execution-admin.stgir.phenom.local",
            }
        ),
        "stgus": _strip_urls(
            {
                "transcript": "http://mcs-campaign-execution-admin.stg.phenom.local",
                "spx_transforms": "http://spx-enterprise-search-transforms.stg.phenom.local",
                "spx_jobs": "http://spx-jobs-service.stg.phenom.local",
                "jd_needs": "http://mcs-campaign-execution-admin.stg.phenom.local",
            }
        ),
        "stgir": _strip_urls(
            {
                "transcript": "http://mcs-campaign-execution-admin.stgir.phenom.local",
                "spx_transforms": "http://spx-enterprise-search-transforms.stgir.phenom.local",
                "spx_jobs": "http://spx-jobs-service.stgir.phenom.local",
                "jd_needs": "http://mcs-campaign-execution-admin.stgir.phenom.local",
            }
        ),
    }


def _merge_overrides(table: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    raw = (os.getenv("PHENOM_REGION_OVERRIDES") or "").strip()
    if not raw:
        return table
    try:
        over = json.loads(raw)
    except json.JSONDecodeError:
        return table
    if not isinstance(over, dict):
        return table
    out = {k: dict(v) for k, v in table.items()}
    for key, patch in over.items():
        if not isinstance(patch, dict):
            continue
        key_l = str(key).strip().lower()
        if key_l not in out:
            out[key_l] = {}
        for field, url in patch.items():
            if isinstance(url, str) and url.strip():
                out[key_l][str(field).strip()] = url.strip().rstrip("/")
    return out


_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_region_key(selected_env: str) -> Optional[str]:
    """
    Map UI tokens like produs, prodIR, prod-in, stgus to canonical table keys.
    Returns None if unknown / ambiguous — caller should use .env defaults.
    """
    if not selected_env or not str(selected_env).strip():
        return None
    t = _ALNUM.sub("", str(selected_env).strip().lower())
    if not t:
        return None

    direct = {"produs", "prodir", "stgus", "stgir"}
    if t in direct:
        return t

    aliases = {
        "prodin": "prodir",
        "prodireland": "prodir",
        "prodire": "prodir",
        "prodindia": "prodir",
        "irprod": "prodir",
        "usprod": "produs",
        "productionus": "produs",
        "stagingus": "stgus",
        "stagingir": "stgir",
        "stgin": "stgir",
        "stgindia": "stgir",
    }
    if t in aliases:
        return aliases[t]

    # e.g. prodIR -> prodir after alnum fold might be prodir already; produs stays
    if "prod" in t and ("ir" in t or "in" in t or "india" in t):
        return "prodir"
    if "stg" in t and ("ir" in t or "in" in t or "india" in t):
        return "stgir"
    if t.startswith("stg") and "us" in t:
        return "stgus"
    if t.startswith("prod") and "us" in t:
        return "produs"

    return None


def resolve_api_bases(selected_env_from_url: str, selected_env_fallback: str = "") -> ApiBases:
    """
    Resolve MCS/SPX hosts for this row. Uses selectedEnv from Link; if empty, TRANSCRIPT_SELECTED_ENV from config.
    If still no match, uses static URLs from config (.env).
    """
    import config as cfg

    token = (selected_env_from_url or "").strip() or (selected_env_fallback or "").strip()

    fallback_bases = ApiBases(
        transcript=cfg.TRANSCRIPT_API_BASE_URL,
        spx_transforms=cfg.SPX_TRANSFORMS_BASE_URL,
        spx_jobs=cfg.SPX_JOBS_BASE_URL,
        jd_needs=cfg.JD_NEEDS_API_BASE_URL,
        region_key="",
        selected_env_token=token,
    )

    if (os.getenv("DISABLE_REGION_URL_RESOLUTION") or "").strip().lower() in ("1", "true", "yes"):
        return fallback_bases

    key = normalize_region_key(token)
    table = _merge_overrides(_built_in_regions())

    if key is None and token:
        raw = token.strip().lower()
        if raw in table:
            key = raw

    if not key or key not in table:
        return fallback_bases

    row = table[key]
    return ApiBases(
        transcript=row.get("transcript") or fallback_bases.transcript,
        spx_transforms=row.get("spx_transforms") or fallback_bases.spx_transforms,
        spx_jobs=row.get("spx_jobs") or fallback_bases.spx_jobs,
        jd_needs=row.get("jd_needs") or fallback_bases.jd_needs,
        region_key=key,
        selected_env_token=token,
    )
