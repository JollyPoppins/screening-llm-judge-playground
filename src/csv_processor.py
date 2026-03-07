"""
CSV processing for Screening LLM Judge.
- Column B: URL containing callId (query param)
- Column D: Human reviewer comments (HITL)
- Column G: Human issue category (HITL)
Row numbers are 1-based (header = row 1).
"""
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd


# Column indices (0-based): B=1, D=3, G=6
COL_CALL_ID_URL = 1   # Column B
COL_COMMENTS = 3      # Column D
COL_ISSUE_CATEGORY = 6  # Column G


@dataclass
class RowInput:
    """Single row selected for processing."""
    row_number: int
    call_id: str
    comments: str
    issue_category: str
    raw_url: str


def extract_call_id_from_url(url: str) -> Optional[str]:
    """
    Extract callId from URL query string.
    Example: ...?callId=5fed10b4-56c0-4a33-a9f8-9a43e7b43d17_cid_69a836746f75187b253c78f9
    """
    if not url or not isinstance(url, str):
        return None
    match = re.search(r"[?&]callId=([^&\s]+)", url.strip())
    return match.group(1).strip() if match else None


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
    """Load CSV; normalize column count by padding if needed."""
    df = pd.read_csv(path)
    # Ensure we have at least 7 columns (A–G) for indexing
    while len(df.columns) <= COL_ISSUE_CATEGORY:
        df[f"Unnamed_{len(df.columns)}"] = ""
    return df


def get_rows_from_csv(csv_path: Path, row_numbers: list[int]) -> list[RowInput]:
    """
    For each 1-based row number, read Column B (URL), D (comments), G (issue category).
    Returns list of RowInput; row_number in RowInput is 1-based.
    """
    df = load_csv(csv_path)
    results = []
    for rn in row_numbers:
        # 1-based: row 1 = index 0 (header), row 5 = index 4
        idx = rn - 1
        if idx < 0 or idx >= len(df):
            continue
        row = df.iloc[idx]
        raw_url = _cell(row, COL_CALL_ID_URL)
        call_id = extract_call_id_from_url(raw_url)
        if not call_id:
            continue
        results.append(RowInput(
            row_number=rn,
            call_id=call_id,
            comments=_cell(row, COL_COMMENTS),
            issue_category=_cell(row, COL_ISSUE_CATEGORY),
            raw_url=raw_url,
        ))
    return results


def _cell(row: pd.Series, col: int) -> str:
    """Safe string from row at column index."""
    if col >= len(row):
        return ""
    v = row.iloc[col]
    return "" if pd.isna(v) else str(v).strip()
