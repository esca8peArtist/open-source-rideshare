"""Pre-built audit event dispatchers for regulated platform activities.

Each function logs a specific event type.  Like notification events, these
are fire-and-forget — they never raise, so business operations are unaffected.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.audit import log_event


# ── Ride lifecycle ──────────────────────────────────────────────────────

async def audit_ride_requested(
    db: AsyncSession, *, ride_id: int, rider_id: int, pickup: str, dropoff: str,
) -> None:
    await log_event(
        db, category="ride", event_type="ride_requested",
        description=f"Ride #{ride_id} requested: {pickup} → {dropoff}",
        ride_id=ride_id, user_id=rider_id, actor_id=rider_id, actor_role="rider",
    )


async def audit_ride_matched(
    db: AsyncSession, *, ride_id: int, driver_id: int, rider_id: int,
) -> None:
    await log_event(
        db, category="ride", event_type="ride_matched",
        description=f"Ride #{ride_id} matched to driver #{driver_id}",
        ride_id=ride_id, user_id=rider_id, actor_id=driver_id, actor_role="driver",
    )


async def audit_ride_completed(
    db: AsyncSession, *, ride_id: int, driver_id: int, rider_id: int, fare: float,
) -> None:
    await log_event(
        db, category="ride", event_type="ride_completed",
        description=f"Ride #{ride_id} completed — fare ${fare:.2f}",
        ride_id=ride_id, user_id=rider_id, actor_id=driver_id, actor_role="driver",
        metadata={"fare": fare},
    )


async def audit_ride_cancelled(
    db: AsyncSession, *, ride_id: int, cancelled_by: int, role: str, reason: str | None = None,
) -> None:
    await log_event(
        db, category="ride", event_type="ride_cancelled",
        description=f"Ride #{ride_id} cancelled by {role} #{cancelled_by}" + (f": {reason}" if reason else ""),
        ride_id=ride_id, actor_id=cancelled_by, actor_role=role,
        severity="warning",
    )


# ── Safety ──────────────────────────────────────────────────────────────

async def audit_sos_triggered(
    db: AsyncSession, *, sos_id: int, user_id: int, ride_id: int | None,
) -> None:
    await log_event(
        db, category="safety", event_type="sos_triggered",
        description=f"SOS alert #{sos_id} triggered by user #{user_id}",
        severity="critical", user_id=user_id, ride_id=ride_id,
        actor_id=user_id, target_type="sos_alert", target_id=sos_id,
    )


async def audit_sos_resolved(
    db: AsyncSession, *, sos_id: int, resolved_by: int, status: str,
) -> None:
    await log_event(
        db, category="safety", event_type="sos_resolved",
        description=f"SOS alert #{sos_id} resolved as {status} by admin #{resolved_by}",
        severity="critical", actor_id=resolved_by, actor_role="admin",
        target_type="sos_alert", target_id=sos_id,
    )


# ── Driver verification ────────────────────────────────────────────────

async def audit_document_reviewed(
    db: AsyncSession, *, document_id: int, driver_profile_id: int,
    reviewer_id: int, decision: str, reason: str | None = None,
) -> None:
    sev = "info" if decision == "approved" else "warning"
    await log_event(
        db, category="verification", event_type=f"document_{decision}",
        description=f"Document #{document_id} for driver profile #{driver_profile_id} {decision}" + (f": {reason}" if reason else ""),
        severity=sev, actor_id=reviewer_id, actor_role="admin",
        target_type="driver_document", target_id=document_id,
    )


# ── Disputes ────────────────────────────────────────────────────────────

async def audit_dispute_filed(
    db: AsyncSession, *, dispute_id: int, ride_id: int, filed_by: int,
    dispute_type: str,
) -> None:
    await log_event(
        db, category="dispute", event_type="dispute_filed",
        description=f"Dispute #{dispute_id} ({dispute_type}) filed for ride #{ride_id}",
        ride_id=ride_id, actor_id=filed_by, actor_role="user",
        target_type="dispute", target_id=dispute_id,
    )


async def audit_dispute_resolved(
    db: AsyncSession, *, dispute_id: int, ride_id: int, resolved_by: int,
    resolution: str, refund_amount: float | None = None,
) -> None:
    desc = f"Dispute #{dispute_id} resolved: {resolution}"
    if refund_amount:
        desc += f" (refund ${refund_amount:.2f})"
    await log_event(
        db, category="dispute", event_type="dispute_resolved",
        description=desc, ride_id=ride_id,
        actor_id=resolved_by, actor_role="admin",
        target_type="dispute", target_id=dispute_id,
        metadata={"resolution": resolution, "refund_amount": refund_amount},
    )


# ── Payments ────────────────────────────────────────────────────────────

async def audit_payment_completed(
    db: AsyncSession, *, payment_id: int, ride_id: int, amount: float,
    payment_type: str,
) -> None:
    await log_event(
        db, category="payment", event_type="payment_completed",
        description=f"Payment #{payment_id} completed — ${amount:.2f} ({payment_type}) for ride #{ride_id}",
        ride_id=ride_id, target_type="payment", target_id=payment_id,
        metadata={"amount": amount, "payment_type": payment_type},
    )


async def audit_payment_refunded(
    db: AsyncSession, *, payment_id: int, ride_id: int, amount: float,
    actor_id: int | None = None,
) -> None:
    await log_event(
        db, category="payment", event_type="payment_refunded",
        description=f"Payment #{payment_id} refunded — ${amount:.2f} for ride #{ride_id}",
        severity="warning", ride_id=ride_id,
        actor_id=actor_id, actor_role="admin" if actor_id else None,
        target_type="payment", target_id=payment_id,
    )


# ── Payouts ─────────────────────────────────────────────────────────────

async def audit_payout_completed(
    db: AsyncSession, *, payout_id: int, driver_id: int, amount: float,
) -> None:
    await log_event(
        db, category="payout", event_type="payout_completed",
        description=f"Payout #{payout_id} — ${amount:.2f} transferred to driver #{driver_id}",
        user_id=driver_id, target_type="payout", target_id=payout_id,
        metadata={"amount": amount},
    )


# ── Admin actions ───────────────────────────────────────────────────────

async def audit_admin_action(
    db: AsyncSession, *, admin_id: int, action: str, description: str,
    target_type: str | None = None, target_id: int | None = None,
    metadata: dict | None = None,
) -> None:
    await log_event(
        db, category="admin", event_type=action,
        description=description,
        actor_id=admin_id, actor_role="admin",
        target_type=target_type, target_id=target_id,
        metadata=metadata,
    )


# ── Account lifecycle ──────────────────────────────────────────────────

async def audit_account_event(
    db: AsyncSession, *, user_id: int, event_type: str, description: str,
) -> None:
    await log_event(
        db, category="account", event_type=event_type,
        description=description, user_id=user_id,
        actor_id=user_id,
    )
