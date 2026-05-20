"""
LLM judge Playground — batch rows, Fetch / Run, Human vs LLM.
"""
import base64
import html
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Auto-load when no real manual upload: ~/Documents/target.csv
DOCUMENTS_TARGET_CSV = (Path.home() / "Documents" / "target.csv").resolve()

from dotenv import load_dotenv

_env_file = ROOT / ".env"
_example_file = ROOT / ".env.example"
if not _env_file.exists() and _example_file.exists():
    _env_file.write_text(_example_file.read_text(), encoding="utf-8")
load_dotenv(ROOT / ".env", override=True)
load_dotenv(Path.cwd() / ".env", override=True)
_has_gemini = (os.getenv("GEMINI_API_KEY") or "").strip() or (
    (os.getenv("GEMINI_GATEWAY_BASE_URL") or "").strip()
)
if not _has_gemini:
    load_dotenv(ROOT / ".env.example", override=True)
    load_dotenv(Path.cwd() / ".env.example", override=True)

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import config as app_config
from src.csv_processor import (
    RowInput,
    load_csv,
    parse_row_spec,
    collect_batch_row_inputs,
    COL_DATE,
    COL_CANDIDATE_NAME,
    COL_COMMENTS,
    COL_AI_RATING,
    COL_CANDIDATE_RATING,
    COL_ISSUE_CATEGORIES,
    COL_ANNOTATOR_NAME,
    COL_REVIEWED_BY,
    COL_WEEK_NUM,
    COL_MONTH,
    COL_TENANT,
    COL_SCREENING_DATE,
)
from src.region_routing import resolve_api_bases
from src.data_aggregation import assemble_row, AssembledRow
from src.llm_judge import run_judge_one, JudgeResult, fetch_audio_bytes
from src.prompt_loader import load_prompt_from_file
from src.issue_display import club_llm_issue_categories, human_issue_categories_tags_html


def _cell(row: pd.Series, col: int) -> str:
    if col >= len(row):
        return ""
    v = row.iloc[col]
    return "" if pd.isna(v) else str(v).strip()


def _cell_raw_no_strip(row: pd.Series, col: int) -> str:
    """Preserve leading/trailing space and all newlines (e.g. column D)."""
    if col >= len(row):
        return ""
    v = row.iloc[col]
    return "" if pd.isna(v) else str(v)


def _parse_judge_output_dict(raw: str) -> Optional[dict]:
    """Best-effort parse top-level JSON object from LLM output (handles fenced blocks)."""
    if not raw or not str(raw).strip():
        return None
    text = str(raw).strip()
    m = re.match(r"^```(?:json)?\s*\n?(.*)\n?```\s*$", text, re.DOTALL | re.I)
    if m:
        text = m.group(1).strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    return None


def _issues_list_from_obj(obj: dict) -> list[dict]:
    issues = obj.get("issues")
    if not isinstance(issues, list):
        return []
    return [x for x in issues if isinstance(x, dict)]


def _hitl_listings_display(raw: str) -> str:
    """One line per entry from HITL_equivalent_issue_listings (array of strings); model text often already numbered."""
    obj = _parse_judge_output_dict(raw)
    if not obj:
        return "(could not parse JSON — no HITL_equivalent_issue_listings)"
    lst = obj.get("HITL_equivalent_issue_listings")
    if lst is None:
        return "(no HITL_equivalent_issue_listings in JSON)"
    if not isinstance(lst, list):
        return "(HITL_equivalent_issue_listings is not an array)"
    if not lst:
        return "(empty list)"
    lines = [str(item).strip() for item in lst if str(item).strip()]
    return "\n".join(lines) if lines else "(empty list)"


