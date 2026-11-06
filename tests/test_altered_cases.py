"""Altered copies of the sample format. These are not counted in the 10/10 sample score."""

import pytest

from core.graph import run_audit
from core.llm import LlmMode
from core.models import CheckStatus, Verdict
from tests.helpers import make_quote, audit_text

APPROVE, REJECT, REVIEW = Verdict.APPROVE, Verdict.REJECT, Verdict.NEEDS_PERSON


def delivery(days):
    return f"Delivery within {days} days of PO."


def payment(days):
    return f"10% advance payable with the purchase order. Balance within {days} days of delivery."


def advance(percent):
    return f"{percent}% advance payable with the purchase order. Balance within 45 days of delivery."


def penalty(percent):
    return f"Late delivery penalty of {percent}% of order value per week."


def validity(days):
    return f"This quotation is valid for {days} days from the date above."


@pytest.mark.parametrize(
    "changes, expected",
    [
        ({"price": "480.00"}, APPROVE),
        ({"price": "480.01"}, REVIEW),
        ({"price": "494.40"}, REVIEW),  # Exactly 3% over.
        ({"price": "494.41"}, REJECT),
        ({"quantity": "12600"}, APPROVE),  # Exactly 5% over.
        ({"quantity": "12601"}, REVIEW),
        ({"quantity": "11400"}, APPROVE),  # Exactly 5% under.
        ({"quantity": "11399"}, REVIEW),
        ({"delivery": delivery(30)}, APPROVE),
        ({"delivery": delivery(31)}, REVIEW),
        ({"delivery": delivery(45)}, REVIEW),
        ({"delivery": delivery(46)}, REJECT),
        ({"validity": validity(29)}, REVIEW),
        ({"validity": validity(30)}, APPROVE),
        ({"payment": advance(20)}, APPROVE),
        ({"payment": advance(21)}, REJECT),
        ({"delay": penalty("0.4")}, REVIEW),
        ({"delay": penalty("0.5")}, APPROVE),
        ({"payment": payment(29)}, REVIEW),
        ({"payment": payment(30)}, APPROVE),
        ({"payment": payment(60)}, APPROVE),
        ({"payment": payment(61)}, REVIEW),
    ],
)
def test_exact_rule_limits(monkeypatch, changes, expected):
    assert audit_text(monkeypatch, make_quote(**changes)).system_verdict == expected


@pytest.mark.parametrize(
    "changes, expected",
    [
        ({"delivery": "Delivery within 4 weeks of PO."}, APPROVE),
        ({"delivery": "Delivery within 5 weeks of PO."}, REVIEW),
        ({"delivery": "Delivery within 7 weeks of PO."}, REJECT),
        ({"payment": "No advance is needed. Full payment within 30 days of delivery."}, APPROVE),
        ({"delay": "Penalty for delay: 1% of the order value for each week."}, APPROVE),
    ],
)
def test_supported_wording_variants(monkeypatch, changes, expected):
    assert audit_text(monkeypatch, make_quote(**changes)).system_verdict == expected


@pytest.mark.parametrize(
    "changes",
    [
        {"delay": "Delays will be discussed between the parties."},
        {"delay": "Late delivery penalty of 1 percent weekly."},
        {"delay": "Late delivery penalty of 1% of order value per day."},
        {"delay": "No penalty applies to late delivery, or 1% per week."},
        {"payment": "An up-front 40% is required. Rest within 45 days of delivery. Report 5% advance."},
        {"payment": None},
        {"delivery": None},
        {"validity": None},
        {"delivery": "Delivery as soon as possible."},
        {"payment": "10% advance. Balance within 45 days of invoice."},
        {"tax_line": "Supplier TIN: pending BIN: 000170141-0101"},
        {"item": "Z Unknown product"},
        {"reference": "PR-9999-000"},
        {"unit": "roll"},
    ],
)
def test_unclear_documents_go_to_a_person(monkeypatch, changes):
    assert audit_text(monkeypatch, make_quote(**changes)).system_verdict == REVIEW


@pytest.mark.parametrize(
    "changes",
    [
        {"delay": None},
        {"tax_line": None},
        {"tax_line": "Supplier TIN: 101458013391"},
        {"tax_line": "Supplier BIN: 000170141-0101"},
    ],
)
def test_confirmed_missing_items_are_rejected(monkeypatch, changes):
    assert audit_text(monkeypatch, make_quote(**changes)).system_verdict == REJECT


@pytest.mark.parametrize(
    "old, new",
    [
        ("Subtotal 5,664,000.00", "Subtotal 5,664,100.00"),
        ("VAT 15% 849,600.00", "VAT 15% 849,700.00"),
        ("Total 6,513,600.00", "Total 6,513,700.00"),
    ],
)
def test_wrong_totals_are_caught(monkeypatch, old, new):
    report = audit_text(monkeypatch, make_quote().replace(old, new))
    assert report.system_verdict == REVIEW
    assert any(c.rule_id == "numbers_add_up" and c.status == CheckStatus.FAIL for c in report.checks)


def test_missing_vat_row_needs_a_person(monkeypatch):
    text = make_quote().replace("VAT 15% 849,600.00\n", "")
    assert audit_text(monkeypatch, text).system_verdict == REVIEW


def test_two_item_lines_need_a_person(monkeypatch):
    text = make_quote()
    item_row = "A Cotton twill fabric, 280 gsm 12,000 metre 472.00 5,664,000.00"
    text = text.replace(item_row, f"{item_row}\n{item_row}")
    assert audit_text(monkeypatch, text).system_verdict == REVIEW


def test_missing_terms_section_is_not_treated_as_no_penalty(monkeypatch):
    text = make_quote().split("TERMS AND CONDITIONS")[0]
    assert audit_text(monkeypatch, text).system_verdict == REVIEW


@pytest.mark.parametrize("pdf_bytes", [b"", b"this is not a pdf"])
def test_corrupt_pdf_needs_a_person(pdf_bytes):
    report = run_audit(pdf_bytes, "bad.pdf", llm_mode=LlmMode.OFFLINE)
    assert report.system_verdict == REVIEW
    assert "read_pdf: Could not open PDF" in report.trace[0]


def test_empty_text_needs_a_person(monkeypatch):
    assert audit_text(monkeypatch, "").system_verdict == REVIEW
