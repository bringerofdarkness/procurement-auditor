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
config/rules.yaml
core/        models, pdf_reader, extractors, math_checks, rules, graph, llm
data/        supplied samples
tests/       unit, samples, altered cases
app.py
```

## Build checklist

### 1. Core
- [ ] Project setup and requirements
- [ ] Pydantic schemas
- [ ] PDF text and table reader
- [ ] Regex clause extractor
- [ ] Math and request comparison
- [ ] `rules.yaml` and rule engine with three states
- [ ] Quote verification

### 2. Pipeline
- [ ] LangGraph nodes and edges
- [ ] `decide` logic
- [ ] Human pause and resume
- [ ] Per-step trace

### 3. LLM
- [ ] Gemini client with structured output
- [ ] Regex vs Gemini comparison
- [ ] Rate limit, timeout and bad JSON handling
- [ ] Saved responses and `replay` mode

### 4. App
- [ ] Batch results and score
- [ ] Pack details with quotes and differences
- [ ] Human review screen
- [ ] Rule controls for live changes
- [ ] PDF upload (optional)
- [ ] Deploy to Streamlit Cloud (optional)

### 5. Submission
- [ ] README with run steps
- [ ] One-page note
- [ ] Loom, 5 minutes or less
- [ ] GitHub repo public, no API key committed
- [ ] Live-change practice

## Test plan
Run: `pytest -v`

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
- [ ] Limits: price exactly 3%; quantity exactly 5%; delivery 30, 31, 45, 46; validity 29, 30; advance 20, 21; penalty 0.4, 0.5
- [ ] Wording: "4 weeks"; "No advance"; reworded penalty clause
- [ ] Multiple findings are all reported (Packs 09, 10)
- [ ] Empty or no-text PDF → Review
- [ ] Unknown item or wrong PR → Review
- [ ] Unreadable penalty clause → Review, not Reject
- [ ] Fake quote from LLM → Review
- [ ] Gemini failure, 429 or bad JSON → no crash, safe result
- [ ] Missing field never leads to Approve

**3. LLM**
- [ ] Compare regex-only vs hybrid on altered cases
- [ ] Run live 3 times and check verdicts stay the same

**4. End to end**
- [ ] Fresh clone, follow README, works with no key
- [ ] Pause on a Review pack, resume, decision recorded
- [ ] Change a threshold and see the verdict change
- [ ] Move a rule's severity and see the verdict change
- [ ] Add a new rule and rerun

## Done means
- [ ] 10/10 on samples
- [ ] All tests pass
- [ ] Every verdict has reasons and quotes
- [ ] Known weaknesses listed in the note
