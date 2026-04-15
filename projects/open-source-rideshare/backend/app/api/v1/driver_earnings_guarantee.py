"""Driver minimum earnings guarantee API.

Driver endpoints:
  GET  /drivers/me/earnings-guarantee/current      — current week in-progress estimate
  GET  /drivers/me/earnings-guarantee/history      — all past weekly records

Admin endpoints:
  GET  /admin/earnings-guarantee/policy            — active policy
  POST /admin/earnings-guarantee/policy            — create / update policy
  GET  /admin/earnings-guarantee/calculate         — dry-run preview for a week
  POST /admin/earnings-guarantee/process           — persist records for a completed week
  GET  /admin/earnings-guarantee/records           — list records (filter by week/status)
  GET  /admin/earnings-guarantee/records/{id}      — single record detail
  POST /admin/earnings-guarantee/records/{id}/pay  — mark individual record paid
  POST /admin/earnings-guarantee/pay-all           — bulk-pay all pending for a week
  GET  /admin/earnings-guarantee/summary           — aggregate platform stats
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_driver
from app.db.database import get_db
from app.models.driver import DriverProfile
from app.models.driver_earnings_guarantee import GuaranteeStatus
from app.models.user import User
from app.schemas.driver_earnings_guarantee import (
    DriverCurrentWeekEstimate,
    DriverGuaranteeHistoryResponse,
    GuaranteeSummaryResponse,
    PayAllWeekRequest,
    PayAllWeekResponse,
    PayRecordRequest,
    PolicyCreateRequest,
    PolicyResponse,
    ProcessWeekRequest,
    WeeklyGuaranteeRecordDetailResponse,
    WeeklyGuaranteeRecordResponse,
    WeekPreviewResponse,
    WeekRecordsListResponse,
)
from app.services.driver_earnings_guarantee import (
    get_active_policy,
    get_current_week_estimate,
    get_driver_history,
    get_guarantee_summary,
    list_week_records,
    pay_all_week,
    pay_record,
    preview_week,
    process_week,
    set_policy,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["earnings-guarantee"])


# ---------------------------------------------------------------------------
# Driver endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/drivers/me/earnings-guarantee/current",
    response_model=DriverCurrentWeekEstimate,
)
async def get_my_current_week_estimate(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return this driver's in-progress earnings guarantee estimate for the current week.

    Not persisted — shows live ride counts and projected shortfall so drivers
    know whether they're on track to meet the guarantee threshold.
    """
    driver_profile = await db.get(DriverProfile, None)
    # We only need the user_id — estimation is keyed by user_id
    result = await get_current_week_estimate(db, current_user.id)
    return result


@router.get(
    "/drivers/me/earnings-guarantee/history",
    response_model=DriverGuaranteeHistoryResponse,
)
async def get_my_guarantee_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return this driver's past weekly guarantee records (newest first)."""
    records = await get_driver_history(db, current_user.id)
    total_received = sum(
        float(r.shortfall_usd) for r in records if r.status == GuaranteeStatus.paid
    )
    return DriverGuaranteeHistoryResponse(
        driver_id=current_user.id,
        total_records=len(records),
        total_received_usd=round(total_received, 2),
        records=[WeeklyGuaranteeRecordResponse.model_validate(r) for r in records],
    )


# ---------------------------------------------------------------------------
# Admin: policy management
# ---------------------------------------------------------------------------