def _category_severity_from_issues(issues: list[dict]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for item in issues:
        cat = (item.get("category") or item.get("name") or item.get("label") or "").strip()
        if not cat:
            continue
        sev = (item.get("severity") or "medium").strip().lower()
        if sev not in ("low", "medium", "high"):
            sev = "medium"
        out.append((cat, sev))
    return out


def _pretty_issue_type_tag_label(raw: str) -> str:
    """Underscores → spaces, strip stray ×n suffixes, sentence case (first letter only)."""
    s = (raw or "").replace("_", " ").strip()
    s = re.sub(r"\s*[×x]\s*\d+\s*$", "", s, flags=re.I).strip()
    if not s:
        return ""
    return s[:1].upper() + s[1:].lower()


def _issue_type_tag_pairs_from_issues(issues: list[dict]) -> list[tuple[str, str]]:
    """(display label, severity) from issue_type_tag."""
    out: list[tuple[str, str]] = []
    for item in issues:
        tag = (item.get("issue_type_tag") or "").strip()
        if not tag:
            continue
        display = _pretty_issue_type_tag_label(tag)
        if not display:
            continue
        sev = (item.get("severity") or "medium").strip().lower()
        if sev not in ("low", "medium", "high"):
            sev = "medium"
        out.append((display, sev))
    return out


def _parse_llm_issue_categories(raw: str) -> list[tuple[str, str]]:
    """(category label, severity) for badges under full output and Excel."""
    if not raw or not str(raw).strip():
        return []
    obj = _parse_judge_output_dict(raw)
    if obj:
        pairs = _category_severity_from_issues(_issues_list_from_obj(obj))
        if pairs:
            return pairs
        ic = obj.get("issueCategories")
        if isinstance(ic, list):
            ic_out: list[tuple[str, str]] = []
            for item in ic:
                if isinstance(item, str):
                    m = re.match(r"(.+?)\s*[(\[]\s*(low|medium|high)\s*[)\]]", item, re.I)
                    if m:
                        ic_out.append((m.group(1).strip(), m.group(2).lower()))
                    else:
                        ic_out.append((item.strip(), "medium"))
                elif isinstance(item, dict):
                    cat = (item.get("category") or item.get("name") or item.get("label") or "").strip()
                    if cat:
                        sev = (item.get("severity") or "medium").strip().lower()
                        if sev not in ("low", "medium", "high"):
                            sev = "medium"
                        ic_out.append((cat, sev))
            if ic_out:
                return ic_out
    text = str(raw).strip()
    out: list[tuple[str, str]] = []
    try:
        for match in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text):
            try:
                obj = json.loads(match.group())
                if isinstance(obj, dict):
                    issues = obj.get("issueCategories") or obj.get("issues") or []
                    if isinstance(issues, list):
                        for item in issues:
                            if isinstance(item, dict):
                                cat = (item.get("category") or item.get("name") or item.get("label") or "").strip()
                                sev = (item.get("severity") or "medium").strip().lower()
                                if sev not in ("low", "medium", "high"):
                                    sev = "medium"
                                if cat:
                                    out.append((cat, sev))
                            elif isinstance(item, str):
                                m = re.match(r"(.+?)\s*[(\[]\s*(low|medium|high)\s*[)\]]", item, re.I)
                                if m:
                                    out.append((m.group(1).strip(), m.group(2).lower()))
                                else:
                                    out.append((item.strip(), "medium"))
                    break
            except (json.JSONDecodeError, TypeError):
                continue
    except Exception:
        pass
    if out:
        return out
    lines = text.split("\n")
    for i, line in enumerate(lines):
        line = line.strip()
        m = re.search(r"[-*]?\s*(.+?)\s*[(\[]\s*(low|medium|high)\s*[)\]]", line, re.I)
        if m:
            out.append((m.group(1).strip(), m.group(2).lower()))
        else:
            m2 = re.search(r"(?:issue|category)\s*:?\s*(.+?)(?:\s*[.;]|\s+severity)", line, re.I)
            if m2:
                cat = m2.group(1).strip()
                sev = "medium"
                if i + 1 < len(lines):
                    next_m = re.search(r"severity\s*:?\s*(low|medium|high)", lines[i + 1], re.I)
                    if next_m:
                        sev = next_m.group(1).lower()
                out.append((cat, sev))
    return out


def _parse_llm_issue_type_tags(raw: str) -> list[tuple[str, str]]:
    """(issue_type_tag display label, severity) from structured issues[]."""
    if not raw or not str(raw).strip():
        return []
    obj = _parse_judge_output_dict(raw)
    if not obj:
        return []
    return _issue_type_tag_pairs_from_issues(_issues_list_from_obj(obj))


def _on_use_default_prompt_change() -> None:
    if st.session_state.get("cb_use_prompt_file"):
        st.session_state.judge_prompt_template = load_prompt_from_file(ROOT)
        st.session_state._file_prompt_synced = True
    else:
        st.session_state._file_prompt_synced = False


def _call_id_link_html(row_input: RowInput) -> str:
    """Call ID text linking to the screening URL when available."""
    cid = (row_input.call_id or "").strip()
    url = (row_input.raw_url or "").strip()
    if not cid:
        return "—"
    if url:
        safe_url = html.escape(url, quote=True)
        return f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer">{html.escape(cid)}</a>'
    return html.escape(cid)


