"""Step 3: compare the quote with the company's purchase request."""

import csv
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel

from core.models import RequestComparison, SupplierDocument

PURCHASE_REQUEST_PATH = Path(__file__).parent.parent / "task1-procurement" / "purchase-request.csv"


class RequestLine(BaseModel):
    pr_number: str
    item: str
    description: str
    unit: str
    quantity: Decimal
    maximum_price: Decimal


def load_purchase_request(path: Path = PURCHASE_REQUEST_PATH) -> dict[str, RequestLine]:
    # utf-8-sig: the supplied CSV starts with a byte order mark.
    with path.open(newline="", encoding="utf-8-sig") as file:
        return {
            row["Item"]: RequestLine(
                pr_number=row["PR number"],
                item=row["Item"],
                description=row["Description"],
                unit=row["Unit"],
                quantity=Decimal(row["Quantity requested"]),
                maximum_price=Decimal(row["Maximum unit price (BDT)"]),
            )
            for row in csv.DictReader(file)
        }


def _percent_difference(actual: Decimal, expected: Decimal) -> Decimal:
    return (actual - expected) / expected * 100


def compare_to_request(
    document: SupplierDocument, request: dict[str, RequestLine]
) -> RequestComparison:
    """Any mismatch is recorded as a problem. It is never silently corrected."""
    if len(document.lines) != 1:
        return RequestComparison(
            problems=[f"Expected one item line, found {len(document.lines)}."]
        )

    line = document.lines[0]
    requested = request.get(line.item)
    if requested is None:
        return RequestComparison(
            problems=[f"Item {line.item} is not in the purchase request."],
            item=line.item,
            quote=line.quote,
        )

    problems = []
    if document.reference != requested.pr_number:
        problems.append(
            f"Reference {document.reference} does not match {requested.pr_number}."
        )
    if line.description.lower() != requested.description.lower():
        problems.append(
            f"Description '{line.description}' does not match '{requested.description}'."
        )
    if line.unit.lower() != requested.unit.lower():
        problems.append(f"Unit '{line.unit}' does not match '{requested.unit}'.")

    return RequestComparison(
        problems=problems,
        item=line.item,
        quoted_quantity=line.quantity,
        requested_quantity=requested.quantity,
        quantity_difference_percent=_percent_difference(line.quantity, requested.quantity),
        quoted_price=line.unit_price,
        maximum_price=requested.maximum_price,
        price_difference_percent=_percent_difference(line.unit_price, requested.maximum_price),
        quote=line.quote,
    )
