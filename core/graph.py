"""The fixed-step LangGraph workflow, and the functions used to run it."""

import operator
import uuid
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from core import models
from core.extractors import extract_terms, merge_terms, parse_document, verify_quotes
from core.llm import LlmMode, default_mode, read_terms
from core.models import (
    AuditReport,
    AuditStatus,
    HumanDecision,
    RequestComparison,
    RuleSet,
    SupplierDocument,
    Terms,
    Verdict,
)
from core.pdf_reader import read_pdf_text
from core.purchase_request import compare_to_request, load_purchase_request
from core.rules import decide, load_rules, run_checks


class AuditState(TypedDict, total=False):
    audit_id: str
    file_name: str
    pdf_bytes: bytes
    rule_set: RuleSet
    llm_mode: LlmMode
    text: str
    document: SupplierDocument
    terms: Terms
    llm_note: str
    comparison: RequestComparison
    checks: list[models.CheckResult]
    report: AuditReport
    human_decision: HumanDecision
    trace: Annotated[list[str], operator.add]


def read_pdf_step(state: AuditState) -> dict[str, Any]:
    text, error = read_pdf_text(state["pdf_bytes"])
    return {"text": text, "trace": [f"read_pdf: {error or f'{len(text)} characters read'}"]}


def extract_fields_step(state: AuditState) -> dict[str, Any]:
    text = state["text"]
    gemini_terms, llm_note = read_terms(text, state["llm_mode"])
    return {
        "document": parse_document(text),
        "terms": merge_terms(extract_terms(text), gemini_terms),
        "llm_note": llm_note,
        "trace": [f"extract_fields: {llm_note}"],
    }


def verify_quotes_step(state: AuditState) -> dict[str, Any]:
    terms = verify_quotes(state["terms"], state["text"])
    return {"terms": terms, "trace": ["verify_quotes: checked every quote against the document"]}


def compare_to_request_step(state: AuditState) -> dict[str, Any]:
    comparison = compare_to_request(state["document"], load_purchase_request())
    result = "matched" if comparison.is_matched else "; ".join(comparison.problems)
    return {"comparison": comparison, "trace": [f"compare_to_request: {result}"]}


def check_rules_step(state: AuditState) -> dict[str, Any]:
    checks = run_checks(
        state["document"], state["terms"], state["comparison"], state["rule_set"]
    )
    return {"checks": checks, "trace": [f"check_rules: ran {len(checks)} checks"]}


def decide_step(state: AuditState) -> dict[str, Any]:
    verdict, reasons = decide(state["checks"])
    trace = [f"decide: {verdict.value}"]
    report = AuditReport(
        audit_id=state["audit_id"],
        file_name=state["file_name"],
        status=AuditStatus.WAITING_FOR_PERSON,
        system_verdict=verdict,
        reasons=reasons,
        document=state["document"],
        terms=state["terms"],
        comparison=state["comparison"],
        checks=state["checks"],
        llm_note=state["llm_note"],
        trace=[*state["trace"], *trace],
    )
    return {"report": report, "trace": trace}


def route_after_decide(state: AuditState) -> str:
    needs_person = state["report"].system_verdict == Verdict.NEEDS_PERSON
    return "human_review" if needs_person else "final_report"


def human_review_step(state: AuditState) -> dict[str, Any]:
    """Pause the workflow here until a person answers."""
    answer = interrupt({"audit_id": state["audit_id"], "reasons": state["report"].reasons})
    decision = HumanDecision(**answer)
    return {
        "human_decision": decision,
        "trace": [f"human_review: {decision.reviewer} chose {decision.decision.value}"],
    }


def final_report_step(state: AuditState) -> dict[str, Any]:
    decision = state.get("human_decision")
    final_verdict = decision.decision if decision else state["report"].system_verdict
    trace = [f"final_report: {final_verdict.value}"]
    report = state["report"].model_copy(
        update={
            "status": AuditStatus.COMPLETE,
            "final_verdict": final_verdict,
            "human_decision": decision,
            "trace": [*state["trace"], *trace],
        }
    )
    return {"report": report, "trace": trace}


def _checkpoint_serializer() -> JsonPlusSerializer:
    """Allow our own models to be restored when a paused audit resumes."""
    state_types = [
        value
        for value in vars(models).values()
        if isinstance(value, type) and value.__module__ == models.__name__
    ]
    allowed = [(models.__name__, state_type.__name__) for state_type in state_types]
    return JsonPlusSerializer(allowed_msgpack_modules=[*allowed, ("core.llm", "LlmMode")])


def build_graph():
    builder = StateGraph(AuditState)
    steps = [
        ("read_pdf", read_pdf_step),
        ("extract_fields", extract_fields_step),
        ("verify_quotes", verify_quotes_step),
        ("compare_to_request", compare_to_request_step),
        ("check_rules", check_rules_step),
        ("decide", decide_step),
    ]
    previous = START
    for name, step in steps:
        builder.add_node(name, step)
        builder.add_edge(previous, name)
        previous = name

    builder.add_node("human_review", human_review_step)
    builder.add_node("final_report", final_report_step)
    builder.add_conditional_edges("decide", route_after_decide)
    builder.add_edge("human_review", "final_report")
    builder.add_edge("final_report", END)
    return builder.compile(checkpointer=MemorySaver(serde=_checkpoint_serializer()))


GRAPH = build_graph()


def _config(audit_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": audit_id}}


def run_audit(
    pdf_bytes: bytes,
    file_name: str,
    rule_set: RuleSet | None = None,
    llm_mode: LlmMode | None = None,
) -> AuditReport:
    """Check one document. A report in WAITING_FOR_PERSON status is paused for review."""
    audit_id = str(uuid.uuid4())
    state = {
        "audit_id": audit_id,
        "file_name": file_name,
        "pdf_bytes": pdf_bytes,
        "rule_set": rule_set or load_rules(),
        "llm_mode": llm_mode or default_mode(),
        "trace": [],
    }
    GRAPH.invoke(state, _config(audit_id))
    return get_report(audit_id)


def get_report(audit_id: str) -> AuditReport:
    """Return the latest report. Raises KeyError if the audit does not exist."""
    values = GRAPH.get_state(_config(audit_id)).values
    if "report" not in values:
        raise KeyError(audit_id)
    return values["report"]


def resume_review(audit_id: str, decision: Verdict, reviewer: str, note: str = "") -> AuditReport:
    """Give a person's decision to a paused audit and finish it."""
    if decision == Verdict.NEEDS_PERSON:
        raise ValueError("A person must choose Approve or Reject.")
    if get_report(audit_id).status != AuditStatus.WAITING_FOR_PERSON:
        raise ValueError("This audit is not waiting for a person.")

    answer = {"decision": decision, "reviewer": reviewer, "note": note}
    GRAPH.invoke(Command(resume=answer), _config(audit_id))
    return get_report(audit_id)
