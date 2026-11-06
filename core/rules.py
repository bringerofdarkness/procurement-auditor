"""Steps 4 and 5: run every company rule, then choose the verdict.

Each rule returns PASS, FAIL or UNKNOWN. A rule returns None when another rule
already covers the case, for example when delivery is too late to review.
"""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml

from core.math_checks import find_math_errors, has_all_amounts
from core.models import (
    CheckResult,
    CheckStatus,
    ExtractedField,
    FieldStatus,
    RequestComparison,
    RuleSet,
    Severity,
    SupplierDocument,
    Terms,
    Verdict,
)

RULES_PATH = Path(__file__).parent.parent / "config" / "rules.yaml"


@dataclass(frozen=True)
class RuleContext:
    document: SupplierDocument
    terms: Terms
    comparison: RequestComparison
    limits: dict[str, Decimal]


@dataclass(frozen=True)
class Outcome:
    status: CheckStatus
    message: str
    quotes: tuple[str, ...] = ()


RuleCheck = Callable[[RuleContext], Outcome | None]
RULE_CHECKS: dict[str, RuleCheck] = {}


def rule(rule_id: str) -> Callable[[RuleCheck], RuleCheck]:
    """Register a function as the check for a rule in rules.yaml."""

    def register(check: RuleCheck) -> RuleCheck:
        RULE_CHECKS[rule_id] = check
        return check

    return register


def _passed(message: str, *quotes: str | None) -> Outcome:
    return Outcome(CheckStatus.PASS, message, tuple(q for q in quotes if q))


def _failed(message: str, *quotes: str | None) -> Outcome:
    return Outcome(CheckStatus.FAIL, message, tuple(q for q in quotes if q))


def _unknown(message: str, *quotes: str | None) -> Outcome:
    return Outcome(CheckStatus.UNKNOWN, message, tuple(q for q in quotes if q))


def _unreadable(field: ExtractedField, what: str) -> Outcome:
    return _unknown(field.note or f"Could not read {what}.", field.quote)


@rule("request_match")
def check_request_match(context: RuleContext) -> Outcome:
    comparison = context.comparison
    if comparison.is_matched:
        return _passed("Item, unit and PR reference match the purchase request.", comparison.quote)
    return _unknown(" ".join(comparison.problems), comparison.quote)


@rule("price_over_limit")
def check_price_over_limit(context: RuleContext) -> Outcome:
    percent = context.comparison.price_difference_percent
    limit = context.limits["price_over_max_reject_percent"]
    quote = context.comparison.quote
    if percent is None:
        return _unknown("Unit price could not be compared with the maximum.", quote)
    if percent > limit:
        return _failed(
            f"Unit price {context.comparison.quoted_price} is {percent:.2f}% above the maximum "
            f"{context.comparison.maximum_price}. The limit is {limit}%.",
            quote,
        )
    return _passed(f"Unit price is not more than {limit}% above the maximum.", quote)


@rule("price_above_max")
def check_price_above_max(context: RuleContext) -> Outcome | None:
    percent = context.comparison.price_difference_percent
    limit = context.limits["price_over_max_reject_percent"]
    quote = context.comparison.quote
    if percent is None:
        return _unknown("Unit price could not be compared with the maximum.", quote)
    if percent > limit:
        return None
    if percent > 0:
        return _failed(
            f"Unit price {context.comparison.quoted_price} is {percent:.2f}% above the maximum "
            f"{context.comparison.maximum_price}.",
            quote,
        )
    return _passed(
        f"Unit price {context.comparison.quoted_price} is within the maximum "
        f"{context.comparison.maximum_price}.",
        quote,
    )


