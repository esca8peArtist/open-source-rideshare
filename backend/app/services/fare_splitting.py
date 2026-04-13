import logging
from datetime import datetime, timezone
from typing import Any

import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.fare_split import FareSplit, SplitStatus
from app.models.ride import Ride, RideStatus
from app.models.user import User

logger = logging.getLogger(__name__)

stripe.api_key = settings.stripe_secret_key

MAX_SPLIT_PARTICIPANTS = 5  # initiator + up to 4 others


async def create_fare_split(
    ride_id: int,
    initiator_id: int,
    participants: list[dict[str, Any]],
    split_equally: bool,
    db: AsyncSession,
) -> dict[str, Any]:
    """Create a fare split for a ride.

    Args:
        ride_id: The ride to split.
        initiator_id: The rider who is initiating the split.
        participants: List of dicts with user_id/phone/email and optional share_percentage.
        split_equally: If True, ignore individual percentages and split equally.
        db: Database session.

    Returns:
        Dict with split details or error.
    """
    # Validate ride exists and belongs to initiator
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()

    if not ride:
        return {"error": "Ride not found"}
    if ride.rider_id != initiator_id:
        return {"error": "Only the ride initiator can create a fare split"}

    # Can only split active or completed rides (need a fare to split)
    allowed_statuses = {
        RideStatus.REQUESTED, RideStatus.MATCHED, RideStatus.DRIVER_EN_ROUTE,
        RideStatus.ARRIVED, RideStatus.IN_PROGRESS, RideStatus.COMPLETED,
    }
    if ride.status not in allowed_statuses:
        return {"error": f"Cannot split fare for ride in {ride.status.value} status"}

    # Check for existing active split
    result = await db.execute(
        select(FareSplit).where(
            FareSplit.ride_id == ride_id,
            FareSplit.status.notin_([SplitStatus.CANCELLED, SplitStatus.DECLINED, SplitStatus.EXPIRED]),
        )
    )
    existing = result.scalars().all()
    if existing:
        return {"error": "Fare split already exists for this ride. Cancel it first to create a new one."}

    total_participants = len(participants) + 1  # +1 for initiator
    if total_participants > MAX_SPLIT_PARTICIPANTS:
        return {"error": f"Cannot split with more than {MAX_SPLIT_PARTICIPANTS - 1} participants"}

    # Determine fare to split
    fare = ride.actual_fare if ride.actual_fare else ride.estimated_fare

    # Calculate shares
    if split_equally:
        share_pct = 100.0 / total_participants
        share_amount = round(fare * share_pct / 100.0, 2)
    else:
        # Validate custom percentages sum correctly
        custom_pcts = [p.get("share_percentage", 0) for p in participants]
        if any(pct is None or pct <= 0 for pct in custom_pcts):
            return {"error": "All participants must have a valid share_percentage when not splitting equally"}
        initiator_pct = 100.0 - sum(custom_pcts)
        if initiator_pct < 0:
            return {"error": "Participant shares exceed 100%"}
        if initiator_pct == 0:
            return {"error": "Initiator must have a share greater than 0%"}

    splits = []

    # Create initiator's split
    if split_equally:
        init_pct = share_pct
        init_amount = share_amount
    else:
        init_pct = initiator_pct
        init_amount = round(fare * init_pct / 100.0, 2)

    initiator_split = FareSplit(
        ride_id=ride_id,
        user_id=initiator_id,
        is_initiator=True,
        status=SplitStatus.ACCEPTED,  # Initiator auto-accepts
        share_amount=init_amount,
        share_percentage=round(init_pct, 2),
    )
    db.add(initiator_split)
    splits.append(initiator_split)

    # Create participant splits
    for p in participants:
        if split_equally:
            p_pct = share_pct
            p_amount = share_amount
        else:
            p_pct = p["share_percentage"]
            p_amount = round(fare * p_pct / 100.0, 2)

        # Resolve user_id from phone/email if needed
        user_id = p.get("user_id")
        invite_phone = p.get("phone")
        invite_email = p.get("email")

        if not user_id and invite_phone:
            result = await db.execute(
                select(User).where(User.phone == invite_phone)
            )
            found = result.scalar_one_or_none()
            if found:
                user_id = found.id

        if not user_id and invite_email:
            result = await db.execute(
                select(User).where(User.email == invite_email)
            )
            found = result.scalar_one_or_none()
            if found:
                user_id = found.id

        split = FareSplit(
            ride_id=ride_id,
            user_id=user_id,
            invite_phone=invite_phone if not user_id else None,
            invite_email=invite_email if not user_id else None,
            is_initiator=False,
            status=SplitStatus.PENDING,
            share_amount=p_amount,
            share_percentage=round(p_pct, 2),
        )
        db.add(split)
        splits.append(split)

    # Adjust rounding — ensure amounts sum to the fare exactly
    total_assigned = sum(s.share_amount for s in splits)
    diff = round(fare - total_assigned, 2)
    if diff != 0:
        # Add/subtract rounding difference to initiator's share
        initiator_split.share_amount = round(initiator_split.share_amount + diff, 2)

    await db.commit()

    # Refresh to get IDs
    for s in splits:
        await db.refresh(s)

    logger.info(
        "Fare split created for ride %d: %d participants, $%.2f each (equal=%s)",
        ride_id, total_participants, splits[0].share_amount, split_equally,
    )

    return {
        "ride_id": ride_id,
        "total_fare": fare,
        "split_count": len(splits),
        "splits": [_split_to_dict(s) for s in splits],
        "all_accepted": all(s.status in (SplitStatus.ACCEPTED, SplitStatus.PAID) for s in splits),
        "all_paid": all(s.status == SplitStatus.PAID for s in splits),
    }


