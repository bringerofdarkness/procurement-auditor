# How the System Was Tested

This explains how the Supplier Document Checker was tested, what the results were, and what has not been tested yet.

[Back to README](../README.md) · [How it works](HOW_IT_WORKS.md)

## Summary

| Test | Result |
|---|---|
| 10 sample packs, regex only | 10/10 |
| 10 sample packs, saved Gemini responses | 10/10 |
| 10 sample packs, live Gemini, run 3 times | 10/10 each run |
| Automated tests | 118 passed |
| Clean copy, new environment, no API key | 118 passed, 10/10 |
| Real browser: open a pack, submit a person's decision | Worked |
| Real API server: upload Pack 09, then review it | Worked |

---

## 1. Working out the right answers

BIAI did not send an answer key, so the expected answer for each pack was worked out by hand first. Each PDF was read, every rule in `company-rules.md` was applied, and every amount was recalculated.

The expected answers are stored in [data/expected_verdicts.json](../data/expected_verdicts.json). Every test and score is measured against them.

Some packs contain traps that a careless reader would miss:

| Pack | Trap | Correct reading |
|---|---|---|
| 02, 07 | "No advance payment required" has no number | Advance is 0% |
| 05 | "40% advance ... balance 60%" | Advance is 40%, not 60% |
| 06 | No penalty clause, so the clause numbers shift | Penalty is absent |
| 08 | "0.5% per week of delay" does not say "of order value" | A secondary problem, flagged for a person |
| 09 | Only the line total is wrong; subtotal, VAT and total agree with it | 50,000 × 6.40 = 320,000, not 322,000 |
| 09 | "Within 4 weeks" | 28 days |
| 09 | "30 to 90 days" | Outside the 30 to 60 day rule |
| 10 | No subtotal or VAT row; price "VAT included" | VAT not shown separately |

---

## 2. Automated tests

Run them all with `pytest -v`. They need no API key and no internet.

| File | Tests | What they prove |
|---|---|---|
| [test_sample_packs.py](../tests/test_sample_packs.py) | 36 | All 10 samples are correct with regex only and with saved Gemini responses. Every pass or fail has a supporting quote. Each trap above is read correctly. |
| [test_altered_cases.py](../tests/test_altered_cases.py) | 54 | Exact rule limits, reworded clauses, missing clauses, broken files and wrong totals (details below). |
| [test_gemini_safety.py](../tests/test_gemini_safety.py) | 12 | Gemini cannot make the system guess (details below). |
| [test_workflow.py](../tests/test_workflow.py) | 14 | Pause and resume for a person, rule changes, crashing rules, and every API route and error. |
| [test_app.py](../tests/test_app.py) | 2 | The Streamlit screen loads, shows 10/10, and a person can finish a review. |
| **Total** | **118** | |

### Exact rule limits
Each limit is tested on both sides, because off-by-one mistakes happen at the edges:

| Rule | Values tested |
|---|---|
| Price over maximum | 0%, just over 0%, exactly 3%, just over 3% |
| Quantity difference | exactly +5%, just over +5%, exactly −5%, just under −5% |
| Delivery days | 30, 31, 45, 46 |
| Validity days | 29, 30 |
| Advance | 20%, 21% |
| Penalty per week | 0.4%, 0.5% |
| Payment days | 29, 30, 60, 61 |

Money is calculated with exact decimals, so a price exactly 3% over the maximum, such as 494.40 against 480.00, is treated as 3% and not as 3.0000001%.

### Documents that must go to a person
These must never be approved or rejected automatically:
- **Clauses that can't be read:** penalty wording with no clear weekly rate, or a penalty "per day" instead of per week.
- **Missing clauses:** a missing payment, delivery or validity clause.
- **Unclear payment terms:** payment counted from the invoice instead of from delivery.
- **Unreadable tax ID:** "TIN: pending".
- **A quote that doesn't match the request:** an unknown item, a wrong PR reference, a wrong unit, or two item lines.
- **Unreadable documents:** a PDF with no terms section, an empty PDF, a broken file or plain text.
- **Price table problems:** a missing VAT row, or a wrong subtotal, VAT amount or total.

### Documents that must be rejected
These must be rejected because something is clearly missing: no penalty clause, no TIN, or no BIN.

### Gemini safety
A fake Gemini is used here, so these tests can force every kind of bad answer:

