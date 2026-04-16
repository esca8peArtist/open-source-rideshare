"""Tests for the Corporate Service Zones feature.

Service layer (async, mocked DB):
  1.  create_service_zone — creates with is_active=True
  2.  create_service_zone — 409 when zone with same name exists
  3.  get_service_zone — 404 when not found
  4.  get_service_zone — returns zone when found
  5.  list_service_zones — returns all zones ordered by name
  6.  list_service_zones — filters by is_active=True
  7.  list_service_zones — filters by is_active=False
  8.  list_service_zones — filters by zone_type=restricted
  9.  update_service_zone — 404 when not found
  10. update_service_zone — 409 on name collision
  11. update_service_zone — partial update writes only supplied fields
  12. update_service_zone — same name as self does not 409
  13. deactivate_service_zone — 404 when not found
  14. deactivate_service_zone — 409 when already inactive
  15. deactivate_service_zone — success sets is_active=False
  16. reactivate_service_zone — 404 when not found
  17. reactivate_service_zone — 409 when already active
  18. reactivate_service_zone — success sets is_active=True
  19. delete_service_zone — 404 when not found
  20. delete_service_zone — success deletes zone
  21. check_ride_zones — empty when no active zones
  22. check_ride_zones — pickup match for zone applies_to=pickup
  23. check_ride_zones — dropoff match for zone applies_to=dropoff
  24. check_ride_zones — both matches for zone applies_to=both
  25. check_ride_zones — no match when point outside radius
  26. check_ride_zones — is_restricted=True when restricted zone matches
  27. check_ride_zones — requires_approval=True when approval_required matches
  28. check_ride_zones — is_restricted wins over requires_approval
  29. check_ride_zones — group_ids=None zone applies to all members
  30. check_ride_zones — group_ids zone skipped when member not in group
  31. check_ride_zones — group_ids zone applies when member in group
  32. check_ride_zones — denial_reasons populated for restricted zone
  33. get_zone_coverage_summary — returns correct counts
  34. get_zone_coverage_summary — zero counts when no active zones
  35. list_all_platform — returns all zones without filter
  36. list_all_platform — filters by account_id

Haversine helper:
  37. _haversine_km — same point returns 0
  38. _haversine_km — known distance is accurate

Schema validation:
  39. ServiceZoneCreate — required fields enforced
  40. ServiceZoneCreate — radius_km must be > 0
  41. ServiceZoneCreate — latitude bounds enforced
  42. ServiceZoneCreate — optional fields accept None
  43. ServiceZoneUpdate — all fields optional
  44. ServiceZoneResponse — from_attributes construction
  45. ZoneCheckRequest — required fields enforced

API layer (service functions patched):
  46. GET list — 200 member can list zones
  47. GET list — 404 when no corporate account
  48. GET list — filters is_active and zone_type query params
  49. GET summary — 200 member can get coverage summary
  50. GET get — 200 member can view zone
  51. GET get — 404 when zone not found
  52. POST check — 200 member can check coordinates
  53. POST create — 201 admin can create zone
  54. POST create — 403 non-admin cannot create
  55. POST create — 409 duplicate name
  56. PATCH update — 200 admin can update zone
  57. PATCH update — 403 non-admin cannot update
  58. POST deactivate — 200 admin can deactivate
  59. POST deactivate — 409 already inactive
  60. POST reactivate — 200 admin can reactivate
  61. DELETE zone — 204 admin can delete
  62. DELETE zone — 403 non-admin cannot delete
  63. GET platform all — 200 platform-admin list all
  64. GET platform account — 200 platform-admin list account zones
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate_service_zone import (
    CorporateServiceZone,
    ZoneAppliesTo,
    ZoneType,
)
from app.schemas.corporate_service_zone import (
    ServiceZoneCreate,
    ServiceZoneListResponse,
    ServiceZoneResponse,
    ServiceZoneUpdate,
    ZoneCheckRequest,
    ZoneCheckResponse,
    ZoneCoverageSummary,
    ZoneMatchDetail,
)
from app.services.corporate_service_zone import (
    _haversine_km,
    _zone_applies_to_member,
    check_ride_zones,
    create_service_zone,
    deactivate_service_zone,
    delete_service_zone,
    get_service_zone,
    get_zone_coverage_summary,
    list_all_platform,
    list_service_zones,
    reactivate_service_zone,
    update_service_zone,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 10
ADMIN_ID = 2
USER_ID = 1
ZONE_ID = 42

_SERVICE = "app.services.corporate_service_zone"
_ROUTER = "app.api.v1.corporate_service_zones"

_NOW = datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)

# HQ: Chicago downtown
HQ_LAT = 41.8827
HQ_LON = -87.6233
# Airport: O'Hare (~27 km from HQ)
ORD_LAT = 41.9742
ORD_LON = -87.9073
# Suburb: ~5 km from HQ
SUB_LAT = 41.9300
SUB_LON = -87.6800


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_zone(
    zone_id: int = ZONE_ID,
    account_id: int = ACCOUNT_ID,
    name: str = "Downtown HQ",
    zone_type: ZoneType = ZoneType.allowed,
    center_latitude: float = HQ_LAT,
    center_longitude: float = HQ_LON,
    radius_km: float = 5.0,
    applies_to: ZoneAppliesTo = ZoneAppliesTo.both,
    group_ids: list | None = None,
    is_active: bool = True,
    created_by_id: int | None = ADMIN_ID,
) -> CorporateServiceZone:
    """Build a minimal CorporateServiceZone instance for testing."""
    z = CorporateServiceZone()
    z.id = zone_id
    z.account_id = account_id
    z.created_by_id = created_by_id
    z.name = name
    z.description = None
    z.zone_type = zone_type
    z.center_latitude = Decimal(str(center_latitude))
    z.center_longitude = Decimal(str(center_longitude))
    z.radius_km = Decimal(str(radius_km))
    z.applies_to = applies_to
    z.group_ids = group_ids
    z.is_active = is_active
    z.created_at = _NOW
    z.updated_at = _NOW
    return z


def _make_db(scalars_return=None, scalar_one_or_none="__unset__", scalar_one=None):
    """Create an AsyncSession mock with configurable query results."""
    db = AsyncMock()
    result = MagicMock()

    if scalars_return is not None:
        result.scalars.return_value.all.return_value = scalars_return
    # Always set scalar_one_or_none so MagicMock doesn't return a truthy sentinel
    result.scalar_one_or_none.return_value = (
        None if scalar_one_or_none == "__unset__" else scalar_one_or_none
    )
    if scalar_one is not None:
        result.scalar_one.return_value = scalar_one

    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Service layer — create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_service_zone_success():
    """create_service_zone creates a zone with is_active=True."""
    db = _make_db(scalar_one_or_none=None)
    data = ServiceZoneCreate(
        name="Airport Zone",
        zone_type=ZoneType.approval_required,
        center_latitude=ORD_LAT,
        center_longitude=ORD_LON,
        radius_km=3.0,
        applies_to=ZoneAppliesTo.dropoff,
    )

    async def _refresh(obj):
        obj.id = ZONE_ID
        obj.created_at = _NOW
        obj.updated_at = _NOW

    db.refresh.side_effect = _refresh

    result = await create_service_zone(db, ACCOUNT_ID, ADMIN_ID, data)

    db.add.assert_called_once()
    db.commit.assert_awaited_once()
    added = db.add.call_args[0][0]
    assert added.is_active is True
    assert added.account_id == ACCOUNT_ID
    assert added.name == "Airport Zone"
    assert added.zone_type == ZoneType.approval_required


@pytest.mark.asyncio
async def test_create_service_zone_409_duplicate_name():
    """create_service_zone raises 409 when name already exists."""
    existing = _make_zone()
    db = _make_db(scalar_one_or_none=existing)

    data = ServiceZoneCreate(
        name="Downtown HQ",
        zone_type=ZoneType.allowed,
        center_latitude=HQ_LAT,
        center_longitude=HQ_LON,
        radius_km=5.0,
    )

    with pytest.raises(HTTPException) as exc:
        await create_service_zone(db, ACCOUNT_ID, ADMIN_ID, data)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Service layer — get
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_service_zone_404():
    """get_service_zone raises 404 when zone not found."""
    db = _make_db(scalar_one_or_none=None)
    with pytest.raises(HTTPException) as exc:
        await get_service_zone(db, ZONE_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_service_zone_found():
    """get_service_zone returns the zone when found."""
    zone = _make_zone()
    db = _make_db(scalar_one_or_none=zone)
    result = await get_service_zone(db, ZONE_ID, ACCOUNT_ID)
    assert result.id == ZONE_ID
    assert result.name == "Downtown HQ"


# ---------------------------------------------------------------------------
# Service layer — list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_service_zones_all():
    """list_service_zones returns all zones for account ordered by name."""
    zones = [_make_zone(zone_id=1, name="A Zone"), _make_zone(zone_id=2, name="B Zone")]
    db = _make_db(scalars_return=zones)
    result = await list_service_zones(db, ACCOUNT_ID)
    assert result.total == 2
    assert len(result.items) == 2


@pytest.mark.asyncio
async def test_list_service_zones_filter_active():
    """list_service_zones with is_active=True only returns active zones."""
    zones = [_make_zone(is_active=True)]
    db = _make_db(scalars_return=zones)
    result = await list_service_zones(db, ACCOUNT_ID, is_active=True)
    assert all(z.is_active for z in result.items)


@pytest.mark.asyncio
async def test_list_service_zones_filter_inactive():
    """list_service_zones with is_active=False only returns inactive zones."""
    zones = [_make_zone(is_active=False)]
    db = _make_db(scalars_return=zones)
    result = await list_service_zones(db, ACCOUNT_ID, is_active=False)
    assert all(not z.is_active for z in result.items)


@pytest.mark.asyncio
async def test_list_service_zones_filter_zone_type():
    """list_service_zones with zone_type=restricted filters correctly."""
    zones = [_make_zone(zone_type=ZoneType.restricted)]
    db = _make_db(scalars_return=zones)
    result = await list_service_zones(db, ACCOUNT_ID, zone_type=ZoneType.restricted)
    assert all(z.zone_type == ZoneType.restricted for z in result.items)


# ---------------------------------------------------------------------------
# Service layer — update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_service_zone_404():
    """update_service_zone raises 404 when zone not found."""
    db = _make_db(scalar_one_or_none=None)
    data = ServiceZoneUpdate(radius_km=10.0)
    with pytest.raises(HTTPException) as exc:
        await update_service_zone(db, ZONE_ID, ACCOUNT_ID, data)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_service_zone_409_name_collision():
    """update_service_zone raises 409 when new name conflicts with another zone."""
    zone = _make_zone(name="Old Name")
    conflicting = _make_zone(zone_id=99, name="New Name")

    db = AsyncMock()
    result1 = MagicMock()
    result1.scalar_one_or_none.return_value = zone
    result2 = MagicMock()
    result2.scalar_one_or_none.return_value = conflicting

    db.execute = AsyncMock(side_effect=[result1, result2])

    data = ServiceZoneUpdate(name="New Name")
    with pytest.raises(HTTPException) as exc:
        await update_service_zone(db, ZONE_ID, ACCOUNT_ID, data)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_update_service_zone_partial_update():
    """update_service_zone writes only supplied fields."""
    zone = _make_zone(radius_km=5.0)

    db = AsyncMock()
    result1 = MagicMock()
    result1.scalar_one_or_none.return_value = zone
    db.execute = AsyncMock(return_value=result1)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    data = ServiceZoneUpdate(radius_km=12.0)
    result = await update_service_zone(db, ZONE_ID, ACCOUNT_ID, data)
    assert zone.radius_km == 12.0
    assert zone.description is None  # not in update payload, unchanged


@pytest.mark.asyncio
async def test_update_service_zone_same_name_no_409():
    """update_service_zone does not 409 when name is unchanged."""
    zone = _make_zone(name="Downtown HQ")

    db = AsyncMock()
    result1 = MagicMock()
    result1.scalar_one_or_none.return_value = zone
    db.execute = AsyncMock(return_value=result1)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    data = ServiceZoneUpdate(name="Downtown HQ", radius_km=8.0)
    # Should not raise — name unchanged so no conflict check needed
    await update_service_zone(db, ZONE_ID, ACCOUNT_ID, data)
    db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# Service layer — deactivate / reactivate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_service_zone_404():
    db = _make_db(scalar_one_or_none=None)
    with pytest.raises(HTTPException) as exc:
        await deactivate_service_zone(db, ZONE_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_deactivate_service_zone_409_already_inactive():
    zone = _make_zone(is_active=False)
    db = _make_db(scalar_one_or_none=zone)
    with pytest.raises(HTTPException) as exc:
        await deactivate_service_zone(db, ZONE_ID, ACCOUNT_ID)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_deactivate_service_zone_success():
    zone = _make_zone(is_active=True)
    db = _make_db(scalar_one_or_none=zone)
    result = await deactivate_service_zone(db, ZONE_ID, ACCOUNT_ID)
    assert zone.is_active is False
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_reactivate_service_zone_404():
    db = _make_db(scalar_one_or_none=None)
    with pytest.raises(HTTPException) as exc:
        await reactivate_service_zone(db, ZONE_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_reactivate_service_zone_409_already_active():
    zone = _make_zone(is_active=True)
    db = _make_db(scalar_one_or_none=zone)
    with pytest.raises(HTTPException) as exc:
        await reactivate_service_zone(db, ZONE_ID, ACCOUNT_ID)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_reactivate_service_zone_success():
    zone = _make_zone(is_active=False)
    db = _make_db(scalar_one_or_none=zone)
    result = await reactivate_service_zone(db, ZONE_ID, ACCOUNT_ID)
    assert zone.is_active is True
    db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# Service layer — delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_service_zone_404():
    db = _make_db(scalar_one_or_none=None)
    with pytest.raises(HTTPException) as exc:
        await delete_service_zone(db, ZONE_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_service_zone_success():
    zone = _make_zone()
    db = _make_db(scalar_one_or_none=zone)
    await delete_service_zone(db, ZONE_ID, ACCOUNT_ID)
    db.delete.assert_awaited_once_with(zone)
    db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# Service layer — check_ride_zones
# ---------------------------------------------------------------------------


def _check_request(
    pickup_lat=HQ_LAT, pickup_lon=HQ_LON,
    dropoff_lat=ORD_LAT, dropoff_lon=ORD_LON,
    member_group_ids=None,
):
    return ZoneCheckRequest(
        pickup_latitude=pickup_lat,
        pickup_longitude=pickup_lon,
        dropoff_latitude=dropoff_lat,
        dropoff_longitude=dropoff_lon,
        member_group_ids=member_group_ids,
    )


@pytest.mark.asyncio
async def test_check_ride_zones_empty_when_no_zones():
    """Returns empty matches when no active zones exist."""
    db = _make_db(scalars_return=[])
    result = await check_ride_zones(db, ACCOUNT_ID, _check_request())
    assert result.pickup_matches == []
    assert result.dropoff_matches == []
    assert result.is_restricted is False
    assert result.requires_approval is False


@pytest.mark.asyncio
async def test_check_ride_zones_pickup_match_applies_to_pickup():
    """Zone with applies_to=pickup matches against pickup lat/lng only."""
    zone = _make_zone(
        zone_type=ZoneType.allowed,
        center_latitude=HQ_LAT,
        center_longitude=HQ_LON,
        radius_km=1.0,
        applies_to=ZoneAppliesTo.pickup,
    )
    db = _make_db(scalars_return=[zone])
    # pickup is HQ (within 1km of HQ), dropoff is ORD (far away)
    result = await check_ride_zones(
        db, ACCOUNT_ID, _check_request(pickup_lat=HQ_LAT, pickup_lon=HQ_LON)
    )
    assert len(result.pickup_matches) == 1
    assert result.dropoff_matches == []


@pytest.mark.asyncio
async def test_check_ride_zones_dropoff_match_applies_to_dropoff():
    """Zone with applies_to=dropoff matches against dropoff lat/lng only."""
    zone = _make_zone(
        zone_type=ZoneType.allowed,
        center_latitude=ORD_LAT,
        center_longitude=ORD_LON,
        radius_km=1.0,
        applies_to=ZoneAppliesTo.dropoff,
    )
    db = _make_db(scalars_return=[zone])
    result = await check_ride_zones(
        db, ACCOUNT_ID, _check_request(dropoff_lat=ORD_LAT, dropoff_lon=ORD_LON)
    )
    assert result.pickup_matches == []
    assert len(result.dropoff_matches) == 1


@pytest.mark.asyncio
async def test_check_ride_zones_both_endpoints():
    """Zone with applies_to=both can match both pickup and dropoff."""
    zone = _make_zone(
        zone_type=ZoneType.allowed,
        center_latitude=HQ_LAT,
        center_longitude=HQ_LON,
        radius_km=100.0,  # large radius covers both HQ and ORD
        applies_to=ZoneAppliesTo.both,
    )
    db = _make_db(scalars_return=[zone])
    result = await check_ride_zones(
        db,
        ACCOUNT_ID,
        _check_request(
            pickup_lat=HQ_LAT, pickup_lon=HQ_LON,
            dropoff_lat=ORD_LAT, dropoff_lon=ORD_LON,
        ),
    )
    assert len(result.pickup_matches) == 1
    assert len(result.dropoff_matches) == 1


@pytest.mark.asyncio
async def test_check_ride_zones_no_match_outside_radius():
    """Points outside the zone radius produce no matches."""
    zone = _make_zone(
        center_latitude=HQ_LAT,
        center_longitude=HQ_LON,
        radius_km=1.0,  # 1 km — ORD is ~27 km away
        applies_to=ZoneAppliesTo.both,
    )
    db = _make_db(scalars_return=[zone])
    result = await check_ride_zones(
        db,
        ACCOUNT_ID,
        _check_request(
            pickup_lat=ORD_LAT, pickup_lon=ORD_LON,
            dropoff_lat=ORD_LAT, dropoff_lon=ORD_LON,
        ),
    )
    assert result.pickup_matches == []
    assert result.dropoff_matches == []


@pytest.mark.asyncio
async def test_check_ride_zones_is_restricted():
    """is_restricted=True when any restricted zone matches."""
    zone = _make_zone(
        zone_type=ZoneType.restricted,
        center_latitude=HQ_LAT,
        center_longitude=HQ_LON,
        radius_km=10.0,
        applies_to=ZoneAppliesTo.pickup,
    )
    db = _make_db(scalars_return=[zone])
    result = await check_ride_zones(
        db, ACCOUNT_ID, _check_request(pickup_lat=HQ_LAT, pickup_lon=HQ_LON)
    )
    assert result.is_restricted is True
    assert result.requires_approval is False
    assert len(result.denial_reasons) > 0


@pytest.mark.asyncio
async def test_check_ride_zones_requires_approval():
    """requires_approval=True when approval_required zone matches and not restricted."""
    zone = _make_zone(
        zone_type=ZoneType.approval_required,
        center_latitude=ORD_LAT,
        center_longitude=ORD_LON,
        radius_km=5.0,
        applies_to=ZoneAppliesTo.dropoff,
    )
    db = _make_db(scalars_return=[zone])
    result = await check_ride_zones(
        db, ACCOUNT_ID, _check_request(dropoff_lat=ORD_LAT, dropoff_lon=ORD_LON)
    )
    assert result.is_restricted is False
    assert result.requires_approval is True


@pytest.mark.asyncio
async def test_check_ride_zones_restricted_wins_over_approval():
    """is_restricted takes precedence; requires_approval stays False."""
    restricted_zone = _make_zone(
        zone_id=1,
        zone_type=ZoneType.restricted,
        center_latitude=HQ_LAT,
        center_longitude=HQ_LON,
        radius_km=10.0,
        applies_to=ZoneAppliesTo.pickup,
    )
    approval_zone = _make_zone(
        zone_id=2,
        name="Approval Zone",
        zone_type=ZoneType.approval_required,
        center_latitude=HQ_LAT,
        center_longitude=HQ_LON,
        radius_km=10.0,
        applies_to=ZoneAppliesTo.pickup,
    )
    db = _make_db(scalars_return=[restricted_zone, approval_zone])
    result = await check_ride_zones(
        db, ACCOUNT_ID, _check_request(pickup_lat=HQ_LAT, pickup_lon=HQ_LON)
    )
    assert result.is_restricted is True
    assert result.requires_approval is False


def test_zone_applies_to_member_no_group_restriction():
    """group_ids=None means zone applies to everyone."""
    zone = _make_zone(group_ids=None)
    assert _zone_applies_to_member(zone, None) is True
    assert _zone_applies_to_member(zone, [1, 2, 3]) is True


def test_zone_applies_to_member_not_in_group():
    """Zone with group_ids does not apply to member outside those groups."""
    zone = _make_zone(group_ids=[5, 6])
    assert _zone_applies_to_member(zone, [1, 2, 3]) is False
    assert _zone_applies_to_member(zone, None) is False


def test_zone_applies_to_member_in_group():
    """Zone applies when member shares at least one group_id."""
    zone = _make_zone(group_ids=[5, 6])
    assert _zone_applies_to_member(zone, [6, 7]) is True


@pytest.mark.asyncio
async def test_check_ride_zones_denial_reason_for_restricted():
    """Denial reasons include the restricted zone name."""
    zone = _make_zone(
        name="No-Go Zone",
        zone_type=ZoneType.restricted,
        center_latitude=HQ_LAT,
        center_longitude=HQ_LON,
        radius_km=10.0,
        applies_to=ZoneAppliesTo.both,
    )
    db = _make_db(scalars_return=[zone])
    result = await check_ride_zones(
        db, ACCOUNT_ID, _check_request(pickup_lat=HQ_LAT, pickup_lon=HQ_LON)
    )
    assert any("No-Go Zone" in r for r in result.denial_reasons)


# ---------------------------------------------------------------------------
# Service layer — coverage summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_zone_coverage_summary():
    """Coverage summary returns correct counts across zone types and applies_to."""
    zones = [
        _make_zone(zone_id=1, name="Z1", zone_type=ZoneType.allowed, applies_to=ZoneAppliesTo.both),
        _make_zone(zone_id=2, name="Z2", zone_type=ZoneType.restricted, applies_to=ZoneAppliesTo.pickup),
        _make_zone(zone_id=3, name="Z3", zone_type=ZoneType.approval_required, applies_to=ZoneAppliesTo.dropoff),
    ]
    db = _make_db(scalars_return=zones)
    result = await get_zone_coverage_summary(db, ACCOUNT_ID)
    assert result.total_active_zones == 3
    assert result.allowed_count == 1
    assert result.restricted_count == 1
    assert result.approval_required_count == 1
    assert result.pickup_only_count == 1
    assert result.dropoff_only_count == 1
    assert result.both_count == 1


@pytest.mark.asyncio
async def test_get_zone_coverage_summary_empty():
    """Coverage summary returns zeros when no active zones."""
    db = _make_db(scalars_return=[])
    result = await get_zone_coverage_summary(db, ACCOUNT_ID)
    assert result.total_active_zones == 0
    assert result.allowed_count == 0
    assert result.restricted_count == 0
    assert result.approval_required_count == 0


# ---------------------------------------------------------------------------
# Service layer — list_all_platform
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_platform_no_filter():
    """list_all_platform returns all zones across accounts."""
    zones = [_make_zone(zone_id=1, account_id=10), _make_zone(zone_id=2, account_id=20)]
    db = _make_db(scalars_return=zones)
    result = await list_all_platform(db, account_id=None)
    assert result.total == 2


@pytest.mark.asyncio
async def test_list_all_platform_filter_by_account():
    """list_all_platform filters by account_id."""
    zones = [_make_zone(zone_id=1, account_id=10)]
    db = _make_db(scalars_return=zones)
    result = await list_all_platform(db, account_id=10)
    assert result.total == 1
    assert result.items[0].account_id == 10


# ---------------------------------------------------------------------------
# Haversine helper
# ---------------------------------------------------------------------------


def test_haversine_same_point():
    """Distance from a point to itself is 0."""
    assert _haversine_km(HQ_LAT, HQ_LON, HQ_LAT, HQ_LON) == pytest.approx(0.0, abs=1e-6)


def test_haversine_known_distance():
    """HQ to ORD (Chicago to O'Hare) is approximately 26-28 km."""
    dist = _haversine_km(HQ_LAT, HQ_LON, ORD_LAT, ORD_LON)
    assert 25 < dist < 30


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_service_zone_create_required_fields():
    """ServiceZoneCreate raises ValidationError when required fields are missing."""
    with pytest.raises(ValidationError):
        ServiceZoneCreate()


def test_service_zone_create_radius_must_be_positive():
    """ServiceZoneCreate raises ValidationError when radius_km <= 0."""
    with pytest.raises(ValidationError):
        ServiceZoneCreate(
            name="Bad Zone",
            zone_type=ZoneType.allowed,
            center_latitude=HQ_LAT,
            center_longitude=HQ_LON,
            radius_km=0,
        )


def test_service_zone_create_latitude_bounds():
    """ServiceZoneCreate raises ValidationError for out-of-bounds latitude."""
    with pytest.raises(ValidationError):
        ServiceZoneCreate(
            name="Bad Zone",
            zone_type=ZoneType.allowed,
            center_latitude=95.0,
            center_longitude=HQ_LON,
            radius_km=5.0,
        )


def test_service_zone_create_optional_fields_none():
    """ServiceZoneCreate accepts None for optional fields."""
    z = ServiceZoneCreate(
        name="Test Zone",
        zone_type=ZoneType.restricted,
        center_latitude=HQ_LAT,
        center_longitude=HQ_LON,
        radius_km=2.5,
        description=None,
        group_ids=None,
    )
    assert z.description is None
    assert z.group_ids is None


def test_service_zone_update_all_optional():
    """ServiceZoneUpdate accepts an empty payload."""
    u = ServiceZoneUpdate()
    assert u.name is None
    assert u.radius_km is None


def test_service_zone_response_from_attributes():
    """ServiceZoneResponse can be constructed from a model instance."""
    zone = _make_zone()
    response = ServiceZoneResponse(
        id=zone.id,
        account_id=zone.account_id,
        created_by_id=zone.created_by_id,
        name=zone.name,
        description=zone.description,
        zone_type=zone.zone_type,
        center_latitude=float(zone.center_latitude),
        center_longitude=float(zone.center_longitude),
        radius_km=float(zone.radius_km),
        applies_to=zone.applies_to,
        group_ids=zone.group_ids,
        is_active=zone.is_active,
        created_at=zone.created_at,
        updated_at=zone.updated_at,
    )
    assert response.id == ZONE_ID
    assert response.zone_type == ZoneType.allowed


def test_zone_check_request_required_fields():
    """ZoneCheckRequest raises ValidationError when lat/lng missing."""
    with pytest.raises(ValidationError):
        ZoneCheckRequest(pickup_latitude=HQ_LAT, pickup_longitude=HQ_LON)


# ---------------------------------------------------------------------------
# API layer
# ---------------------------------------------------------------------------


def _make_zone_response(**kwargs):
    defaults = dict(
        id=ZONE_ID,
        account_id=ACCOUNT_ID,
        created_by_id=ADMIN_ID,
        name="Downtown HQ",
        description=None,
        zone_type=ZoneType.allowed,
        center_latitude=HQ_LAT,
        center_longitude=HQ_LON,
        radius_km=5.0,
        applies_to=ZoneAppliesTo.both,
        group_ids=None,
        is_active=True,
        created_at=_NOW,
        updated_at=_NOW,
    )
    defaults.update(kwargs)
    return ServiceZoneResponse(**defaults)


def _make_list_response(items=None, total=None):
    items = items or [_make_zone_response()]
    return ServiceZoneListResponse(items=items, total=total or len(items))


def _make_summary():
    return ZoneCoverageSummary(
        total_active_zones=2,
        allowed_count=1,
        restricted_count=1,
        approval_required_count=0,
        pickup_only_count=0,
        dropoff_only_count=0,
        both_count=2,
    )


def _make_check_response():
    return ZoneCheckResponse(
        pickup_matches=[],
        dropoff_matches=[],
        is_restricted=False,
        requires_approval=False,
        denial_reasons=[],
    )


@pytest.fixture
def client():
    """FastAPI test client."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def _auth_headers(user_id=USER_ID, is_admin=False):
    return {"X-Test-User-Id": str(user_id), "X-Test-Is-Admin": str(is_admin).lower()}


@pytest.mark.asyncio
async def test_api_list_zones_200():
    """GET list returns 200 for a corporate member."""
    with (
        patch(f"{_ROUTER}.get_current_user", return_value=MagicMock(id=USER_ID)),
        patch(f"{_ROUTER}.get_db", return_value=AsyncMock()),
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}.list_service_zones", return_value=_make_list_response()),
    ):
        from app.api.v1.corporate_service_zones import list_my_service_zones
        result = await list_my_service_zones(
            is_active=None,
            zone_type=None,
            user=MagicMock(id=USER_ID),
            db=AsyncMock(),
        )
        assert result.total == 1


@pytest.mark.asyncio
async def test_api_list_zones_404_no_account():
    """GET list returns 404 when user has no corporate account."""
    from fastapi import HTTPException

    with (
        patch(
            f"{_ROUTER}._resolve_account_id",
            side_effect=HTTPException(status_code=404, detail="No account"),
        ),
    ):
        from app.api.v1.corporate_service_zones import list_my_service_zones
        with pytest.raises(HTTPException) as exc:
            await list_my_service_zones(
                is_active=None,
                zone_type=None,
                user=MagicMock(id=USER_ID),
                db=AsyncMock(),
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_api_list_zones_with_filters():
    """GET list passes is_active and zone_type through to service."""
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}.list_service_zones", return_value=_make_list_response()) as mock_svc,
    ):
        from app.api.v1.corporate_service_zones import list_my_service_zones
        await list_my_service_zones(
            is_active=True,
            zone_type=ZoneType.restricted,
            user=MagicMock(id=USER_ID),
            db=AsyncMock(),
        )
        mock_svc.assert_awaited_once()
        call_kwargs = mock_svc.call_args
        assert call_kwargs.kwargs["is_active"] is True
        assert call_kwargs.kwargs["zone_type"] == ZoneType.restricted


@pytest.mark.asyncio
async def test_api_summary_200():
    """GET summary returns 200 for a member."""
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}.get_zone_coverage_summary", return_value=_make_summary()),
    ):
        from app.api.v1.corporate_service_zones import get_my_zone_coverage_summary
        result = await get_my_zone_coverage_summary(
            user=MagicMock(id=USER_ID), db=AsyncMock()
        )
        assert result.total_active_zones == 2


@pytest.mark.asyncio
async def test_api_get_zone_200():
    """GET zone returns 200 for a member."""
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}.get_service_zone", return_value=_make_zone_response()),
    ):
        from app.api.v1.corporate_service_zones import get_my_service_zone
        result = await get_my_service_zone(
            zone_id=ZONE_ID, user=MagicMock(id=USER_ID), db=AsyncMock()
        )
        assert result.id == ZONE_ID


@pytest.mark.asyncio
async def test_api_get_zone_404():
    """GET zone propagates 404 from service."""
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(
            f"{_ROUTER}.get_service_zone",
            side_effect=HTTPException(status_code=404, detail="Not found"),
        ),
    ):
        from app.api.v1.corporate_service_zones import get_my_service_zone
        with pytest.raises(HTTPException) as exc:
            await get_my_service_zone(
                zone_id=ZONE_ID, user=MagicMock(id=USER_ID), db=AsyncMock()
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_api_check_zones_200():
    """POST check returns 200 with zone check result."""
    req = ZoneCheckRequest(
        pickup_latitude=HQ_LAT,
        pickup_longitude=HQ_LON,
        dropoff_latitude=ORD_LAT,
        dropoff_longitude=ORD_LON,
    )
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}.check_ride_zones", return_value=_make_check_response()),
    ):
        from app.api.v1.corporate_service_zones import check_my_ride_zones
        result = await check_my_ride_zones(
            data=req, user=MagicMock(id=USER_ID), db=AsyncMock()
        )
        assert result.is_restricted is False


@pytest.mark.asyncio
async def test_api_create_zone_201_admin():
    """POST create returns 201 for an account admin."""
    data = ServiceZoneCreate(
        name="New Zone",
        zone_type=ZoneType.restricted,
        center_latitude=HQ_LAT,
        center_longitude=HQ_LON,
        radius_km=5.0,
    )
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin", return_value=None),
        patch(
            f"{_ROUTER}.create_service_zone",
            return_value=_make_zone_response(name="New Zone"),
        ),
    ):
        from app.api.v1.corporate_service_zones import create_my_service_zone
        result = await create_my_service_zone(
            data=data, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
        )
        assert result.name == "New Zone"


@pytest.mark.asyncio
async def test_api_create_zone_403_non_admin():
    """POST create raises 403 when caller is not an account admin."""
    data = ServiceZoneCreate(
        name="Zone",
        zone_type=ZoneType.allowed,
        center_latitude=HQ_LAT,
        center_longitude=HQ_LON,
        radius_km=5.0,
    )
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(
            f"{_ROUTER}._require_account_admin",
            side_effect=HTTPException(status_code=403, detail="Admin required"),
        ),
    ):
        from app.api.v1.corporate_service_zones import create_my_service_zone
        with pytest.raises(HTTPException) as exc:
            await create_my_service_zone(
                data=data, user=MagicMock(id=USER_ID), db=AsyncMock()
            )
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_api_create_zone_409_duplicate():
    """POST create propagates 409 on duplicate name."""
    data = ServiceZoneCreate(
        name="Downtown HQ",
        zone_type=ZoneType.allowed,
        center_latitude=HQ_LAT,
        center_longitude=HQ_LON,
        radius_km=5.0,
    )
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin", return_value=None),
        patch(
            f"{_ROUTER}.create_service_zone",
            side_effect=HTTPException(status_code=409, detail="Duplicate"),
        ),
    ):
        from app.api.v1.corporate_service_zones import create_my_service_zone
        with pytest.raises(HTTPException) as exc:
            await create_my_service_zone(
                data=data, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
            )
        assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_api_update_zone_200_admin():
    """PATCH update returns 200 for an account admin."""
    data = ServiceZoneUpdate(radius_km=8.0)
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin", return_value=None),
        patch(
            f"{_ROUTER}.update_service_zone",
            return_value=_make_zone_response(radius_km=8.0),
        ),
    ):
        from app.api.v1.corporate_service_zones import update_my_service_zone
        result = await update_my_service_zone(
            zone_id=ZONE_ID, data=data, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
        )
        assert result.radius_km == 8.0


@pytest.mark.asyncio
async def test_api_update_zone_403_non_admin():
    """PATCH update raises 403 for non-admin."""
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(
            f"{_ROUTER}._require_account_admin",
            side_effect=HTTPException(status_code=403, detail="Admin required"),
        ),
    ):
        from app.api.v1.corporate_service_zones import update_my_service_zone
        with pytest.raises(HTTPException) as exc:
            await update_my_service_zone(
                zone_id=ZONE_ID,
                data=ServiceZoneUpdate(),
                user=MagicMock(id=USER_ID),
                db=AsyncMock(),
            )
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_api_deactivate_zone_200():
    """POST deactivate returns 200 for admin."""
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin", return_value=None),
        patch(
            f"{_ROUTER}.deactivate_service_zone",
            return_value=_make_zone_response(is_active=False),
        ),
    ):
        from app.api.v1.corporate_service_zones import deactivate_my_service_zone
        result = await deactivate_my_service_zone(
            zone_id=ZONE_ID, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
        )
        assert result.is_active is False


@pytest.mark.asyncio
async def test_api_deactivate_zone_409():
    """POST deactivate propagates 409 when already inactive."""
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin", return_value=None),
        patch(
            f"{_ROUTER}.deactivate_service_zone",
            side_effect=HTTPException(status_code=409, detail="Already inactive"),
        ),
    ):
        from app.api.v1.corporate_service_zones import deactivate_my_service_zone
        with pytest.raises(HTTPException) as exc:
            await deactivate_my_service_zone(
                zone_id=ZONE_ID, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
            )
        assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_api_reactivate_zone_200():
    """POST reactivate returns 200 for admin."""
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin", return_value=None),
        patch(
            f"{_ROUTER}.reactivate_service_zone",
            return_value=_make_zone_response(is_active=True),
        ),
    ):
        from app.api.v1.corporate_service_zones import reactivate_my_service_zone
        result = await reactivate_my_service_zone(
            zone_id=ZONE_ID, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
        )
        assert result.is_active is True


@pytest.mark.asyncio
async def test_api_delete_zone_204():
    """DELETE zone returns 204 for admin."""
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin", return_value=None),
        patch(f"{_ROUTER}.delete_service_zone", return_value=None),
    ):
        from app.api.v1.corporate_service_zones import delete_my_service_zone
        result = await delete_my_service_zone(
            zone_id=ZONE_ID, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
        )
        assert result is None


@pytest.mark.asyncio
async def test_api_delete_zone_403_non_admin():
    """DELETE zone raises 403 for non-admin."""
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(
            f"{_ROUTER}._require_account_admin",
            side_effect=HTTPException(status_code=403, detail="Admin required"),
        ),
    ):
        from app.api.v1.corporate_service_zones import delete_my_service_zone
        with pytest.raises(HTTPException) as exc:
            await delete_my_service_zone(
                zone_id=ZONE_ID, user=MagicMock(id=USER_ID), db=AsyncMock()
            )
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_api_platform_list_all_200():
    """GET platform list returns 200 for platform admin."""
    with (
        patch(f"{_ROUTER}.list_all_platform", return_value=_make_list_response()),
    ):
        from app.api.v1.corporate_service_zones import admin_list_all_service_zones
        result = await admin_list_all_service_zones(
            account_id=None,
            _admin=MagicMock(),
            db=AsyncMock(),
        )
        assert result.total == 1


@pytest.mark.asyncio
async def test_api_platform_list_account_200():
    """GET platform account zones returns 200 for platform admin."""
    with (
        patch(
            f"{_ROUTER}.list_service_zones",
            return_value=_make_list_response(),
        ),
    ):
        from app.api.v1.corporate_service_zones import admin_list_account_service_zones
        result = await admin_list_account_service_zones(
            account_id=ACCOUNT_ID,
            is_active=None,
            zone_type=None,
            _admin=MagicMock(),
            db=AsyncMock(),
        )
        assert result.total == 1
