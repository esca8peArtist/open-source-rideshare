from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import require_rider
from app.models.user import User
from app.schemas.trip_share import TripShareLinkResponse, TripShareView
from app.services.trip_share import (
    create_trip_share_link,
    get_active_link_for_ride,
    get_trip_share_view,
    revoke_trip_share_link,
)

router = APIRouter(tags=["trip-share"])


# ---------------------------------------------------------------------------
# Authenticated rider endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/riders/me/rides/{ride_id}/share-link",
    response_model=TripShareLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_share_link(ride_id: int, user: User = Depends(require_rider)):
    """Generate a public trip share link for the given ride.

    If an active link already exists for this ride it is revoked and a new one
    is created, so only one active link exists per ride at any time.
    """
    record = create_trip_share_link(rider_id=user.id, ride_id=ride_id)
    return TripShareLinkResponse(**record)


@router.get(
    "/riders/me/rides/{ride_id}/share-link",
    response_model=TripShareLinkResponse,
)
async def get_share_link(ride_id: int, user: User = Depends(require_rider)):
    """Return the active share link for the given ride, 404 if none."""
    record = get_active_link_for_ride(rider_id=user.id, ride_id=ride_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active share link found for this ride",
        )
    return TripShareLinkResponse(**record)


@router.delete(
    "/riders/me/rides/{ride_id}/share-link",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_share_link(ride_id: int, user: User = Depends(require_rider)):
    """Revoke the active share link for the given ride."""
    try:
        revoke_trip_share_link(rider_id=user.id, ride_id=ride_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ---------------------------------------------------------------------------
# Public endpoint — no auth required
# ---------------------------------------------------------------------------


@router.get(
    "/trip-share/{token}",
    response_model=TripShareView,
)
async def view_trip_share(token: str):
    """Public read-only view of a shared ride. No authentication required.

    Returns 404 if the token is not found, 410 if it has been revoked or
    has expired.
    """
    try:
        view = get_trip_share_view(token)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Share link has expired or been revoked",
        )
    return TripShareView(**view)