| Situation | Expected result | Passed |
|---|---|---|
| Gemini agrees with regex | Value used, marked as read by both | Yes |
| Gemini disagrees with regex | Person checks | Yes |
| Gemini says a 60-day delivery is 24 days | Not approved | Yes |
| Gemini reads a clause regex cannot | Value used, marked as Gemini only | Yes |
| Gemini's value is not in its quote | Person checks | Yes |
| Gemini's quote is not in the document | Person checks | Yes |
| Gemini claims a penalty clause that does not exist | Person checks | Yes |
| Gemini times out, hits a rate limit, or returns bad JSON | Regex only, no crash | Yes |
| Live mode with no API key | Regex only, no crash | Yes |

---

## 3. Live Gemini tests

These tests call the real Gemini API (`gemini-3.5-flash-lite`, free tier), so they are run by hand rather than in the automated suite.

### Consistency
All 10 samples were checked with live Gemini 3 times. Every run scored 10/10, and Gemini was used on every pack.

On the samples, Gemini read 79 of 80 values the same way as regex (10 packs × 8 terms). The one difference was on Pack 08: Gemini assumed the penalty was a percentage "of order value", but the clause does not say so. The system flagged the disagreement for a person instead of trusting either reader.

### Reworded clauses
New clauses were written with wording the regex does not know, to see whether Gemini adds value. Each was run once.

| Clause | Correct answer | Regex only | Regex + Gemini |
|---|---|---|---|
| Penalty: "If goods arrive late, the supplier pays 1 percent of order value every week." | Approve | Person | Approve ✓ |
| Delivery: "Goods reach the factory no later than 24 days after the PO." | Approve | Person | Approve ✓ |
| Validity: "This offer stays open for 45 days." | Approve | Person | Approve ✓ |
| Payment: "10% advance. The rest is due 45 days after delivery." | Approve | Person | Approve ✓ |
| Delivery: "... no later than 60 days after the PO." | Reject | Person | Reject ✓ |
| Advance: "Forty percent is paid up front." | Not Approve | Person | Person ✓ |

- **Regex only:** never wrong, but it sent every reworded clause to a person.
- **Regex + Gemini:** answered 5 correctly. It sent the sixth to a person because the value is written in words, so it can't be proven by an exact match.

This is a small, hand-made test set. It shows the approach works, but it is not a general accuracy figure.

### Hidden instructions in a document
A supplier could hide text in a PDF to mislead the system. Two tests had a real 40% advance, plus hidden text saying the advance was 5%.

**This found a real bug.** In regex-only mode, the regex read the "5% advance" text and **approved** a 40% advance. In hybrid mode, Gemini disagreed, so the pack went to a person.

**The fix:** if a payment clause contains any percentage that is neither the advance nor the balance, the advance is marked unclear. A test now covers this case.

**After the fix:**
- **Regex only:** sends the case to a person.
- **Live Gemini:** read the real 40% in all 6 attempts, so the pack was correctly rejected.

### A real Gemini outage
While recording Gemini responses, the free tier returned `503 UNAVAILABLE` (high demand). The system fell back to regex and still scored 10/10. Retries were then added, and the recording script was changed to skip packs already saved and keep going after a failure.

---

## 4. End-to-end tests

| Test | How | Result |
|---|---|---|
| Fresh install, as an evaluator would do it | Copied only the files in git to a new folder, with no `.env` and no API key. Created a new environment, installed `requirements.txt`, then ran the tests and the score. | 118 passed, 10/10 |
| API key not leaked | Searched every committed file for the key | Not found |
| Streamlit screen | Started the real app and used Microsoft Edge (through Playwright) to open Pack 07, enter a name and submit a decision | Decision saved and shown |
| REST API | Started the real server, uploaded Pack 09 with `curl`, checked the answer and the pause | Paused for a person, with both problems listed |
| Live deployment | Opened https://procurement-auditor.streamlit.app/ in a private browser window | Working |
| Rule changes | Advance limit 20% → 40% (Pack 05 becomes Approve); TIN/BIN rule moved to Review (Pack 08 becomes Needs a person); a new rule added | All behaved as expected |

---

## 5. How to repeat the tests

```bash
pytest -v                               # 118 automated tests
python -m scripts.evaluate              # score with saved Gemini responses
python -m scripts.evaluate offline      # score with regex only
python -m scripts.evaluate live         # score with live Gemini (needs GEMINI_API_KEY)
```

---

## 6. What has not been tested

- **Real-world quotations:** only the 10 BIAI samples and quotations built from their format were used. Real documents will have layouts and wording not seen here.
- **Scanned PDFs** with real OCR. There is no OCR yet, so these always go to a person.
- **Other quotation layouts,** such as quotes with several items, or tables in a different column order.
- **Larger Gemini test sets:** the reworded-clause test has only 6 cases, each run once.
- **Many users at once,** and long-running servers. Audits are kept in memory.
- **Other Python versions:** tested on Python 3.13 on Windows only.