async def get_fare_split(
    ride_id: int, user_id: int, db: AsyncSession
) -> dict[str, Any]:
    """Get fare split details for a ride."""
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if not ride:
        return {"error": "Ride not found"}

    result = await db.execute(
        select(FareSplit).where(
            FareSplit.ride_id == ride_id,
            FareSplit.status.notin_([SplitStatus.CANCELLED]),
        ).order_by(FareSplit.is_initiator.desc(), FareSplit.id)
    )
    splits = result.scalars().all()

    if not splits:
        return {"error": "No fare split found for this ride"}

    # Check authorization: must be a participant or the ride owner
    participant_ids = {s.user_id for s in splits if s.user_id}
    if user_id not in participant_ids and ride.rider_id != user_id:
        return {"error": "Not authorized to view this fare split"}

    fare = ride.actual_fare if ride.actual_fare else ride.estimated_fare

    return {
        "ride_id": ride_id,
        "total_fare": fare,
        "split_count": len(splits),
        "splits": [_split_to_dict(s) for s in splits],
        "all_accepted": all(s.status in (SplitStatus.ACCEPTED, SplitStatus.PAID) for s in splits),
        "all_paid": all(s.status == SplitStatus.PAID for s in splits),
    }


async def respond_to_split(
    split_id: int, user_id: int, accept: bool, db: AsyncSession
) -> dict[str, Any]:
    """Accept or decline a fare split invitation."""
    result = await db.execute(select(FareSplit).where(FareSplit.id == split_id))
    split = result.scalar_one_or_none()

    if not split:
        return {"error": "Fare split not found"}
    if split.user_id != user_id:
        return {"error": "Not authorized to respond to this split"}
    if split.is_initiator:
        return {"error": "Initiator cannot respond to their own split"}
    if split.status != SplitStatus.PENDING:
        return {"error": f"Cannot respond to split in {split.status.value} status"}

    now = datetime.now(timezone.utc)

    if accept:
        split.status = SplitStatus.ACCEPTED
        split.responded_at = now
        await db.commit()
        logger.info("User %d accepted fare split %d", user_id, split_id)
        return _split_to_dict(split)
    else:
        split.status = SplitStatus.DECLINED
        split.responded_at = now

        # Redistribute declined share back to initiator
        result = await db.execute(
            select(FareSplit).where(
                FareSplit.ride_id == split.ride_id,
                FareSplit.is_initiator == True,
            )
        )
        initiator_split = result.scalar_one_or_none()
        if initiator_split:
            initiator_split.share_amount = round(
                initiator_split.share_amount + split.share_amount, 2
            )
            initiator_split.share_percentage = round(
                initiator_split.share_percentage + split.share_percentage, 2
            )

        split.share_amount = 0.0
        split.share_percentage = 0.0

        await db.commit()
        logger.info("User %d declined fare split %d — share redistributed to initiator", user_id, split_id)
        return _split_to_dict(split)


async def create_split_payment(
    split_id: int, user_id: int, db: AsyncSession
) -> dict[str, Any]:
    """Create a Stripe payment intent for a participant's share."""
    result = await db.execute(select(FareSplit).where(FareSplit.id == split_id))
    split = result.scalar_one_or_none()

    if not split:
        return {"error": "Fare split not found"}
    if split.user_id != user_id:
        return {"error": "Not authorized to pay this split"}
    if split.status not in (SplitStatus.ACCEPTED,):
        return {"error": f"Cannot pay split in {split.status.value} status — must be accepted first"}
    if split.share_amount <= 0:
        return {"error": "No amount to pay"}

    # Check if already has a payment intent
    if split.stripe_payment_intent_id:
        return {
            "split_id": split.id,
            "share_amount": split.share_amount,
            "client_secret": None,
            "payment_intent_id": split.stripe_payment_intent_id,
            "status": split.status.value,
        }

    amount_cents = int(round(split.share_amount * 100))

    intent = stripe.PaymentIntent.create(
        amount=amount_cents,
        currency="usd",
        metadata={
            "ride_id": str(split.ride_id),
            "split_id": str(split.id),
            "user_id": str(user_id),
            "type": "fare_split",
        },
        automatic_payment_methods={"enabled": True},
    )

    split.stripe_payment_intent_id = intent.id
    await db.commit()

    logger.info(
        "Split payment intent created: split %d, $%.2f (intent %s)",
        split_id, split.share_amount, intent.id,
    )

    return {
        "split_id": split.id,
        "share_amount": split.share_amount,
        "client_secret": intent.client_secret,
        "payment_intent_id": intent.id,
        "status": "pending",
    }


