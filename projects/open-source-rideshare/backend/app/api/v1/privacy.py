"""GDPR/CCPA Data Privacy Compliance endpoints.

Gives users legal control over their data in compliance with GDPR (EU) and
CCPA (California).  All personal data is handled carefully here — input is
validated, errors never leak internal state, and admin operations are
guarded behind role checks.

User endpoints (require authentication):
  GET    /privacy/consents                          — list my consent records
  POST   /privacy/consents                          — record a consent decision
  POST   /privacy/data-export                       — request a data export
  GET    /privacy/data-export/{request_id}          — check export status
  GET    /privacy/data-export/{request_id}/download — download export data
  POST   /privacy/delete-account                    — request account deletion
  GET    /privacy/delete-account/status             — check deletion request
  DELETE /privacy/delete-account/{request_id}       — cancel deletion request

Admin endpoints (require admin role):
  GET  /privacy/admin/exports                           — list all exports
  GET  /privacy/admin/deletions                         — list all deletions
  POST /privacy/admin/deletions/{request_id}/execute    — execute deletion
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_admin
from app.models.privacy import ExportStatus
from app.models.user import User
from app.schemas.privacy import (
    ConsentRecordResponse,
    DataExportRequestResponse,
    DeletionRequestResponse,
    RecordConsentRequest,
    RequestDeletionBody,
)
from app.services import privacy as svc

logger = logging.getLogger(__name__)

router = APIRouter(tags=["privacy"])


# ---------------------------------------------------------------------------
# Consent endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/privacy/consents",
    response_model=list[ConsentRecordResponse],
    summary="List my consent records",
)
def get_my_consents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ConsentRecordResponse]:
    """Return all privacy consent records for the authenticated user."""
    records = svc.get_user_consents(db, current_user.id)
    return [ConsentRecordResponse.model_validate(r) for r in records]


@router.post(
    "/privacy/consents",
    response_model=ConsentRecordResponse,
    status_code=status.HTTP_200_OK,
    summary="Record a consent decision",
)
def record_consent(
    body: RecordConsentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConsentRecordResponse:
    """Record or update the authenticated user's consent for a policy version.

    If a record already exists for this user + policy + version, it is
    updated in place.
    """
    record = svc.record_consent(
        db,
        user_id=current_user.id,
        policy_type=body.policy_type,
        policy_version=body.policy_version,
        consented=body.consented,
        ip_address=body.ip_address,
        user_agent=body.user_agent,
    )
    return ConsentRecordResponse.model_validate(record)


# ---------------------------------------------------------------------------
# Data export endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/privacy/data-export",
    response_model=DataExportRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request a personal data export (GDPR right of access)",
)
def request_data_export(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DataExportRequestResponse:
    """Create a data export request for the authenticated user.

    Returns 409 if there is already a PENDING or PROCESSING request.
    """
    try:
        record = svc.request_data_export(db, current_user.id)
    except ValueError as exc:
        if str(exc) == "export_in_progress":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A data export request is already in progress.",
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bad request.")
    return DataExportRequestResponse.model_validate(record)


@router.get(
    "/privacy/data-export/{request_id}",
    response_model=DataExportRequestResponse,
    summary="Check data export request status",
)
def get_export_status(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DataExportRequestResponse:
    """Return the status of an export request that belongs to the current user."""
    record = svc.get_export_request(db, request_id, current_user.id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Export request not found.",
        )
    return DataExportRequestResponse.model_validate(record)


@router.get(
    "/privacy/data-export/{request_id}/download",
    summary="Download personal data export",
)
def download_export(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Download the exported data for a READY export request.

    Increments the download counter.  Returns 404 if the request is not
    found, does not belong to the user, or has expired.
    """
    record = svc.get_export_request(db, request_id, current_user.id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Export request not found.",
        )

    if record.status == ExportStatus.EXPIRED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Export request has expired.",
        )

    if record.status not in (ExportStatus.READY, ExportStatus.DOWNLOADED):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Export is not yet ready for download.",
        )

    data = svc.generate_user_data_export(db, current_user.id)
    svc.mark_export_downloaded(db, request_id)
    return data


# ---------------------------------------------------------------------------
# Account deletion endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/privacy/delete-account",
    response_model=DeletionRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request account deletion (GDPR right to erasure)",
)
def request_account_deletion(
    body: RequestDeletionBody | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DeletionRequestResponse:
    """Create an account deletion request for the authenticated user.

    Account deletion is scheduled 30 days from now to allow cancellation.
    Returns 409 if an active deletion request already exists.
    """
    reason = body.reason if body else None
    try:
        record = svc.request_account_deletion(db, current_user.id, reason=reason)
    except ValueError as exc:
        if str(exc) == "deletion_pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account deletion request is already active.",
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bad request.")
    return DeletionRequestResponse.model_validate(record)


@router.get(
    "/privacy/delete-account/status",
    response_model=DeletionRequestResponse | None,
    summary="Get current deletion request status",
)
def get_deletion_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DeletionRequestResponse | None:
    """Return the most recent active deletion request for the current user."""
    record = svc.get_deletion_request(db, current_user.id)
    if record is None:
        return None
    return DeletionRequestResponse.model_validate(record)


@router.delete(
    "/privacy/delete-account/{request_id}",
    response_model=DeletionRequestResponse,
    summary="Cancel an account deletion request",
)
def cancel_deletion(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DeletionRequestResponse:
    """Cancel a PENDING or CONFIRMED deletion request.

    Returns 404 if the request does not belong to the current user.
    Returns 409 if the request is in a non-cancellable state.
    """
    try:
        record = svc.cancel_deletion_request(db, request_id, current_user.id)
    except ValueError as exc:
        msg = str(exc)
        if msg == "not_found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Deletion request not found.",
            )
        if msg == "cannot_cancel":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This deletion request cannot be cancelled.",
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bad request.")
    return DeletionRequestResponse.model_validate(record)


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/privacy/admin/exports",
    response_model=list[DataExportRequestResponse],
    summary="Admin: list all data export requests",
)
def admin_list_exports(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[DataExportRequestResponse]:
    """Return a paginated list of all data export requests (admin only)."""
    records = svc.get_all_export_requests(db, skip=skip, limit=limit)
    return [DataExportRequestResponse.model_validate(r) for r in records]


@router.get(
    "/privacy/admin/deletions",
    response_model=list[DeletionRequestResponse],
    summary="Admin: list all account deletion requests",
)
def admin_list_deletions(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[DeletionRequestResponse]:
    """Return a paginated list of all account deletion requests (admin only)."""
    records = svc.get_all_deletion_requests(db, skip=skip, limit=limit)
    return [DeletionRequestResponse.model_validate(r) for r in records]


@router.post(
    "/privacy/admin/deletions/{request_id}/execute",
    summary="Admin: execute an account deletion",
)
def admin_execute_deletion(
    request_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict:
    """Anonymise the user's PII and finalise the deletion request.

    This action is irreversible.  The user row is retained for referential
    integrity but all personal data is overwritten.
    """
    # Look up the deletion request to get user_id
    from app.models.privacy import AccountDeletionRequest

    req = db.query(AccountDeletionRequest).filter(AccountDeletionRequest.id == request_id).first()
    if req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deletion request not found.",
        )

    svc.execute_account_deletion(db, req.user_id)
    return {"success": True, "user_id": req.user_id}
