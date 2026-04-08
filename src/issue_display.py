"""LLM issue category clubbing (by label + severity) and human issue tag HTML."""
from __future__ import annotations

import html
import re
from collections import OrderedDict


def club_llm_issue_categories(pairs: list[tuple[str, str]]) -> list[tuple[str, str, int]]:
    """
    Group identical (normalized label, severity) and return (display_label, severity, count).
    Yellow (medium) and red (high) with same title stay separate.
    """
    if not pairs:
        return []
    # Preserve first-seen display string per (norm_label, sev)
    order: list[tuple[str, str]] = []
    display_for: dict[tuple[str, str], str] = {}
    counts: dict[tuple[str, str], int] = {}

    for cat, sev in pairs:
        raw_cat = (cat or "").strip()
        sev_norm = (sev or "medium").strip().lower()
        if sev_norm not in ("low", "medium", "high"):
            sev_norm = "medium"
        key = (raw_cat.lower(), sev_norm)
        counts[key] = counts.get(key, 0) + 1
        if key not in display_for:
            display_for[key] = raw_cat
            order.append(key)

    return [(display_for[k], k[1], counts[k]) for k in order]


def human_issue_categories_tags_html(issue_categories_csv: str) -> str:
    """Comma-separated human categories as grey pill tags."""
    if not issue_categories_csv or not str(issue_categories_csv).strip():
        return '<span class="hitl-tag">(none)</span>'
    parts = [p.strip() for p in re.split(r"\s*,\s*", str(issue_categories_csv).strip()) if p.strip()]
    if not parts:
        return '<span class="hitl-tag">(none)</span>'
    return " ".join(
        f'<span class="hitl-tag">{html.escape(p)}</span>' for p in parts
    )
