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
if not (os.getenv("GEMINI_API_KEY") or "").strip():
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


def _clean_judge_output_for_display(raw: str) -> str:
    if not raw or not raw.strip():
        return "(empty)"
    text = raw.strip()
    text = re.sub(r"```(?:json)?\s*\n?(.*?)\n?```", r"\1", text, flags=re.DOTALL)
    try:
        for pattern in [r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", r"\[.*\]"]:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                obj = json.loads(match.group())
                if isinstance(obj, dict):
                    parts = []
                    for key in ("comments", "summary", "assessment", "evaluation", "comment", "text", "output"):
                        if key in obj and obj[key]:
                            parts.append(str(obj[key]).strip())
                    if obj.get("issueCategories") or obj.get("issues"):
                        issues = obj.get("issueCategories") or obj.get("issues")
                        if isinstance(issues, list):
                            parts.append("Issue categories: " + ", ".join(str(i) for i in issues))
                        elif isinstance(issues, str):
                            parts.append("Issue categories: " + issues)
                    if parts:
                        return "\n\n".join(parts)
                break
    except (json.JSONDecodeError, TypeError):
        pass
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _parse_llm_issue_categories(raw: str) -> list[tuple[str, str]]:
    if not raw or not raw.strip():
        return []
    text = raw.strip()
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


def _render_llm_issue_tags(raw_output: str) -> None:
    llm_issues = _parse_llm_issue_categories(raw_output or "")
    if not llm_issues:
        st.caption("(no issue categories parsed from LLM output)")
        return
    clubbed = club_llm_issue_categories(llm_issues)
    parts = []
    for cat, sev, n in clubbed:
        safe_sev = sev if sev in ("low", "medium", "high") else "medium"
        count_badge = f' <span class="llm-count-badge">×{n}</span>' if n > 1 else ""
        parts.append(
            f'<span class="severity-tag severity-{safe_sev}">{html.escape(cat)}{count_badge}</span>'
        )
    st.markdown(" ".join(parts), unsafe_allow_html=True)


def _llm_categories_plain_text(raw_output: str) -> str:
    pairs = _parse_llm_issue_categories(raw_output or "")
    if not pairs:
        return ""
    clubbed = club_llm_issue_categories(pairs)
    parts: list[str] = []
    for cat, sev, n in clubbed:
        s = f"{cat} ({sev})"
        if n > 1:
            s += f" ×{n}"
        parts.append(s)
    return "; ".join(parts)


def _excel_two_cell_line(comment: str, categories: str) -> str:
    """Single line with tab so Excel pastes into two columns."""

    def flatten(s: str) -> str:
        return " ".join((s or "").replace("\t", " ").split())

    return flatten(comment) + "\t" + flatten(categories)


def _render_excel_copy_button(comment: str, categories: str, uid: str) -> None:
    safe_id = re.sub(r"[^a-zA-Z0-9_]", "_", uid)[:72]
    payload = _excel_two_cell_line(comment, categories)
    b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    b64_js = json.dumps(b64)
    html_snip = f"""
<div>
  <button type="button" id="cp_{safe_id}" style="padding:0.2rem 0.65rem;font-size:0.85rem;cursor:pointer;border-radius:6px;border:1px solid #94a3b8;background:#f8fafc;">Copy for Excel</button>
  <span id="cpm_{safe_id}" style="margin-left:6px;font-size:0.75rem;color:#64748b;"></span>
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
    components.html(html_snip, height=48)


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
        h_llm, h_copy = st.columns([5, 1])
        with h_llm:
            st.markdown("**LLM judge output**")
        with h_copy:
            if judge_result and not judge_result.error:
                clean_for_copy = _clean_judge_output_for_display(judge_result.raw_output or "")
                cats_plain = _llm_categories_plain_text(judge_result.raw_output or "")
                _render_excel_copy_button(clean_for_copy, cats_plain, f"main_{suffix}")

        if judge_result:
            if judge_result.error:
                st.error(judge_result.error)
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
            if compact and judge_result and not judge_result.error:
                clean_for_copy = _clean_judge_output_for_display(judge_result.raw_output or "")
                cats_plain = _llm_categories_plain_text(judge_result.raw_output or "")
                _render_excel_copy_button(clean_for_copy, cats_plain, f"cmp_{suffix}")
        if judge_result:
            clean_output = _clean_judge_output_for_display(judge_result.raw_output or "")
            st.text_area(
                f"LLM text row {rn}",
                value=clean_output,
                height=140,
                key=f"ta_llm_{suffix}",
            )
            st.markdown('<span class="judge-label">LLM — Issue categories</span>', unsafe_allow_html=True)
            _render_llm_issue_tags(judge_result.raw_output or "")
        else:
            st.caption("No LLM result yet for this row.")

    st.markdown("---")


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
        help="Hide transcript, KB, JD, audio, CSV table, issue tags, and the main LLM output block. Human vs LLM stays visible (with Copy in compact mode).",
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
        help="One number, comma-separated (e.g. 12,34,45), or a range (e.g. 3-7). Up to 5 rows.",
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
            items = []
            prompt = st.session_state.judge_prompt_template
            for ri in rows:
                with st.spinner(f"Fetching row {ri.row_number}…"):
                    assembled = assemble_row(ri)
                with st.spinner(f"Running judge for row {ri.row_number}…"):
                    jr = run_judge_one(
                        assembled,
                        prompt,
                        include_transcript=st.session_state.include_transcript,
                        include_kb=st.session_state.include_kb,
                        include_jd=st.session_state.include_jd,
                        include_audio=st.session_state.include_audio,
                    )
                items.append(
                    {
                        "row_number": ri.row_number,
                        "row_input": ri,
                        "assembled": assembled,
                        "judge_result": jr,
                    }
                )
            st.session_state.batch_items = items
            st.session_state._last_fetch_spec = st.session_state.row_spec_input.strip()
            st.success(f"Fetched and ran judge for {len(items)} row(s).")
            st.rerun()

if run_btn:
    items = st.session_state.batch_items
    if not items:
        st.error("Fetch first, then Run.")
    else:
        prompt = st.session_state.judge_prompt_template
        for item in items:
            a = item.get("assembled")
            if not a:
                continue
            with st.spinner(f"Running judge for row {item['row_number']}…"):
                item["judge_result"] = run_judge_one(
                    a,
                    prompt,
                    include_transcript=st.session_state.include_transcript,
                    include_kb=st.session_state.include_kb,
                    include_jd=st.session_state.include_jd,
                    include_audio=st.session_state.include_audio,
                )
        st.session_state.batch_items = items
        st.success("Run complete.")
        st.rerun()

st.subheader("Results by row")
_last = (st.session_state.get("_last_fetch_spec") or "").strip()
_curr = (st.session_state.row_spec_input or "").strip()
if csv_path and st.session_state.batch_items and _last and _curr != _last:
    st.warning("Row selection changed since the last fetch. Click **Fetch** or **Fetch and Run** to refresh.")

if not csv_path or not st.session_state.batch_items:
    st.info("Upload a CSV, enter row number(s), then **Fetch** or **Fetch and Run**.")
elif spec_err:
    st.warning(spec_err)
else:
    df = load_csv(csv_path)
    compact = bool(st.session_state.get("compact_row_view", False))
    for i, item in enumerate(st.session_state.batch_items):
        _render_one_row_block(
            item,
            df,
            suffix=f"{item['row_number']}_{i}",
            compact=compact,
        )
