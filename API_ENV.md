# Where each API setting goes (`.env`)

Edit **`.env`** in the project root (copy from `.env.example`). Nothing here should be committed with real secrets.

| Variable | What it powers | Typical value / notes |
|----------|----------------|------------------------|
| **`TRANSCRIPT_API_BASE_URL`** | **Fallback** transcript MCS host when `selectedEnv` is missing or unknown | Still used as default bucket |
| **`TRANSCRIPT_SELECTED_ENV`** | Fallback `selectedEnv` when the Link has no `?selectedEnv=` | e.g. `produs` or `prodir` |
| **`SPX_TRANSFORMS_BASE_URL`** | **Fallback** KB host when region is unknown | Same |
| **`SPX_JOBS_BASE_URL`** | **Fallback** jobs host when region is unknown | Same |
| **`JD_NEEDS_API_BASE_URL`** | **Fallback** getMongoDocument host when region is unknown | Same |
| **`PHENOM_REGION_OVERRIDES`** | Optional JSON to fix hostnames per region (see below) | Only if built-in IR/stg hostnames differ in your network |
| **`DISABLE_REGION_URL_RESOLUTION`** | Set to `1` to ignore `selectedEnv` for URLs and use only the four URLs above | Debugging |

### Dynamic hosts from `?selectedEnv=`

When the Link includes `selectedEnv` (e.g. **produs**, **prodIR** / **prodir**, **stgus**, **stgir**), the app picks **transcript, KB, jobs, and JD-needs** base URLs for that bucket automatically. You do **not** need to edit `.env` per row.

Built-in buckets: **produs** (prod US), **prodir** (prod IR / India-style), **stgus**, **stgir**. If DNS in your org uses different hostnames, set **`PHENOM_REGION_OVERRIDES`** in `.env` to JSON, for example:

```json
{"prodir":{"transcript":"http://mcs-campaign-execution-admin.CORRECT.phenom.local","spx_transforms":"http://...","spx_jobs":"http://...","jd_needs":"http://..."}}
```
| **`XPLUS_API_BASE_URL`** | Optional alternate path to resolve job id from `callId` | Leave empty if you only use JD needs |
| **`XPLUS_API_KEY`** | Auth for X+ if required | Optional |
| **`GEMINI_API_KEY`** | **LLM Judge (Run)** — Google Gemini | From [Google AI Studio](https://aistudio.google.com/apikey) |
| **`GEMINI_JUDGE_MODEL`** | Model name | e.g. `gemini-2.5-flash` |

## CSV columns the app reads

- **Column B (Link)** — must contain `callId=...` in the query string. If the real app uses **`?selectedEnv=produs`**, keep that on the link; the app now forwards **`selectedEnv`** into the transcript request.
- **Column L (Tenant)** — this is **`refNum`** for transcript, KB, and jobs. It must match the org/stack where the conversation exists.

## “Conversation data not found”

The server is reachable but has **no row** for that **`callId` + `refNum` (+ environment)**. Check:

1. **VPN** on for `.phenom.local`.
2. **Prod vs stg** — if the call is from staging, set **`TRANSCRIPT_API_BASE_URL`** to the **stg** MCS host.
3. **`selectedEnv`** — set on the Link or via **`TRANSCRIPT_SELECTED_ENV`**.
4. **Tenant** — column L must be the correct **refNum**.
5. **Real data** — `sample_input.csv` row 2 uses a fake `callId`; row 3 may be expired for your environment.

Use the in-app expander **“Transcript request (IDs we send)”** to verify values.

## Quick check from Terminal

```bash
python3 verify_setup.py
```
