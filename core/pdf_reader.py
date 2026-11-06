"""Step 1: get the text out of a PDF."""

import io

import pdfplumber


def read_pdf_text(pdf_bytes: bytes) -> tuple[str, str | None]:
    """Return (text, error). A bad file gives empty text, never an exception."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
    except Exception as error:  # pdfplumber raises many types on corrupt files.
        return "", f"Could not open PDF: {error}"

    text = "\n".join(pages).strip()
    if not text:
        return "", "PDF has no readable text. It may be a scan."
    return text, None
