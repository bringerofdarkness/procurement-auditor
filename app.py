"""Streamlit screen for procurement officers. Run: streamlit run app.py"""

import json
import os
from decimal import Decimal
from pathlib import Path

import streamlit as st

from core.graph import resume_review, run_audit
from core.llm import LlmMode, default_mode
from core.models import AuditReport, AuditStatus, CheckResult, CheckStatus, RuleSet, Severity, Verdict
from core.rules import load_rules

ROOT = Path(__file__).parent
PACKS = ROOT / "task1-procurement"
EXPECTED = json.loads((ROOT / "data" / "expected_verdicts.json").read_text(encoding="utf-8"))

VERDICT_BADGES = {
    Verdict.APPROVE: ("Approve", "green"),
    Verdict.REJECT: ("Reject", "red"),
    Verdict.NEEDS_PERSON: ("Needs a person to check", "orange"),
}
CHECK_LABELS = {
    CheckStatus.PASS: "✅ Pass",
    CheckStatus.FAIL: "❌ Problem",
    CheckStatus.UNKNOWN: "❓ Not sure",
}
MODE_LABELS = {
    LlmMode.REPLAY: "Saved Gemini responses (no key needed)",
    LlmMode.LIVE: "Live Gemini",
    LlmMode.OFFLINE: "Regex only",
}


def _clean_decimal(value: float) -> Decimal:
    """Turn 45.0 from a number box into 45, so messages read naturally."""
    return Decimal(format(Decimal(str(value)).normalize(), "f"))


def sidebar_settings() -> tuple[RuleSet, LlmMode]:
    """Let a user change rules for this session without editing any file."""
    st.sidebar.header("Settings")
    modes = list(MODE_LABELS)
    if not os.getenv("GEMINI_API_KEY"):
        modes.remove(LlmMode.LIVE)
    start_mode = default_mode() if default_mode() in modes else LlmMode.REPLAY
    mode = st.sidebar.selectbox(
        "Second reader",
        modes,
        index=modes.index(start_mode),
        format_func=MODE_LABELS.get,
    )

    rule_set = load_rules()
    with st.sidebar.expander("Rule limits"):
        limits = {
            name: _clean_decimal(
                st.number_input(name.replace("_", " "), value=float(value), step=0.5)
            )
            for name, value in rule_set.limits.items()
        }
    with st.sidebar.expander("Rule severity"):
        severities = [Severity.REJECT, Severity.REVIEW]
        rules = [
            config.model_copy(
                update={
                    "severity": st.selectbox(
                        config.title,
                        severities,
                        index=severities.index(config.severity),
                        format_func=lambda severity: severity.value.title(),
                        key=f"severity_{config.id}",
                    )
                }
            )
            for config in rule_set.rules
        ]
    return RuleSet(limits=limits, rules=rules), mode


def audit_samples(rule_set: RuleSet, mode: LlmMode) -> dict[str, AuditReport]:
    return {
        name: run_audit((PACKS / name).read_bytes(), name, rule_set, mode) for name in EXPECTED
    }


def current_verdict(report: AuditReport) -> Verdict:
    return report.final_verdict or report.system_verdict


def show_summary(reports: dict[str, AuditReport]) -> None:
    samples = [report for name, report in reports.items() if name in EXPECTED]
    correct = sum(report.system_verdict.value == EXPECTED[report.file_name] for report in samples)
    verdicts = [report.system_verdict for report in reports.values()]
    columns = st.columns(4)
    columns[0].metric("Correct on samples", f"{correct} / {len(samples)}")
    columns[1].metric("Approve", verdicts.count(Verdict.APPROVE))
    columns[2].metric("Reject", verdicts.count(Verdict.REJECT))
    columns[3].metric("Needs a person", verdicts.count(Verdict.NEEDS_PERSON))
    st.caption(
        "BIAI sent no answer key. The score compares against our own reading of the "
        "company rules, using the default limits."
    )

    st.dataframe(
        [
            {
                "File": report.file_name,
                "Supplier": report.document.supplier_name,
                "System answer": report.system_verdict.value,
                "Final decision": report.final_verdict.value
                if report.final_verdict
                else "Waiting for a person",
                "Main reason": report.reasons[0] if report.reasons else "",
            }
            for report in reports.values()
        ],
        hide_index=True,
        width="stretch",
    )


