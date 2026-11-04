# API Routes

**Status:** nothing built yet. Update this file when any route or function changes.

## 1. Our HTTP routes
None in the current plan. Streamlit calls the Python functions in section 3 directly.

## 2. External API

### Gemini: generate content
| | |
|---|---|
| **Route** | `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` |
| **Called from** | `core/llm.py`, in `live` mode only |
| **Auth** | `GEMINI_API_KEY` from `.env`, never committed |
| **Model** | Set in config; confirm the free-tier model and limits before building |
| **Sends** | Terms and conditions text from the fictional samples |
| **Returns** | JSON: field value and exact quote for each clause |
| **On 429, timeout or bad JSON** | Fall back to regex; anything unresolved → Review |

## 3. Internal functions

| Function | Input | Output | Status |
|---|---|---|---|
| `run_audit` | `pdf_bytes`, `file_name`, `thread_id` | Final report, or paused for review | Planned |
| `resume_review` | `thread_id`, `decision`, `reviewer`, `note` | Final report | Planned |
| `load_rules` | Optional session overrides | Active rules | Planned |

## 4. Optional FastAPI routes
**Not being built unless approved.** Useful only if another system must call this one.

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/health` | Service check |
| `POST` | `/audits` | Upload a PDF and start a check |
| `GET` | `/audits/{id}` | Get status and result |
| `POST` | `/audits/{id}/review` | Submit a person's decision |
