# API Routes

Update this file when any route or function changes.

## 1. Our HTTP routes
Defined in `api.py`. Run locally: `uvicorn api:app --reload`. Interactive docs: `/docs`.

| Method | Route | Purpose | Success | Errors |
|---|---|---|---|---|
| `GET` | `/health` | Service check | 200 | - |
| `POST` | `/audits` | Upload a PDF (form field `file`) and run the check | 201 | 413 over 10 MB, 415 not PDF |
| `GET` | `/audits/{id}` | Get the latest report | 200 | 404 not found |
| `POST` | `/audits/{id}/review` | Submit a person's decision | 200 | 404 not found, 409 not waiting, 422 invalid body |

**Review body:** `{"decision": "Approve" | "Reject", "reviewer": "name", "note": "optional"}`

**Report status:** `waiting_for_person` or `complete`.

**Storage:** audits are kept in memory and are lost on restart.

## 2. External API

### Gemini: generate content
| | |
|---|---|
| **Route** | `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` |
| **Called from** | `core/llm.py`, through the `google-genai` SDK, in `live` mode only |
| **Auth** | `GEMINI_API_KEY` from `.env`, never committed |
| **Model** | `gemini-3.5-flash-lite`; change with `GEMINI_MODEL` |
| **Sends** | Full text of the supplier document |
| **Returns** | JSON: status, value and exact quote for each contract term |
| **On 429, 503, timeout or bad JSON** | Retries, then falls back to regex only |

## 3. Internal functions
Defined in `core/graph.py` and `core/rules.py`. Used by both `app.py` and `api.py`.

| Function | Input | Output |
|---|---|---|
| `run_audit` | `pdf_bytes`, `file_name`, optional `rule_set`, `llm_mode` | `AuditReport`, complete or waiting for a person |
| `get_report` | `audit_id` | `AuditReport`; `KeyError` if not found |
| `resume_review` | `audit_id`, `decision`, `reviewer`, `note` | Completed `AuditReport` |
| `load_rules` | Optional path to a YAML file | `RuleSet` |
