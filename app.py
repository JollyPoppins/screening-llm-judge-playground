"""
LLM Judge Parser Application — PRD implementation.
Single-row selection, Fetch / Run / Fetch and Run, selective context checkboxes,
tabular CSV view (A–M except D & G), expanded Comments and Issue Categories.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tempfile
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
from src.data_aggregation import assemble_row, AssembledRow
from src.llm_judge import run_judge_one, JudgeResult, DEFAULT_JUDGE_TEMPLATE


def _cell(row: pd.Series, col: int) -> str:
    """Safe string from row at column index."""
    if col >= len(row):
        return ""
    v = row.iloc[col]
    return "" if pd.isna(v) else str(v).strip()


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

    # Validate row exists
    row_exists = False
    row_input: RowInput | None = st.session_state.row_input
    if uploaded and st.session_state.csv_path:
        row_input, err = get_single_row(st.session_state.csv_path, row_number_input)
        if err:
            st.error(err)
            st.session_state.row_input = None
            st.session_state.assembled = None
        else:
            row_exists = True
            st.session_state.row_input = row_input

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

assembled: AssembledRow | None = st.session_state.assembled
judge_result: JudgeResult | None = st.session_state.judge_result

# -----------------------------------------------------------------------------
# 4. Data Retrieval Output Sections (after Fetch) + Selective checkboxes
# -----------------------------------------------------------------------------
if assembled:
    st.subheader("Fetched Data (select what to send to LLM)")

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
    st.text_area("", value=assembled.transcript or "(empty)", height=160, disabled=True, key="ta_transcript")

    # Knowledge Base Section
    st.markdown("**Knowledge Base Section**")
    st.text_area("", value=assembled.knowledge_base or "(empty)", height=120, disabled=True, key="ta_kb")

    # Job Description Section
    st.markdown("**Job Description Section**")
    st.text_area("", value=assembled.job_details_text or "(none)", height=80, disabled=True, key="ta_jd")

    # Audio Player Section (embedded)
    st.markdown("**Audio Player Section**")
    if assembled.recording_url:
        st.audio(assembled.recording_url, format="audio/ogg")
        st.caption(f"Recording: {assembled.recording_url[:90]}...")
    else:
        st.text("(no recording URL)")

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
        st.text_area("", value=judge_result.raw_output or "(empty)", height=140, disabled=True, key="comp_llm")
else:
    st.caption("Select a row, Fetch, then Run to compare human annotations with LLM output.")