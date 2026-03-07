# Screening LLM Judge — Enterprise Evals

Local application to run an LLM judge evaluation on screening calls: fetch data by call ID from two APIs, run a predefined judge prompt, and compare LLM output with human reviewer (HITL) data from a CSV.

## Data source (CSV)

- **Column B**: URL containing `callId` (query parameter). The app extracts the full value of `callId=` as the call ID.
- **Column D**: Human reviewer comments (HITL).
- **Column G**: Human issue category (HITL).

You provide **row numbers** to process (e.g. `5,6,12` or `5-8`). For each selected row the app reads Column B, extracts the call ID, then fetches data from the APIs.

## API flow (placeholder until contract provided)

1. **xPlus API** — input: `callId` → returns: `environment`, `refNumber`, `jobId`.
2. **SPX API (KB)** — input: `jobId` → returns: knowledge base (job description / screening requirements).
3. **Screening API** — input: `callId` → returns: `transcript`, `recordingUrl`.

Data is assembled per row and injected into the LLM judge prompt placeholders (transcript + knowledge base).

## UI (modular panels)

- **Input Panel**: Upload CSV, enter row numbers, **Fetch Data**.
- **Data Display**: Transcript, Knowledge Base, Recording URL (expandable).
- **Human Review (HITL)**: Comments (Column D), Issue Category (Column G) (expandable).
- **LLM Judge**: **Run Judge** button, LLM output (expandable).
- **Compare**: Side-by-side HITL vs LLM judge for the same row (expandable).

All sections can be collapsed/expanded so the product manager can focus on comparison and main information.

## Tech stack

- **CSV processing**: `src/csv_processor.py`
- **API clients**: `src/api_clients/` (xPlus, SPX, Screening)
- **Data aggregation**: `src/data_aggregation.py`
- **LLM judge**: `src/llm_judge.py` (OpenAI-compatible API)
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
| `XPLUS_API_BASE_URL` | xPlus API base URL |
| `XPLUS_API_KEY` | xPlus API key (if required) |
| `SPX_KB_API_BASE_URL` | SPX KB API base URL |
| `SPX_API_KEY` | SPX API key (if required) |
| `SCREENING_API_BASE_URL` | Screening API base URL |
| `SCREENING_API_KEY` | Screening API key (if required) |
| `OPENAI_API_KEY` | LLM judge (OpenAI-compatible) |
| `OPENAI_BASE_URL` | Optional; default `https://api.openai.com/v1` |
| `LLM_JUDGE_MODEL` | Model name (e.g. `gpt-4o-mini`) |

If API URLs are not set, the app uses mock data so you can test the flow locally.

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
