"""The 10 supplied packs. BIAI sent no answer key: expected verdicts are our reading of the rules."""

import json
from pathlib import Path

import pytest

from core.graph import run_audit
from core.llm import LlmMode
from core.models import AuditStatus, CheckStatus, Verdict

ROOT = Path(__file__).parent.parent
PACKS = ROOT / "task1-procurement"
EXPECTED = json.loads((ROOT / "data" / "expected_verdicts.json").read_text(encoding="utf-8"))


def audit(file_name, mode=LlmMode.OFFLINE):
    return run_audit((PACKS / file_name).read_bytes(), file_name, llm_mode=mode)


@pytest.mark.parametrize("mode", [LlmMode.OFFLINE, LlmMode.REPLAY])
@pytest.mark.parametrize("file_name", EXPECTED)
def test_verdict_matches_expected(file_name, mode):
    assert audit(file_name, mode).system_verdict.value == EXPECTED[file_name]


@pytest.mark.parametrize("file_name", EXPECTED)
def test_every_passed_or_failed_check_has_evidence(file_name):
    for check in audit(file_name).checks:
        is_absence_finding = check.rule_id in {"no_penalty_clause", "tin_bin_missing"}
        if check.status != CheckStatus.UNKNOWN and not is_absence_finding:
            assert check.quotes, f"{check.rule_id} has no quote"


def failed_rules(report):
    return {check.rule_id for check in report.checks if check.status != CheckStatus.PASS}


def test_pack_09_reports_all_of_its_problems():
    report = audit("supplier-pack-09.pdf")
    assert {"numbers_add_up", "payment_terms"} <= failed_rules(report)
    assert report.terms.delivery_days.value == "28"
    math_check = next(check for check in report.checks if check.rule_id == "numbers_add_up")
    assert "320,000.00" in math_check.message and "322,000.00" in math_check.message


def test_pack_10_reports_rejection_and_vat_problem():
    assert {"delivery_too_late", "vat_not_separate"} <= failed_rules(audit("supplier-pack-10.pdf"))


def test_pack_08_also_flags_unclear_penalty_basis():
    assert {"tin_bin_missing", "penalty_too_low"} <= failed_rules(audit("supplier-pack-08.pdf"))


def test_pack_05_reads_advance_not_balance():
    assert audit("supplier-pack-05.pdf").terms.advance_percent.value == "40"


def test_pack_02_reads_no_advance_as_zero():
    assert audit("supplier-pack-02.pdf").terms.advance_percent.value == "0"


def test_approved_pack_finishes_without_waiting():
    report = audit("supplier-pack-01.pdf")
    assert report.status == AuditStatus.COMPLETE
    assert report.final_verdict == Verdict.APPROVE
