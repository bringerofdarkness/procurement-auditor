"""Small REST API over the audit workflow. Run: uvicorn api:app --reload"""

from typing import Literal

from fastapi import FastAPI, HTTPException, UploadFile
from pydantic import BaseModel

from core.graph import get_report, resume_review, run_audit
from core.models import AuditReport, Verdict

MAX_UPLOAD_BYTES = 10 * 1024 * 1024

app = FastAPI(title="Supplier Document Checker")


class ReviewRequest(BaseModel):
    decision: Literal["Approve", "Reject"]
    reviewer: str
    note: str = ""


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/audits", status_code=201)
def create_audit(file: UploadFile) -> AuditReport:
    file_name = file.filename or "upload.pdf"
    if not file_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="Only PDF files are accepted.")

    pdf_bytes = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(pdf_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than 10 MB.")
    return run_audit(pdf_bytes, file_name)


@app.get("/audits/{audit_id}")
def read_audit(audit_id: str) -> AuditReport:
    try:
        return get_report(audit_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Audit not found.") from None


@app.post("/audits/{audit_id}/review")
def review_audit(audit_id: str, review: ReviewRequest) -> AuditReport:
    try:
        return resume_review(audit_id, Verdict(review.decision), review.reviewer, review.note)
    except KeyError:
        raise HTTPException(status_code=404, detail="Audit not found.") from None
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
