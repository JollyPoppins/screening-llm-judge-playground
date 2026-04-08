"""
CSV processing for Screening LLM Judge (PRD).
Columns A–M: Date, Link, Candidate Name, Comments, AI Rating, Candidate Rating,
Issue Categories, Annotator Name, Reviewed By, Week Number, Month, Tenant, Screening Date.
Row numbers are 1-based (header = row 1).
"""
import re
from dataclasses import dataclass
from urllib.parse import unquote
from pathlib import Path
from typing import Optional

import pandas as pd


# Column indices (0-based): A=0 .. M=12
COL_DATE = 0              # A
COL_LINK = 1              # B
COL_CANDIDATE_NAME = 2    # C
COL_COMMENTS = 3          # D
COL_AI_RATING = 4         # E
COL_CANDIDATE_RATING = 5  # F
COL_ISSUE_CATEGORIES = 6  # G (comma-separated)
COL_ANNOTATOR_NAME = 7    # H
COL_REVIEWED_BY = 8       # I
COL_WEEK_NUM = 9          # J
COL_MONTH = 10            # K
COL_TENANT = 11           # L (refNum for APIs)
COL_SCREENING_DATE = 12   # M
# Optional 14th column for job API
COL_JOB_SEQ_NO = 13       # N if present


@dataclass
class RowInput:
    """Single row selected for processing."""
    row_number: int
    call_id: str
    ref_num: str
    selected_env: str  # from Link ?selectedEnv=... or .env TRANSCRIPT_SELECTED_ENV
    job_seq_no: str
    comments: str
    issue_categories: str  # Column G, comma-separated
    raw_url: str
    # Display fields from CSV
    date: str
    candidate_name: str
    ai_rating: str
    candidate_rating: str
    annotator_name: str
    reviewed_by: str
    week_num: str
    month: str
    screening_date: str


def extract_call_id_from_url(url: str) -> Optional[str]:
    """
    Extract callId from URL query string.
    Example: ...?callId=5fed10b4-56c0-4a33-a9f8-9a43e7b43d17_cid_69a836746f75187b253c78f9
    """
    if not url or not isinstance(url, str):
        return None
    match = re.search(r"[?&]callId=([^&\s]+)", url.strip())
    if not match:
        return None
    return unquote(match.group(1).strip())


def extract_selected_env_from_url(url: str) -> str:
    """
    Screening insight links often include ?selectedEnv=produs (or prodin, stg, etc.).
    The transcript service may need this inside the request body (common.selectedEnv).
    """
    if not url or not isinstance(url, str):
        return ""
    match = re.search(r"[?&]selectedEnv=([^&\s#]+)", url.strip(), re.IGNORECASE)
    return unquote(match.group(1).strip()) if match else ""


# UUID pattern (8-4-4-4-12 hex) for validating videoScreenId
_UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def extract_video_screen_id_from_call_id(call_id: str) -> Optional[str]:
    """
    Extract the UUID portion before the _cid delimiter for JD_API_Needs (videoScreenId).
    Example: d922ca89-c450-4a00-80b5-f17bea3c9186_cid_69b1b562... -> d922ca89-c450-4a00-80b5-f17bea3c9186
    Returns None if call_id is invalid or the prefix is not a valid UUID.
    """
    if not call_id or not isinstance(call_id, str):
        return None
    raw = call_id.strip()
    if "_cid" in raw:
        prefix = raw.split("_cid", 1)[0].strip()
    else:
        prefix = raw
    if not prefix or not _UUID_PATTERN.match(prefix):
        return None
    return prefix


MAX_BATCH_ROW_COUNT = 5


def parse_row_spec(value: str) -> tuple[list[int], Optional[str]]:
    """
    Parse row input: single number, comma list (12,34,45), or range (3-7).
    Returns (sorted unique row numbers, None) or ([], error message).
    """
    nums = parse_row_numbers(value or "")
    if not nums:
        return [], "Enter at least one row number (e.g. 5, or 3-7, or 12,34,45)."
    unique_sorted = sorted(set(nums))
    if len(unique_sorted) > MAX_BATCH_ROW_COUNT:
        return [], f"At most {MAX_BATCH_ROW_COUNT} rows at once (you have {len(unique_sorted)})."
    return unique_sorted, None


def parse_row_numbers(value: str) -> list[int]:
    """Parse '5,6,12' or '5-8' into list of 1-based row numbers."""
    if not value or not value.strip():
        return []
    out = []
    for part in value.replace(" ", "").split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            try:
                low, high = int(a.strip()), int(b.strip())
                out.extend(range(low, high + 1))
            except ValueError:
                continue
        else:
            try:
                out.append(int(part.strip()))
            except ValueError:
                continue
    return sorted(set(out))