@rule("quantity_differs")
def check_quantity(context: RuleContext) -> Outcome:
    comparison = context.comparison
    percent = comparison.quantity_difference_percent
    limit = context.limits["quantity_tolerance_percent"]
    if percent is None:
        return _unknown("Quantity could not be compared with the request.", comparison.quote)
    summary = (
        f"Quoted {comparison.quoted_quantity:,} against {comparison.requested_quantity:,} "
        f"requested ({percent:+.2f}%)."
    )
    if abs(percent) > limit:
        return _failed(f"{summary} The limit is {limit}%.", comparison.quote)
    return _passed(summary, comparison.quote)


@rule("advance_too_high")
def check_advance(context: RuleContext) -> Outcome:
    field = context.terms.advance_percent
    limit = context.limits["advance_max_percent"]
    if field.status != FieldStatus.FOUND or field.number is None:
        return _unreadable(field, "the advance payment")
    if field.number > limit:
        return _failed(f"Advance is {field.number}%. The limit is {limit}%.", field.quote)
    return _passed(f"Advance is {field.number}%.", field.quote)


@rule("no_penalty_clause")
def check_penalty_exists(context: RuleContext) -> Outcome:
    field = context.terms.penalty_percent
    if field.status == FieldStatus.ABSENT:
        return _failed(field.note or "The contract has no late-delivery penalty clause.")
    if field.status == FieldStatus.UNCLEAR:
        return _unreadable(field, "the penalty clause")
    return _passed("Late-delivery penalty clause is present.", field.quote)


@rule("penalty_too_low")
def check_penalty_terms(context: RuleContext) -> Outcome | None:
    percent = context.terms.penalty_percent
    basis = context.terms.penalty_basis
    minimum = context.limits["penalty_min_percent"]
    if percent.status == FieldStatus.ABSENT:
        return None
    if percent.status != FieldStatus.FOUND or percent.number is None:
        return _unreadable(percent, "the penalty rate")
    if percent.number < minimum:
        return _failed(f"Penalty is {percent.number}%. The minimum is {minimum}%.", percent.quote)
    if basis.status != FieldStatus.FOUND or basis.value != "order_value":
        return _unknown(
            f"Penalty is {percent.number}% per week, but the clause does not say "
            "it is a percentage of order value.",
            percent.quote,
        )
    return _passed(f"Penalty is {percent.number}% of order value per week.", percent.quote)


@rule("tin_bin_missing")
def check_tax_ids(context: RuleContext) -> Outcome:
    tin, bin_number = context.terms.tin, context.terms.bin
    missing = [
        label
        for label, field in (("TIN", tin), ("BIN", bin_number))
        if field.status == FieldStatus.ABSENT
    ]
    if missing:
        return _failed(f"Missing: {' and '.join(missing)}.", tin.quote or bin_number.quote)
    if tin.status != FieldStatus.FOUND or bin_number.status != FieldStatus.FOUND:
        return _unknown("TIN or BIN could not be read.", tin.quote or bin_number.quote)
    return _passed(f"TIN {tin.value} and BIN {bin_number.value} are present.", tin.quote)


@rule("delivery_too_late")
def check_delivery_limit(context: RuleContext) -> Outcome:
    field = context.terms.delivery_days
    limit = context.limits["delivery_max_days"]
    if field.status != FieldStatus.FOUND or field.number is None:
        return _unreadable(field, "the delivery time")
    if field.number > limit:
        return _failed(f"Delivery is {field.number} days. The limit is {limit}.", field.quote)
    return _passed(f"Delivery is {field.number} days after the PO.", field.quote)


@rule("delivery_needs_check")
def check_delivery_band(context: RuleContext) -> Outcome | None:
    field = context.terms.delivery_days
    if field.status != FieldStatus.FOUND or field.number is None:
        return _unreadable(field, "the delivery time")
    if field.number > context.limits["delivery_max_days"]:
        return None
    if field.number > context.limits["delivery_auto_ok_max_days"]:
        return _failed(f"Delivery is {field.number} days, so a person must check it.", field.quote)
    return _passed(f"Delivery is {field.number} days after the PO.", field.quote)


