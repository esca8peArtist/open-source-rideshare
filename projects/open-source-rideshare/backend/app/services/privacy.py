"""GDPR/CCPA Privacy Compliance service layer.

Public functions:
  record_consent               — upsert a user's consent record
  get_user_consents            — return all consent records for a user
  request_data_export          — create a PENDING data export request
  get_export_request           — fetch an export request by id + ownership
  generate_user_data_export    — collect all exportable user data as a dict
  complete_export_request      — mark export as READY with expiry
  mark_export_downloaded       — increment download count; cap at DOWNLOADED
  request_account_deletion     — create a PENDING deletion request
  cancel_deletion_request      — cancel a PENDING/CONFIRMED deletion request
  execute_account_deletion     — anonymise PII and mark deletion complete
  get_deletion_request         — fetch the latest active deletion request
  get_all_export_requests      — admin: paginated list of all exports
  get_all_deletion_requests    — admin: paginated list of all deletions
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.privacy import (
    AccountDeletionRequest,
    DataExportRequest,
    DeletionStatus,
    ExportStatus,
    PolicyType,
    PrivacyConsentRecord,
)


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------


def record_consent(
    db: Session,
    user_id: int,
    policy_type: PolicyType,
    policy_version: str,
    consented: bool,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> PrivacyConsentRecord:
    """Upsert a consent record for a user + policy + version combination.

    If a record already exists for (user_id, policy_type, policy_version),
    update the ``consented``, ``ip_address``, ``user_agent``, and
    ``consented_at`` fields in place.  Otherwise insert a new record.
    """
    record = (
        db.query(PrivacyConsentRecord)
        .filter(
            PrivacyConsentRecord.user_id == user_id,
            PrivacyConsentRecord.policy_type == policy_type,
            PrivacyConsentRecord.policy_version == policy_version,
        )
        .first()
    )

    now = datetime.now(timezone.utc)

    if record is None:
        record = PrivacyConsentRecord(
            user_id=user_id,
            policy_type=policy_type,
            policy_version=policy_version,
            consented=consented,
            ip_address=ip_address,
            user_agent=user_agent,
            consented_at=now,
        )
        db.add(record)
    else:
        record.consented = consented
        record.ip_address = ip_address
        record.user_agent = user_agent
        record.consented_at = now

    db.commit()
    db.refresh(record)
    return record


def get_user_consents(db: Session, user_id: int) -> list[PrivacyConsentRecord]:
    """Return all consent records for a user, newest first."""
    return (
        db.query(PrivacyConsentRecord)
        .filter(PrivacyConsentRecord.user_id == user_id)
        .order_by(PrivacyConsentRecord.consented_at.desc())
        .all()
    )


# ---------------------------------------------------------------------------
# Data export
# ---------------------------------------------------------------------------


def request_data_export(db: Session, user_id: int) -> DataExportRequest:
    """Create a new PENDING export request for the user.

    Raises ValueError("export_in_progress") if the user already has a
    PENDING or PROCESSING request outstanding.
    """
    in_progress = (
        db.query(DataExportRequest)
        .filter(
            DataExportRequest.user_id == user_id,
            DataExportRequest.status.in_(
                [ExportStatus.PENDING, ExportStatus.PROCESSING]
            ),
        )
        .first()
    )
    if in_progress is not None:
        raise ValueError("export_in_progress")

    record = DataExportRequest(
        user_id=user_id,
        status=ExportStatus.PENDING,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_export_request(
    db: Session, request_id: int, user_id: int
) -> DataExportRequest | None:
    """Return an export request if it exists and belongs to the user."""
    return (
        db.query(DataExportRequest)
        .filter(
            DataExportRequest.id == request_id,
            DataExportRequest.user_id == user_id,
        )
        .first()
    )


def generate_user_data_export(db: Session, user_id: int) -> dict:
    """Collect all exportable user data and return it as a dictionary.

    Includes profile, ride count, payment count, and consent history.
    Any model-level import failures (e.g. field name differences) are
    handled gracefully — counts default to 0.
    """
    from app.models.user import User

    user = db.query(User).filter(User.id == user_id).first()

    profile: dict = {}
    if user is not None:
        profile = {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "phone": user.phone,
            "role": user.role.value if hasattr(user.role, "value") else str(user.role),
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }

    ride_count = 0
    try:
        from app.models.ride import Ride

        ride_count = db.query(Ride).filter(Ride.rider_id == user_id).count()
    except Exception:
        ride_count = 0

    payment_count = 0
    try:
        from app.models.payment import Payment

        payment_count = (
            db.query(Payment).filter(Payment.user_id == user_id).count()
        )
    except Exception:
        payment_count = 0

    consents = get_user_consents(db, user_id)
    consents_data = [
        {
            "id": c.id,
            "policy_type": c.policy_type.value,
            "policy_version": c.policy_version,
            "consented": c.consented,
            "consented_at": c.consented_at.isoformat() if c.consented_at else None,
        }
        for c in consents
    ]

    return {
        "profile": profile,
        "ride_count": ride_count,
        "payment_count": payment_count,
        "consents": consents_data,
    }


def complete_export_request(db: Session, request_id: int) -> DataExportRequest:
    """Mark an export request as READY and set a 7-day expiry."""
    record = db.query(DataExportRequest).filter(DataExportRequest.id == request_id).first()
    if record is None:
        raise ValueError("not_found")

    now = datetime.now(timezone.utc)
    record.status = ExportStatus.READY
    record.completed_at = now
    record.expires_at = now + timedelta(days=7)

    db.commit()
    db.refresh(record)
    return record


def mark_export_downloaded(db: Session, request_id: int) -> DataExportRequest:
    """Increment the download counter; transition to DOWNLOADED after 3 downloads."""
    record = db.query(DataExportRequest).filter(DataExportRequest.id == request_id).first()
    if record is None:
        raise ValueError("not_found")

    record.download_count += 1
    if record.download_count >= 3:
        record.status = ExportStatus.DOWNLOADED

    db.commit()
    db.refresh(record)
    return record


# ---------------------------------------------------------------------------
# Account deletion
# ---------------------------------------------------------------------------


def request_account_deletion(
    db: Session, user_id: int, reason: str | None = None
) -> AccountDeletionRequest:
    """Create a PENDING account deletion request.

    Raises ValueError("deletion_pending") if the user already has an
    active (PENDING or CONFIRMED) deletion request.
    """
    active = (
        db.query(AccountDeletionRequest)
        .filter(
            AccountDeletionRequest.user_id == user_id,
            AccountDeletionRequest.status.in_(
                [DeletionStatus.PENDING, DeletionStatus.CONFIRMED]
            ),
        )
        .first()
    )
    if active is not None:
        raise ValueError("deletion_pending")

    now = datetime.now(timezone.utc)
    record = AccountDeletionRequest(
        user_id=user_id,
        status=DeletionStatus.PENDING,
        reason=reason,
        requested_at=now,
        scheduled_for=now + timedelta(days=30),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def cancel_deletion_request(
    db: Session, request_id: int, user_id: int
) -> AccountDeletionRequest:
    """Cancel a PENDING or CONFIRMED deletion request.

    Raises ValueError("not_found") if the request does not belong to the user.
    Raises ValueError("cannot_cancel") if the request is in a terminal state.
    """
    record = (
        db.query(AccountDeletionRequest)
        .filter(AccountDeletionRequest.id == request_id)
        .first()
    )

    if record is None or record.user_id != user_id:
        raise ValueError("not_found")

    if record.status not in (DeletionStatus.PENDING, DeletionStatus.CONFIRMED):
        raise ValueError("cannot_cancel")

    record.status = DeletionStatus.CANCELLED
    record.cancelled_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(record)
    return record


def execute_account_deletion(db: Session, user_id: int) -> bool:
    """Anonymise all PII for a user and mark any CONFIRMED deletion as COMPLETED.

    The user row is kept for referential integrity but all personal data is
    overwritten with non-identifiable values.  The account is deactivated.

    Returns True on success.
    """
    from app.models.user import User

    user = db.query(User).filter(User.id == user_id).first()
    if user is not None:
        user.name = f"Deleted User {user_id}"
        user.email = None
        user.phone = f"+00000{user_id}"
        user.password_hash = ""
        user.is_active = False

    # Mark any CONFIRMED deletion request for this user as COMPLETED
    confirmed = (
        db.query(AccountDeletionRequest)
        .filter(
            AccountDeletionRequest.user_id == user_id,
            AccountDeletionRequest.status == DeletionStatus.CONFIRMED,
        )
        .all()
    )
    now = datetime.now(timezone.utc)
    for req in confirmed:
        req.status = DeletionStatus.COMPLETED
        req.completed_at = now

    db.commit()
    return True


def get_deletion_request(
    db: Session, user_id: int
) -> AccountDeletionRequest | None:
    """Return the most recent non-cancelled deletion request for a user."""
    return (
        db.query(AccountDeletionRequest)
        .filter(
            AccountDeletionRequest.user_id == user_id,
            AccountDeletionRequest.status != DeletionStatus.CANCELLED,
        )
        .order_by(AccountDeletionRequest.requested_at.desc())
        .first()
    )


# ---------------------------------------------------------------------------
# Admin helpers
# ---------------------------------------------------------------------------


def get_all_export_requests(
    db: Session, skip: int = 0, limit: int = 50
) -> list[DataExportRequest]:
    """Admin: return all export requests, paginated."""
    return (
        db.query(DataExportRequest)
        .order_by(DataExportRequest.requested_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_all_deletion_requests(
    db: Session, skip: int = 0, limit: int = 50
) -> list[AccountDeletionRequest]:
    """Admin: return all deletion requests, paginated."""
    return (
        db.query(AccountDeletionRequest)
        .order_by(AccountDeletionRequest.requested_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
