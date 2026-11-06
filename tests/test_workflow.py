"""Human pause and resume, rule configuration, and the REST API."""

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import app
from core.graph import get_report, resume_review, run_audit
from core.llm import LlmMode
from core.models import AuditStatus, CheckStatus, RuleConfig, RuleSet, Severity, Verdict
from core.rules import RULE_CHECKS, Outcome, decide, load_rules, run_checks

PACKS = Path(__file__).parent.parent / "task1-procurement"


def pack(number: int) -> tuple[bytes, str]:
    name = f"supplier-pack-{number:02d}.pdf"
    return (PACKS / name).read_bytes(), name


def audit_pack(number, rule_set=None):
    pdf_bytes, name = pack(number)
    return run_audit(pdf_bytes, name, rule_set, LlmMode.OFFLINE)


def changed_rules(limit=None, severity=None) -> RuleSet:
    rule_set = load_rules()
    if limit:
        rule_set.limits[limit[0]] = limit[1]
    if severity:
        for config in rule_set.rules:
            if config.id == severity[0]:
                config.severity = severity[1]
    return rule_set


def test_review_pack_pauses_then_records_the_person():
    report = audit_pack(7)
    assert report.status == AuditStatus.WAITING_FOR_PERSON
    assert report.final_verdict is None

    finished = resume_review(report.audit_id, Verdict.APPROVE, "Rahima", "Short supply accepted.")
    assert finished.status == AuditStatus.COMPLETE
    assert finished.final_verdict == Verdict.APPROVE
    assert finished.system_verdict == Verdict.NEEDS_PERSON
    assert finished.human_decision.reviewer == "Rahima"
    assert "human_review" in finished.trace[-2]


def test_finished_audit_cannot_be_reviewed():
    with pytest.raises(ValueError):
        resume_review(audit_pack(1).audit_id, Verdict.REJECT, "Rahima")


def test_person_must_make_a_real_decision():
    with pytest.raises(ValueError):
        resume_review(audit_pack(7).audit_id, Verdict.NEEDS_PERSON, "Rahima")


def test_unknown_audit_raises_key_error():
    with pytest.raises(KeyError):
        get_report("does-not-exist")


def test_changing_a_limit_changes_the_verdict():
    rules = changed_rules(limit=("advance_max_percent", Decimal(40)))
    assert audit_pack(5).system_verdict == Verdict.REJECT
    assert audit_pack(5, rules).system_verdict == Verdict.APPROVE


def test_moving_severity_changes_the_verdict():
    rules = changed_rules(severity=("tin_bin_missing", Severity.REVIEW))
    assert audit_pack(8, rules).system_verdict == Verdict.NEEDS_PERSON


def test_removing_a_rule_stops_it_running():
    rules = load_rules()
    rules.rules = [config for config in rules.rules if config.id != "quantity_differs"]
    assert audit_pack(7, rules).system_verdict == Verdict.APPROVE


def test_rule_without_code_stops_at_load(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text(
        "limits: {}\nrules:\n  - {id: made_up, severity: reject, title: Made up}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="made_up"):
        load_rules(path)


def test_a_new_rule_only_needs_yaml_and_one_function(monkeypatch, tmp_path):
    def supplier_is_not_blocked(context):
        if context.document.supplier_name == "Padma Textile Mills Ltd":
            return Outcome(CheckStatus.FAIL, "This supplier is blocked.")
        return Outcome(CheckStatus.PASS, "Supplier is not blocked.")

    monkeypatch.setitem(RULE_CHECKS, "blocked_supplier", supplier_is_not_blocked)
    path = tmp_path / "rules.yaml"
    path.write_text(
        "limits: {}\nrules:\n  - {id: blocked_supplier, severity: reject, title: Blocked supplier}\n",
        encoding="utf-8",
    )
    assert audit_pack(1, load_rules(path)).system_verdict == Verdict.REJECT
    assert audit_pack(2, load_rules(path)).system_verdict == Verdict.APPROVE


def test_a_crashing_rule_is_unknown_not_a_pass(monkeypatch):
    def broken(_):
        raise RuntimeError("boom")

    monkeypatch.setitem(RULE_CHECKS, "broken", broken)
    rule_set = RuleSet(
        limits={}, rules=[RuleConfig(id="broken", severity=Severity.REJECT, title="Broken")]
    )
    report = audit_pack(1)
    checks = run_checks(report.document, report.terms, report.comparison, rule_set)
    assert checks[0].status == CheckStatus.UNKNOWN
    assert decide(checks)[0] == Verdict.NEEDS_PERSON


def test_no_checks_never_approves():
    assert decide([])[0] == Verdict.NEEDS_PERSON


client = TestClient(app)


def upload(number: int):
    pdf_bytes, name = pack(number)
    return client.post("/audits", files={"file": (name, pdf_bytes, "application/pdf")})


def test_api_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_api_full_review_flow():
    created = upload(7)
    assert created.status_code == 201
    audit_id = created.json()["audit_id"]
    assert created.json()["status"] == "waiting_for_person"

    review = {"decision": "Reject", "reviewer": "Rahima"}
    response = client.post(f"/audits/{audit_id}/review", json=review)
    assert response.status_code == 200
    assert client.get(f"/audits/{audit_id}").json()["final_verdict"] == "Reject"

    assert client.post(f"/audits/{audit_id}/review", json=review).status_code == 409


def test_api_errors():
    assert client.get("/audits/missing").status_code == 404
    review = {"decision": "Approve", "reviewer": "Rahima"}
    assert client.post("/audits/missing/review", json=review).status_code == 404

    not_pdf = client.post("/audits", files={"file": ("a.txt", b"hello", "text/plain")})
    assert not_pdf.status_code == 415

    audit_id = upload(7).json()["audit_id"]
    invalid = {"decision": "Needs a person to check", "reviewer": "Rahima"}
    assert client.post(f"/audits/{audit_id}/review", json=invalid).status_code == 422
