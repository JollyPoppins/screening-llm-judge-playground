"""
Optional Snowflake sink for the LLM-judge playground.

Writes one row per JudgeResult into LLM_JUDGE.SCREENING.JUDGE_RUNS via the
Snowflake REST `/api/v2/statements` endpoint, reusing the same Programmatic
Access Token configured for the Snowflake MCP server.

This module is intentionally side-effect free when Snowflake env vars are
missing — the playground keeps working without Snowflake. To enable logging
in the Streamlit app, wrap the existing `run_judge_one(...)` call with
`log_judge_run(judge_result, row_input, ...)` after it returns.

Required env vars (matching the snowflake-mcp-setup skill):
    SNOWFLAKE_ACCOUNT_URL   e.g. https://acme-prod.snowflakecomputing.com
    SNOWFLAKE_PAT_TOKEN     PAT used as Bearer for Snowflake REST
    SNOWFLAKE_WAREHOUSE     warehouse to use for the INSERT
    SNOWFLAKE_DATABASE      defaults to LLM_JUDGE
    SNOWFLAKE_SCHEMA        defaults to SCREENING
    SNOWFLAKE_ROLE          optional, role the PAT should assume
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

import requests

from src.csv_processor import RowInput
from src.llm_judge import JudgeResult


_DEFAULT_DATABASE = "LLM_JUDGE"
_DEFAULT_SCHEMA = "SCREENING"


@dataclass
class _SnowflakeConfig:
    account_url: str
    token: str
    warehouse: str
    database: str
    schema: str
    role: Optional[str]


def _config() -> Optional[_SnowflakeConfig]:
    """Read env vars; return None when sink should be a no-op."""
    account = (os.getenv("SNOWFLAKE_ACCOUNT_URL") or "").strip().rstrip("/")
    token = (os.getenv("SNOWFLAKE_PAT_TOKEN") or "").strip()
    warehouse = (os.getenv("SNOWFLAKE_WAREHOUSE") or "").strip()
    if not (account and token and warehouse):
        return None
    return _SnowflakeConfig(
        account_url=account,
        token=token,
        warehouse=warehouse,
        database=(os.getenv("SNOWFLAKE_DATABASE") or _DEFAULT_DATABASE).strip(),
        schema=(os.getenv("SNOWFLAKE_SCHEMA") or _DEFAULT_SCHEMA).strip(),
        role=(os.getenv("SNOWFLAKE_ROLE") or "").strip() or None,
    )


def _prompt_version(prompt_template: str) -> str:
    """Stable short hash so prompt edits get their own bucket in analytics."""
    return hashlib.sha1((prompt_template or "").encode("utf-8")).hexdigest()[:10]


# Look for "Issue category: ..." or "Issue: ..." on the first non-empty lines.
_ISSUE_RE = re.compile(r"^\s*(?:issue\s*category|issue)\s*[:\-]\s*(.+)$", re.IGNORECASE)
# Look for "Rating: 4", "Score: 3.5", "Severity: 4/5", etc.
_RATING_RE = re.compile(
    r"\b(?:rating|score|severity)\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)(?:\s*/\s*[0-9]+)?",
    re.IGNORECASE,
)


def _parse_issue_and_rating(raw_output: str) -> tuple[Optional[str], Optional[float]]:
    """Best-effort extraction of the judge's issue label + numeric rating."""
    if not raw_output:
        return None, None
    issue: Optional[str] = None
    for line in raw_output.splitlines():
        m = _ISSUE_RE.match(line)
        if m:
            issue = m.group(1).strip().rstrip(".")
            break
    rating: Optional[float] = None
    m = _RATING_RE.search(raw_output)
    if m:
        try:
            rating = float(m.group(1))
        except ValueError:
            rating = None
    return issue, rating


