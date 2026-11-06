"""Step 2: turn document text into structured data.

The price table is always read by code. Contract terms are read by regex and,
when available, by Gemini. The regex rules are strict: wording they do not
recognise becomes UNCLEAR, so it goes to a person instead of being guessed.
"""

import re
from decimal import Decimal

from core.models import ExtractedField, FieldStatus, LineItem, SupplierDocument, Terms

MONEY = r"([\d,]+\.\d{2})"
NUMBER = r"(\d+(?:\.\d+)?)"

ITEM_ROW = re.compile(
    rf"^([A-Z])\s+(.+?)\s+([\d,]+)\s+(\S+)\s+{MONEY}\s+{MONEY}$", re.MULTILINE
)
SUBTOTAL_ROW = re.compile(rf"^Subtotal\s+{MONEY}$", re.MULTILINE)
VAT_ROW = re.compile(rf"^VAT\s+{NUMBER}%\s+{MONEY}$", re.MULTILINE)
TOTAL_ROW = re.compile(rf"^Total(?:\s*\([^)]*\))?\s+{MONEY}$", re.MULTILINE)

TERMS_HEADING = "TERMS AND CONDITIONS"
CLAUSE_START = re.compile(r"^\d+\.\s+([A-Z][A-Za-z ]*)\.\s", re.MULTILINE)
SIGNATURE = re.compile(r"\nFor\s.*", re.DOTALL)

