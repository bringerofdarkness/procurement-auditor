"""Exact arithmetic checks. All money uses Decimal, so results are never rounded by accident."""

from decimal import ROUND_HALF_UP, Decimal

from core.models import SupplierDocument

CENT = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _mismatch(label: str, expected: Decimal, shown: Decimal) -> str | None:
    if _money(expected) == _money(shown):
        return None
    return f"{label}: should be {expected:,.2f}, document shows {shown:,.2f}."


def find_math_errors(document: SupplierDocument) -> list[str]:
    """Check line totals, subtotal, VAT amount and grand total."""
    checks = [
        _mismatch(
            f"Line {line.item} ({line.quantity:,} x {line.unit_price})",
            line.quantity * line.unit_price,
            line.amount,
        )
        for line in document.lines
    ]
    lines_total = sum((line.amount for line in document.lines), Decimal(0))

    if document.subtotal is not None:
        checks.append(_mismatch("Subtotal", lines_total, document.subtotal))

    base = document.subtotal if document.subtotal is not None else lines_total
    has_vat_row = document.vat_percent is not None and document.vat_amount is not None
    if has_vat_row:
        checks.append(
            _mismatch(
                f"VAT at {document.vat_percent}%",
                base * document.vat_percent / 100,
                document.vat_amount,
            )
        )

    if document.total is not None:
        tax = document.vat_amount if has_vat_row else Decimal(0)
        checks.append(_mismatch("Total", base + tax, document.total))

    return [check for check in checks if check is not None]


def has_all_amounts(document: SupplierDocument) -> bool:
    return bool(document.lines) and document.total is not None
