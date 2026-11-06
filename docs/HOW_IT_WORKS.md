# How It Works

This document explains every part of the Supplier Document Checker in plain words: each step, each function, each rule and each API route.

[Back to README](../README.md)

## Contents
1. [The big picture](#1-the-big-picture)
2. [One document, start to finish](#2-one-document-start-to-finish)
3. [The data shapes](#3-the-data-shapes)
4. [The workflow steps](#4-the-workflow-steps)
5. [Reading the document](#5-reading-the-document)
6. [The Gemini reader](#6-the-gemini-reader)
7. [The rules](#7-the-rules)
8. [The REST API](#8-the-rest-api)
9. [The Streamlit screen](#9-the-streamlit-screen)
10. [Scripts and tests](#10-scripts-and-tests)
11. [How to change the system](#11-how-to-change-the-system)
12. [Words used](#12-words-used)

---

## 1. The big picture

The system works like a careful clerk following a checklist:

1. Read the quotation.
2. Write down the important facts, along with the exact sentence each fact came from.
3. Ask a second clerk (Gemini) to read the contract terms too, and compare notes.
4. Throw out any fact whose sentence cannot be found in the document.
5. Compare the quote with what the company asked for.
6. Go through every company rule and mark each one: pass, fail or not sure.
7. Give the answer. If it is "Needs a person to check", stop and wait.

Three ideas guide the whole design:
- **Not sure means ask a person.** Approve is only given when every rule passed.
- **AI reads, code decides.** Gemini helps read text. It never does math or chooses the answer.
- **Everything is proven.** Every result comes with the exact text from the document.

---

## 2. One document, start to finish

Here is what happens to `supplier-pack-09.pdf`:

| Step | What happens |
|---|---|
| Read PDF | The text is pulled out of the PDF. |
| Extract fields | **Price table:** quantity 50,000, unit price 6.40, line amount 322,000.00, VAT 15%.<br/>**Terms (regex):** advance 5%, payment up to 90 days, delivery "4 weeks" = 28 days.<br/>**Gemini:** reads the same terms. Both readers agree. |
| Verify quotes | Every quote is found word for word in the PDF. |
| Compare to request | Item D is in the purchase request: same quantity, price 1.54% under the maximum. |
| Check rules | `numbers_add_up` fails: 50,000 × 6.40 = 320,000.00, not 322,000.00.<br/>`payment_terms` fails: 90 days is outside 30 to 60. All other rules pass. |
| Decide | No reject rule failed, but review rules did, so the answer is **Needs a person to check**. |
| Pause | The workflow stops and waits. |
| Person decides | A reviewer chooses Approve or Reject and gives their name. |
| Final report | Stores the system's answer, the person's decision, the reasons, quotes and every step taken. |

---

## 3. The data shapes

File: [core/models.py](../core/models.py). These are the "forms" that pass between steps. Each is a Pydantic model, so data is checked for the right type automatically.

### Answer types
| Name | Values | Meaning |
|---|---|---|
| `Verdict` | Approve, Reject, Needs a person to check | The final answer |
| `Severity` | reject, review | What happens when a rule fails |
| `CheckStatus` | pass, fail, unknown | The result of one rule |
| `FieldStatus` | found, absent, unclear | Whether a value was read |
| `AuditStatus` | waiting_for_person, complete | Whether the workflow is paused |

`absent` and `unclear` are different on purpose:
- **absent** means the document clearly does not contain it, for example no penalty clause anywhere.
- **unclear** means it is mentioned but could not be read, or the document itself could not be read.

### Main shapes
| Name | What it holds |
|---|---|
| `ExtractedField` | One value, its status, the quote that proves it, which reader found it, and a note. `.number` gives the value as a number. |
| `Terms` | The 8 contract terms: advance %, payment days, delivery days, penalty %, penalty basis, validity days, TIN, BIN |
| `LineItem` | One row of the price table, with its original text |
| `SupplierDocument` | Supplier name, quotation number, date, PR reference, price table, subtotal, VAT and total |
| `RequestComparison` | Quoted vs requested price and quantity, the differences in percent, and any mismatch problems. `.is_matched` is true when there are none. |
| `RuleConfig` / `RuleSet` | One rule from `rules.yaml`, and the full set of rules with their limits |
| `CheckResult` | One rule's result: status, message and quotes |
| `HumanDecision` | A person's decision, name and note |
| `AuditReport` | Everything about one document: both answers, reasons, data, checks and the step-by-step trace |

---

## 4. The workflow steps

File: [core/graph.py](../core/graph.py). This connects the steps into a LangGraph workflow.

### Steps (nodes)
| Function | What it does |
|---|---|
| `read_pdf_step` | Gets the text from the PDF. |
| `extract_fields_step` | Reads the price table and the terms with regex, asks Gemini, and merges both readings. |
| `verify_quotes_step` | Checks every quote really appears in the document. |
| `compare_to_request_step` | Compares the quote with the purchase request. |
| `check_rules_step` | Runs every rule. |
| `decide_step` | Picks the answer and builds the first version of the report. |
| `route_after_decide` | Sends "Needs a person" to the pause step, and everything else to the final step. |
| `human_review_step` | Pauses the workflow with LangGraph's `interrupt` until a person answers. |
| `final_report_step` | Adds the person's decision, if any, and marks the report complete. |

### Building and running
| Function | What it does |
|---|---|
| `build_graph` | Connects the steps in order, adds the pause branch, and attaches memory so a paused audit can resume. |
| `_checkpoint_serializer` | Lists our data shapes as safe to save and load while an audit is paused. |
| `_config` | Builds LangGraph's settings for one audit ID. |
| `run_audit(pdf_bytes, file_name, rule_set, llm_mode)` | **Main entry point.** Checks one document and returns its report, either complete or waiting for a person. |
| `get_report(audit_id)` | Returns the latest report for an audit. Raises `KeyError` if it does not exist. |
| `resume_review(audit_id, decision, reviewer, note)` | Gives a person's decision to a paused audit and finishes it. Refuses if the audit is not paused, or if the decision is not Approve or Reject. |

Both the Streamlit screen and the API call these same three functions, so the logic exists in one place.

---

## 5. Reading the document

### PDF text
File: [core/pdf_reader.py](../core/pdf_reader.py)

| Function | What it does |
|---|---|
| `read_pdf_text(pdf_bytes)` | Returns the text and an error message. A broken or scanned PDF gives empty text and a message, never a crash. Empty text means every rule becomes "not sure", so the document goes to a person. |

### Fields and terms
File: [core/extractors.py](../core/extractors.py)

**Price table**

| Function | What it does |
|---|---|
| `parse_document(text)` | Reads the supplier name, quotation number, date, PR reference, item rows, subtotal, VAT and total. Each row keeps its original text as proof. |

**Contract terms (regex reader)**

The regex reader is strict on purpose. If wording is unusual, it says "unclear" instead of guessing.

| Function | What it does |
|---|---|
| `split_clauses(text)` | Splits the terms section into clauses by heading (Payment, Delivery and so on). It does not rely on clause numbers, because Pack 06 has a clause missing and the numbers shift. |
| `_read_advance` | Reads the advance %. "No advance" means 0. Unclear if any other percentage in the clause is not explained, for example text claiming "5% advance" next to a real 40%. |
| `_read_payment_days` | Reads the latest payment day after delivery. "30 to 90 days" gives 90. |
| `_read_delivery_days` | Reads days from the PO to delivery. "4 weeks" gives 28. |
| `_read_penalty` | Finds the clause about late delivery. **Absent** if no clause mentions it. **Unclear** if the rate is not one clear weekly percentage. Also records whether the rate is a percentage "of order value". |
| `_read_validity_days` | Reads how many days the quotation is valid. |
| `_read_tax_id` | Reads the TIN or BIN. **Absent** if not mentioned at all; **unclear** if mentioned without a number, for example "TIN: pending". |
| `extract_terms(text)` | Runs all of the above and returns the 8 terms. |

**Combining two readers**

| Function | What it does |
|---|---|
| `merge_terms(regex_terms, gemini_terms)` | Combines regex and Gemini readings, one term at a time. Without Gemini, the regex reading is used alone. |
| `_merge_field` | Applies the rules in the table below. |
| `_same_reading` | Checks whether two readings match. Numbers are compared as numbers, so 10 equals 10.0. |
| `_value_appears_in_quote` | Checks that a value read only by Gemini is visible in its quote. A value given in days may also appear in the quote as weeks. |
| `verify_quotes(terms, text)` | Any value whose quote is not in the document becomes **unclear**. |

How `_merge_field` decides:

| Regex says | Gemini says | Result |
|---|---|---|
| Found X | Found X | Use X; both readers agree |
| Found X | Found Y | **Unclear** → a person checks |
| Unclear | Found X, and X is in its quote | Use X; Gemini rescued it |
| Absent | Found | **Unclear** → a person checks |
| Same status, not found | Same status, not found | Keep that status |

**Small helpers:** `normalize_whitespace`, `_to_decimal`, `_found`, `_unclear`, `_absent` and `_single_value`. `_single_value` only accepts a value if the text gives exactly one answer.

### Purchase request
File: [core/purchase_request.py](../core/purchase_request.py)

| Function | What it does |
|---|---|
| `load_purchase_request()` | Reads `purchase-request.csv` into one `RequestLine` per item. |
| `compare_to_request(document, request)` | Finds the item in the request and works out the price and quantity differences in percent. It records a problem for more than one item line, an unknown item, or a wrong PR reference, description or unit. |
| `_percent_difference` | (quoted − requested) ÷ requested × 100 |

### Math
File: [core/math_checks.py](../core/math_checks.py). Uses Python's `Decimal`, so 6.40 is exactly 6.40 and there are no rounding surprises.

| Function | What it does |
|---|---|
| `find_math_errors(document)` | Checks four things: quantity × unit price = line amount; lines add up to the subtotal; subtotal × VAT % = VAT amount; and subtotal + VAT = total. When there is no VAT row, as in Pack 10, the total must equal the lines. |
| `has_all_amounts(document)` | True if the price table was read. |
| `_money` / `_mismatch` | Round to cents, and write a clear message when two amounts differ. |

---

## 6. The Gemini reader

File: [core/llm.py](../core/llm.py)

Gemini is a **second, independent reader** of contract terms. It returns, for each term, a status, a value and the exact quote. Its instructions tell it to treat the document as data, ignore any instructions written inside it, never calculate prices and never judge the terms.

### Three modes
| Mode | When | What happens |
|---|---|---|
| `replay` | Default | Uses saved responses from `data/llm_responses.json`. No key needed, and results are repeatable. A file with no saved response uses regex only. |
| `live` | `LLM_MODE=live` with a key | Calls Gemini. Retries short-lived errors. If it still fails, uses regex only. |
| `offline` | `LLM_MODE=offline` | Regex only. |

### Functions
| Function | What it does |
|---|---|
| `read_terms(text, mode)` | **Main entry.** Returns Gemini's terms, or `None`, plus a note explaining what happened. Never crashes: any API, network, quota or format error gives `None`. |
| `call_gemini(text)` | One Gemini call with a fixed JSON format, temperature 0, a 30-second timeout and up to 4 attempts. |
| `default_mode()` | Reads `LLM_MODE` from the environment. The default is `replay`. |
| `has_saved_response` / `save_response` / `_load_saved_responses` | Look up, save and load responses for replay mode. |
| `_cache_key(text)` | A fingerprint of the document text and prompt version. If either changes, old saved responses are not reused. |
| `_to_terms(response)` | Converts Gemini's answer into the same `Terms` shape the regex reader uses. |

**Settings:** `GEMINI_API_KEY`, `GEMINI_MODEL` (default `gemini-3.5-flash-lite`) and `LLM_MODE`.

---

## 7. The rules

File: [core/rules.py](../core/rules.py). Limits and severities are in [config/rules.yaml](../config/rules.yaml).

Every rule returns **pass**, **fail** or **not sure**. A rule returns nothing when another rule already covers the case. For example, if delivery is over 45 days, the reject rule handles it and the review rule stays quiet.

### Reject rules
| ID | Fails when | Not sure when |
|---|---|---|
| `price_over_limit` | Price is more than 3% over the maximum | Price could not be compared |
| `advance_too_high` | Advance is over 20% | Advance could not be read |
| `no_penalty_clause` | No clause mentions late delivery at all | A clause exists but cannot be read |
| `tin_bin_missing` | TIN or BIN is not in the document | Mentioned but no number, for example "pending" |
| `delivery_too_late` | Delivery is over 45 days | Delivery time could not be read |

### Review rules (Needs a person to check)
| ID | Fails when | Not sure when |
|---|---|---|
| `request_match` | - | Item, unit, description or PR reference does not match, or there is more than one item |
| `price_above_max` | Price is over the maximum by 3% or less | Price could not be compared |
| `quantity_differs` | Quantity differs by more than 5% | Quantity could not be compared |
| `payment_terms` | Payment is outside 30 to 60 days | Payment terms are unclear |
| `delivery_needs_check` | Delivery is 31 to 45 days | Delivery time could not be read |
| `vat_not_separate` | No VAT row, or VAT is not 15% | Price table could not be read |
| `numbers_add_up` | Any math check fails | Price table could not be read |
| `validity_too_short` | Valid for under 30 days | Validity could not be read |
| `penalty_too_low` | Penalty is under 0.5% per week | Rate unclear, or not stated as a percentage of order value |

### Engine functions
| Function | What it does |
|---|---|
| `@rule("id")` | Registers a function as the check for a rule ID in `rules.yaml`. |
| `load_rules(path)` | Loads `rules.yaml`. Stops with a clear error if a rule in the file has no check in the code. |
| `run_checks(document, terms, comparison, rule_set)` | Runs every rule listed in the YAML file. A rule that crashes counts as **not sure**, never as a pass. |
| `decide(checks)` | Any reject rule failed → **Reject**. Any rule failed or not sure → **Needs a person**. All passed → **Approve**. No rules run → **Needs a person**. |
| `RuleContext` | What each rule can see: the document, terms, comparison and limits. |
| `Outcome`, `_passed`, `_failed`, `_unknown`, `_unreadable` | Small helpers for building a rule's result. |

---

## 8. The REST API

File: [api.py](../api.py). Start it with `uvicorn api:app --reload`, then open http://localhost:8000/docs.

| Method | Route | Function | Success | Errors |
|---|---|---|---|---|
| `GET` | `/health` | `health` | 200 `{"status": "ok"}` | - |
| `POST` | `/audits` | `create_audit` | 201 report | 413 file over 10 MB, 415 not a PDF |
| `GET` | `/audits/{id}` | `read_audit` | 200 report | 404 not found |
| `POST` | `/audits/{id}/review` | `review_audit` | 200 report | 404 not found, 409 not waiting for a person, 422 bad body |

### Examples
Check a document:
```bash
curl -F "file=@task1-procurement/supplier-pack-09.pdf" http://localhost:8000/audits
```
The reply is the full report. Note its `audit_id` and `status`.

If `status` is `waiting_for_person`, send a decision:
```bash
curl -X POST http://localhost:8000/audits/<audit_id>/review \
  -H "Content-Type: application/json" \
  -d '{"decision": "Reject", "reviewer": "Rahima", "note": "Line total is wrong."}'
```
`decision` must be `Approve` or `Reject`.

Audits are kept in memory, so they are lost when the server restarts.

---

## 9. The Streamlit screen

File: [app.py](../app.py)

| Function | What it does |
|---|---|
| `main` | Builds the page. It checks all samples once per session, handles the "run again" and upload buttons, and shows the summary and the chosen report. |
| `sidebar_settings` | Builds the sidebar: reader mode, rule limits and rule severity. Returns the rules for this session; the YAML file is not changed. "Live Gemini" only appears when a key is set. |
| `audit_samples` | Checks all 10 sample packs. |
| `show_summary` | Shows the score, the answer counts and the table. |
| `show_report` | Shows one document: answer, reasons, review form, what was read, comparison, checks, workflow steps and the download button. |
| `show_comparison` | Shows the quote vs request table. |
| `show_check` | Shows one rule's result and its quotes. |
| `show_review_form` | Shows the Approve / Reject form. On submit, it calls `resume_review`. |
| `current_verdict` | The person's decision if there is one, otherwise the system's answer. |
| `_clean_decimal`, `_delivery_text` | Small display helpers. |

---

## 10. Scripts and tests

### Scripts
| Command | What it does |
|---|---|
| `python -m scripts.evaluate [replay\|offline\|live]` | Prints each sample's answer, any unclear terms and the score. |
| `python -m scripts.record_llm_responses` | Calls Gemini for samples with no saved response and saves the answers. It is safe to run again. |

### Tests
Run all with `pytest -v`.

| File | What it proves |
|---|---|
| `test_sample_packs.py` | All 10 samples are correct in regex-only and replay modes. Every pass or fail has a quote. Specific traps are read correctly: "4 weeks", "No advance", the 40% advance next to "balance 60%", and Pack 09's math. |
| `test_altered_cases.py` | Exact limits, such as exactly 3% over or delivery of 45 vs 46 days. Also reworded clauses, missing clauses, broken PDFs, unknown items and wrong totals. Uses changed copies of the sample format, not real data. |
| `test_gemini_safety.py` | Gemini disagreement goes to a person. Made-up quotes are rejected. Gemini cannot hide a rejection. Gemini failures fall back safely. Uses a fake Gemini, so no network is needed. |
| `test_workflow.py` | Pause and resume, changing limits and severities, adding and removing rules, crashing rules, and every API route and error code. |
| `test_app.py` | The Streamlit screen loads, shows 10/10, and a person can finish a review. |
| `helpers.py` | Builds test quotations, and runs the real workflow on text. |

---

## 11. How to change the system

### Change a limit
In `config/rules.yaml`, change for example `advance_max_percent: 20` to `25`. You can also change it in the app's sidebar under **Rule limits**.

### Move a rule between Reject and Review
In `config/rules.yaml`, change `severity: reject` to `severity: review`, or use **Rule severity** in the sidebar.

### Turn a rule off
Delete its line from `config/rules.yaml`.

### Add a new rule
1. Add a line to `config/rules.yaml`:
   ```yaml
   - {id: blocked_supplier, severity: reject, title: "Supplier is not blocked"}
   ```
2. Add a check to `core/rules.py`:
   ```python
   @rule("blocked_supplier")
   def check_blocked_supplier(context: RuleContext) -> Outcome:
       if context.document.supplier_name == "Example Ltd":
           return _failed("This supplier is blocked.")
       return _passed("Supplier is not blocked.")
   ```
3. Restart the app. If the YAML and code do not match, `load_rules` stops with a clear error.

### Read a new contract term
1. Add the field to `Terms` in `core/models.py`, and to `LlmTerms` and the prompt in `core/llm.py`.
2. Write a `_read_...` function in `core/extractors.py`, and call it in `extract_terms`.
3. Increase `PROMPT_VERSION` in `core/llm.py`, then run `python -m scripts.record_llm_responses`.

---

## 12. Words used

| Word | Meaning |
|---|---|
| **PR** | Purchase request: what the company asked to buy, and the maximum price |
| **PO** | Purchase order: the company's order to the supplier |
| **TIN / BIN** | Tax and business identification numbers in Bangladesh |
| **Regex** | A strict text pattern, used to find values like "within 45 days" |
| **LangGraph** | A library for building workflows as fixed, connected steps |
| **Interrupt** | LangGraph's way to pause a workflow and wait for a person |
| **Replay mode** | Using saved Gemini answers instead of calling Gemini |
| **Audit trail** | The record of every step, and who made each decision |