def _render_csv_record_table(row: pd.Series, row_input: RowInput) -> None:
    """8-column grid: row1 A–D (each colspan 2); row2 E,F,H–M. D preserves newlines (pre)."""
    def td(colspan: int, label: str, inner_html: str, *, td_class: str = "") -> str:
        cs = f' colspan="{colspan}"' if colspan > 1 else ""
        cls = " ".join(p for p in ("csv-cell", td_class) if p).strip()
        return (
            f'<td class="{cls}"{cs}>'
            f'<div class="csv-lbl">{html.escape(label)}</div>'
            f'<div class="csv-val">{inner_html}</div></td>'
        )

    def esc_val(col_idx: int) -> str:
        v = _cell(row, col_idx)
        return html.escape(v) if v else "—"

    raw_d = _cell_raw_no_strip(row, COL_COMMENTS)
    if raw_d == "":
        inner_d = "—"
    else:
        inner_d = f'<span class="csv-val-d-pre">{html.escape(raw_d)}</span>'

    r1 = (
        "<tr>"
        + td(2, "A · Date", esc_val(COL_DATE))
        + td(2, "B · Call ID → link", _call_id_link_html(row_input))
        + td(2, "C · Candidate", esc_val(COL_CANDIDATE_NAME))
        + td(2, "D · Comments", inner_d, td_class="csv-cell-d")
        + "</tr>"
    )
    r2 = (
        "<tr>"
        + td(1, "E · AI rating", esc_val(COL_AI_RATING))
        + td(1, "F · Cand. rating", esc_val(COL_CANDIDATE_RATING))
        + td(1, "H · Annotator", esc_val(COL_ANNOTATOR_NAME))
        + td(1, "I · Reviewed by", esc_val(COL_REVIEWED_BY))
        + td(1, "J · Week", esc_val(COL_WEEK_NUM))
        + td(1, "K · Month", esc_val(COL_MONTH))
        + td(1, "L · Tenant", esc_val(COL_TENANT))
        + td(1, "M · Screen. date", esc_val(COL_SCREENING_DATE))
        + "</tr>"
    )
    table = (
        '<table class="csv-mini-table" role="grid">'
        "<colgroup>"
        + "".join('<col style="width:12.5%">' for _ in range(8))
        + "</colgroup>"
        + r1
        + r2
        + "</table>"
    )
    st.markdown(table, unsafe_allow_html=True)


def _render_llm_severity_badge_row(pairs: list[tuple[str, str]], *, empty_caption: str) -> None:
    """Severity-colored pills with ×n when (label, severity) repeats."""
    if not pairs:
        st.caption(empty_caption)
        return
    clubbed = club_llm_issue_categories(pairs)
    parts: list[str] = []
    for label, sev, n in clubbed:
        safe_sev = sev if sev in ("low", "medium", "high") else "medium"
        count_badge = f' <span class="llm-count-badge">×{n}</span>' if n > 1 else ""
        parts.append(
            f'<span class="severity-tag severity-{safe_sev}">{html.escape(label)}{count_badge}</span>'
        )
    st.markdown(" ".join(parts), unsafe_allow_html=True)


def _llm_issue_type_tags_csv(raw_output: str) -> str:
    """Unique issue type tags only (no × counts), title case, comma-separated."""
    pairs = _parse_llm_issue_type_tags(raw_output or "")
    if not pairs:
        return ""
    seen: set[str] = set()
    ordered: list[str] = []
    for label, _ in pairs:
        key = label.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(label)
    return ", ".join(ordered)


def _quote_tsv_field_for_excel(s: str) -> str:
    """Quote so Excel pastes one cell; unquoted newlines would become new rows."""
    if "\n" in s or "\r" in s or '"' in s:
        s = s.replace("\r\n", "\n").replace("\r", "\n")
        return '"' + s.replace('"', '""') + '"'
    return s


def _excel_clipboard_hitl_and_tags(llm_output_multiline: str, issue_tags_csv: str) -> str:
    """Tab-separated row: left cell may be multiline (quoted); right is comma-separated tags."""
    left = (llm_output_multiline or "").replace("\t", " ")
    left = left.replace("\r\n", "\n").replace("\r", "\n")
    right = (issue_tags_csv or "").replace("\t", " ").replace("\n", " ")
    right = " ".join(right.split())
    return _quote_tsv_field_for_excel(left) + "\t" + _quote_tsv_field_for_excel(right)


