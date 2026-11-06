"""Build quotation text for altered test cases. No real data is used."""

from decimal import Decimal

from core.graph import run_audit
from core.llm import LlmMode

PAYMENT = "10% advance payable with the purchase order. Balance within 45 days of delivery."
DELIVERY = "Delivery within 24 days of PO."
DELAY = "Late delivery penalty of 1% of order value per week."
VALIDITY = "This quotation is valid for 45 days from the date above."
TAX_LINE = "Supplier TIN: 101458013391 BIN: 000170141-0101"


def make_quote(
    price="472.00",
    quantity="12000",
    item="A Cotton twill fabric, 280 gsm",
    unit="metre",
    reference="PR-2026-114",
    payment=PAYMENT,
    delivery=DELIVERY,
    delay=DELAY,
    validity=VALIDITY,
    tax_line=TAX_LINE,
):
    """Return valid quote text by default. Pass None to remove a clause."""
    amount = Decimal(quantity) * Decimal(price)
    vat = amount * Decimal("0.15")
    clauses = [
        ("Payment", payment),
        ("Delivery", delivery),
        ("Delay", delay),
        ("Validity", validity),
        ("Quality", "Goods are supplied as per the buyer's approved sample."),
    ]
    terms = [
        f"{number}. {heading}. {body}"
        for number, (heading, body) in enumerate(
            [clause for clause in clauses if clause[1] is not None], start=1
        )
    ]
    return "\n".join(
        [
            "Test Supplier Ltd",
            "QUOTATION",
            "Quotation no. QT-TEST Date 2026-10-21",
            f"To Aamar Garments Ltd (fictional) Reference {reference}",
            "Item Description Qty Unit Unit price (BDT) Amount (BDT)",
            f"{item} {int(quantity):,} {unit} {Decimal(price):,.2f} {amount:,.2f}",
            f"Subtotal {amount:,.2f}",
            f"VAT 15% {vat:,.2f}",
            f"Total {amount + vat:,.2f}",
            tax_line or "",
            "TERMS AND CONDITIONS",
            *terms,
            "For Test Supplier Ltd",
        ]
    )


def audit_text(monkeypatch, text, mode=LlmMode.OFFLINE, rule_set=None):
    """Run the real workflow on text, skipping only the PDF reader."""
    monkeypatch.setattr("core.graph.read_pdf_text", lambda _: (text, None if text else "no text"))
    return run_audit(b"", "test.pdf", rule_set, mode)
