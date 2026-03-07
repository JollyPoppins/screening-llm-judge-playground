"""
Screening LLM Judge — Enterprise Evals (local).
Run: streamlit run app.py (from project root)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
from src.csv_processor import (
    parse_row_numbers,
    get_rows_from_csv,
    RowInput,
)
from src.data_aggregation import assemble_all, AssembledRow
from src.llm_judge import run_judge_for_all, JudgeResult

# -----------------------------------------------------------------------------
# Page config & enterprise styling
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Screening LLM Judge | Evals",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .main { background-color: #f8fafc; }
    h1, h2, h3 { color: #0f172a; font-family: 'Segoe UI', system-ui, sans-serif; }
    .panel {
        background: #fff;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 1rem 1.25rem;
        margin-bottom: 1rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }
    .compare-row { display: flex; gap: 1rem; margin: 0.5rem 0; }
    .compare-box {
        flex: 1;
        padding: 12px;
        border-radius: 6px;
        border: 1px solid #e2e8f0;
        background: #f8fafc;
    }
    .hitl-label { color: #0ea5e9; font-weight: 600; }
    .judge-label { color: #8b5cf6; font-weight: 600; }
    div[data-testid="stExpander"] { border-radius: 8px; }
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# Session state
# -----------------------------------------------------------------------------
if "assembled_rows" not in st.session_state:
    st.session_state.assembled_rows = []
if "judge_results" not in st.session_state:
    st.session_state.judge_results = []
if "current_csv_path" not in st.session_state:
    st.session_state.current_csv_path = None

# -----------------------------------------------------------------------------
# Input panel (always visible)
# -----------------------------------------------------------------------------
st.title("⚖️ Screening LLM Judge")
st.caption("Enterprise evals: fetch by call ID, run judge, compare with HITL.")

with st.expander("📥 Input Panel", expanded=True):
    uploaded = st.file_uploader("Upload CSV", type=["csv"], key="csv_upload")
    row_input = st.text_input(
        "Row numbers to process (e.g. 5,6,12 or 5-8)",
        placeholder="5,6,12",
        key="row_numbers",
    )
    fetch_clicked = st.button("Fetch Data", type="primary", key="fetch_btn")

if fetch_clicked:
    if not uploaded:
        st.error("Please upload a CSV file first.")
    elif not row_input.strip():
        st.error("Please enter at least one row number.")
    else:
        rows = parse_row_numbers(row_input)
        if not rows:
            st.error("Could not parse row numbers. Use format like 5,6,12 or 5-8.")
        else:
            with st.spinner("Reading CSV and extracting call IDs..."):
                import tempfile
                with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
                    tmp.write(uploaded.getvalue())
                    tmp_path = Path(tmp.name)
                try:
                    row_inputs = get_rows_from_csv(tmp_path, rows)
                finally:
                    tmp_path.unlink(missing_ok=True)
            if not row_inputs:
                st.error("No valid rows found. Check that Column B contains URLs with callId=...")
            else:
                with st.spinner("Calling APIs (xPlus → SPX → Screening)..."):
                    st.session_state.assembled_rows = assemble_all(row_inputs)
                    st.session_state.judge_results = []
                st.success(f"Fetched data for {len(st.session_state.assembled_rows)} row(s).")

assembled_rows: list[AssembledRow] = st.session_state.assembled_rows
judge_results: list[JudgeResult] = st.session_state.judge_results

# -----------------------------------------------------------------------------
# Data display (modular, expandable)
# -----------------------------------------------------------------------------
if assembled_rows:
    with st.expander("📄 Data Display — Transcript, Knowledge Base, Recording URL", expanded=True):
        sel_idx = st.selectbox(
            "Select row",
            range(len(assembled_rows)),
            format_func=lambda i: f"Row {assembled_rows[i].row_number} — {assembled_rows[i].call_id[:24]}...",
            key="data_sel",
        )
        if sel_idx is not None:
            r = assembled_rows[sel_idx]
            if r.error:
                st.warning(f"Error for this row: {r.error}")
            st.subheader("Transcript")
            st.text_area("", value=r.transcript or "(empty)", height=180, key="disp_transcript", disabled=True)
            st.subheader("Knowledge Base")
            st.text_area("", value=r.knowledge_base or "(empty)", height=120, key="disp_kb", disabled=True)
            st.subheader("Recording URL")
            if r.recording_url:
                st.link_button("Open recording", r.recording_url, key="rec_link")
            else:
                st.text("(none)")

    # -------------------------------------------------------------------------
    # Human Review (HITL) — expandable
    # -------------------------------------------------------------------------
    with st.expander("👤 Human Review (HITL) — Comments & Issue Category", expanded=True):
        hitl_idx = st.selectbox(
            "Select row",
            range(len(assembled_rows)),
            format_func=lambda i: f"Row {assembled_rows[i].row_number}",
            key="hitl_sel",
        )
        if hitl_idx is not None:
            r = assembled_rows[hitl_idx]
            st.markdown("**Comments (Column D)**")
            st.text_area("", value=r.hitl_comments or "(none)", height=100, key="hitl_comments", disabled=True)
            st.markdown("**Issue Category (Column G)**")
            st.text(r.hitl_issue_category or "(none)")

    # -------------------------------------------------------------------------
    # LLM Judge — Run & output
    # -------------------------------------------------------------------------
    with st.expander("🤖 LLM Judge — Run Judge & Output", expanded=True):
        if st.button("Run Judge", type="primary", key="run_judge_btn"):
            with st.spinner("Running LLM judge for all fetched rows..."):
                st.session_state.judge_results = run_judge_for_all(assembled_rows)
            st.rerun()
        judge_results = st.session_state.judge_results
        if judge_results:
            j_sel = st.selectbox(
                "Select row result",
                range(len(judge_results)),
                format_func=lambda i: f"Row {judge_results[i].row_number}",
                key="judge_sel",
            )
            if j_sel is not None:
                j = judge_results[j_sel]
                if j.error:
                    st.error(j.error)
                st.text_area("LLM output", value=j.raw_output or "(empty)", height=200, key="judge_out", disabled=True)

    # -------------------------------------------------------------------------
    # Contrast: HITL vs LLM Judge (side-by-side)
    # -------------------------------------------------------------------------
    with st.expander("🔄 Compare — HITL vs LLM Judge", expanded=True):
        st.caption("Compare human reviewer feedback with LLM judge output for the same row.")
        c_sel = st.selectbox(
            "Select row to compare",
            range(len(assembled_rows)),
            format_func=lambda i: f"Row {assembled_rows[i].row_number}",
            key="compare_sel",
        )
        if c_sel is not None and c_sel < len(judge_results):
            a = assembled_rows[c_sel]
            j = judge_results[c_sel]
            col1, col2 = st.columns(2)
            with col1:
                st.markdown('<span class="hitl-label">HITL — Comments</span>', unsafe_allow_html=True)
                st.text_area("", value=a.hitl_comments or "(none)", height=120, key="comp_hitl_c", disabled=True)
                st.markdown('<span class="hitl-label">HITL — Issue Category</span>', unsafe_allow_html=True)
                st.text(a.hitl_issue_category or "(none)")
            with col2:
                st.markdown('<span class="judge-label">LLM Judge — Output</span>', unsafe_allow_html=True)
                st.text_area("", value=j.raw_output or "(empty)", height=120, key="comp_judge", disabled=True)
                if j.error:
                    st.error(j.error)
        elif assembled_rows and not judge_results:
            st.info("Run the judge first to see comparison.")
else:
    st.info("Upload a CSV, enter row numbers, and click **Fetch Data** to begin.")
