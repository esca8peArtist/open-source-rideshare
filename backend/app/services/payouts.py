import logging
from datetime import date, datetime

import stripe
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.payment import Payment, PaymentStatus, PaymentType
from app.models.payout import (
    DriverBankAccount,
    DriverPayout,
    PayoutFrequency,
    PayoutStatus,
)
from app.models.ride import Ride, RideStatus

logger = logging.getLogger(__name__)

stripe.api_key = settings.stripe_secret_key


class PayoutError(Exception):
    pass


# ---- Stripe Connect Account Management ----


async def create_connect_account(
    driver_id: int,
    return_url: str,
    refresh_url: str,
    db: AsyncSession,
) -> dict:
    """Create a Stripe Connect Express account for the driver and return onboarding link."""
    result = await db.execute(
        select(DriverBankAccount).where(DriverBankAccount.driver_id == driver_id)
    )
    existing = result.scalar_one_or_none()
    if existing and existing.is_active:
        raise PayoutError("Driver already has an active bank account")

    account = stripe.Account.create(
        type="express",
        country="US",
        capabilities={"transfers": {"requested": True}},
        metadata={"driver_id": str(driver_id)},
    )

    link = stripe.AccountLink.create(
        account=account.id,
        refresh_url=refresh_url,
        return_url=return_url,
        type="account_onboarding",
    )

    if existing:
        existing.stripe_connect_account_id = account.id
        existing.account_status = "pending"
        existing.is_active = True
    else:
        bank_account = DriverBankAccount(
            driver_id=driver_id,
            stripe_connect_account_id=account.id,
            account_status="pending",
        )
        db.add(bank_account)

    await db.commit()

    return {
        "account_id": account.id,
        "onboarding_url": link.url,
    }


async def handle_connect_account_updated(
    account_data: dict, db: AsyncSession
) -> None:
    """Handle Stripe account.updated webhook — update bank account status."""
    account_id = account_data["id"]

    result = await db.execute(
        select(DriverBankAccount).where(
            DriverBankAccount.stripe_connect_account_id == account_id
        )
    )
    bank_account = result.scalar_one_or_none()
    if not bank_account:
        logger.warning("No bank account found for Stripe Connect account %s", account_id)
        return

    charges_enabled = account_data.get("charges_enabled", False)
    payouts_enabled = account_data.get("payouts_enabled", False)

    if charges_enabled and payouts_enabled:
        bank_account.account_status = "active"
    elif account_data.get("requirements", {}).get("currently_due"):
        bank_account.account_status = "requires_info"
    else:
        bank_account.account_status = "pending"

    external_accounts = account_data.get("external_accounts", {}).get("data", [])
    if external_accounts:
        ext = external_accounts[0]
        bank_account.bank_last_four = ext.get("last4")
        bank_account.bank_name = ext.get("bank_name")

    await db.commit()
    logger.info(
        "Connect account %s updated — status: %s", account_id, bank_account.account_status
    )