async def handle_split_payment_succeeded(
    split_id: int, db: AsyncSession
) -> None:
    """Mark a split as paid after Stripe confirms payment."""
    result = await db.execute(select(FareSplit).where(FareSplit.id == split_id))
    split = result.scalar_one_or_none()
    if split:
        split.status = SplitStatus.PAID
        await db.commit()
        logger.info("Fare split %d marked as paid", split_id)


async def cancel_fare_split(
    ride_id: int, user_id: int, db: AsyncSession
) -> dict[str, Any]:
    """Cancel all splits for a ride. Only the initiator can cancel."""
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if not ride:
        return {"error": "Ride not found"}
    if ride.rider_id != user_id:
        return {"error": "Only the ride initiator can cancel the fare split"}

    result = await db.execute(
        select(FareSplit).where(
            FareSplit.ride_id == ride_id,
            FareSplit.status.notin_([SplitStatus.CANCELLED]),
        )
    )
    splits = result.scalars().all()

    if not splits:
        return {"error": "No active fare split found for this ride"}

    # Cannot cancel if any split is already paid
    paid = [s for s in splits if s.status == SplitStatus.PAID]
    if paid:
        return {"error": "Cannot cancel split — some participants have already paid"}

    for s in splits:
        s.status = SplitStatus.CANCELLED

    await db.commit()

    logger.info("Fare split cancelled for ride %d by user %d", ride_id, user_id)
    return {"ride_id": ride_id, "status": "cancelled", "splits_cancelled": len(splits)}


async def expire_pending_splits(
    ride_id: int, db: AsyncSession
) -> int:
    """Expire all pending splits for a ride (called when ride completes).

    Returns the number of splits expired.
    """
    result = await db.execute(
        select(FareSplit).where(
            FareSplit.ride_id == ride_id,
            FareSplit.status == SplitStatus.PENDING,
        )
    )
    pending = result.scalars().all()

    if not pending:
        return 0

    # Redistribute expired shares to initiator
    result = await db.execute(
        select(FareSplit).where(
            FareSplit.ride_id == ride_id,
            FareSplit.is_initiator == True,
        )
    )
    initiator_split = result.scalar_one_or_none()

    expired_count = 0
    for s in pending:
        s.status = SplitStatus.EXPIRED
        if initiator_split:
            initiator_split.share_amount = round(
                initiator_split.share_amount + s.share_amount, 2
            )
            initiator_split.share_percentage = round(
                initiator_split.share_percentage + s.share_percentage, 2
            )
        s.share_amount = 0.0
        s.share_percentage = 0.0
        expired_count += 1

    await db.commit()

    if expired_count:
        logger.info("Expired %d pending splits for ride %d", expired_count, ride_id)

    return expired_count


async def update_split_amounts_for_actual_fare(
    ride_id: int, actual_fare: float, db: AsyncSession
) -> None:
    """Recalculate split amounts when actual fare differs from estimate.

    Called when a ride completes and actual_fare is set.
    Only updates splits that haven't been paid yet.
    """
    result = await db.execute(
        select(FareSplit).where(
            FareSplit.ride_id == ride_id,
            FareSplit.status.notin_([SplitStatus.CANCELLED, SplitStatus.DECLINED, SplitStatus.EXPIRED]),
        )
    )
    splits = result.scalars().all()

    if not splits:
        return

    for s in splits:
        if s.status != SplitStatus.PAID:
            s.share_amount = round(actual_fare * s.share_percentage / 100.0, 2)

    # Fix rounding
    total = sum(s.share_amount for s in splits if s.status != SplitStatus.PAID)
    unpaid_fare = actual_fare - sum(s.share_amount for s in splits if s.status == SplitStatus.PAID)
    diff = round(unpaid_fare - total, 2)
    if diff != 0:
        initiator = next((s for s in splits if s.is_initiator and s.status != SplitStatus.PAID), None)
        if initiator:
            initiator.share_amount = round(initiator.share_amount + diff, 2)

    await db.commit()


def _split_to_dict(split: FareSplit) -> dict[str, Any]:
    return {
        "id": split.id,
        "ride_id": split.ride_id,
        "user_id": split.user_id,
        "invite_phone": split.invite_phone,
        "invite_email": split.invite_email,
        "is_initiator": split.is_initiator,
        "status": split.status.value,
        "share_amount": split.share_amount,
        "share_percentage": split.share_percentage,
        "created_at": split.created_at.isoformat() if split.created_at else None,
        "responded_at": split.responded_at.isoformat() if split.responded_at else None,
    }
