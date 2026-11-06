# Build Plan: Supplier Document Checker

Source of truth: `BIAI-AI-Engineer-Round2-Brief.md`. This plan overrides `PROJECT_MASTER_GUIDE.md` where they differ.

**Deadline:** extension requested, not yet confirmed. Deadline: ________

## What we are building
A LangGraph pipeline with a Streamlit screen. It reads each supplier PDF and returns **Approve**, **Reject** or **Needs a person to check**, with reasons and exact quotes.

**Stack:** Python, LangGraph, pdfplumber, Pydantic, Gemini free tier, YAML rules, Streamlit, pytest.

## Pipeline
`read_pdf → extract_fields → verify_quotes → compare_to_request → check_rules → decide → human_review (Review only) → final_report`

| Step | Job | If it fails |
|---|---|---|
| `read_pdf` | Get text and table | No text → Review |
| `extract_fields` | Table by code; clauses by regex and Gemini | Disagreement or missing → UNKNOWN |
| `verify_quotes` | Confirm each quote is in the PDF | Not found → UNKNOWN |
| `compare_to_request` | Show price and quantity differences | Item or PR not matched → UNKNOWN |
| `check_rules` | Run all rules and math with `Decimal` | Each returns PASS, FAIL or UNKNOWN |
| `decide` | Pick verdict by code only | See below |
| `human_review` | Pause until a person decides | Stays paused |
| `final_report` | System verdict, human decision, reasons, quotes | - |

## Verdict logic
1. Any Reject rule FAIL → **Reject**
2. Any Review rule FAIL, or any UNKNOWN → **Needs a person**
3. All checks PASS → **Approve**

## Rules we apply
- Stored in `config/rules.yaml`: id, severity, threshold.
- **Reject:** price > 3% over max; advance > 20%; no penalty clause; TIN or BIN missing; delivery > 45 days.
- **Review:** price 0-3% over max; quantity off by > 5%; payment unclear or outside 30-60 days; delivery 31-45 days; VAT not separate at 15%; numbers do not add up; validity < 30 days.
- **Our decisions (state in the note):**
  - Penalty below 0.5%, or not clearly "of order value" → Review
  - "Within 30 days of delivery" meets the 30-60 day rule
  - Delivery date is not computable because there is no PO date, so we report the duration

## LLM modes
| Mode | Used for | Behaviour |
|---|---|---|
| `live` | Normal use | Calls Gemini |
| `replay` | Default for evaluators and tests | Uses saved responses, no key needed |
| `offline` | Gemini down or rate-limited | Regex only; anything unresolved → Review |

Gemini never does math and never sets a verdict.

## Folder layout
```
config/rules.yaml      limits and severities
core/                  models, pdf_reader, extractors, llm, purchase_request, math_checks, rules, graph
data/                  expected verdicts, saved Gemini responses
scripts/               evaluate, record_llm_responses
task1-procurement/     samples from BIAI, unchanged
tests/                 samples, altered cases, Gemini safety, workflow, app
app.py                 Streamlit screen
api.py                 FastAPI routes
```

## Build checklist

### 1. Core
- [x] Project setup and requirements
- [x] Pydantic schemas
- [x] PDF text reader
- [x] Regex clause extractor
- [x] Math and request comparison
- [x] `rules.yaml` and rule engine with three states
- [x] Quote verification

### 2. Pipeline
- [x] LangGraph nodes and edges
- [x] `decide` logic
- [x] Human pause and resume
- [x] Per-step trace

### 3. LLM
- [x] Gemini client with structured output
- [x] Regex vs Gemini comparison
- [x] Rate limit, timeout and bad JSON handling
- [x] Saved responses and `replay` mode

### 4. App
- [x] Batch results and score
- [x] Pack details with quotes and differences
- [x] Human review screen
- [x] Rule controls for live changes
- [x] PDF upload (optional)
- [ ] Deploy to Streamlit Cloud (optional)

### 5. FastAPI (local only)
- [x] `/health`, `/audits`, `/audits/{id}`, `/audits/{id}/review`
- [x] Route tests

### 6. Submission
- [ ] README with run steps
- [ ] One-page note
- [ ] Loom, 5 minutes or less
- [ ] GitHub repo public, no API key committed
- [ ] Live-change practice

## Test plan
Run: `pytest -v` (all tests) and `python -m scripts.evaluate` (sample score)

**1. Sample files.** BIAI sent no answer key, so these are our own reading of the rules.

| Pack | Expected | Main reason |
|---|---|---|
| 01 | Approve | All pass |
| 02 | Approve | All pass |
| 03 | Reject | Price 9.05% over |
| 04 | Review | Price 2.31% over |
| 05 | Reject | Advance 40% |
| 06 | Reject | No penalty clause |
| 07 | Review | Quantity off by 17.5% |
| 08 | Reject | TIN/BIN missing |
| 09 | Review | Line total wrong; payment 30-90 days |
| 10 | Reject | Delivery 60 days; VAT not separate |

**2. Unit and altered cases** (kept separate; not counted in the 10/10 score)
- [x] Limits: price exactly 3%; quantity exactly 5%; delivery 30, 31, 45, 46; validity 29, 30; advance 20, 21; penalty 0.4, 0.5
- [x] Wording: "4 weeks"; "No advance"; reworded penalty clause
- [x] Multiple findings are all reported (Packs 09, 10)
- [x] Empty or no-text PDF → Review
- [x] Unknown item or wrong PR → Review
- [x] Unreadable penalty clause → Review, not Reject
- [x] Fake quote from LLM → Review
- [x] Gemini failure, 429 or bad JSON → no crash, safe result
- [x] Missing field never leads to Approve

**3. LLM**
- [x] Compare regex-only vs hybrid on altered cases
- [x] Run live 3 times and check verdicts stay the same

**4. End to end**
- [ ] Fresh clone, follow README, works with no key
- [x] Pause on a Review pack, resume, decision recorded
- [x] Change a threshold and see the verdict change
- [x] Move a rule's severity and see the verdict change
- [x] Add a new rule and rerun

## Done means
- [x] 10/10 on samples
- [x] All tests pass
- [ ] Every verdict has reasons and quotes
- [ ] Known weaknesses listed in the note
