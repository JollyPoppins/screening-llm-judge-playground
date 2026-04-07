"""
LLM Judge Parser Application — PRD implementation.
Single-row selection, Fetch / Run / Fetch and Run, selective context checkboxes,
tabular CSV view (A–M except D & G), expanded Comments and Issue Categories.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Load .env so GEMINI_API_KEY and API URLs are available
# The app reads from .env. If .env doesn't exist, copy .env.example → .env so your key is used.
from dotenv import load_dotenv
_env_file = ROOT / ".env"
_example_file = ROOT / ".env.example"
if not _env_file.exists() and _example_file.exists():
    _env_file.write_text(_example_file.read_text(), encoding="utf-8")
load_dotenv(ROOT / ".env", override=True)
load_dotenv(Path.cwd() / ".env", override=True)
# Fallback: if key still missing (e.g. you edited only .env.example), load from .env.example
if not (os.getenv("GEMINI_API_KEY") or "").strip():
    load_dotenv(ROOT / ".env.example", override=True)
    load_dotenv(Path.cwd() / ".env.example", override=True)

import html
import json
import re
import tempfile
from typing import Optional
import pandas as pd
import streamlit as st
from src.csv_processor import (
    load_csv,
    get_single_row,
    RowInput,
    COL_DATE,
    COL_LINK,
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
import config as app_config
from src.region_routing import resolve_api_bases
from src.data_aggregation import assemble_row, AssembledRow
from src.llm_judge import run_judge_one, JudgeResult, DEFAULT_JUDGE_TEMPLATE, fetch_audio_bytes


def _cell(row: pd.Series, col: int) -> str:
    """Safe string from row at column index."""
    if col >= len(row):
        return ""
    v = row.iloc[col]
    return "" if pd.isna(v) else str(v).strip()


def _clean_judge_output_for_display(raw: str) -> str:
    """Extract human-readable content from judge output, stripping JSON/code blocks."""
    if not raw or not raw.strip():
        return "(empty)"
    text = raw.strip()
    # Remove markdown code blocks (```json ... ``` or ``` ... ```)
    text = re.sub(r"```(?:json)?\s*\n?(.*?)\n?```", r"\1", text, flags=re.DOTALL)
    # Try to parse as JSON and pull out readable fields
    try:
        # Find first { ... } or [ ... ] that might be JSON
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
    # Fallback: strip extra newlines and return as-is (already readable)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _parse_llm_issue_categories(raw: str) -> list[tuple[str, str]]:
    """Parse (category_label, severity) from judge output. Severity: low | medium | high."""
    if not raw or not raw.strip():
        return []
    text = raw.strip()
    out: list[tuple[str, str]] = []
    # Try JSON first
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
                                # "Category (severity)" or just "Category"
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
    # Heuristic: " - Category (high)" or "Issue: X. Severity: low" or "Category: X" with next line "Severity: high"
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
                # Check next line for "Severity: X"
                if i + 1 < len(lines):
                    next_m = re.search(r"severity\s*:?\s*(low|medium|high)", lines[i + 1], re.I)
                    if next_m:
                        sev = next_m.group(1).lower()
                out.append((cat, sev))
    return out


# -----------------------------------------------------------------------------
# Page config
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="LLM Judge Parser Application",
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
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# Session state
# -----------------------------------------------------------------------------
if "uploaded_csv" not in st.session_state:
    st.session_state.uploaded_csv = None
if "csv_path" not in st.session_state:
    st.session_state.csv_path = None
if "selected_row_number" not in st.session_state:
    st.session_state.selected_row_number = None
if "row_input" not in st.session_state:
    st.session_state.row_input = None
if "assembled" not in st.session_state:
    st.session_state.assembled = None
if "assembled_row_number" not in st.session_state:
    st.session_state.assembled_row_number = None  # row number that assembled data is for
if "judge_result" not in st.session_state:
    st.session_state.judge_result = None
if "judge_prompt_template" not in st.session_state:
    st.session_state.judge_prompt_template = DEFAULT_JUDGE_TEMPLATE
if "include_transcript" not in st.session_state:
    st.session_state.include_transcript = True
if "include_kb" not in st.session_state:
    st.session_state.include_kb = True
if "include_jd" not in st.session_state:
    st.session_state.include_jd = True
if "include_audio" not in st.session_state:
    st.session_state.include_audio = True

# -----------------------------------------------------------------------------
# 1. CSV Upload & Row Selection (single row)
# -----------------------------------------------------------------------------
st.title("⚖️ LLM Judge Parser Application")

with st.expander("📥 CSV Upload & Row Selection", expanded=True):
    uploaded = st.file_uploader("Upload CSV file", type=["csv"], key="csv_upload")
    if uploaded:
        st.session_state.uploaded_csv = uploaded.getvalue()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            tmp.write(st.session_state.uploaded_csv)
            st.session_state.csv_path = Path(tmp.name)

    row_number_input = st.number_input(
        "Row number (select one record)",
        min_value=1,
        value=st.session_state.selected_row_number or 1,
        step=1,
        key="row_num_input",
    )
    st.session_state.selected_row_number = row_number_input

    # If user changed row number, clear assembled data so we don't show the previous row's data
    if st.session_state.assembled_row_number is not None and st.session_state.assembled_row_number != row_number_input:
        st.session_state.assembled = None
        st.session_state.assembled_row_number = None
        st.session_state.judge_result = None

    # Validate row exists
    row_exists = False
    row_input: Optional[RowInput] = st.session_state.row_input
    if uploaded and st.session_state.csv_path:
        row_input, err = get_single_row(st.session_state.csv_path, row_number_input)
        if err:
            st.error(err)
            st.session_state.row_input = None
            st.session_state.assembled = None
        else:
            row_exists = True
            st.session_state.row_input = row_input

    if uploaded and st.session_state.csv_path and row_exists and row_input:
        from_link = (row_input.selected_env or "").strip()
        from_env = (app_config.TRANSCRIPT_SELECTED_ENV or "").strip()
        effective_env = from_link or from_env
        rb = resolve_api_bases(from_link, from_env)
        with st.expander("Transcript request (IDs & hosts — use if debugging “conversation data not found”)", expanded=False):
            st.markdown(
                f"- **Region bucket:** `{rb.region_key or 'defaults from .env (no recognized selectedEnv)'}`\n"
                f"- **Transcript MCS:** `{rb.transcript}`\n"
                f"- **KB (SPX transforms):** `{rb.spx_transforms}`\n"
                f"- **Jobs (SPX jobs):** `{rb.spx_jobs}`\n"
                f"- **JD needs (getMongoDocument):** `{rb.jd_needs}`\n"
                f"- **callId** (from Link): `{row_input.call_id}`\n"
                f"- **refNum** (CSV column L): `{row_input.ref_num}`\n"
                f"- **selectedEnv** (API body `common`): `{effective_env or '— not set — add ?selectedEnv= to Link or set TRANSCRIPT_SELECTED_ENV in .env'}`\n"
            )
            st.caption(
                "Hosts are chosen from **selectedEnv** on the Link (prod US / prod IR / stg US / stg IR). "
                "Override bad DNS with **PHENOM_REGION_OVERRIDES** in `.env` (JSON). "
                "VPN required for `.phenom.local`."
            )

# -----------------------------------------------------------------------------
# 2. LLM Judge Prompt Section (editable)
# -----------------------------------------------------------------------------
st.subheader("LLM Judge Prompt")
st.caption("Placeholders: {TS} = Transcript, {KB} = Knowledge Base, {JD} = Job Description. Data is inserted only when the corresponding checkbox is enabled.")
prompt_template = st.text_area(
    "Edit the prompt below",
    value=st.session_state.judge_prompt_template,
    height=200,
    key="prompt_edit",
)
st.session_state.judge_prompt_template = prompt_template

# -----------------------------------------------------------------------------
# 3. Action Controls: Fetch | Run | Fetch and Run
# -----------------------------------------------------------------------------
col_f, col_r, col_fr = st.columns(3)
with col_f:
    fetch_btn = st.button("Fetch", type="secondary", use_container_width=True)
with col_r:
    run_btn = st.button("Run", type="secondary", use_container_width=True)
with col_fr:
    fetch_run_btn = st.button("Fetch and Run", type="primary", use_container_width=True)

if fetch_btn:
    if not uploaded or not st.session_state.csv_path:
        st.error("Please upload a CSV file first.")
    elif not row_exists or not st.session_state.row_input:
        st.error("Row does not exist.")
    else:
        with st.spinner("Fetching data (Transcript → KB → Job)..."):
            st.session_state.assembled = assemble_row(st.session_state.row_input)
            st.session_state.assembled_row_number = row_number_input
        st.success("Fetch complete.")
        st.rerun()

if fetch_run_btn:
    if not uploaded or not st.session_state.csv_path:
        st.error("Please upload a CSV file first.")
    elif not row_exists or not st.session_state.row_input:
        st.error("Row does not exist.")
    else:
        with st.spinner("Fetching then running LLM judge..."):
            st.session_state.assembled = assemble_row(st.session_state.row_input)
            st.session_state.assembled_row_number = row_number_input
            if st.session_state.assembled:
                st.session_state.judge_result = run_judge_one(
                    st.session_state.assembled,
                    st.session_state.judge_prompt_template,
                    include_transcript=st.session_state.include_transcript,
                    include_kb=st.session_state.include_kb,
                    include_jd=st.session_state.include_jd,
                    include_audio=st.session_state.include_audio,
                )
        st.rerun()

if run_btn:
    if not st.session_state.assembled:
        st.error("Fetch data first, then Run.")
    else:
        with st.spinner("Running LLM judge..."):
            st.session_state.judge_result = run_judge_one(
                st.session_state.assembled,
                st.session_state.judge_prompt_template,
                include_transcript=st.session_state.include_transcript,
                include_kb=st.session_state.include_kb,
                include_jd=st.session_state.include_jd,
                include_audio=st.session_state.include_audio,
            )
        st.rerun()

# Only show assembled data if it's for the currently selected row
assembled: Optional[AssembledRow] = None
if st.session_state.assembled is not None and st.session_state.assembled_row_number == row_number_input:
    assembled = st.session_state.assembled
judge_result: Optional[JudgeResult] = st.session_state.judge_result if assembled else None

# -----------------------------------------------------------------------------
# 4. Data Retrieval Output Sections (after Fetch) + Selective checkboxes
# -----------------------------------------------------------------------------
if assembled:
    st.subheader("Fetched Data (select what to send to LLM)")
    st.caption(
        f"API region: **{assembled.api_region_key}** · Transcript host: `{assembled.transcript_base_url}`"
    )

    # Checkboxes for selective context (PRD §8)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.session_state.include_transcript = st.checkbox("Include **Transcript** in judge", value=st.session_state.include_transcript, key="cb_ts")
    with c2:
        st.session_state.include_kb = st.checkbox("Include **Knowledge Base** in judge", value=st.session_state.include_kb, key="cb_kb")
    with c3:
        st.session_state.include_jd = st.checkbox("Include **Job Description** in judge", value=st.session_state.include_jd, key="cb_jd")
    with c4:
        st.session_state.include_audio = st.checkbox("Include **Audio** in judge", value=st.session_state.include_audio, key="cb_audio")

    # Transcript Section
    st.markdown("---")
    st.markdown("**Transcript Section**")
    if assembled.error:
        st.warning(f"Fetch error: {assembled.error}")
        if "conversation data not found" in assembled.error.lower():
            st.info(
                "**Fix transcript “not found” quickly:**\n"
                "1. Confirm **VPN** is on and `.env` URLs match where the call lives (**prod** vs **stg**).\n"
                "2. Add **`?selectedEnv=produs`** (or whatever the screening UI uses) to the Link, **or** set **`TRANSCRIPT_SELECTED_ENV`** in `.env`.\n"
                "3. Confirm column **L (Tenant)** matches the **refNum** for that customer/stack.\n"
                "4. Use a **fresh export** — old `callId` values may be purged.\n\n"
                "Open **“Transcript request”** above to see the exact IDs sent to the server."
            )
    st.text_area("", value=assembled.transcript or "(empty)", height=160, disabled=True, key="ta_transcript")

    # Knowledge Base Section
    st.markdown("**Knowledge Base Section**")
    st.text_area("", value=assembled.knowledge_base or "(empty)", height=120, disabled=True, key="ta_kb")

    # Job Description Section (fetched via X+ → job API per PRD; no CSV column)
    st.markdown("**Job Description Section**")
    jd_text = assembled.job_details_text or ""
    if not jd_text.strip():
        st.text_area("", value="(none)", height=80, disabled=True, key="ta_jd")
        st.caption("No job description. Fetched from X+ API (callId → jobId) then SPX job API. Configure XPLUS_API_BASE_URL if needed.")
    else:
        st.text_area("", value=jd_text, height=80, disabled=True, key="ta_jd")

    # Audio Player Section: extract recording URL from transcript API, fetch audio file, display embedded (per PRD)
    st.markdown("**Audio Player Section**")
    if assembled.recording_url:
        audio_bytes = fetch_audio_bytes(assembled.recording_url)
        if audio_bytes:
            st.audio(audio_bytes, format="audio/ogg")
        else:
            st.audio(assembled.recording_url, format="audio/ogg")
        url_display = assembled.recording_url[:90] + "..." if len(assembled.recording_url) > 90 else assembled.recording_url
        st.caption(f"Recording: {url_display}")
    else:
        st.text("(no recording URL)")
        st.caption("Transcript API returns recording link (e.g. recordingLocation). Ensure the response is parsed correctly.")

# -----------------------------------------------------------------------------
# 5. CSV Record Display: table A–M except D & G; expanded D and G
# -----------------------------------------------------------------------------
if row_input and st.session_state.csv_path:
    st.subheader("CSV Record Display")
    df = load_csv(st.session_state.csv_path)
    idx = row_input.row_number - 1
    if idx >= 0 and idx < len(df):
        row = df.iloc[idx]
        # Table: A, B, C, E, F, H, I, J, K, L, M (exclude D and G)
        table_data = {
            "Column": ["A – Date", "B – Link", "C – Candidate Name", "E – AI Rating", "F – Candidate Rating", "H – Annotator Name", "I – Reviewed By", "J – Week Number", "K – Month", "L – Tenant", "M – Screening Date"],
            "Value": [
                _cell(row, COL_DATE),
                _cell(row, COL_LINK),
                _cell(row, COL_CANDIDATE_NAME),
                _cell(row, COL_AI_RATING),
                _cell(row, COL_CANDIDATE_RATING),
                _cell(row, COL_ANNOTATOR_NAME),
                _cell(row, COL_REVIEWED_BY),
                _cell(row, COL_WEEK_NUM),
                _cell(row, COL_MONTH),
                _cell(row, COL_TENANT),
                _cell(row, COL_SCREENING_DATE),
            ],
        }
        st.table(table_data)

    st.markdown("**Comments (Column D)**")
    st.text_area("", value=row_input.comments or "(none)", height=120, disabled=True, key="ta_comments")

    st.markdown("**Issue Categories (Column G)**")
    st.text(row_input.issue_categories or "(none)")

# -----------------------------------------------------------------------------
# 6. LLM Judge Output Section
# -----------------------------------------------------------------------------
st.subheader("LLM Judge Output")
if judge_result:
    if judge_result.error:
        st.error(judge_result.error)
    st.text_area("Result", value=judge_result.raw_output or "(empty)", height=220, disabled=True, key="ta_judge_out")
else:
    st.info("Run or Fetch and Run to see the LLM judge result.")

# -----------------------------------------------------------------------------
# 7. Human vs LLM Comparison
# -----------------------------------------------------------------------------
st.subheader("Human vs LLM Comparison")
if row_input and judge_result:
    col_h, col_llm = st.columns(2)
    with col_h:
        st.markdown('<span class="hitl-label">Human — Comments (Column D)</span>', unsafe_allow_html=True)
        st.text_area("", value=row_input.comments or "(none)", height=140, disabled=True, key="comp_comments")
        st.markdown('<span class="hitl-label">Human — Issue Categories (Column G)</span>', unsafe_allow_html=True)
        st.text(row_input.issue_categories or "(none)")
    with col_llm:
        st.markdown('<span class="judge-label">LLM Judge Output</span>', unsafe_allow_html=True)
        clean_output = _clean_judge_output_for_display(judge_result.raw_output or "")
        st.text_area("", value=clean_output, height=140, disabled=True, key="comp_llm")
        st.markdown('<span class="judge-label">LLM — Issue Categories</span>', unsafe_allow_html=True)
        llm_issues = _parse_llm_issue_categories(judge_result.raw_output or "")
        if llm_issues:
            tags_html = " ".join(
                f'<span class="severity-tag severity-{sev}">{html.escape(cat)}</span>'
                for cat, sev in llm_issues
            )
            st.markdown(tags_html, unsafe_allow_html=True)
        else:
            st.caption("(no issue categories parsed from LLM output)")
else:
    st.caption("Select a row, Fetch, then Run to compare human annotations with LLM output.")