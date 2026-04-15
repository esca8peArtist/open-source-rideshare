"""Ride receipt endpoints.

Provides a dedicated router for receipt retrieval, separate from the main
rides router. Both riders and drivers on a completed ride may fetch the
receipt.

Endpoints:
  GET /rides/{ride_id}/receipt  — authenticated rider or driver gets receipt
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.ride import RideReceiptResponse
from app.services.receipts import generate_receipt

router = APIRouter(tags=["receipts"])


@router.get(
    "/rides/{ride_id}/receipt",
    response_model=RideReceiptResponse,
    summary="Get a detailed receipt for a completed ride",
)
async def get_ride_receipt(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a full fare breakdown and payment summary for a completed ride.

    The requesting user must be either the rider or the driver on the ride.
    Returns 404 if the ride does not exist, is not completed, or the user is
    not a participant.
    """
    receipt = await generate_receipt(ride_id, user.id, db)
    if not receipt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Receipt not available — ride not found, not completed, or access denied",
        )
    return RideReceiptResponse(**receipt)
