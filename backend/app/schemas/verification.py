from datetime import datetime

from pydantic import BaseModel


class DocumentSubmitRequest(BaseModel):
    document_type: str  # DocumentType enum value
    document_ref: str
    document_number: str | None = None
    expiry_date: datetime | None = None


class DocumentReviewRequest(BaseModel):
    status: str  # "approved", "rejected", "under_review"
    rejection_reason: str | None = None
    review_notes: str | None = None


class DocumentResponse(BaseModel):
    id: int
    driver_profile_id: int
    document_type: str
    status: str
    document_ref: str
    document_number: str | None
    expiry_date: datetime | None
    reviewed_by: int | None
    reviewed_at: datetime | None
    rejection_reason: str | None
    review_notes: str | None
    submitted_at: datetime

    model_config = {"from_attributes": True}


class VerificationStatusResponse(BaseModel):
    documents: list[DocumentResponse]
    missing_required: list[str]
    all_required_approved: bool