def _bind(value: Any, sql_type: str = "TEXT") -> dict[str, Any]:
    """Bindings format expected by /api/v2/statements (positional, ?)."""
    if value is None:
        return {"type": sql_type, "value": None}
    if sql_type == "BOOLEAN":
        return {"type": "BOOLEAN", "value": "true" if value else "false"}
    if sql_type in ("FIXED", "REAL"):
        return {"type": sql_type, "value": str(value)}
    if sql_type == "TIMESTAMP_NTZ":
        return {"type": "TIMESTAMP_NTZ", "value": str(value)}
    return {"type": "TEXT", "value": str(value)}


def _post_statement(cfg: _SnowflakeConfig, sql: str, bindings: list[dict[str, Any]]) -> tuple[bool, str]:
    url = f"{cfg.account_url}/api/v2/statements"
    headers = {
        "Authorization": f"Bearer {cfg.token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Snowflake-Authorization-Token-Type": "PROGRAMMATIC_ACCESS_TOKEN",
    }
    body: dict[str, Any] = {
        "statement": sql,
        "warehouse": cfg.warehouse,
        "database": cfg.database,
        "schema": cfg.schema,
        "bindings": {str(i + 1): b for i, b in enumerate(bindings)},
        "timeout": 30,
    }
    if cfg.role:
        body["role"] = cfg.role
    try:
        r = requests.post(url, headers=headers, data=json.dumps(body), timeout=30)
    except requests.exceptions.RequestException as e:
        return False, f"snowflake-sink: request failed: {e}"
    if r.status_code in (200, 202):
        return True, ""
    return False, f"snowflake-sink: HTTP {r.status_code}: {r.text[:500]}"


_INSERT_SQL = """
INSERT INTO JUDGE_RUNS (
    RUN_ID, RUN_AT, CALL_ID, REF_NUM, ROW_NUMBER,
    MODEL, PROMPT_VERSION, PROMPT_TEXT,
    INCLUDE_TRANSCRIPT, INCLUDE_KB, INCLUDE_JD, INCLUDE_AUDIO,
    RAW_OUTPUT, LLM_ISSUE_CATEGORY, LLM_RATING,
    LATENCY_MS, ERROR
) SELECT
    ?, TO_TIMESTAMP_NTZ(?), ?, ?, ?,
    ?, ?, ?,
    ?, ?, ?, ?,
    ?, ?, ?,
    ?, ?
""".strip()


def log_judge_run(
    judge_result: JudgeResult,
    row_input: Optional[RowInput],
    *,
    prompt_template: str,
    model: str,
    include_transcript: bool,
    include_kb: bool,
    include_jd: bool,
    include_audio: bool,
    latency_ms: Optional[int] = None,
) -> Optional[str]:
    """
    Persist a judge run to Snowflake. Returns None on success or when the sink
    is disabled (no env vars). Returns an error string on failure — the caller
    can surface it in the UI but should not abort the judge flow.
    """
    cfg = _config()
    if cfg is None:
        return None

    issue, rating = _parse_issue_and_rating(judge_result.raw_output)
    run_at = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())

    bindings = [
        _bind(uuid.uuid4().hex, "TEXT"),
        _bind(run_at, "TIMESTAMP_NTZ"),
        _bind(judge_result.call_id, "TEXT"),
        _bind(getattr(row_input, "ref_num", "") or "", "TEXT"),
        _bind(judge_result.row_number, "FIXED"),
        _bind(model, "TEXT"),
        _bind(_prompt_version(prompt_template), "TEXT"),
        _bind(prompt_template, "TEXT"),
        _bind(include_transcript, "BOOLEAN"),
        _bind(include_kb, "BOOLEAN"),
        _bind(include_jd, "BOOLEAN"),
        _bind(include_audio, "BOOLEAN"),
        _bind(judge_result.raw_output or "", "TEXT"),
        _bind(issue, "TEXT"),
        _bind(rating, "REAL"),
        _bind(latency_ms, "FIXED"),
        _bind(judge_result.error, "TEXT"),
    ]
    ok, err = _post_statement(cfg, _INSERT_SQL, bindings)
    return None if ok else err
