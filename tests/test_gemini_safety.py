"""Gemini can help, but it must never make the system guess. No network calls are made here."""

import pytest
from pydantic import BaseModel, ValidationError

from core.llm import LlmField, LlmMode, LlmTerms
from core.models import Terms, Verdict
from tests.helpers import DELAY, audit_text, make_quote


def gemini_reading(**overrides) -> LlmTerms:
    """A Gemini response that matches the default test quote."""
    fields = {
        "advance_percent": LlmField(status="found", value="10", quote="10% advance"),
        "payment_days": LlmField(status="found", value="45", quote="within 45 days of delivery"),
        "delivery_days": LlmField(status="found", value="24", quote="within 24 days of PO"),
        "penalty_percent": LlmField(status="found", value="1", quote=DELAY),
        "penalty_basis": LlmField(status="found", value="order_value", quote=DELAY),
        "validity_days": LlmField(status="found", value="45", quote="valid for 45 days"),
        "tin": LlmField(status="found", value="101458013391", quote="TIN: 101458013391"),
        "bin": LlmField(status="found", value="000170141-0101", quote="BIN: 000170141-0101"),
    }
    return LlmTerms(**{**fields, **overrides})


def audit_with_gemini(monkeypatch, text, response=None, error=None):
    def fake_call(_):
        if error:
            raise error
        return response

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("core.llm.call_gemini", fake_call)
    return audit_text(monkeypatch, text, mode=LlmMode.LIVE)


def test_agreement_is_marked_as_two_readers(monkeypatch):
    report = audit_with_gemini(monkeypatch, make_quote(), gemini_reading())
    assert report.system_verdict == Verdict.APPROVE
    assert report.terms.advance_percent.source == "regex+gemini"


def test_disagreement_goes_to_a_person(monkeypatch):
    wrong = LlmField(status="found", value="5", quote="10% advance")
    report = audit_with_gemini(monkeypatch, make_quote(), gemini_reading(advance_percent=wrong))
    assert report.system_verdict == Verdict.NEEDS_PERSON
    assert "Readers disagree" in report.terms.advance_percent.note


def test_gemini_cannot_hide_a_rejection_found_by_regex(monkeypatch):
    says_fine = LlmField(status="found", value="24", quote="within 24 days")
    text = make_quote(delivery="Delivery within 60 days of PO.")
    report = audit_with_gemini(monkeypatch, text, gemini_reading(delivery_days=says_fine))
    assert report.system_verdict != Verdict.APPROVE


def test_gemini_can_read_a_clause_regex_cannot(monkeypatch):
    clause = "Late delivery penalty of 1 percent of order value per week."
    reading = gemini_reading(
        penalty_percent=LlmField(status="found", value="1", quote=clause),
        penalty_basis=LlmField(status="found", value="order_value", quote=clause),
    )
    report = audit_with_gemini(monkeypatch, make_quote(delay=clause), reading)
    assert report.system_verdict == Verdict.APPROVE
    assert report.terms.penalty_percent.source == "gemini"


def test_gemini_value_not_in_its_quote_is_not_accepted(monkeypatch):
    clause = "Late delivery penalty of 1 percent of order value per week."
    reading = gemini_reading(penalty_percent=LlmField(status="found", value="2", quote=clause))
    report = audit_with_gemini(monkeypatch, make_quote(delay=clause), reading)
    assert report.system_verdict == Verdict.NEEDS_PERSON


def test_invented_quote_is_not_accepted(monkeypatch):
    clause = "Late delivery penalty of 1 percent of order value per week."
    invented = "The supplier pays 1 percent weekly."
    reading = gemini_reading(penalty_percent=LlmField(status="found", value="1", quote=invented))
    report = audit_with_gemini(monkeypatch, make_quote(delay=clause), reading)
    assert report.system_verdict == Verdict.NEEDS_PERSON
    assert "not found in the document" in report.terms.penalty_percent.note


def test_gemini_cannot_turn_absent_clause_into_present(monkeypatch):
    reading = gemini_reading(
        penalty_percent=LlmField(status="found", value="1", quote="made up"),
        penalty_basis=LlmField(status="found", value="order_value", quote="made up"),
    )
    report = audit_with_gemini(monkeypatch, make_quote(delay=None), reading)
    assert report.system_verdict == Verdict.NEEDS_PERSON


class _BadShape(BaseModel):
    number: int


def _validation_error() -> ValidationError:
    try:
        _BadShape(number="not a number")
    except ValidationError as error:
        return error


@pytest.mark.parametrize("error", [TimeoutError(), RuntimeError("429"), _validation_error()])
def test_gemini_failure_falls_back_to_regex(monkeypatch, error):
    report = audit_with_gemini(monkeypatch, make_quote(), error=error)
    assert report.system_verdict == Verdict.APPROVE
    assert "regex only" in report.llm_note


def test_live_mode_without_key_falls_back_to_regex(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    report = audit_text(monkeypatch, make_quote(), mode=LlmMode.LIVE)
    assert "no API key" in report.llm_note


def test_gemini_schema_covers_every_contract_term():
    assert set(LlmTerms.model_fields) == set(Terms.model_fields)