def load_csv(path: Path) -> pd.DataFrame:
    """Load CSV; ensure at least 13 columns (A–M)."""
    df = pd.read_csv(path)
    min_cols = COL_SCREENING_DATE + 1  # 13
    while len(df.columns) < min_cols:
        df[f"Unnamed_{len(df.columns)}"] = ""
    return df


def get_single_row(csv_path: Path, row_number: int) -> tuple[Optional[RowInput], Optional[str]]:
    """
    Get exactly one row by 1-based row number.
    Returns (RowInput, None) on success, or (None, "Row does not exist") if row missing/invalid.
    """
    df = load_csv(csv_path)
    idx = row_number - 1
    if idx < 0 or idx >= len(df):
        return None, "Row does not exist"
    row = df.iloc[idx]
    raw_url = _cell(row, COL_LINK)
    call_id = extract_call_id_from_url(raw_url)
    ref_num = _cell(row, COL_TENANT)
    if not call_id or not ref_num:
        return None, "Row does not exist"
    job_seq_no = _cell(row, COL_JOB_SEQ_NO) if len(row) > COL_JOB_SEQ_NO else ""
    selected_env = extract_selected_env_from_url(raw_url)
    return RowInput(
        row_number=row_number,
        call_id=call_id,
        ref_num=ref_num,
        selected_env=selected_env,
        job_seq_no=job_seq_no,
        comments=_cell(row, COL_COMMENTS),
        issue_categories=_cell(row, COL_ISSUE_CATEGORIES),
        raw_url=raw_url,
        date=_cell(row, COL_DATE),
        candidate_name=_cell(row, COL_CANDIDATE_NAME),
        ai_rating=_cell(row, COL_AI_RATING),
        candidate_rating=_cell(row, COL_CANDIDATE_RATING),
        annotator_name=_cell(row, COL_ANNOTATOR_NAME),
        reviewed_by=_cell(row, COL_REVIEWED_BY),
        week_num=_cell(row, COL_WEEK_NUM),
        month=_cell(row, COL_MONTH),
        screening_date=_cell(row, COL_SCREENING_DATE),
    ), None


def collect_batch_row_inputs(csv_path: Path, row_numbers: list[int]) -> tuple[list[RowInput], list[str]]:
    """Resolve each row number; return valid RowInputs in same order as row_numbers, plus error strings."""
    errors: list[str] = []
    rows: list[RowInput] = []
    for rn in row_numbers:
        ri, err = get_single_row(csv_path, rn)
        if err:
            errors.append(f"Row {rn}: {err}")
        else:
            rows.append(ri)
    return rows, errors


def get_rows_from_csv(csv_path: Path, row_numbers: list[int]) -> list[RowInput]:
    """
    For each 1-based row number, read columns per schema. Link → callId, Tenant → refNum.
    Skips rows missing callId or refNum (Tenant).
    """
    df = load_csv(csv_path)
    results = []
    for rn in row_numbers:
        idx = rn - 1
        if idx < 0 or idx >= len(df):
            continue
        row = df.iloc[idx]
        raw_url = _cell(row, COL_LINK)
        call_id = extract_call_id_from_url(raw_url)
        ref_num = _cell(row, COL_TENANT)
        if not call_id or not ref_num:
            continue
        job_seq_no = _cell(row, COL_JOB_SEQ_NO) if COL_JOB_SEQ_NO < len(row) else ""  # no-op if COL_JOB_SEQ_NO >= 13
        selected_env = extract_selected_env_from_url(raw_url)
        results.append(RowInput(
            row_number=rn,
            call_id=call_id,
            ref_num=ref_num,
            selected_env=selected_env,
            job_seq_no=job_seq_no,
            comments=_cell(row, COL_COMMENTS),
            issue_categories=_cell(row, COL_ISSUE_CATEGORIES),
            raw_url=raw_url,
            date=_cell(row, COL_DATE),
            candidate_name=_cell(row, COL_CANDIDATE_NAME),
            ai_rating=_cell(row, COL_AI_RATING),
            candidate_rating=_cell(row, COL_CANDIDATE_RATING),
            annotator_name=_cell(row, COL_ANNOTATOR_NAME),
            reviewed_by=_cell(row, COL_REVIEWED_BY),
            week_num=_cell(row, COL_WEEK_NUM),
            month=_cell(row, COL_MONTH),
            screening_date=_cell(row, COL_SCREENING_DATE),
        ))
    return results


def _cell(row: pd.Series, col: int) -> str:
    """Safe string from row at column index."""
    if col >= len(row):
        return ""
    v = row.iloc[col]
    return "" if pd.isna(v) else str(v).strip()
