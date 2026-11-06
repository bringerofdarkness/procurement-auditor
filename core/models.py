"""Data shapes passed between the pipeline steps."""

from decimal import Decimal, InvalidOperation
from enum import Enum

from pydantic import BaseModel, Field


class Verdict(str, Enum):
    APPROVE = "Approve"
    REJECT = "Reject"
    NEEDS_PERSON = "Needs a person to check"


class Severity(str, Enum):
    REJECT = "reject"
    REVIEW = "review"


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class FieldStatus(str, Enum):
    FOUND = "found"
    ABSENT = "absent"  # Confirmed not in the document.
    UNCLEAR = "unclear"  # Mentioned but unreadable, or the document is unreadable.


class AuditStatus(str, Enum):
    WAITING_FOR_PERSON = "waiting_for_person"
    COMPLETE = "complete"


class ExtractedField(BaseModel):
    """One value read from the contract, with the text that proves it."""

    status: FieldStatus = FieldStatus.UNCLEAR
    value: str | None = None
    quote: str | None = None
    source: str = "regex"
    note: str | None = None

    @property
    def number(self) -> Decimal | None:
        try:
            return Decimal(self.value) if self.value is not None else None
        except InvalidOperation:
            return None


class Terms(BaseModel):
    """Contract terms the company rules depend on."""

    advance_percent: ExtractedField = Field(default_factory=ExtractedField)
    payment_days: ExtractedField = Field(default_factory=ExtractedField)
    delivery_days: ExtractedField = Field(default_factory=ExtractedField)
    penalty_percent: ExtractedField = Field(default_factory=ExtractedField)
    penalty_basis: ExtractedField = Field(default_factory=ExtractedField)
    validity_days: ExtractedField = Field(default_factory=ExtractedField)
    tin: ExtractedField = Field(default_factory=ExtractedField)
    bin: ExtractedField = Field(default_factory=ExtractedField)


class LineItem(BaseModel):
    item: str
    description: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    amount: Decimal
    quote: str


class SupplierDocument(BaseModel):
    """The quotation header and price table."""

    supplier_name: str | None = None
    quotation_no: str | None = None
    quotation_date: str | None = None
    reference: str | None = None
    lines: list[LineItem] = Field(default_factory=list)
    subtotal: Decimal | None = None
    subtotal_quote: str | None = None
    vat_percent: Decimal | None = None
    vat_amount: Decimal | None = None
    vat_quote: str | None = None
    total: Decimal | None = None
    total_quote: str | None = None


class RequestComparison(BaseModel):
    """How the quoted line differs from the purchase request."""

    problems: list[str] = Field(default_factory=list)
    item: str | None = None
    quoted_quantity: Decimal | None = None
    requested_quantity: Decimal | None = None
    quantity_difference_percent: Decimal | None = None
    quoted_price: Decimal | None = None
    maximum_price: Decimal | None = None
    price_difference_percent: Decimal | None = None
    quote: str | None = None

    @property
    def is_matched(self) -> bool:
        return not self.problems


class RuleConfig(BaseModel):
    id: str
    severity: Severity
    title: str


class RuleSet(BaseModel):
    limits: dict[str, Decimal]
    rules: list[RuleConfig]


class CheckResult(BaseModel):
    rule_id: str
    title: str
    severity: Severity
    status: CheckStatus
    message: str
    quotes: list[str] = Field(default_factory=list)


class HumanDecision(BaseModel):
    decision: Verdict
    reviewer: str
    note: str = ""


class AuditReport(BaseModel):
    """The final answer for one document."""

    audit_id: str
    file_name: str
    status: AuditStatus
    system_verdict: Verdict
    final_verdict: Verdict | None = None
    human_decision: HumanDecision | None = None
    reasons: list[str]
    document: SupplierDocument
    terms: Terms
    comparison: RequestComparison
    checks: list[CheckResult]
    llm_note: str
    trace: list[str]
