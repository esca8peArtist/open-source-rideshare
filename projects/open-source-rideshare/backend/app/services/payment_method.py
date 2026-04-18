from __future__ import annotations

import logging
from datetime import datetime, timezone

import stripe

from app.config import settings
from app.schemas.payment_method import PaymentMethodCreate, PaymentMethodResponse, SetupIntentResponse

logger = logging.getLogger(__name__)

stripe.api_key = settings.stripe_secret_key

# ---------------------------------------------------------------------------
# In-memory store (same pattern as other rider safety services)
# ---------------------------------------------------------------------------

_next_id: int = 1
_methods: dict[int, dict] = {}  # pm_id -> record


def _reset_store() -> None:
    global _next_id, _methods
    _next_id = 1
    _methods = {}


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------


def create_setup_intent() -> SetupIntentResponse:
    """Create a Stripe SetupIntent so the client can collect card details.

    Degrades gracefully when Stripe is not configured (returns stub).
    """
    try:
        intent = stripe.SetupIntent.create(usage="off_session")
        return SetupIntentResponse(
            setup_intent_id=intent.id,
            client_secret=intent.client_secret,
        )
    except Exception as exc:
        logger.warning("Stripe SetupIntent creation failed (stub returned): %s", exc)
        return SetupIntentResponse(setup_intent_id="si_stub", client_secret=None)


def add_payment_method(user_id: int, data: PaymentMethodCreate) -> PaymentMethodResponse:
    """Save a confirmed payment method for the rider.

    Raises:
        RuntimeError: if the same stripe_payment_method_id is already saved for this user.
    """
    global _next_id

    for m in _methods.values():
        if m["user_id"] == user_id and m["stripe_payment_method_id"] == data.stripe_payment_method_id:
            raise RuntimeError("Payment method already saved")

    user_methods = [m for m in _methods.values() if m["user_id"] == user_id]
    is_default = len(user_methods) == 0

    record: dict = {
        "id": _next_id,
        "user_id": user_id,
        "stripe_payment_method_id": data.stripe_payment_method_id,
        "card_brand": data.card_brand,
        "card_last4": data.card_last4,
        "card_exp_month": data.card_exp_month,
        "card_exp_year": data.card_exp_year,
        "is_default": is_default,
        "created_at": datetime.now(tz=timezone.utc),
    }
    _methods[_next_id] = record
    _next_id += 1
    return PaymentMethodResponse(**record)


def list_payment_methods(user_id: int) -> list[PaymentMethodResponse]:
    """Return all saved payment methods for the rider, newest-first."""
    user_methods = [m for m in _methods.values() if m["user_id"] == user_id]
    user_methods.sort(key=lambda m: m["created_at"], reverse=True)
    return [PaymentMethodResponse(**m) for m in user_methods]


def get_payment_method(pm_id: int, user_id: int) -> dict | None:
    """Return the raw record if it exists and belongs to user_id, else None."""
    m = _methods.get(pm_id)
    if m and m["user_id"] == user_id:
        return m
    return None


def remove_payment_method(pm_id: int, user_id: int) -> None:
    """Delete a saved payment method.

    Raises:
        LookupError: if not found or wrong owner.

    Side effect: if the deleted method was the default, promotes the oldest
    remaining method to default.
    """
    m = _methods.get(pm_id)
    if not m or m["user_id"] != user_id:
        raise LookupError("Payment method not found")

    was_default = m["is_default"]
    del _methods[pm_id]

    if was_default:
        remaining = sorted(
            [r for r in _methods.values() if r["user_id"] == user_id],
            key=lambda r: r["created_at"],
        )
        if remaining:
            remaining[0]["is_default"] = True


def set_default_payment_method(pm_id: int, user_id: int) -> PaymentMethodResponse:
    """Set a payment method as the rider's default, clearing all others.

    Raises:
        LookupError: if not found or wrong owner.
    """
    m = _methods.get(pm_id)
    if not m or m["user_id"] != user_id:
        raise LookupError("Payment method not found")

    for record in _methods.values():
        if record["user_id"] == user_id:
            record["is_default"] = record["id"] == pm_id

    return PaymentMethodResponse(**_methods[pm_id])
