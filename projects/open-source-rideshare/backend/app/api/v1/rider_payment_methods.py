from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import require_rider
from app.models.user import User
from app.schemas.payment_method import (
    PaymentMethodCreate,
    PaymentMethodListResponse,
    PaymentMethodResponse,
    SetupIntentResponse,
)
from app.services.payment_method import (
    add_payment_method,
    create_setup_intent,
    list_payment_methods,
    remove_payment_method,
    set_default_payment_method,
)

router = APIRouter(prefix="/riders/me/payment-methods", tags=["rider-payment-methods"])


@router.post("/setup-intent", response_model=SetupIntentResponse)
async def get_setup_intent(user: User = Depends(require_rider)):
    """Create a Stripe SetupIntent so the client can securely collect card details."""
    return create_setup_intent()


@router.post("", response_model=PaymentMethodResponse, status_code=status.HTTP_201_CREATED)
async def save_payment_method(
    data: PaymentMethodCreate,
    user: User = Depends(require_rider),
):
    """Attach a confirmed Stripe PaymentMethod to the rider's account.

    The client must have already confirmed the SetupIntent. Pass the resulting
    stripe_payment_method_id along with the card display fields.
    The first saved method is automatically set as the default.
    """
    try:
        return add_payment_method(user.id, data)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("", response_model=PaymentMethodListResponse)
async def get_payment_methods(user: User = Depends(require_rider)):
    """List all saved payment methods for the authenticated rider, newest-first."""
    items = list_payment_methods(user.id)
    return PaymentMethodListResponse(items=items, total=len(items))


@router.delete("/{pm_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_payment_method(pm_id: int, user: User = Depends(require_rider)):
    """Remove a saved payment method.

    If the deleted method was the default, the oldest remaining method becomes
    the new default automatically.
    """
    try:
        remove_payment_method(pm_id, user.id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.put("/{pm_id}/default", response_model=PaymentMethodResponse)
async def make_default_payment_method(pm_id: int, user: User = Depends(require_rider)):
    """Set an existing saved payment method as the rider's default."""
    try:
        return set_default_payment_method(pm_id, user.id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