def show_comparison(report: AuditReport) -> None:
    comparison = report.comparison
    st.subheader("Quote against purchase request")
    if comparison.quoted_price is None:
        st.warning(" ".join(comparison.problems))
        return
    st.table(
        [
            {
                "": "Unit price (BDT)",
                "Quote": f"{comparison.quoted_price:,.2f}",
                "Request": f"{comparison.maximum_price:,.2f} maximum",
                "Difference": f"{comparison.price_difference_percent:+.2f}%",
            },
            {
                "": "Quantity",
                "Quote": f"{comparison.quoted_quantity:,}",
                "Request": f"{comparison.requested_quantity:,}",
                "Difference": f"{comparison.quantity_difference_percent:+.2f}%",
            },
        ]
    )


def show_check(check: CheckResult) -> None:
    st.markdown(f"**{CHECK_LABELS[check.status]}: {check.title}** ({check.severity.value} rule)")
    st.write(check.message)
    for quote in check.quotes:
        st.code(quote, language=None, wrap_lines=True)


def show_review_form(report: AuditReport, reports: dict[str, AuditReport]) -> None:
    st.subheader("A person must decide")
    with st.form(f"review_{report.audit_id}"):
        decision = st.radio("Decision", [Verdict.APPROVE, Verdict.REJECT], format_func=lambda v: v.value)
        reviewer = st.text_input("Your name")
        note = st.text_area("Note")
        if st.form_submit_button("Submit decision", type="primary", key="submit_review"):
            if not reviewer.strip():
                st.error("Please enter your name.")
                return
            reports[report.file_name] = resume_review(
                report.audit_id, decision, reviewer.strip(), note
            )
            st.rerun()


def show_report(report: AuditReport, reports: dict[str, AuditReport]) -> None:
    label, color = VERDICT_BADGES[current_verdict(report)]
    st.markdown(f"### :{color}[{label}]")
    if report.human_decision:
        st.write(
            f"Decided by {report.human_decision.reviewer}. "
            f"The system's answer was: {report.system_verdict.value}."
        )
        if report.human_decision.note:
            st.write(f"Note: {report.human_decision.note}")

    st.subheader("Why")
    for reason in report.reasons:
        st.write(f"- {reason}")

    if report.status == AuditStatus.WAITING_FOR_PERSON:
        show_review_form(report, reports)

    document = report.document
    st.subheader("What was read")
    st.write(
        f"**Supplier:** {document.supplier_name or 'Not read'}  \n"
        f"**Quotation:** {document.quotation_no or 'Not read'}, "
        f"dated {document.quotation_date or 'not read'}  \n"
        f"**Delivery:** {_delivery_text(report)}  \n"
        f"**Second reader:** {report.llm_note}"
    )
    show_comparison(report)

    st.subheader("All checks, with the exact text")
    problems_first = sorted(report.checks, key=lambda check: check.status == CheckStatus.PASS)
    for check in problems_first:
        show_check(check)

    with st.expander("Workflow steps"):
        for step in report.trace:
            st.write(step)
    st.download_button(
        "Download report (JSON)",
        report.model_dump_json(indent=2),
        file_name=f"{Path(report.file_name).stem}-report.json",
        mime="application/json",
    )


def _delivery_text(report: AuditReport) -> str:
    days = report.terms.delivery_days.value
    return f"{days} days after the purchase order" if days else "Not read"


def main() -> None:
    st.set_page_config(page_title="Supplier Document Checker", layout="wide")
    st.title("Supplier Document Checker")
    st.write(
        "Checks each supplier quote against the purchase request and company rules. "
        "When it is not sure, it stops and asks a person."
    )

    rule_set, mode = sidebar_settings()
    if "reports" not in st.session_state:
        st.session_state.reports = audit_samples(rule_set, mode)
    reports: dict[str, AuditReport] = st.session_state.reports

    if st.sidebar.button("Run all samples again", type="primary"):
        reports.update(audit_samples(rule_set, mode))

    uploaded = st.sidebar.file_uploader("Check your own PDF", type="pdf")
    if uploaded and st.sidebar.button("Check this PDF"):
        report = run_audit(uploaded.getvalue(), uploaded.name, rule_set, mode)
        reports[uploaded.name] = report

    show_summary(reports)
    st.divider()
    selected = st.selectbox("Open a document", list(reports), key="selected_document")
    show_report(reports[selected], reports)


if __name__ == "__main__":
    main()
