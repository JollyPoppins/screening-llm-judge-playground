# LLM Judge Parser Application

Local application per PRD: CSV upload, **single-row** selection, Fetch / Run / Fetch and Run, editable LLM judge prompt with placeholders `{TS}`, `{KB}`, `{JD}`, selective context checkboxes, and Human vs LLM comparison.

## Data source (CSV)

Columns **A–M**: Date, Link, Candidate Name, Comments, AI Rating, Candidate Rating, **Issue Categories**, **Annotator Name**, Reviewed By, Week Number, Month, **Tenant**, Screening Date.

- **B – Link**: URL with `callId`; the app extracts the full call ID from the query string.
- **L – Tenant**: `refNum` used for transcript, KB, and job APIs.
- **D – Comments** and **G – Issue Categories** are shown in expanded sections (not in the compact table).

You select **one row number** at a time. If the row does not exist or is invalid (missing callId/refNum), the app shows **"Row does not exist"**.

## API flow

1. **Conversational Intelligence Transcript** — POST with `callId`, `refNum` → transcript + recording URL.
2. **SPX get-document** — POST with `refNum` (CRM-SCREENING, getAgentKBDetails) → knowledge base.
3. **SPX jobs service** — POST with `jobSeqNo` and `refNum` → job description (optional; add 14th column for Job Seq No if needed).

## Application structure (PRD)

- **CSV Upload & Row Selection**: Upload CSV, enter a single row number. "Row does not exist" if invalid.
- **LLM Judge Prompt**: Editable text area; placeholders `{TS}`, `{KB}`, `{JD}` replaced with fetched data when the corresponding checkbox is enabled.
- **Actions**: **Fetch** (get data for selected row) | **Run** (run LLM judge with current prompt and checkboxes) | **Fetch and Run** (fetch then run).
- **After Fetch**: Transcript, Knowledge Base, Job Description, and **Audio Player** (embedded) sections, each with a checkbox to **include in LLM judge**.
- **CSV Record Display**: Table of columns A–M **except D and G**; then **Comments (Column D)** and **Issue Categories (Column G)** in separate sections.
- **LLM Judge Output**: Dedicated result panel after Run.
- **Human vs LLM Comparison**: LLM output vs human Comments and Issue Categories.
- **Selective context**: Checkboxes for Transcript, Knowledge Base, Job Description, and Audio control what is sent to Gemini; data is inserted only if the prompt contains the relevant placeholder.

## Tech stack

- **CSV processing**: `src/csv_processor.py`
- **API clients**: `src/api_clients/` (transcript, KB get-document, jobs)
- **Data aggregation**: `src/data_aggregation.py`
- **LLM judge**: `src/llm_judge.py` (Google Gemini)
- **Config**: `.env` (see `.env.example`); env vars for API endpoints and keys.

## Setup (local)

```bash
cd screening-llm-judge
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
cp .env.example .env
# Edit .env with API base URLs and keys when available.
streamlit run app.py
```

Open the URL shown in the terminal (e.g. http://localhost:8501).

## Environment variables

| Variable | Description |
|----------|-------------|
| `TRANSCRIPT_API_BASE_URL` | Transcript API (default: mcs-campaign-execution-admin.prod.phenom.local) |
| `SPX_TRANSFORMS_BASE_URL` | SPX get-document (default: spx-enterprise-search-transforms.prod.phenom.local) |
| `SPX_JOBS_BASE_URL` | SPX jobs service (default: spx-jobs-service.prod.phenom.local) |
| `GEMINI_API_KEY` | Google Gemini API key (required for Run Judge) |
| `GEMINI_JUDGE_MODEL` | Model name (default: `gemini-1.5-flash`) |

Override base URLs in `.env` if your environment uses different hosts (e.g. for VPN or staging).

## Pushing to GitHub (new project)

The project is already initialized with one commit. To push as a **new** GitHub repo:

1. On GitHub: **New repository** → name it `screening-llm-judge` (or any name) → do **not** add a README (we already have one).
2. Locally, from the project folder:

```bash
cd screening-llm-judge
git remote add origin https://github.com/YOUR_USERNAME/screening-llm-judge.git
git branch -M main
git push -u origin main
```

Replace `YOUR_USERNAME` with your GitHub username (or org). Use the repo URL GitHub shows (HTTPS or SSH).