PENALTY_WORDS = re.compile(
    r"\b(late|delay|delays|delayed|penalty|penalties|liquidated damages)\b", re.IGNORECASE
)
WEEKLY = re.compile(r"per week|each (full )?week|weekly|a week", re.IGNORECASE)
ORDER_VALUE = re.compile(r"of (the )?order value", re.IGNORECASE)
PENALTY_BASIS_VALUES = {"order_value", "unspecified"}


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def _to_decimal(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


def _found(value: str, quote: str) -> ExtractedField:
    return ExtractedField(status=FieldStatus.FOUND, value=value, quote=quote)


def _unclear(note: str, quote: str | None = None) -> ExtractedField:
    return ExtractedField(status=FieldStatus.UNCLEAR, note=note, quote=quote)


def _absent(note: str, quote: str | None = None) -> ExtractedField:
    return ExtractedField(status=FieldStatus.ABSENT, note=note, quote=quote)


def _single_value(pattern: str, text: str) -> str | None:
    """Return the value only if the text gives exactly one distinct answer."""
    matches = {Decimal(match) for match in re.findall(pattern, text, re.IGNORECASE)}
    return format(matches.pop(), "f") if len(matches) == 1 else None


def parse_document(text: str) -> SupplierDocument:
    """Read the quotation header and price table."""
    lines = text.splitlines()
    document = SupplierDocument(supplier_name=lines[0].strip() if lines else None)

    for field_name, pattern in {
        "quotation_no": r"Quotation no\.\s*(\S+)",
        "quotation_date": r"\bDate\s+(\d{4}-\d{2}-\d{2})",
        "reference": r"\bReference\s+(\S+)",
    }.items():
        if match := re.search(pattern, text):
            setattr(document, field_name, match.group(1))

    document.lines = [
        LineItem(
            item=row.group(1),
            description=row.group(2),
            quantity=_to_decimal(row.group(3)),
            unit=row.group(4),
            unit_price=_to_decimal(row.group(5)),
            amount=_to_decimal(row.group(6)),
            quote=row.group(0),
        )
        for row in ITEM_ROW.finditer(text)
    ]

    if row := SUBTOTAL_ROW.search(text):
        document.subtotal = _to_decimal(row.group(1))
        document.subtotal_quote = row.group(0)
    if row := VAT_ROW.search(text):
        document.vat_percent = Decimal(row.group(1))
        document.vat_amount = _to_decimal(row.group(2))
        document.vat_quote = row.group(0)
    if row := TOTAL_ROW.search(text):
        document.total = _to_decimal(row.group(1))
        document.total_quote = row.group(0)

    return document


def split_clauses(text: str) -> dict[str, str]:
    """Map clause heading to clause text. Never relies on clause numbers."""
    if TERMS_HEADING not in text:
        return {}
    section = SIGNATURE.sub("", text.split(TERMS_HEADING, 1)[1])
    starts = list(CLAUSE_START.finditer(section))

    clauses = {}
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(section)
        body = section[start.start() : end]
        clauses[start.group(1).lower()] = normalize_whitespace(re.sub(r"^\d+\.\s+", "", body))
    return clauses


def _read_advance(clause: str | None) -> ExtractedField:
    if clause is None:
        return _unclear("No payment clause found.")

    advance_pattern = rf"{NUMBER}\s*%\s+advance"
    has_no_advance = re.search(r"\bno advance\b", clause, re.IGNORECASE)
    percent = _single_value(advance_pattern, clause)

    # A percentage that is neither the advance nor the balance could be the real advance.
    explained = rf"{advance_pattern}|balance\s+{NUMBER}\s*%"
    has_other_percent = "%" in re.sub(explained, "", clause, flags=re.IGNORECASE)

    if has_no_advance and percent is None and not has_other_percent:
        return _found("0", clause)
    if percent is not None and not has_no_advance and not has_other_percent:
        return _found(percent, clause)
    return _unclear("Advance payment wording is not clear.", clause)


def _read_payment_days(clause: str | None) -> ExtractedField:
    """Return the latest payment day, so a 30 to 90 day range gives 90."""
    if clause is None:
        return _unclear("No payment clause found.")

    if ranges := re.findall(r"within\s+(\d+)\s+to\s+(\d+)\s+days", clause, re.IGNORECASE):
        if len(ranges) == 1:
            return _found(ranges[0][1], clause)
        return _unclear("Payment clause gives several ranges.", clause)

    days = _single_value(r"within\s+(\d+)\s+days\s+(?:of|after)\s+delivery", clause)
    if days is None:
        return _unclear("Payment days after delivery are not clear.", clause)
    return _found(days, clause)


def _read_delivery_days(clause: str | None) -> ExtractedField:
    if clause is None:
        return _unclear("No delivery clause found.")

    pattern = r"within\s+(\d+)\s+(day|week)s?\s+(?:of|from)\s+.*?\b(?:PO|purchase order)\b"
    matches = re.findall(pattern, clause, re.IGNORECASE)
    if len(matches) != 1:
        return _unclear("Delivery time after the PO is not clear.", clause)

    amount, unit = matches[0]
    days = int(amount) * 7 if unit.lower() == "week" else int(amount)
    return _found(str(days), clause)


def _read_penalty(clauses: dict[str, str]) -> tuple[ExtractedField, ExtractedField]:
    """Return (penalty percent, penalty basis)."""
    if not clauses:
        missing = _unclear("Terms section could not be read.")
        return missing, missing

    matching = [clause for clause in clauses.values() if PENALTY_WORDS.search(clause)]
    if not matching:
        note = "No clause mentions late delivery or a penalty. Checked: " + ", ".join(clauses) + "."
        return _absent(note), _absent(note)
    if len(matching) > 1:
        note = "Several clauses mention delay or penalty."
        return _unclear(note), _unclear(note)

    clause = matching[0]
    percents = re.findall(rf"{NUMBER}\s*%", clause)
    negated = re.search(r"\bno\b.{0,30}\bpenalty\b|\bwaived\b", clause, re.IGNORECASE)
    if len(set(percents)) != 1 or not WEEKLY.search(clause) or negated:
        note = "Penalty clause exists, but its weekly rate is not clear."
        return _unclear(note, clause), _unclear(note, clause)

    basis = "order_value" if ORDER_VALUE.search(clause) else "unspecified"
    return _found(percents[0], clause), _found(basis, clause)


def _read_validity_days(clause: str | None) -> ExtractedField:
    if clause is None:
        return _unclear("No validity clause found.")
    days = _single_value(r"valid for\s+(\d+)\s+days", clause)
    return _found(days, clause) if days else _unclear("Validity period is not clear.", clause)


def _read_tax_id(text: str, label: str, long_name: str) -> ExtractedField:
    line = next((row for row in text.splitlines() if re.search(rf"\b{label}\b", row, re.I)), None)
    if line is not None:
        if match := re.search(rf"\b{label}\s*:\s*(\d[\d-]*)", line, re.IGNORECASE):
            return _found(match.group(1), line)
        return _unclear(f"{label} is mentioned, but no number is given.", line)

    if re.search(long_name, text, re.IGNORECASE):
        return _unclear(f"{label} is mentioned, but no number could be read.")

    evidence = next((row for row in text.splitlines() if "registration" in row.lower()), None)
    return _absent(f"No {label} in the document.", evidence)


def extract_terms(text: str) -> Terms:
    """Read contract terms using strict regex rules."""
    if not text:
        return Terms()

    clauses = split_clauses(text)
    penalty_percent, penalty_basis = _read_penalty(clauses)
    return Terms(
        advance_percent=_read_advance(clauses.get("payment")),
        payment_days=_read_payment_days(clauses.get("payment")),
        delivery_days=_read_delivery_days(clauses.get("delivery")),
        penalty_percent=penalty_percent,
        penalty_basis=penalty_basis,
        validity_days=_read_validity_days(clauses.get("validity")),
        tin=_read_tax_id(text, "TIN", "tax identification"),
        bin=_read_tax_id(text, "BIN", "business identification"),
    )


def _same_reading(first: ExtractedField, second: ExtractedField) -> bool:
    if first.status != second.status:
        return False
    if first.status != FieldStatus.FOUND:
        return True
    if first.number is not None and second.number is not None:
        return first.number == second.number
    return first.value == second.value


def _merge_field(regex: ExtractedField, gemini: ExtractedField) -> ExtractedField:
    """Combine two readings. Automatic use needs agreement, or a Gemini rescue."""
    if _same_reading(regex, gemini):
        return regex.model_copy(update={"source": "regex+gemini"})

    can_rescue = regex.status == FieldStatus.UNCLEAR and gemini.status == FieldStatus.FOUND
    if can_rescue and _value_appears_in_quote(gemini):
        return gemini.model_copy(update={"note": "Read by Gemini only. Regex could not read it."})

    return ExtractedField(
        status=FieldStatus.UNCLEAR,
        source="regex+gemini",
        quote=regex.quote or gemini.quote,
        note=(
            f"Readers disagree: regex={regex.status.value}:{regex.value}, "
            f"gemini={gemini.status.value}:{gemini.value}."
        ),
    )


def _value_appears_in_quote(field: ExtractedField) -> bool:
    """A Gemini-only value must be visible in its quote, or be weeks turned into days."""
    if field.value is None or field.quote is None:
        return False
    if field.value in PENALTY_BASIS_VALUES:
        return True
    if re.search(rf"(?<![\d.]){re.escape(field.value)}(?![\d])", field.quote):
        return True

    number = field.number
    if number is None or number % 7 != 0:
        return False
    return re.search(rf"\b{number // 7}\s+weeks?\b", field.quote, re.IGNORECASE) is not None


def merge_terms(regex_terms: Terms, gemini_terms: Terms | None) -> Terms:
    """Without Gemini, the regex reading stands alone."""
    if gemini_terms is None:
        return regex_terms
    return Terms(
        **{
            name: _merge_field(getattr(regex_terms, name), getattr(gemini_terms, name))
            for name in Terms.model_fields
        }
    )


def verify_quotes(terms: Terms, text: str) -> Terms:
    """Any value whose quote is not really in the document becomes UNCLEAR."""
    document = normalize_whitespace(text)
    verified = {}
    for name in Terms.model_fields:
        field: ExtractedField = getattr(terms, name)
        is_proven = field.quote is not None and normalize_whitespace(field.quote) in document
        if field.status == FieldStatus.FOUND and not is_proven:
            field = ExtractedField(
                status=FieldStatus.UNCLEAR,
                source=field.source,
                note=f"Quote for this value was not found in the document: {field.quote!r}",
            )
        verified[name] = field
    return Terms(**verified)