def _render_copy_to_excel_button(llm_output_multiline: str, issue_tags_csv: str, uid: str) -> None:
    """Copy LLM output + issue type tags as two Excel columns (tab-separated)."""
    safe_id = re.sub(r"[^a-zA-Z0-9_]", "_", uid)[:72]
    payload = _excel_clipboard_hitl_and_tags(llm_output_multiline, issue_tags_csv)
    b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    b64_js = json.dumps(b64)
    html_snip = f"""
<div style="display:flex;align-items:center;justify-content:flex-end;gap:10px;font-family:system-ui,-apple-system,sans-serif;">
  <button type="button" id="cp_{safe_id}" style="
    appearance:none;
    -webkit-appearance:none;
    font:inherit;
    font-size:0.8125rem;
    font-weight:600;
    letter-spacing:0.01em;
    padding:0.5rem 1rem;
    border:none;
    border-radius:10px;
    color:#fafafa;
    background:linear-gradient(165deg,#8b5cf6 0%,#6d28d9 55%,#5b21b6 100%);
    box-shadow:0 1px 2px rgba(15,23,42,0.08),0 4px 12px rgba(109,40,217,0.35);
    cursor:pointer;
    transition:transform 0.12s ease,box-shadow 0.12s ease,filter 0.12s ease;
  " onmouseover="this.style.filter='brightness(1.06)'" onmouseout="this.style.filter='none'">Copy to Excel</button>
  <span id="cpm_{safe_id}" style="font-size:0.75rem;color:#64748b;min-width:3.5rem;"></span>
</div>
<script>
(function() {{
  const b64 = {b64_js};
  const btn = document.getElementById('cp_{safe_id}');
  const msg = document.getElementById('cpm_{safe_id}');
  if (!btn) return;
  btn.addEventListener('click', async function() {{
    try {{
      const bin = atob(b64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const text = new TextDecoder('utf-8').decode(bytes);
      await navigator.clipboard.writeText(text);
      if (msg) {{ msg.textContent = 'Copied'; setTimeout(function() {{ msg.textContent = ''; }}, 2000); }}
    }} catch (e) {{
      if (msg) msg.textContent = 'Copy failed';
    }}
  }});
}})();
</script>
"""
    components.html(html_snip, height=52)


