"""Driver Emergency Assistance Fund service layer.

Public functions:
  get_or_create_fund       — get/create the singleton fund record
  add_contribution         — deposit money into the fund
  create_application       — driver submits an emergency assistance request
  start_review             — admin marks application under_review
  approve_application      — admin approves with a specific disbursement amount
  deny_application         — admin denies the application with a reason
  disburse_application     — admin marks approved application as disbursed
  withdraw_application     — driver withdraws their own pending application
  get_driver_applications  — list a driver's own applications
  admin_list_applications  — admin list with optional status filter
  get_fund_summary         — aggregate fund stats for admin dashboard
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hardship_fund import (
    ApplicationStatus,
    ApplicationType,
    ContributionSource,
    DriverHardshipFund,
    HardshipApplication,
    HardshipContribution,
)


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class HardshipFundError(Exception):
    """Raised by service functions for expected business-rule violations."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Fund record
# ---------------------------------------------------------------------------


async def get_or_create_fund(db: AsyncSession) -> DriverHardshipFund:
    """Return the singleton fund record, creating it with zero balances if absent."""
    result = await db.execute(select(DriverHardshipFund).limit(1))
    fund = result.scalar_one_or_none()
    if fund is None:
        fund = DriverHardshipFund(
            total_balance_usd=Decimal("0"),
            total_contributed_usd=Decimal("0"),
            total_disbursed_usd=Decimal("0"),
        )
        db.add(fund)
        await db.commit()
        await db.refresh(fund)
    return fund


# ---------------------------------------------------------------------------
# Contributions
# ---------------------------------------------------------------------------


async def add_contribution(
    db: AsyncSession,
    source: ContributionSource,
    amount_usd: Decimal,
    driver_id: int | None = None,
    note: str | None = None,
) -> HardshipContribution:
    """Record a deposit and increment the fund balance."""
    fund = await get_or_create_fund(db)

    contribution = HardshipContribution(
        source=source,
        amount_usd=amount_usd,
        driver_id=driver_id,
        note=note,
    )
    db.add(contribution)

    fund.total_balance_usd = Decimal(str(fund.total_balance_usd)) + amount_usd
    fund.total_contributed_usd = Decimal(str(fund.total_contributed_usd)) + amount_usd

    await db.commit()
    await db.refresh(contribution)
    return contribution


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------