@rule("payment_terms")
def check_payment_terms(context: RuleContext) -> Outcome:
    field = context.terms.payment_days
    low, high = context.limits["payment_min_days"], context.limits["payment_max_days"]
    if field.status != FieldStatus.FOUND or field.number is None:
        return _unreadable(field, "the payment terms")
    if low <= field.number <= high:
        return _passed(f"Payment within {field.number} days is in the {low}-{high} range.", field.quote)
    return _failed(f"Payment up to {field.number} days is outside {low}-{high} days.", field.quote)


@rule("vat_not_separate")
def check_vat(context: RuleContext) -> Outcome:
    document = context.document
    required = context.limits["vat_percent"]
    if not has_all_amounts(document):
        return _unknown("The price table could not be read.")
    if document.vat_amount is None:
        return _failed(f"VAT is not shown separately at {required}%.", document.total_quote)
    if document.vat_percent != required:
        return _failed(f"VAT is {document.vat_percent}%, not {required}%.", document.vat_quote)
    return _passed(f"VAT is shown separately at {required}%.", document.vat_quote)


@rule("numbers_add_up")
def check_numbers(context: RuleContext) -> Outcome:
    document = context.document
    if not has_all_amounts(document):
        return _unknown("The price table could not be read.")

    quotes = [line.quote for line in document.lines]
    quotes += [document.subtotal_quote, document.vat_quote, document.total_quote]
    errors = find_math_errors(document)
    if errors:
        return _failed(" ".join(errors), *quotes)
    return _passed("Line total, subtotal, VAT and total all add up.", *quotes)


@rule("validity_too_short")
def check_validity(context: RuleContext) -> Outcome:
    field = context.terms.validity_days
    minimum = context.limits["validity_min_days"]
    if field.status != FieldStatus.FOUND or field.number is None:
        return _unreadable(field, "the validity period")
    if field.number < minimum:
        return _failed(f"Valid for {field.number} days. The minimum is {minimum}.", field.quote)
    return _passed(f"Valid for {field.number} days.", field.quote)


def load_rules(path: Path = RULES_PATH) -> RuleSet:
    """Load rules.yaml and stop early if a rule has no check in the code."""
    with path.open(encoding="utf-8") as file:
        rule_set = RuleSet(**yaml.safe_load(file))

    unknown_ids = [config.id for config in rule_set.rules if config.id not in RULE_CHECKS]
    if unknown_ids:
        raise ValueError(f"rules.yaml has rules with no check in core/rules.py: {unknown_ids}")
    return rule_set


def run_checks(
    document: SupplierDocument,
    terms: Terms,
    comparison: RequestComparison,
    rule_set: RuleSet,
) -> list[CheckResult]:
    """Run every rule. A rule that crashes counts as UNKNOWN, never as a pass."""
    context = RuleContext(document, terms, comparison, rule_set.limits)
    results = []
    for config in rule_set.rules:
        try:
            outcome = RULE_CHECKS[config.id](context)
        except Exception as error:  # One broken rule must not stop or pass the audit.
            outcome = _unknown(f"This check could not run: {error}")
        if outcome is not None:
            results.append(
                CheckResult(
                    rule_id=config.id,
                    title=config.title,
                    severity=config.severity,
                    status=outcome.status,
                    message=outcome.message,
                    quotes=list(outcome.quotes),
                )
            )
    return results


def decide(checks: list[CheckResult]) -> tuple[Verdict, list[str]]:
    """Choose the verdict. Approve is only reached when every check passed."""
    rejections = [
        check.message
        for check in checks
        if check.status == CheckStatus.FAIL and check.severity == Severity.REJECT
    ]
    if rejections:
        return Verdict.REJECT, rejections

    open_items = [check.message for check in checks if check.status != CheckStatus.PASS]
    if open_items:
        return Verdict.NEEDS_PERSON, open_items
    if not checks:
        return Verdict.NEEDS_PERSON, ["No rules were run."]
    return Verdict.APPROVE, ["All company rules passed."]
