from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import require_admin, require_rider
from app.models.user import User
from app.schemas.trip_share import AdminTripShareEntry, AdminTripShareListResponse, TripShareLinkResponse, TripShareView
from app.services.trip_share import (
    admin_revoke_by_token,
    create_trip_share_link,
    get_active_link_for_ride,
    get_trip_share_view,
    list_trip_share_links,
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


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/admin/trip-shares",
    response_model=AdminTripShareListResponse,
)
async def admin_list_trip_shares(
    rider_id: int | None = Query(None, description="Filter by rider user ID"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _admin: User = Depends(require_admin),
):
    """List all trip share links.  Optionally filter by rider or active status."""
    items = list_trip_share_links(rider_id=rider_id, is_active=is_active, skip=skip, limit=limit)
    total = len(list_trip_share_links(rider_id=rider_id, is_active=is_active, skip=0, limit=10_000))
    return AdminTripShareListResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=[AdminTripShareEntry(**r) for r in items],
    )


@router.delete(
    "/admin/trip-shares/{token}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def admin_revoke_trip_share(
    token: str,
    _admin: User = Depends(require_admin),
):
    """Revoke a trip share link by token regardless of ownership."""
    try:
        admin_revoke_by_token(token)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