def _render_one_row_block(
    item: dict[str, Any],
    df: pd.DataFrame,
    suffix: str,
    *,
    compact: bool = False,
) -> None:
    """Transcript section through Human vs LLM for one batch row."""
    rn = item["row_number"]
    row_input = item["row_input"]
    assembled: Optional[AssembledRow] = item.get("assembled")
    judge_result: Optional[JudgeResult] = item.get("judge_result")

    st.markdown(f"### Row **{rn}**")

    if not assembled:
        st.info("Fetch this batch to load transcript, KB, and job data for this row.")
        return

    show_bulk = not compact

    if row_input and show_bulk:
        from_link = (row_input.selected_env or "").strip()
        from_env = (app_config.TRANSCRIPT_SELECTED_ENV or "").strip()
        effective_env = from_link or from_env
        rb = resolve_api_bases(from_link, from_env)
        with st.expander(f"Transcript request (row {rn})", expanded=False):
            st.markdown(
                f"- **Region bucket:** `{rb.region_key or 'defaults from .env'}`\n"
                f"- **Transcript MCS:** `{rb.transcript}`\n"
                f"- **callId:** `{row_input.call_id}`\n"
                f"- **refNum:** `{row_input.ref_num}`\n"
                f"- **selectedEnv:** `{effective_env or '—'}`\n"
            )

    if show_bulk:
        st.caption(
            f"API region: **{assembled.api_region_key}** · Transcript host: `{assembled.transcript_base_url}`"
        )

        st.markdown("**Transcript**")
        if assembled.error:
            st.warning(f"Fetch error: {assembled.error}")
        st.text_area(
            f"Transcript row {rn}",
            value=assembled.transcript or "(empty)",
            height=160,
            key=f"ta_tr_{suffix}",
        )

        st.markdown("**Knowledge base**")
        st.text_area(
            f"KB row {rn}",
            value=assembled.knowledge_base or "(empty)",
            height=120,
            key=f"ta_kb_{suffix}",
        )

        st.markdown("**Job description**")
        jd_text = assembled.job_details_text or ""
        if not jd_text.strip():
            st.text_area(
                f"JD row {rn}",
                value="(none)",
                height=80,
                key=f"ta_jd_{suffix}",
            )
            st.caption("No job description from JD needs → jobs API for this row.")
        else:
            st.text_area(
                f"JD row {rn}",
                value=jd_text,
                height=80,
                key=f"ta_jd_{suffix}",
            )

        st.markdown("**Audio**")
        if assembled.recording_url:
            audio_bytes = fetch_audio_bytes(assembled.recording_url)
            if audio_bytes:
                st.audio(audio_bytes, format="audio/ogg")
            else:
                st.audio(assembled.recording_url, format="audio/ogg")
        else:
            st.caption("(no recording URL)")

        st.markdown("---")
        st.markdown("**CSV record (A–D row 1 · E–M row 2; column G below as tags)**")
        idx = row_input.row_number - 1
        if idx >= 0 and idx < len(df):
            row = df.iloc[idx]
            _render_csv_record_table(row, row_input)

        st.markdown("**Human — issue categories (column G)**")
        st.markdown(
            human_issue_categories_tags_html(row_input.issue_categories or ""),
            unsafe_allow_html=True,
        )

        st.markdown("---")
        st.markdown("**LLM judge output**")

        if judge_result:
            if judge_result.error:
                st.error(judge_result.error)
            else:
                st.markdown(
                    '<span class="judge-label">LLM — Issue categories</span>',
                    unsafe_allow_html=True,
                )
                _render_llm_severity_badge_row(
                    _parse_llm_issue_categories(judge_result.raw_output or ""),
                    empty_caption="(no issue categories parsed from LLM output)",
                )
            st.text_area(
                f"Judge output row {rn}",
                value=judge_result.raw_output or "(empty)",
                height=220,
                key=f"ta_jo_{suffix}",
            )
        else:
            st.caption("Run or Fetch and Run to see output for this row.")
    else:
        st.caption(
            f"**Compact view** — row {rn}: fetched data, CSV, and LLM block hidden. "
            "Turn off the toggle above to show everything."
        )

    st.markdown("**Human vs LLM**")
    col_h, col_llm = st.columns(2)
    with col_h:
        st.markdown('<span class="hitl-label">Human — Comments (D)</span>', unsafe_allow_html=True)
        st.text_area(
            f"Human comments row {rn}",
            value=row_input.comments or "(none)",
            height=140,
            key=f"ta_hc_{suffix}",
        )
        st.markdown('<span class="hitl-label">Human — Issue categories (G)</span>', unsafe_allow_html=True)
        st.markdown(
            human_issue_categories_tags_html(row_input.issue_categories or ""),
            unsafe_allow_html=True,
        )
    with col_llm:
        llm_h1, llm_h2 = st.columns([4, 1])
        with llm_h1:
            st.markdown('<span class="judge-label">LLM output</span>', unsafe_allow_html=True)
        with llm_h2:
            if judge_result and not judge_result.error:
                _raw = judge_result.raw_output or ""
                _render_copy_to_excel_button(
                    _hitl_listings_display(_raw),
                    _llm_issue_type_tags_csv(_raw),
                    f"llm_out_{suffix}",
                )
        if judge_result:
            if judge_result.error:
                llm_side_text = judge_result.raw_output or "(empty)"
            else:
                llm_side_text = _hitl_listings_display(judge_result.raw_output or "")
            st.text_area(
                f"LLM text row {rn}",
                value=llm_side_text,
                height=140,
                key=f"ta_llm_{suffix}",
            )
            st.markdown(
                '<span class="judge-label">LLM — Issue type tags</span>',
                unsafe_allow_html=True,
            )
            _render_llm_severity_badge_row(
                _parse_llm_issue_type_tags(judge_result.raw_output or ""),
                empty_caption="(no issue type tags parsed from LLM output)",
            )
        else:
            st.caption("No LLM result yet for this row.")

    st.markdown("---")


def _judge_progress_html() -> Optional[str]:
    """HTML body (no outer wrapper) while incremental Run / Fetch+Run is in progress."""
    if st.session_state.get("_run_judge_active"):
        idx = int(st.session_state.get("_run_judge_idx", 0))
        items = st.session_state.get("batch_items") or []
        if items and idx < len(items):
            rn = items[idx]["row_number"]
            return (
                f"<strong>Running LLM judge</strong> — CSV row <strong>{html.escape(str(rn))}</strong> "
                f"({idx + 1} of {len(items)}). Each row appears below as soon as it finishes."
            )
    if st.session_state.get("_fr_active"):
        nums_fr = st.session_state.get("_fr_row_numbers") or []
        idx = int(st.session_state.get("_fr_idx", 0))
        if nums_fr and idx < len(nums_fr):
            rn = nums_fr[idx]
            return (
                f"<strong>Fetch and run</strong> — CSV row <strong>{html.escape(str(rn))}</strong> "
                f"({idx + 1} of {len(nums_fr)}). Each row appears below as soon as it finishes."
            )
    return None


def _render_judge_progress_banner(inner_html: str) -> None:
    """Rotating loader + status (uses global @keyframes judge-spin)."""
    st.markdown(
        '<div style="display:flex;align-items:flex-start;gap:0.65rem;padding:0.75rem 1rem;'
        "background:#e0f2fe;border-radius:0.5rem;border:1px solid #7dd3fc;color:#0c4a6e;\">"
        '<div aria-hidden="true" title="Loading" style="margin-top:2px;min-width:1.15rem;height:1.15rem;'
        "border-radius:50%;border:2.5px solid #bae6fd;border-top-color:#0284c7;"
        "animation:judge-spin 0.75s linear infinite;flex-shrink:0;\"></div>"
        f'<div style="flex:1;line-height:1.45;">{inner_html}</div></div>',
        unsafe_allow_html=True,
    )


# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="LLM judge Playground",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .main { background-color: #f8fafc; }
    h1, h2, h3 { color: #0f172a; font-family: 'Segoe UI', system-ui, sans-serif; }
    .hitl-label { color: #0ea5e9; font-weight: 600; }
    .judge-label { color: #8b5cf6; font-weight: 600; }
    .section-box { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }
    .severity-tag { display: inline-block; padding: 0.2em 0.6em; border-radius: 4px; font-size: 0.9em; font-weight: 500; margin: 0.15em 0.15em 0 0; }
    .severity-low { background-color: #dbeafe; color: #1e40af; border: 1px solid #93c5fd; }
    .severity-medium { background-color: #fef9c3; color: #854d0e; border: 1px solid #fde047; }
    .severity-high { background-color: #fee2e2; color: #b91c1c; border: 1px solid #fca5a5; }
    .llm-count-badge { font-weight: 700; margin-left: 0.15em; font-size: 0.95em; opacity: 0.9; }
    .hitl-tag { display: inline-block; background-color: #e5e7eb; color: #374151; border: 1px solid #d1d5db;
                border-radius: 4px; padding: 0.15em 0.5em; font-size: 0.88em; margin: 0.12em 0.12em 0 0; }
    .csv-mini-table { width: 100%; border-collapse: collapse; table-layout: fixed; background: #fff; margin: 0.35rem 0; border: 1px solid #94a3b8; }
    .csv-mini-table td.csv-cell { border: 1px solid #94a3b8; padding: 0.45rem 0.55rem; vertical-align: top; word-wrap: break-word; overflow-wrap: anywhere; }
    .csv-mini-table td.csv-cell-d { overflow-wrap: normal; word-wrap: normal; }
    .csv-mini-table .csv-lbl { font-size: 0.68rem; color: #475569; font-weight: 600; margin-bottom: 0.3rem; line-height: 1.2; }
    .csv-mini-table .csv-val { font-size: 0.8rem; color: #0f172a; line-height: 1.35; }
    .csv-mini-table .csv-val-d-pre { white-space: pre; display: block; overflow-x: auto; max-height: 50vh; font-family: ui-monospace, monospace; font-size: 0.78rem; }
    .csv-mini-table a { color: #2563eb; text-decoration: underline; word-break: break-all; }
    @keyframes judge-spin { to { transform: rotate(360deg); } }
</style>
""", unsafe_allow_html=True)

if "uploaded_csv" not in st.session_state:
    st.session_state.uploaded_csv = None
if "csv_path" not in st.session_state:
    st.session_state.csv_path = None
if "batch_items" not in st.session_state:
    st.session_state.batch_items = None
if "row_spec_input" not in st.session_state:
    st.session_state.row_spec_input = "1"
if "include_transcript" not in st.session_state:
    st.session_state.include_transcript = True
if "include_kb" not in st.session_state:
    st.session_state.include_kb = True
if "include_jd" not in st.session_state:
    st.session_state.include_jd = True
if "include_audio" not in st.session_state:
    st.session_state.include_audio = True
if "judge_prompt_template" not in st.session_state:
    st.session_state.judge_prompt_template = ""

hdr_l, hdr_r = st.columns([5, 2])
with hdr_l:
    st.markdown("# ⚖️ LLM judge Playground")
with hdr_r:
    st.toggle(
        "Compact row view",
        help="Hide transcript, KB, JD, audio, CSV table, issue tags, and the main LLM judge output block. Human vs LLM stays visible (Copy to Excel stays beside LLM output).",
        key="compact_row_view",
    )

with st.expander("📥 CSV upload & row selection", expanded=True):
    uploaded = st.file_uploader("Upload CSV file", type=["csv"], key="csv_upload")
    upload_bytes = b""
    if uploaded is not None:
        try:
            upload_bytes = uploaded.getvalue() or b""
        except Exception:
            upload_bytes = b""

    if len(upload_bytes) > 0:
        st.session_state.uploaded_csv = upload_bytes
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            tmp.write(upload_bytes)
            st.session_state.csv_path = Path(tmp.name)
        st.caption("Using the file uploaded above (overrides Documents **target.csv**).")
    elif DOCUMENTS_TARGET_CSV.is_file():
        st.session_state.csv_path = DOCUMENTS_TARGET_CSV
        st.caption(
            f"Using **`{DOCUMENTS_TARGET_CSV}`** — upload a file above to override."
        )
    else:
        st.session_state.csv_path = None
        st.caption(
            f"No CSV loaded. Place **`target.csv`** in Documents or upload here. "
            f"Expected path: `{DOCUMENTS_TARGET_CSV}`"
        )

    st.text_input(
        "Row number(s)",
        help="One number, comma-separated (e.g. 12,34,45), or a range (e.g. 3-7). Up to 10 rows.",
        key="row_spec_input",
    )

st.subheader("LLM judge prompt")
st.caption("Placeholders: {TS}, {KB}, {JD} — filled when the matching include checkbox is enabled.")

if "cb_use_prompt_file" not in st.session_state:
    st.session_state.cb_use_prompt_file = True
st.checkbox(
    "Use default prompt from **prompt.txt** (uncheck to write your own from scratch)",
    key="cb_use_prompt_file",
    on_change=_on_use_default_prompt_change,
)

if st.session_state.cb_use_prompt_file:
    if not st.session_state.get("_file_prompt_synced"):
        st.session_state.judge_prompt_template = load_prompt_from_file(ROOT)
        st.session_state._file_prompt_synced = True
else:
    st.session_state._file_prompt_synced = False

st.text_area(
    "Prompt text",
    height=220,
    key="judge_prompt_template",
    label_visibility="collapsed",
)

st.subheader("Context sent to the judge (all rows)")
st.caption("Applies to **Run** and **Fetch and Run** for every row in the batch.")
cx1, cx2, cx3, cx4 = st.columns(4)
with cx1:
    st.checkbox("Include **Transcript**", key="include_transcript")
with cx2:
    st.checkbox("Include **Knowledge base**", key="include_kb")
with cx3:
    st.checkbox("Include **Job description**", key="include_jd")
with cx4:
    st.checkbox("Include **Audio**", key="include_audio")

col_f, col_r, col_fr = st.columns(3)
with col_f:
    fetch_btn = st.button("Fetch", type="secondary", use_container_width=True)
with col_r:
    run_btn = st.button("Run", type="secondary", use_container_width=True)
with col_fr:
    fetch_run_btn = st.button("Fetch and Run", type="primary", use_container_width=True)

csv_path = st.session_state.csv_path
nums, spec_err = parse_row_spec(st.session_state.row_spec_input)

if fetch_btn:
    if not csv_path:
        st.error("Upload a CSV file first.")
    elif spec_err:
        st.error(spec_err)
    else:
        rows, row_errs = collect_batch_row_inputs(csv_path, nums)
        for e in row_errs:
            st.warning(e)
        if not rows:
            st.error("No valid rows to fetch.")
        else:
            st.session_state._run_judge_active = False
            st.session_state._fr_active = False
            st.session_state._fr_row_numbers = None
            st.session_state._fr_idx = 0
            items: list[dict[str, Any]] = []
            for ri in rows:
                with st.spinner(f"Fetching row {ri.row_number}…"):
                    assembled = assemble_row(ri)
                items.append(
                    {
                        "row_number": ri.row_number,
                        "row_input": ri,
                        "assembled": assembled,
                        "judge_result": None,
                    }
                )
            st.session_state.batch_items = items
            st.session_state._last_fetch_spec = st.session_state.row_spec_input.strip()
            st.success(f"Fetched {len(items)} row(s).")
            st.rerun()

if fetch_run_btn:
    if not csv_path:
        st.error("Upload a CSV file first.")
    elif spec_err:
        st.error(spec_err)
    else:
        rows, row_errs = collect_batch_row_inputs(csv_path, nums)
        for e in row_errs:
            st.warning(e)
        if not rows:
            st.error("No valid rows to fetch.")
        else:
            st.session_state._run_judge_active = False
            st.session_state._fr_row_numbers = [ri.row_number for ri in rows]
            st.session_state._fr_idx = 0
            st.session_state.batch_items = []
            st.session_state._fr_active = True
            st.session_state._last_fetch_spec = st.session_state.row_spec_input.strip()
            st.rerun()

if run_btn:
    items = st.session_state.batch_items
    if not items:
        st.error("Fetch first, then Run.")
    else:
        st.session_state._fr_active = False
        st.session_state._fr_row_numbers = None
        st.session_state._fr_idx = 0
        for it in items:
            it["judge_result"] = None
        st.session_state._run_judge_active = True
        st.session_state._run_judge_idx = 0
        st.rerun()

st.subheader("Results by row")
if msg_done := st.session_state.pop("_batch_completion_message", None):
    st.success(msg_done)
_last = (st.session_state.get("_last_fetch_spec") or "").strip()
_curr = (st.session_state.row_spec_input or "").strip()
if csv_path and st.session_state.batch_items and _last and _curr != _last:
    st.warning("Row selection changed since the last fetch. Click **Fetch** or **Fetch and Run** to refresh.")

_fr_busy = bool(st.session_state.get("_fr_active"))
_has_batch_rows = bool(st.session_state.batch_items)

if not csv_path:
    st.info("Upload a CSV, enter row number(s), then **Fetch** or **Fetch and Run**.")
elif spec_err:
    st.warning(spec_err)
elif not _has_batch_rows and not _fr_busy:
    st.info("Upload a CSV, enter row number(s), then **Fetch** or **Fetch and Run**.")
else:
    df = load_csv(csv_path)
    compact = bool(st.session_state.get("compact_row_view", False))
    if st.session_state.batch_items is None:
        st.session_state.batch_items = []
    _prog_html = _judge_progress_html()
    if _prog_html:
        _render_judge_progress_banner(_prog_html)
    for i, item in enumerate(st.session_state.batch_items):
        _render_one_row_block(
            item,
            df,
            suffix=f"{item['row_number']}_{i}",
            compact=compact,
        )
    if _prog_html:
        _render_judge_progress_banner(_prog_html)

    _ran_incremental_step = False
    if st.session_state.get("_fr_active"):
        nums_fr = st.session_state.get("_fr_row_numbers") or []
        idx = int(st.session_state.get("_fr_idx", 0))
        if nums_fr and idx < len(nums_fr) and csv_path:
            rn = nums_fr[idx]
            with st.spinner(f"Fetching and running judge for row {rn}…"):
                part_rows, _part_errs = collect_batch_row_inputs(csv_path, [rn])
                if not part_rows:
                    jr = JudgeResult(
                        row_number=rn,
                        call_id="",
                        raw_output="",
                        error="Fetch and Run: could not load this row from the CSV (check row number and file).",
                    )
                    st.session_state.batch_items = list(st.session_state.batch_items or []) + [
                        {
                            "row_number": rn,
                            "row_input": None,
                            "assembled": None,
                            "judge_result": jr,
                        }
                    ]
                else:
                    ri = part_rows[0]
                    assembled = assemble_row(ri)
                    jr = run_judge_one(
                        assembled,
                        st.session_state.judge_prompt_template,
                        include_transcript=st.session_state.include_transcript,
                        include_kb=st.session_state.include_kb,
                        include_jd=st.session_state.include_jd,
                        include_audio=st.session_state.include_audio,
                    )
                    st.session_state.batch_items = list(st.session_state.batch_items or []) + [
                        {
                            "row_number": ri.row_number,
                            "row_input": ri,
                            "assembled": assembled,
                            "judge_result": jr,
                        }
                    ]
            st.session_state._fr_idx = idx + 1
            _ran_incremental_step = True
            if st.session_state._fr_idx >= len(nums_fr):
                st.session_state._fr_active = False
                st.session_state._fr_row_numbers = None
                st.session_state._batch_completion_message = (
                    f"Fetched and ran judge for {len(nums_fr)} row(s)."
                )
        else:
            st.session_state._fr_active = False
            st.session_state._fr_row_numbers = None
    elif st.session_state.get("_run_judge_active"):
        items = st.session_state.batch_items
        idx = int(st.session_state.get("_run_judge_idx", 0))
        if items and idx < len(items):
            item = items[idx]
            rn = item["row_number"]
            with st.spinner(f"Running judge for row {rn}…"):
                a = item.get("assembled")
                ri = item.get("row_input")
                call_id = (getattr(ri, "call_id", "") or "") if ri else ""
                if not a:
                    items[idx]["judge_result"] = JudgeResult(
                        row_number=item["row_number"],
                        call_id=call_id,
                        raw_output="",
                        error="Judge skipped — nothing assembled for this row.",
                    )
                else:
                    items[idx]["judge_result"] = run_judge_one(
                        a,
                        st.session_state.judge_prompt_template,
                        include_transcript=st.session_state.include_transcript,
                        include_kb=st.session_state.include_kb,
                        include_jd=st.session_state.include_jd,
                        include_audio=st.session_state.include_audio,
                    )
            st.session_state._run_judge_idx = idx + 1
            _ran_incremental_step = True
            if st.session_state._run_judge_idx >= len(items):
                st.session_state._run_judge_active = False
                st.session_state._batch_completion_message = f"Run complete ({len(items)} row(s))."

    if _ran_incremental_step:
        st.rerun()