async def create_application(
    db: AsyncSession,
    driver_id: int,
    application_type: ApplicationType,
    description: str,
    amount_requested_usd: Decimal,
) -> HardshipApplication:
    """Create a new emergency assistance application.

    Raises HardshipFundError(409) if the driver already has a pending or
    under_review application — only one active application at a time.
    """
    # Check for existing active application
    active_statuses = [ApplicationStatus.pending, ApplicationStatus.under_review]
    result = await db.execute(
        select(HardshipApplication).where(
            HardshipApplication.driver_id == driver_id,
            HardshipApplication.status.in_(active_statuses),
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        raise HardshipFundError(
            "Driver already has an active application (pending or under review). "
            "Withdraw or wait for the existing application to be resolved.",
            status_code=409,
        )

    application = HardshipApplication(
        driver_id=driver_id,
        application_type=application_type,
        description=description,
        amount_requested_usd=amount_requested_usd,
        status=ApplicationStatus.pending,
    )
    db.add(application)
    await db.commit()
    await db.refresh(application)
    return application


async def _get_application(
    db: AsyncSession, application_id: int
) -> HardshipApplication:
    """Fetch an application by id; raise 404 if not found."""
    result = await db.execute(
        select(HardshipApplication).where(HardshipApplication.id == application_id)
    )
    application = result.scalar_one_or_none()
    if application is None:
        raise HardshipFundError(
            f"Application {application_id} not found.", status_code=404
        )
    return application


async def start_review(
    db: AsyncSession, application_id: int, admin_id: int
) -> HardshipApplication:
    """Transition a pending application to under_review.

    Raises:
        HardshipFundError(404) — application not found
        HardshipFundError(409) — application is not in pending status
    """
    application = await _get_application(db, application_id)
    if application.status != ApplicationStatus.pending:
        raise HardshipFundError(
            f"Cannot start review: application is '{application.status.value}', expected 'pending'.",
            status_code=409,
        )
    application.status = ApplicationStatus.under_review
    application.reviewed_by_id = admin_id
    application.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(application)
    return application


async def approve_application(
    db: AsyncSession,
    application_id: int,
    admin_id: int,
    approved_amount_usd: Decimal,
    admin_note: str | None = None,
) -> HardshipApplication:
    """Approve an under_review application with a specific disbursement amount.

    Raises:
        HardshipFundError(404) — application not found
        HardshipFundError(409) — application is not under_review
        HardshipFundError(400) — approved amount <= 0 or insufficient fund balance
    """
    application = await _get_application(db, application_id)
    if application.status != ApplicationStatus.under_review:
        raise HardshipFundError(
            f"Cannot approve: application is '{application.status.value}', expected 'under_review'.",
            status_code=409,
        )
    if approved_amount_usd <= 0:
        raise HardshipFundError("approved_amount_usd must be greater than zero.")

    fund = await get_or_create_fund(db)
    if Decimal(str(fund.total_balance_usd)) < approved_amount_usd:
        raise HardshipFundError(
            f"Insufficient fund balance. Available: {fund.total_balance_usd}, "
            f"requested: {approved_amount_usd}.",
            status_code=400,
        )

    application.status = ApplicationStatus.approved
    application.approved_amount_usd = approved_amount_usd
    application.admin_note = admin_note
    application.reviewed_by_id = admin_id
    application.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(application)
    return application


async def deny_application(
    db: AsyncSession,
    application_id: int,
    admin_id: int,
    admin_note: str,
) -> HardshipApplication:
    """Deny a pending or under_review application.

    Raises:
        HardshipFundError(404) — application not found
        HardshipFundError(409) — application is not pending or under_review
    """
    application = await _get_application(db, application_id)
    deniable = {ApplicationStatus.pending, ApplicationStatus.under_review}
    if application.status not in deniable:
        raise HardshipFundError(
            f"Cannot deny: application is '{application.status.value}'. "
            "Only pending or under_review applications can be denied.",
            status_code=409,
        )
    application.status = ApplicationStatus.denied
    application.admin_note = admin_note
    application.reviewed_by_id = admin_id
    application.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(application)
    return application


async def disburse_application(
    db: AsyncSession, application_id: int, admin_id: int
) -> HardshipApplication:
    """Mark an approved application as disbursed and deduct from fund balance.

    Raises:
        HardshipFundError(404) — application not found
        HardshipFundError(409) — application is not approved
    """
    application = await _get_application(db, application_id)
    if application.status != ApplicationStatus.approved:
        raise HardshipFundError(
            f"Cannot disburse: application is '{application.status.value}', expected 'approved'.",
            status_code=409,
        )

    fund = await get_or_create_fund(db)
    disbursed = Decimal(str(application.approved_amount_usd))
    fund.total_balance_usd = Decimal(str(fund.total_balance_usd)) - disbursed
    fund.total_disbursed_usd = Decimal(str(fund.total_disbursed_usd)) + disbursed

    application.status = ApplicationStatus.disbursed
    application.disbursed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(application)
    return application


async def withdraw_application(
    db: AsyncSession, application_id: int, driver_id: int
) -> HardshipApplication:
    """Allow a driver to withdraw their own pending application.

    Raises:
        HardshipFundError(404) — application not found
        HardshipFundError(403) — caller is not the application owner
        HardshipFundError(409) — application is not in pending status
    """
    application = await _get_application(db, application_id)
    if application.driver_id != driver_id:
        raise HardshipFundError(
            "You do not have permission to withdraw this application.",
            status_code=403,
        )
    if application.status != ApplicationStatus.pending:
        raise HardshipFundError(
            f"Cannot withdraw: application is '{application.status.value}'. "
            "Only pending applications can be withdrawn.",
            status_code=409,
        )
    application.status = ApplicationStatus.withdrawn
    await db.commit()
    await db.refresh(application)
    return application


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


async def get_driver_applications(
    db: AsyncSession,
    driver_id: int,
    skip: int = 0,
    limit: int = 50,
) -> list[HardshipApplication]:
    """Return a driver's own applications, newest first."""
    result = await db.execute(
        select(HardshipApplication)
        .where(HardshipApplication.driver_id == driver_id)
        .order_by(HardshipApplication.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def admin_list_applications(
    db: AsyncSession,
    status_filter: ApplicationStatus | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[HardshipApplication]:
    """List all applications; optionally filter by status, newest first."""
    query = select(HardshipApplication).order_by(
        HardshipApplication.created_at.desc()
    )
    if status_filter is not None:
        query = query.where(HardshipApplication.status == status_filter)
    result = await db.execute(query.offset(skip).limit(limit))
    return list(result.scalars().all())


async def get_fund_summary(db: AsyncSession) -> dict:
    """Return aggregate fund stats for the admin dashboard."""
    fund = await get_or_create_fund(db)

    # Application counts by status
    count_result = await db.execute(
        select(HardshipApplication.status, func.count(HardshipApplication.id))
        .group_by(HardshipApplication.status)
    )
    counts: dict[str, int] = {row[0].value: row[1] for row in count_result.all()}

    # Monetary aggregates
    sum_result = await db.execute(
        select(
            func.coalesce(func.sum(HardshipApplication.amount_requested_usd), 0),
            func.coalesce(
                func.sum(HardshipApplication.approved_amount_usd).filter(
                    HardshipApplication.status.in_(
                        [ApplicationStatus.approved, ApplicationStatus.disbursed]
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(HardshipApplication.approved_amount_usd).filter(
                    HardshipApplication.status == ApplicationStatus.disbursed
                ),
                0,
            ),
        )
    )
    sums = sum_result.first()
    total_requested = Decimal(str(sums[0])) if sums else Decimal("0")
    total_approved = Decimal(str(sums[1])) if sums else Decimal("0")
    total_disbursed_apps = Decimal(str(sums[2])) if sums else Decimal("0")

    total_applications_result = await db.execute(
        select(func.count(HardshipApplication.id))
    )
    total_applications = total_applications_result.scalar() or 0

    return {
        "id": fund.id,
        "total_balance_usd": Decimal(str(fund.total_balance_usd)),
        "total_contributed_usd": Decimal(str(fund.total_contributed_usd)),
        "updated_at": fund.updated_at,
        "total_applications": total_applications,
        "pending_count": counts.get("pending", 0),
        "under_review_count": counts.get("under_review", 0),
        "approved_count": counts.get("approved", 0),
        "disbursed_count": counts.get("disbursed", 0),
        "denied_count": counts.get("denied", 0),
        "total_requested_usd": total_requested,
        "total_approved_usd": total_approved,
        "total_disbursed_usd": total_disbursed_apps,
    }