@router.get(
    "/admin/earnings-guarantee/policy",
    response_model=PolicyResponse,
)
async def admin_get_policy(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the currently active earnings guarantee policy."""
    policy = await get_active_policy(db)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active earnings guarantee policy configured",
        )
    return PolicyResponse.model_validate(policy)


@router.post(
    "/admin/earnings-guarantee/policy",
    response_model=PolicyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def admin_set_policy(
    body: PolicyCreateRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new earnings guarantee policy.

    Deactivates the previous policy. History is preserved.
    """
    try:
        policy = await set_policy(
            db=db,
            admin_user_id=admin.id,
            minimum_per_ride_usd=body.minimum_per_ride_usd,
            minimum_rides_to_qualify=body.minimum_rides_to_qualify,
            effective_from=body.effective_from,
            effective_until=body.effective_until,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return PolicyResponse.model_validate(policy)


# ---------------------------------------------------------------------------
# Admin: week calculation and processing
# ---------------------------------------------------------------------------

@router.get(
    "/admin/earnings-guarantee/calculate",
    response_model=WeekPreviewResponse,
)
async def admin_preview_week(
    week_start: date = Query(..., description="ISO Monday date of the week to preview"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Dry-run: compute per-driver guarantee data for a week without persisting.

    Use this before `process` to review the expected shortfall totals.
    """
    try:
        preview = await preview_week(db, week_start)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return preview


@router.post(
    "/admin/earnings-guarantee/process",
    response_model=WeekRecordsListResponse,
)
async def admin_process_week(
    body: ProcessWeekRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Persist WeeklyGuaranteeRecord for every driver who completed rides in the week.

    Idempotent — rerunning updates existing non-paid records.
    """
    try:
        records = await process_week(db, body.week_start, admin.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # Build detail response with names
    pairs = await list_week_records(db, body.week_start)
    name_map = {r.driver_id: name for r, name in pairs}

    from app.services.driver_earnings_guarantee import _week_bounds
    monday, sunday = _week_bounds(body.week_start)

    pending_count = sum(1 for r in records if r.status == GuaranteeStatus.pending)
    total_pending_shortfall = sum(
        float(r.shortfall_usd) for r in records if r.status == GuaranteeStatus.pending
    )

    detail_records = [
        WeeklyGuaranteeRecordDetailResponse(
            **WeeklyGuaranteeRecordResponse.model_validate(r).model_dump(),
            driver_name=name_map.get(r.driver_id, f"Driver#{r.driver_id}"),
        )
        for r in records
    ]

    return WeekRecordsListResponse(
        week_start=monday,
        week_end=sunday,
        total=len(records),
        pending_count=pending_count,
        total_pending_shortfall_usd=round(total_pending_shortfall, 2),
        records=detail_records,
    )


# ---------------------------------------------------------------------------
# Admin: record listing and detail
# ---------------------------------------------------------------------------

@router.get(
    "/admin/earnings-guarantee/records",
    response_model=WeekRecordsListResponse,
)
async def admin_list_records(
    week_start: date = Query(..., description="ISO Monday date of the week"),
    status_filter: GuaranteeStatus | None = Query(None, alias="status"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List guarantee records for a given week, optionally filtered by status."""
    pairs = await list_week_records(db, week_start, status_filter)

    from app.services.driver_earnings_guarantee import _week_bounds
    monday, sunday = _week_bounds(week_start)

    pending_count = sum(1 for r, _ in pairs if r.status == GuaranteeStatus.pending)
    total_pending = sum(
        float(r.shortfall_usd) for r, _ in pairs if r.status == GuaranteeStatus.pending
    )

    detail_records = [
        WeeklyGuaranteeRecordDetailResponse(
            **WeeklyGuaranteeRecordResponse.model_validate(r).model_dump(),
            driver_name=name,
        )
        for r, name in pairs
    ]

    return WeekRecordsListResponse(
        week_start=monday,
        week_end=sunday,
        total=len(detail_records),
        pending_count=pending_count,
        total_pending_shortfall_usd=round(total_pending, 2),
        records=detail_records,
    )


@router.get(
    "/admin/earnings-guarantee/records/{record_id}",
    response_model=WeeklyGuaranteeRecordDetailResponse,
)
async def admin_get_record(
    record_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return detail for a single guarantee record."""
    from sqlalchemy import select
    from app.models.driver_earnings_guarantee import WeeklyGuaranteeRecord
    from app.models.user import User as UserModel

    result = await db.execute(
        select(WeeklyGuaranteeRecord, UserModel)
        .join(UserModel, WeeklyGuaranteeRecord.driver_id == UserModel.id)
        .where(WeeklyGuaranteeRecord.id == record_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")

    record, user = row
    name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email
    return WeeklyGuaranteeRecordDetailResponse(
        **WeeklyGuaranteeRecordResponse.model_validate(record).model_dump(),
        driver_name=name,
    )


# ---------------------------------------------------------------------------
# Admin: payout operations
# ---------------------------------------------------------------------------

@router.post(
    "/admin/earnings-guarantee/records/{record_id}/pay",
    response_model=WeeklyGuaranteeRecordResponse,
)
async def admin_pay_record(
    record_id: int,
    body: PayRecordRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Mark a single pending guarantee record as paid."""
    try:
        record = await pay_record(db, record_id, admin.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")

    return WeeklyGuaranteeRecordResponse.model_validate(record)


@router.post(
    "/admin/earnings-guarantee/pay-all",
    response_model=PayAllWeekResponse,
)
async def admin_pay_all_week(
    body: PayAllWeekRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Bulk-pay all pending guarantee records for a week."""
    count, total = await pay_all_week(db, body.week_start, admin.id)
    from app.services.driver_earnings_guarantee import _week_bounds
    monday, _ = _week_bounds(body.week_start)
    return PayAllWeekResponse(
        week_start=monday,
        records_paid=count,
        total_paid_usd=total,
    )


# ---------------------------------------------------------------------------
# Admin: summary
# ---------------------------------------------------------------------------

@router.get(
    "/admin/earnings-guarantee/summary",
    response_model=GuaranteeSummaryResponse,
)
async def admin_get_summary(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate platform-wide earnings guarantee statistics."""
    return await get_guarantee_summary(db)