async def get_bank_account(driver_id: int, db: AsyncSession) -> DriverBankAccount | None:
    result = await db.execute(
        select(DriverBankAccount).where(
            DriverBankAccount.driver_id == driver_id,
            DriverBankAccount.is_active == True,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def update_payout_frequency(
    driver_id: int, frequency: str, db: AsyncSession
) -> DriverBankAccount:
    bank_account = await get_bank_account(driver_id, db)
    if not bank_account:
        raise PayoutError("No active bank account found")

    bank_account.payout_frequency = PayoutFrequency(frequency)
    await db.commit()
    await db.refresh(bank_account)
    return bank_account


async def deactivate_bank_account(driver_id: int, db: AsyncSession) -> None:
    bank_account = await get_bank_account(driver_id, db)
    if not bank_account:
        raise PayoutError("No active bank account found")

    bank_account.is_active = False
    await db.commit()


# ---- Settlement Calculation ----


async def calculate_settlement(
    driver_id: int,
    period_start: date,
    period_end: date,
    db: AsyncSession,
) -> dict:
    """Calculate earnings for a driver over a given period."""
    # Ride fare earnings
    ride_query = (
        select(
            func.coalesce(func.sum(Payment.driver_payout), 0.0).label("ride_earnings"),
            func.coalesce(func.sum(Payment.tip_amount), 0.0).label("tip_earnings"),
            func.count().label("trip_count"),
        )
        .join(Ride, Payment.ride_id == Ride.id)
        .where(
            Ride.driver_id == driver_id,
            Ride.status == RideStatus.COMPLETED,
            Payment.payment_type == PaymentType.RIDE_FARE,
            Payment.status == PaymentStatus.COMPLETED,
            func.date(Ride.completed_at) >= period_start,
            func.date(Ride.completed_at) <= period_end,
        )
    )
    result = await db.execute(ride_query)
    row = result.one()
    ride_earnings = float(row.ride_earnings)
    tip_earnings = float(row.tip_earnings)
    trip_count = int(row.trip_count)

    # Cancellation fee earnings
    cancel_query = (
        select(func.coalesce(func.sum(Payment.driver_payout), 0.0))
        .join(Ride, Payment.ride_id == Ride.id)
        .where(
            Ride.driver_id == driver_id,
            Payment.payment_type == PaymentType.CANCELLATION_FEE,
            Payment.status == PaymentStatus.COMPLETED,
            func.date(Payment.created_at) >= period_start,
            func.date(Payment.created_at) <= period_end,
        )
    )
    cancel_result = await db.execute(cancel_query)
    cancellation_fee_earnings = float(cancel_result.scalar() or 0.0)

    return {
        "ride_earnings": round(ride_earnings, 2),
        "tip_earnings": round(tip_earnings, 2),
        "cancellation_fee_earnings": round(cancellation_fee_earnings, 2),
        "trip_count": trip_count,
    }


# ---- Payout Creation & Processing ----


async def create_payout(
    driver_id: int,
    period_start: date,
    period_end: date,
    db: AsyncSession,
    bonus_amount: float = 0.0,
    deductions: float = 0.0,
    notes: str | None = None,
) -> DriverPayout:
    """Create a payout record for a driver, calculating earnings from completed rides."""
    bank_account = await get_bank_account(driver_id, db)
    if not bank_account:
        raise PayoutError("Driver has no active bank account")
    if bank_account.account_status != "active":
        raise PayoutError(f"Bank account is not active (status: {bank_account.account_status})")

    # Check for overlapping payout
    overlap_query = select(DriverPayout).where(
        DriverPayout.driver_id == driver_id,
        DriverPayout.status.in_([PayoutStatus.PENDING, PayoutStatus.PROCESSING, PayoutStatus.COMPLETED]),
        DriverPayout.period_start <= period_end,
        DriverPayout.period_end >= period_start,
    )
    result = await db.execute(overlap_query)
    if result.scalar_one_or_none():
        raise PayoutError("Overlapping payout already exists for this period")

    settlement = await calculate_settlement(driver_id, period_start, period_end, db)

    total = (
        settlement["ride_earnings"]
        + settlement["tip_earnings"]
        + settlement["cancellation_fee_earnings"]
        + bonus_amount
        - deductions
    )

    if total <= 0:
        raise PayoutError("Total payout amount must be positive")

    payout = DriverPayout(
        driver_id=driver_id,
        bank_account_id=bank_account.id,
        period_start=period_start,
        period_end=period_end,
        ride_earnings=settlement["ride_earnings"],
        tip_earnings=settlement["tip_earnings"],
        cancellation_fee_earnings=settlement["cancellation_fee_earnings"],
        bonus_amount=bonus_amount,
        deductions=deductions,
        total_amount=round(total, 2),
        trip_count=settlement["trip_count"],
        status=PayoutStatus.PENDING,
        notes=notes,
    )
    db.add(payout)
    await db.commit()
    await db.refresh(payout)

    logger.info(
        "Payout created for driver %d: $%.2f (%d trips, %s to %s)",
        driver_id, total, settlement["trip_count"], period_start, period_end,
    )
    return payout


async def process_payout(payout_id: int, db: AsyncSession) -> DriverPayout:
    """Initiate a Stripe transfer for a pending payout."""
    result = await db.execute(
        select(DriverPayout).where(DriverPayout.id == payout_id)
    )
    payout = result.scalar_one_or_none()
    if not payout:
        raise PayoutError("Payout not found")
    if payout.status != PayoutStatus.PENDING:
        raise PayoutError(f"Payout is not pending (status: {payout.status.value})")

    bank_result = await db.execute(
        select(DriverBankAccount).where(DriverBankAccount.id == payout.bank_account_id)
    )
    bank_account = bank_result.scalar_one_or_none()
    if not bank_account or not bank_account.is_active:
        payout.status = PayoutStatus.FAILED
        payout.failure_reason = "Bank account not found or inactive"
        await db.commit()
        raise PayoutError("Bank account not found or inactive")

    payout.status = PayoutStatus.PROCESSING
    payout.processed_at = datetime.utcnow()
    await db.commit()

    try:
        amount_cents = int(round(payout.total_amount * 100))
        transfer = stripe.Transfer.create(
            amount=amount_cents,
            currency="usd",
            destination=bank_account.stripe_connect_account_id,
            metadata={
                "payout_id": str(payout.id),
                "driver_id": str(payout.driver_id),
                "period": f"{payout.period_start} to {payout.period_end}",
            },
        )
        payout.stripe_transfer_id = transfer.id
        payout.status = PayoutStatus.COMPLETED
        payout.completed_at = datetime.utcnow()
        await db.commit()

        logger.info(
            "Payout %d processed — transfer %s ($%.2f to driver %d)",
            payout.id, transfer.id, payout.total_amount, payout.driver_id,
        )

        # Notify driver that payout is complete
        try:
            from app.services.notification_events import notify_payout_completed
            await notify_payout_completed(
                db, driver_id=payout.driver_id,
                amount=payout.total_amount,
                period=f"{payout.period_start} to {payout.period_end}",
            )
        except Exception:
            logger.exception("Failed to send payout notification for payout %d", payout.id)

    except stripe.error.StripeError as e:
        payout.status = PayoutStatus.FAILED
        payout.failure_reason = str(e)
        await db.commit()
        logger.error("Payout %d failed: %s", payout.id, e)
        raise PayoutError(f"Stripe transfer failed: {e}")

    await db.refresh(payout)
    return payout


async def retry_failed_payout(payout_id: int, db: AsyncSession) -> DriverPayout:
    """Reset a failed payout back to pending for re-processing."""
    result = await db.execute(
        select(DriverPayout).where(DriverPayout.id == payout_id)
    )
    payout = result.scalar_one_or_none()
    if not payout:
        raise PayoutError("Payout not found")
    if payout.status != PayoutStatus.FAILED:
        raise PayoutError("Only failed payouts can be retried")

    payout.status = PayoutStatus.PENDING
    payout.failure_reason = None
    payout.processed_at = None
    await db.commit()
    await db.refresh(payout)
    return payout


# ---- Queries ----


async def get_driver_payouts(
    driver_id: int, db: AsyncSession, limit: int = 20, offset: int = 0
) -> list[DriverPayout]:
    result = await db.execute(
        select(DriverPayout)
        .where(DriverPayout.driver_id == driver_id)
        .order_by(DriverPayout.period_end.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def get_payout_by_id(payout_id: int, db: AsyncSession) -> DriverPayout | None:
    result = await db.execute(
        select(DriverPayout).where(DriverPayout.id == payout_id)
    )
    return result.scalar_one_or_none()


async def get_payout_totals(driver_id: int, db: AsyncSession) -> dict:
    """Get total paid and pending amounts for a driver."""
    paid_query = select(func.coalesce(func.sum(DriverPayout.total_amount), 0.0)).where(
        DriverPayout.driver_id == driver_id,
        DriverPayout.status == PayoutStatus.COMPLETED,
    )
    pending_query = select(func.coalesce(func.sum(DriverPayout.total_amount), 0.0)).where(
        DriverPayout.driver_id == driver_id,
        DriverPayout.status.in_([PayoutStatus.PENDING, PayoutStatus.PROCESSING]),
    )
    paid = float((await db.execute(paid_query)).scalar() or 0.0)
    pending = float((await db.execute(pending_query)).scalar() or 0.0)
    return {"total_paid": round(paid, 2), "total_pending": round(pending, 2)}


# ---- Admin Bulk Operations ----


async def get_admin_payout_overview(db: AsyncSession) -> dict:
    """Admin dashboard overview of payout state."""
    drivers_with_accounts = (
        await db.execute(
            select(func.count()).select_from(DriverBankAccount).where(
                DriverBankAccount.is_active == True  # noqa: E712
            )
        )
    ).scalar() or 0

    pending = await db.execute(
        select(
            func.count().label("count"),
            func.coalesce(func.sum(DriverPayout.total_amount), 0.0).label("amount"),
        ).where(DriverPayout.status.in_([PayoutStatus.PENDING, PayoutStatus.PROCESSING]))
    )
    pending_row = pending.one()

    completed = await db.execute(
        select(
            func.count().label("count"),
            func.coalesce(func.sum(DriverPayout.total_amount), 0.0).label("amount"),
        ).where(DriverPayout.status == PayoutStatus.COMPLETED)
    )
    completed_row = completed.one()

    failed_count = (
        await db.execute(
            select(func.count()).select_from(DriverPayout).where(
                DriverPayout.status == PayoutStatus.FAILED
            )
        )
    ).scalar() or 0

    return {
        "total_drivers_with_accounts": drivers_with_accounts,
        "total_pending_payouts": pending_row.count,
        "total_pending_amount": round(float(pending_row.amount), 2),
        "total_completed_payouts": completed_row.count,
        "total_completed_amount": round(float(completed_row.amount), 2),
        "total_failed_payouts": failed_count,
    }


async def bulk_create_payouts(
    period_start: date,
    period_end: date,
    db: AsyncSession,
    bonus_amount: float = 0.0,
    deductions: float = 0.0,
    notes: str | None = None,
) -> list[DriverPayout]:
    """Create settlement payouts for all eligible drivers with active bank accounts."""
    result = await db.execute(
        select(DriverBankAccount).where(
            DriverBankAccount.is_active == True,  # noqa: E712
            DriverBankAccount.account_status == "active",
        )
    )
    bank_accounts = result.scalars().all()

    payouts = []
    for ba in bank_accounts:
        try:
            payout = await create_payout(
                driver_id=ba.driver_id,
                period_start=period_start,
                period_end=period_end,
                db=db,
                bonus_amount=bonus_amount,
                deductions=deductions,
                notes=notes,
            )
            payouts.append(payout)
        except PayoutError as e:
            logger.warning(
                "Skipping payout for driver %d: %s", ba.driver_id, e
            )

    return payouts
