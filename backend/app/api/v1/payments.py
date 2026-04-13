import logging

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.db.database import get_db
from app.models.payment import Payment, PaymentType
from app.models.ride import Ride, RideStatus
from app.models.user import User
from app.schemas.ride import TipRequest
from app.services.payments import (
    add_tip,
    create_cancellation_payment_intent,
    create_payment_intent,
    handle_payment_failed,
    handle_payment_succeeded,
    process_refund,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/create-intent/{ride_id}")
async def create_payment(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()

    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride.rider_id != user.id:
        raise HTTPException(status_code=403, detail="Only the rider can pay")
    if ride.status != RideStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="Ride must be completed before payment")
    if not ride.actual_fare:
        raise HTTPException(status_code=409, detail="Fare not calculated yet")

    try:
        result = await create_payment_intent(ride, db)
    except stripe.StripeError as e:
        logger.error("Stripe error creating intent for ride %d: %s", ride_id, e)
        raise HTTPException(status_code=502, detail="Payment service unavailable")

    return result


@router.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    from app.db.database import async_session

    async with async_session() as db:
        if event["type"] == "payment_intent.succeeded":
            await handle_payment_succeeded(event["data"]["object"], db)
        elif event["type"] == "payment_intent.payment_failed":
            await handle_payment_failed(event["data"]["object"], db)
        else:
            logger.debug("Unhandled Stripe event type: %s", event["type"])

    return {"status": "ok"}


@router.get("/{ride_id}")
async def get_payment_status(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()

    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride.rider_id != user.id and ride.driver_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    result = await db.execute(
        select(Payment).where(Payment.ride_id == ride_id).order_by(Payment.created_at)
    )
    payments = result.scalars().all()

    if not payments:
        return {"ride_id": ride_id, "status": "no_payment"}

    fare_payment = next((p for p in payments if p.payment_type == PaymentType.RIDE_FARE), None)
    cancel_payment = next((p for p in payments if p.payment_type == PaymentType.CANCELLATION_FEE), None)

    resp: dict = {"ride_id": ride_id}

    if fare_payment:
        resp.update({
            "amount": fare_payment.amount,
            "tip_amount": fare_payment.tip_amount,
            "platform_fee": fare_payment.platform_fee,
            "driver_payout": fare_payment.driver_payout,
            "status": fare_payment.status.value,
        })

    if cancel_payment:
        resp["cancellation_fee"] = {
            "amount": cancel_payment.amount,
            "driver_payout": cancel_payment.driver_payout,
            "status": cancel_payment.status.value,
        }

    if not fare_payment and cancel_payment:
        resp["status"] = cancel_payment.status.value

    return resp


@router.post("/{ride_id}/tip")
async def add_ride_tip(
    ride_id: int,
    req: TipRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()

    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride.rider_id != user.id:
        raise HTTPException(status_code=403, detail="Only the rider can tip")
    if ride.status != RideStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="Ride must be completed before tipping")

    try:
        result = await add_tip(ride_id, req.amount, db)
    except stripe.StripeError as e:
        logger.error("Stripe error adding tip for ride %d: %s", ride_id, e)
        raise HTTPException(status_code=502, detail="Payment service unavailable")

    if "error" in result:
        raise HTTPException(status_code=409, detail=result["error"])

    return result


@router.post("/{ride_id}/refund")
async def refund_payment(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()

    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride.rider_id != user.id:
        raise HTTPException(status_code=403, detail="Only the rider can request a refund")

    try:
        result = await process_refund(ride_id, db)
    except stripe.StripeError as e:
        logger.error("Stripe error processing refund for ride %d: %s", ride_id, e)
        raise HTTPException(status_code=502, detail="Payment service unavailable")

    if "error" in result:
        raise HTTPException(status_code=409, detail=result["error"])

    return result
