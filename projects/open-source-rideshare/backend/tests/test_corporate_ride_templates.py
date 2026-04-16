"""Tests for the Corporate Ride Templates feature.

Service layer (async, mocked DB):
  1.  create_ride_template — creates with is_active=True, use_count=0
  2.  create_ride_template — 409 when template with same name exists
  3.  get_ride_template — 404 when not found
  4.  get_ride_template — returns template when found
  5.  list_ride_templates — returns all templates for account ordered by name
  6.  list_ride_templates — filters by is_active=True
  7.  list_ride_templates — filters by is_active=False
  8.  update_ride_template — 404 when not found
  9.  update_ride_template — 409 on name collision with another template
  10. update_ride_template — partial update writes only supplied fields
  11. update_ride_template — name same as self does not 409
  12. deactivate_ride_template — 404 when not found
  13. deactivate_ride_template — 409 when already inactive
  14. deactivate_ride_template — success sets is_active=False
  15. reactivate_ride_template — 404 when not found
  16. reactivate_ride_template — 409 when already active
  17. reactivate_ride_template — success sets is_active=True
  18. delete_ride_template — 404 when not found
  19. delete_ride_template — success deletes template
  20. record_template_use — 404 when not found
  21. record_template_use — 409 when template is inactive
  22. record_template_use — success increments use_count
  23. get_popular_templates — returns active templates ordered by use_count desc
  24. get_popular_templates — respects limit parameter
  25. list_all_platform — returns all templates without account filter
  26. list_all_platform — filters by account_id

Schema validation:
  27. RideTemplateCreate — name, pickup_location_name, dropoff_location_name required
  28. RideTemplateCreate — name cannot be empty string
  29. RideTemplateCreate — optional fields accept None
  30. RideTemplateUpdate — all fields optional
  31. RideTemplateResponse — from_attributes construction
  32. RideTemplateResponse — lat/lng float conversion
  33. RideTemplateListResponse — items and total construction

API layer (service functions patched):
  34. GET list — 200 member can list templates
  35. GET list — 404 when no corporate account
  36. GET list — filters is_active query param
  37. GET popular — 200 member can get popular templates
  38. GET popular — respects limit param
  39. GET get — 200 member can view template
  40. GET get — 404 when template not found
  41. POST create — 201 admin can create template
  42. POST create — 403 non-admin cannot create
  43. POST create — 409 duplicate name
  44. PATCH update — 200 admin can update template
  45. PATCH update — 403 non-admin cannot update
  46. PATCH update — 409 name collision
  47. POST deactivate — 200 admin can deactivate
  48. POST deactivate — 409 already inactive
  49. POST reactivate — 200 admin can reactivate
  50. POST reactivate — 409 already active
  51. DELETE template — 204 admin can delete
  52. DELETE template — 403 non-admin cannot delete
  53. POST use — 200 member can record use
  54. POST use — 409 inactive template
  55. GET platform all — 200 platform-admin list all templates
  56. GET platform account — 200 platform-admin list account templates
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate_ride_template import CorporateRideTemplate
from app.schemas.corporate_ride_template import (
    RideTemplateCreate,
    RideTemplateListResponse,
    RideTemplateResponse,
    RideTemplateUpdate,
)
from app.services.corporate_ride_template import (
    create_ride_template,
    deactivate_ride_template,
    delete_ride_template,
    get_popular_templates,
    get_ride_template,
    list_all_platform,
    list_ride_templates,
    reactivate_ride_template,
    record_template_use,
    update_ride_template,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 10
ADMIN_ID = 2
USER_ID = 1
TEMPLATE_ID = 77

_SERVICE = "app.services.corporate_ride_template"
_ROUTER = "app.api.v1.corporate_ride_templates"

_NOW = datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_template(
    template_id: int = TEMPLATE_ID,
    account_id: int = ACCOUNT_ID,
    name: str = "Airport Express",
    pickup_location_name: str = "HQ Lobby",
    dropoff_location_name: str = "Terminal 2",
    is_active: bool = True,
    use_count: int = 0,
    created_by_id: int | None = ADMIN_ID,
    vehicle_type: str | None = "standard",
    default_cost_center_id: int | None = None,
    default_trip_purpose_id: int | None = None,
) -> CorporateRideTemplate:
    """Build a minimal CorporateRideTemplate instance for testing."""
    t = CorporateRideTemplate()
    t.id = template_id
    t.account_id = account_id
    t.created_by_id = created_by_id
    t.name = name
    t.description = None
    t.pickup_location_name = pickup_location_name
    t.pickup_address_line1 = "123 Main St"
    t.pickup_address_line2 = None
    t.pickup_city = "Springfield"
    t.pickup_state = "IL"
    t.pickup_country = "US"
    t.pickup_postal_code = "62701"
    t.pickup_latitude = Decimal("39.7817")
    t.pickup_longitude = Decimal("-89.6501")
    t.dropoff_location_name = dropoff_location_name
    t.dropoff_address_line1 = "1 Airport Rd"
    t.dropoff_address_line2 = None
    t.dropoff_city = "Springfield"
    t.dropoff_state = "IL"
    t.dropoff_country = "US"
    t.dropoff_postal_code = "62702"
    t.dropoff_latitude = Decimal("39.8403")
    t.dropoff_longitude = Decimal("-89.6787")
    t.vehicle_type = vehicle_type
    t.default_cost_center_id = default_cost_center_id
    t.default_trip_purpose_id = default_trip_purpose_id
    t.notes = None
    t.use_count = use_count
    t.is_active = is_active
    t.created_at = _NOW
    t.updated_at = _NOW
    return t


def _make_template_response(
    template_id: int = TEMPLATE_ID,
    account_id: int = ACCOUNT_ID,
    name: str = "Airport Express",
    is_active: bool = True,
    use_count: int = 0,
) -> RideTemplateResponse:
    return RideTemplateResponse(
        id=template_id,
        account_id=account_id,
        created_by_id=ADMIN_ID,
        name=name,
        description=None,
        pickup_location_name="HQ Lobby",
        pickup_address_line1="123 Main St",
        pickup_address_line2=None,
        pickup_city="Springfield",
        pickup_state="IL",
        pickup_country="US",
        pickup_postal_code="62701",
        pickup_latitude=39.7817,
        pickup_longitude=-89.6501,
        dropoff_location_name="Terminal 2",
        dropoff_address_line1="1 Airport Rd",
        dropoff_address_line2=None,
        dropoff_city="Springfield",
        dropoff_state="IL",
        dropoff_country="US",
        dropoff_postal_code="62702",
        dropoff_latitude=39.8403,
        dropoff_longitude=-89.6787,
        vehicle_type="standard",
        default_cost_center_id=None,
        default_trip_purpose_id=None,
        notes=None,
        use_count=use_count,
        is_active=is_active,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_db(
    scalar_one_or_none=None,
    scalars_all=None,
    scalar_one=None,
) -> AsyncMock:
    """Build a lightweight async DB mock."""
    db = AsyncMock()

    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_one_or_none
    result.scalar_one.return_value = scalar_one if scalar_one is not None else 0
    if scalars_all is not None:
        result.scalars.return_value.all.return_value = scalars_all
    db.execute.return_value = result
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    db.add = MagicMock()
    return db


# ===========================================================================
# Service layer tests
# ===========================================================================


class TestCreateRideTemplate:
    """Tests for create_ride_template service function."""

    @pytest.mark.asyncio
    async def test_create_sets_defaults(self):
        """Test 1: create_ride_template creates with is_active=True, use_count=0."""
        template = _make_template()
        db = _make_db(scalar_one_or_none=None)  # no name conflict

        async def _refresh(obj):
            obj.id = TEMPLATE_ID
            obj.created_at = _NOW
            obj.updated_at = _NOW
            obj.use_count = 0

        db.refresh.side_effect = _refresh

        data = RideTemplateCreate(
            name="Airport Express",
            pickup_location_name="HQ Lobby",
            dropoff_location_name="Terminal 2",
        )
        result = await create_ride_template(db, ACCOUNT_ID, ADMIN_ID, data)

        db.add.assert_called_once()
        db.commit.assert_awaited_once()
        added = db.add.call_args[0][0]
        assert added.is_active is True
        assert added.use_count == 0
        assert added.account_id == ACCOUNT_ID

    @pytest.mark.asyncio
    async def test_create_409_duplicate_name(self):
        """Test 2: create_ride_template raises 409 when name already exists."""
        existing = _make_template()
        db = _make_db(scalar_one_or_none=existing)

        data = RideTemplateCreate(
            name="Airport Express",
            pickup_location_name="HQ Lobby",
            dropoff_location_name="Terminal 2",
        )
        with pytest.raises(HTTPException) as exc_info:
            await create_ride_template(db, ACCOUNT_ID, ADMIN_ID, data)
        assert exc_info.value.status_code == 409


class TestGetRideTemplate:
    """Tests for get_ride_template service function."""

    @pytest.mark.asyncio
    async def test_get_404_not_found(self):
        """Test 3: get_ride_template raises 404 when template not found."""
        db = _make_db(scalar_one_or_none=None)
        with pytest.raises(HTTPException) as exc_info:
            await get_ride_template(db, TEMPLATE_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_returns_template(self):
        """Test 4: get_ride_template returns template when found."""
        template = _make_template()
        db = _make_db(scalar_one_or_none=template)
        result = await get_ride_template(db, TEMPLATE_ID, ACCOUNT_ID)
        assert result.id == TEMPLATE_ID
        assert result.name == "Airport Express"


class TestListRideTemplates:
    """Tests for list_ride_templates service function."""

    @pytest.mark.asyncio
    async def test_list_all(self):
        """Test 5: list_ride_templates returns all templates ordered by name."""
        templates = [_make_template(name="Airport Express"), _make_template(template_id=78, name="Hotel Transfer")]
        db = _make_db(scalars_all=templates)
        result = await list_ride_templates(db, ACCOUNT_ID)
        assert result.total == 2
        assert len(result.items) == 2

    @pytest.mark.asyncio
    async def test_list_filter_active(self):
        """Test 6: list_ride_templates filters by is_active=True."""
        templates = [_make_template(is_active=True)]
        db = _make_db(scalars_all=templates)
        result = await list_ride_templates(db, ACCOUNT_ID, is_active=True)
        assert result.total == 1
        assert result.items[0].is_active is True

    @pytest.mark.asyncio
    async def test_list_filter_inactive(self):
        """Test 7: list_ride_templates filters by is_active=False."""
        templates = [_make_template(is_active=False)]
        db = _make_db(scalars_all=templates)
        result = await list_ride_templates(db, ACCOUNT_ID, is_active=False)
        assert result.total == 1
        assert result.items[0].is_active is False


class TestUpdateRideTemplate:
    """Tests for update_ride_template service function."""

    @pytest.mark.asyncio
    async def test_update_404_not_found(self):
        """Test 8: update_ride_template raises 404 when template not found."""
        db = _make_db(scalar_one_or_none=None)
        data = RideTemplateUpdate(description="Updated")
        with pytest.raises(HTTPException) as exc_info:
            await update_ride_template(db, TEMPLATE_ID, ACCOUNT_ID, data)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_409_name_collision(self):
        """Test 9: update_ride_template raises 409 on name collision."""
        existing = _make_template()
        other = _make_template(template_id=99, name="Hotel Transfer")

        call_count = 0

        async def side_effect(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # First call: fetch the template to update
                result.scalar_one_or_none.return_value = existing
            else:
                # Second call: check name conflict — another template exists
                result.scalar_one_or_none.return_value = other
            return result

        db = AsyncMock()
        db.execute.side_effect = side_effect
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        data = RideTemplateUpdate(name="Hotel Transfer")
        with pytest.raises(HTTPException) as exc_info:
            await update_ride_template(db, TEMPLATE_ID, ACCOUNT_ID, data)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_update_partial_writes_only_supplied(self):
        """Test 10: update_ride_template writes only supplied fields."""
        template = _make_template(name="Airport Express")
        db = _make_db(scalar_one_or_none=template)

        data = RideTemplateUpdate(description="Updated description")
        result = await update_ride_template(db, TEMPLATE_ID, ACCOUNT_ID, data)

        assert template.description == "Updated description"
        assert template.name == "Airport Express"  # unchanged
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_same_name_no_conflict(self):
        """Test 11: update_ride_template with same name as self does not 409."""
        template = _make_template(name="Airport Express")

        call_count = 0

        async def side_effect(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = template
            else:
                # Name conflict check excludes self — returns None
                result.scalar_one_or_none.return_value = None
            return result

        db = AsyncMock()
        db.execute.side_effect = side_effect
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        data = RideTemplateUpdate(name="Airport Express")
        result = await update_ride_template(db, TEMPLATE_ID, ACCOUNT_ID, data)
        db.commit.assert_awaited_once()


class TestDeactivateRideTemplate:
    """Tests for deactivate_ride_template service function."""

    @pytest.mark.asyncio
    async def test_deactivate_404_not_found(self):
        """Test 12: deactivate_ride_template raises 404 when not found."""
        db = _make_db(scalar_one_or_none=None)
        with pytest.raises(HTTPException) as exc_info:
            await deactivate_ride_template(db, TEMPLATE_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_deactivate_409_already_inactive(self):
        """Test 13: deactivate_ride_template raises 409 when already inactive."""
        template = _make_template(is_active=False)
        db = _make_db(scalar_one_or_none=template)
        with pytest.raises(HTTPException) as exc_info:
            await deactivate_ride_template(db, TEMPLATE_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_deactivate_success(self):
        """Test 14: deactivate_ride_template sets is_active=False."""
        template = _make_template(is_active=True)
        db = _make_db(scalar_one_or_none=template)
        await deactivate_ride_template(db, TEMPLATE_ID, ACCOUNT_ID)
        assert template.is_active is False
        db.commit.assert_awaited_once()


class TestReactivateRideTemplate:
    """Tests for reactivate_ride_template service function."""

    @pytest.mark.asyncio
    async def test_reactivate_404_not_found(self):
        """Test 15: reactivate_ride_template raises 404 when not found."""
        db = _make_db(scalar_one_or_none=None)
        with pytest.raises(HTTPException) as exc_info:
            await reactivate_ride_template(db, TEMPLATE_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_reactivate_409_already_active(self):
        """Test 16: reactivate_ride_template raises 409 when already active."""
        template = _make_template(is_active=True)
        db = _make_db(scalar_one_or_none=template)
        with pytest.raises(HTTPException) as exc_info:
            await reactivate_ride_template(db, TEMPLATE_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_reactivate_success(self):
        """Test 17: reactivate_ride_template sets is_active=True."""
        template = _make_template(is_active=False)
        db = _make_db(scalar_one_or_none=template)
        await reactivate_ride_template(db, TEMPLATE_ID, ACCOUNT_ID)
        assert template.is_active is True
        db.commit.assert_awaited_once()


class TestDeleteRideTemplate:
    """Tests for delete_ride_template service function."""

    @pytest.mark.asyncio
    async def test_delete_404_not_found(self):
        """Test 18: delete_ride_template raises 404 when not found."""
        db = _make_db(scalar_one_or_none=None)
        with pytest.raises(HTTPException) as exc_info:
            await delete_ride_template(db, TEMPLATE_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_success(self):
        """Test 19: delete_ride_template calls db.delete and commit."""
        template = _make_template()
        db = _make_db(scalar_one_or_none=template)
        await delete_ride_template(db, TEMPLATE_ID, ACCOUNT_ID)
        db.delete.assert_awaited_once_with(template)
        db.commit.assert_awaited_once()


class TestRecordTemplateUse:
    """Tests for record_template_use service function."""

    @pytest.mark.asyncio
    async def test_record_use_404_not_found(self):
        """Test 20: record_template_use raises 404 when not found."""
        db = _make_db(scalar_one_or_none=None)
        with pytest.raises(HTTPException) as exc_info:
            await record_template_use(db, TEMPLATE_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_record_use_409_inactive(self):
        """Test 21: record_template_use raises 409 when template is inactive."""
        template = _make_template(is_active=False)
        db = _make_db(scalar_one_or_none=template)
        with pytest.raises(HTTPException) as exc_info:
            await record_template_use(db, TEMPLATE_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_record_use_increments_count(self):
        """Test 22: record_template_use increments use_count by 1."""
        template = _make_template(use_count=5)
        db = _make_db(scalar_one_or_none=template)
        await record_template_use(db, TEMPLATE_ID, ACCOUNT_ID)
        assert template.use_count == 6
        db.commit.assert_awaited_once()


class TestGetPopularTemplates:
    """Tests for get_popular_templates service function."""

    @pytest.mark.asyncio
    async def test_popular_returns_ordered_by_use_count(self):
        """Test 23: get_popular_templates returns active templates ordered by use_count."""
        t1 = _make_template(template_id=1, name="A", use_count=10)
        t2 = _make_template(template_id=2, name="B", use_count=5)

        db = AsyncMock()
        result1 = MagicMock()
        result1.scalars.return_value.all.return_value = [t1, t2]
        result2 = MagicMock()
        result2.scalar_one.return_value = 2
        db.execute.side_effect = [result1, result2]
        db.commit = AsyncMock()

        result = await get_popular_templates(db, ACCOUNT_ID)
        assert result.total == 2
        assert result.items[0].use_count == 10
        assert result.items[1].use_count == 5

    @pytest.mark.asyncio
    async def test_popular_respects_limit(self):
        """Test 24: get_popular_templates respects the limit parameter."""
        t1 = _make_template(template_id=1, name="A", use_count=10)

        db = AsyncMock()
        result1 = MagicMock()
        result1.scalars.return_value.all.return_value = [t1]
        result2 = MagicMock()
        result2.scalar_one.return_value = 5  # total=5, limit=1 returned only 1
        db.execute.side_effect = [result1, result2]

        result = await get_popular_templates(db, ACCOUNT_ID, limit=1)
        assert len(result.items) == 1
        assert result.total == 5  # reflects the full active count


class TestListAllPlatform:
    """Tests for list_all_platform service function."""

    @pytest.mark.asyncio
    async def test_list_all_no_filter(self):
        """Test 25: list_all_platform returns all templates across accounts."""
        templates = [
            _make_template(account_id=1, template_id=1),
            _make_template(account_id=2, template_id=2),
        ]
        db = _make_db(scalars_all=templates)
        result = await list_all_platform(db)
        assert result.total == 2

    @pytest.mark.asyncio
    async def test_list_all_filtered_by_account(self):
        """Test 26: list_all_platform filters by account_id."""
        templates = [_make_template(account_id=ACCOUNT_ID)]
        db = _make_db(scalars_all=templates)
        result = await list_all_platform(db, account_id=ACCOUNT_ID)
        assert result.total == 1
        assert result.items[0].account_id == ACCOUNT_ID


# ===========================================================================
# Schema validation tests
# ===========================================================================


class TestSchemaValidation:
    """Tests for Pydantic schema validation."""

    def test_create_requires_name_and_locations(self):
        """Test 27: RideTemplateCreate requires name, pickup_location_name, dropoff_location_name."""
        with pytest.raises(ValidationError):
            RideTemplateCreate(pickup_location_name="A", dropoff_location_name="B")
        with pytest.raises(ValidationError):
            RideTemplateCreate(name="X", dropoff_location_name="B")
        with pytest.raises(ValidationError):
            RideTemplateCreate(name="X", pickup_location_name="A")

    def test_create_name_cannot_be_empty(self):
        """Test 28: RideTemplateCreate name cannot be empty string."""
        with pytest.raises(ValidationError):
            RideTemplateCreate(
                name="",
                pickup_location_name="HQ",
                dropoff_location_name="Airport",
            )

    def test_create_optional_fields_accept_none(self):
        """Test 29: RideTemplateCreate optional fields can be None."""
        data = RideTemplateCreate(
            name="Route",
            pickup_location_name="HQ",
            dropoff_location_name="Airport",
            vehicle_type=None,
            default_cost_center_id=None,
            default_trip_purpose_id=None,
        )
        assert data.vehicle_type is None
        assert data.default_cost_center_id is None

    def test_update_all_optional(self):
        """Test 30: RideTemplateUpdate can be instantiated with no fields."""
        data = RideTemplateUpdate()
        assert data.name is None
        assert data.pickup_location_name is None

    def test_response_from_attributes(self):
        """Test 31: RideTemplateResponse builds from model attributes."""
        template = _make_template()
        resp = RideTemplateResponse.model_validate(template)
        assert resp.id == TEMPLATE_ID
        assert resp.name == "Airport Express"
        assert resp.is_active is True

    def test_response_lat_lng_float_conversion(self):
        """Test 32: RideTemplateResponse converts Decimal lat/lng to float."""
        template = _make_template()
        resp = RideTemplateResponse.model_validate(template)
        # model_validate with from_attributes — lat/lng come from _to_response
        # Use the helper directly instead
        from app.services.corporate_ride_template import _to_response
        result = _to_response(template)
        assert isinstance(result.pickup_latitude, float)
        assert isinstance(result.pickup_longitude, float)
        assert isinstance(result.dropoff_latitude, float)
        assert isinstance(result.dropoff_longitude, float)

    def test_list_response_construction(self):
        """Test 33: RideTemplateListResponse construction."""
        resp = RideTemplateResponse.model_validate(_make_template())
        list_resp = RideTemplateListResponse(items=[resp], total=1)
        assert list_resp.total == 1
        assert len(list_resp.items) == 1


# ===========================================================================
# API layer tests
# ===========================================================================

# Shared response fixtures
_TEMPLATE_RESP = _make_template_response()
_LIST_RESP = RideTemplateListResponse(items=[_TEMPLATE_RESP], total=1)
_EMPTY_LIST = RideTemplateListResponse(items=[], total=0)


def _make_user(user_id: int = USER_ID, is_admin: bool = False):
    u = MagicMock()
    u.id = user_id
    u.is_active = True
    u.is_admin = is_admin
    return u


class TestApiList:
    """API tests for GET /corporate/accounts/me/ride-templates."""

    @patch(f"{_ROUTER}.list_ride_templates", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._resolve_account_id", new_callable=AsyncMock)
    @patch(f"{_ROUTER}.get_current_user")
    @patch(f"{_ROUTER}.get_db")
    def test_list_200(self, mock_db, mock_user, mock_resolve, mock_list):
        """Test 34: Member can list templates."""
        mock_user.return_value = _make_user()
        mock_resolve.return_value = ACCOUNT_ID
        mock_list.return_value = _LIST_RESP

        import asyncio
        from app.api.v1.corporate_ride_templates import list_my_ride_templates

        result = asyncio.get_event_loop().run_until_complete(
            list_my_ride_templates(is_active=None, user=mock_user.return_value, db=AsyncMock())
        )
        assert result.total == 1

    @patch(f"{_ROUTER}._resolve_account_id", new_callable=AsyncMock)
    @patch(f"{_ROUTER}.get_current_user")
    @patch(f"{_ROUTER}.get_db")
    def test_list_404_no_account(self, mock_db, mock_user, mock_resolve):
        """Test 35: Returns 404 when user has no corporate account."""
        import asyncio
        mock_user.return_value = _make_user()
        mock_resolve.side_effect = HTTPException(status_code=404)

        from app.api.v1.corporate_ride_templates import list_my_ride_templates
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                list_my_ride_templates(is_active=None, user=mock_user.return_value, db=AsyncMock())
            )
        assert exc_info.value.status_code == 404

    @patch(f"{_ROUTER}.list_ride_templates", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._resolve_account_id", new_callable=AsyncMock)
    @patch(f"{_ROUTER}.get_current_user")
    @patch(f"{_ROUTER}.get_db")
    def test_list_passes_is_active(self, mock_db, mock_user, mock_resolve, mock_list):
        """Test 36: is_active filter is forwarded to service."""
        import asyncio
        mock_user.return_value = _make_user()
        mock_resolve.return_value = ACCOUNT_ID
        mock_list.return_value = _EMPTY_LIST

        from app.api.v1.corporate_ride_templates import list_my_ride_templates
        asyncio.get_event_loop().run_until_complete(
            list_my_ride_templates(is_active=True, user=mock_user.return_value, db=AsyncMock())
        )
        mock_list.assert_awaited_once()
        _, kwargs = mock_list.call_args
        assert kwargs.get("is_active") is True


class TestApiPopular:
    """API tests for GET /corporate/accounts/me/ride-templates/popular."""

    @patch(f"{_ROUTER}.get_popular_templates", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._resolve_account_id", new_callable=AsyncMock)
    @patch(f"{_ROUTER}.get_current_user")
    @patch(f"{_ROUTER}.get_db")
    def test_popular_200(self, mock_db, mock_user, mock_resolve, mock_popular):
        """Test 37: Member can get popular templates."""
        import asyncio
        mock_user.return_value = _make_user()
        mock_resolve.return_value = ACCOUNT_ID
        mock_popular.return_value = _LIST_RESP

        from app.api.v1.corporate_ride_templates import get_my_popular_templates
        result = asyncio.get_event_loop().run_until_complete(
            get_my_popular_templates(limit=10, user=mock_user.return_value, db=AsyncMock())
        )
        assert result.total == 1

    @patch(f"{_ROUTER}.get_popular_templates", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._resolve_account_id", new_callable=AsyncMock)
    @patch(f"{_ROUTER}.get_current_user")
    @patch(f"{_ROUTER}.get_db")
    def test_popular_respects_limit(self, mock_db, mock_user, mock_resolve, mock_popular):
        """Test 38: limit param is forwarded to service."""
        import asyncio
        mock_user.return_value = _make_user()
        mock_resolve.return_value = ACCOUNT_ID
        mock_popular.return_value = _EMPTY_LIST

        from app.api.v1.corporate_ride_templates import get_my_popular_templates
        asyncio.get_event_loop().run_until_complete(
            get_my_popular_templates(limit=5, user=mock_user.return_value, db=AsyncMock())
        )
        mock_popular.assert_awaited_once()
        _, kwargs = mock_popular.call_args
        assert kwargs.get("limit") == 5


class TestApiGet:
    """API tests for GET /corporate/accounts/me/ride-templates/{template_id}."""

    @patch(f"{_ROUTER}.get_ride_template", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._resolve_account_id", new_callable=AsyncMock)
    @patch(f"{_ROUTER}.get_current_user")
    @patch(f"{_ROUTER}.get_db")
    def test_get_200(self, mock_db, mock_user, mock_resolve, mock_get):
        """Test 39: Member can view a template."""
        import asyncio
        mock_user.return_value = _make_user()
        mock_resolve.return_value = ACCOUNT_ID
        mock_get.return_value = _TEMPLATE_RESP

        from app.api.v1.corporate_ride_templates import get_my_ride_template
        result = asyncio.get_event_loop().run_until_complete(
            get_my_ride_template(template_id=TEMPLATE_ID, user=mock_user.return_value, db=AsyncMock())
        )
        assert result.id == TEMPLATE_ID

    @patch(f"{_ROUTER}.get_ride_template", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._resolve_account_id", new_callable=AsyncMock)
    @patch(f"{_ROUTER}.get_current_user")
    @patch(f"{_ROUTER}.get_db")
    def test_get_404(self, mock_db, mock_user, mock_resolve, mock_get):
        """Test 40: Returns 404 when template not found."""
        import asyncio
        mock_user.return_value = _make_user()
        mock_resolve.return_value = ACCOUNT_ID
        mock_get.side_effect = HTTPException(status_code=404)

        from app.api.v1.corporate_ride_templates import get_my_ride_template
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                get_my_ride_template(template_id=999, user=mock_user.return_value, db=AsyncMock())
            )
        assert exc_info.value.status_code == 404


class TestApiCreate:
    """API tests for POST /corporate/accounts/me/ride-templates."""

    @patch(f"{_ROUTER}.create_ride_template", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._resolve_account_id", new_callable=AsyncMock)
    @patch(f"{_ROUTER}.get_current_user")
    @patch(f"{_ROUTER}.get_db")
    def test_create_201_admin(self, mock_db, mock_user, mock_resolve, mock_admin, mock_create):
        """Test 41: Admin can create a template."""
        import asyncio
        mock_user.return_value = _make_user(is_admin=True)
        mock_resolve.return_value = ACCOUNT_ID
        mock_admin.return_value = None
        mock_create.return_value = _TEMPLATE_RESP

        data = RideTemplateCreate(
            name="Airport Express",
            pickup_location_name="HQ Lobby",
            dropoff_location_name="Terminal 2",
        )
        from app.api.v1.corporate_ride_templates import create_my_ride_template
        result = asyncio.get_event_loop().run_until_complete(
            create_my_ride_template(data=data, user=mock_user.return_value, db=AsyncMock())
        )
        assert result.name == "Airport Express"

    @patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._resolve_account_id", new_callable=AsyncMock)
    @patch(f"{_ROUTER}.get_current_user")
    @patch(f"{_ROUTER}.get_db")
    def test_create_403_non_admin(self, mock_db, mock_user, mock_resolve, mock_admin):
        """Test 42: Non-admin cannot create a template."""
        import asyncio
        mock_user.return_value = _make_user()
        mock_resolve.return_value = ACCOUNT_ID
        mock_admin.side_effect = HTTPException(status_code=403)

        data = RideTemplateCreate(
            name="X",
            pickup_location_name="A",
            dropoff_location_name="B",
        )
        from app.api.v1.corporate_ride_templates import create_my_ride_template
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                create_my_ride_template(data=data, user=mock_user.return_value, db=AsyncMock())
            )
        assert exc_info.value.status_code == 403

    @patch(f"{_ROUTER}.create_ride_template", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._resolve_account_id", new_callable=AsyncMock)
    @patch(f"{_ROUTER}.get_current_user")
    @patch(f"{_ROUTER}.get_db")
    def test_create_409_duplicate(self, mock_db, mock_user, mock_resolve, mock_admin, mock_create):
        """Test 43: Returns 409 on duplicate name."""
        import asyncio
        mock_user.return_value = _make_user(is_admin=True)
        mock_resolve.return_value = ACCOUNT_ID
        mock_admin.return_value = None
        mock_create.side_effect = HTTPException(status_code=409)

        data = RideTemplateCreate(
            name="Airport Express",
            pickup_location_name="HQ",
            dropoff_location_name="Airport",
        )
        from app.api.v1.corporate_ride_templates import create_my_ride_template
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                create_my_ride_template(data=data, user=mock_user.return_value, db=AsyncMock())
            )
        assert exc_info.value.status_code == 409


class TestApiUpdate:
    """API tests for PATCH /corporate/accounts/me/ride-templates/{template_id}."""

    @patch(f"{_ROUTER}.update_ride_template", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._resolve_account_id", new_callable=AsyncMock)
    @patch(f"{_ROUTER}.get_current_user")
    @patch(f"{_ROUTER}.get_db")
    def test_update_200(self, mock_db, mock_user, mock_resolve, mock_admin, mock_update):
        """Test 44: Admin can update a template."""
        import asyncio
        mock_user.return_value = _make_user(is_admin=True)
        mock_resolve.return_value = ACCOUNT_ID
        mock_admin.return_value = None
        mock_update.return_value = _TEMPLATE_RESP

        from app.api.v1.corporate_ride_templates import update_my_ride_template
        result = asyncio.get_event_loop().run_until_complete(
            update_my_ride_template(
                template_id=TEMPLATE_ID,
                data=RideTemplateUpdate(description="New desc"),
                user=mock_user.return_value,
                db=AsyncMock(),
            )
        )
        assert result.id == TEMPLATE_ID

    @patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._resolve_account_id", new_callable=AsyncMock)
    @patch(f"{_ROUTER}.get_current_user")
    @patch(f"{_ROUTER}.get_db")
    def test_update_403_non_admin(self, mock_db, mock_user, mock_resolve, mock_admin):
        """Test 45: Non-admin cannot update a template."""
        import asyncio
        mock_user.return_value = _make_user()
        mock_resolve.return_value = ACCOUNT_ID
        mock_admin.side_effect = HTTPException(status_code=403)

        from app.api.v1.corporate_ride_templates import update_my_ride_template
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                update_my_ride_template(
                    template_id=TEMPLATE_ID,
                    data=RideTemplateUpdate(),
                    user=mock_user.return_value,
                    db=AsyncMock(),
                )
            )
        assert exc_info.value.status_code == 403

    @patch(f"{_ROUTER}.update_ride_template", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._resolve_account_id", new_callable=AsyncMock)
    @patch(f"{_ROUTER}.get_current_user")
    @patch(f"{_ROUTER}.get_db")
    def test_update_409_name_collision(self, mock_db, mock_user, mock_resolve, mock_admin, mock_update):
        """Test 46: Returns 409 on name collision."""
        import asyncio
        mock_user.return_value = _make_user(is_admin=True)
        mock_resolve.return_value = ACCOUNT_ID
        mock_admin.return_value = None
        mock_update.side_effect = HTTPException(status_code=409)

        from app.api.v1.corporate_ride_templates import update_my_ride_template
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                update_my_ride_template(
                    template_id=TEMPLATE_ID,
                    data=RideTemplateUpdate(name="Conflict"),
                    user=mock_user.return_value,
                    db=AsyncMock(),
                )
            )
        assert exc_info.value.status_code == 409


class TestApiDeactivate:
    """API tests for POST /corporate/accounts/me/ride-templates/{id}/deactivate."""

    @patch(f"{_ROUTER}.deactivate_ride_template", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._resolve_account_id", new_callable=AsyncMock)
    @patch(f"{_ROUTER}.get_current_user")
    @patch(f"{_ROUTER}.get_db")
    def test_deactivate_200(self, mock_db, mock_user, mock_resolve, mock_admin, mock_deactivate):
        """Test 47: Admin can deactivate a template."""
        import asyncio
        mock_user.return_value = _make_user(is_admin=True)
        mock_resolve.return_value = ACCOUNT_ID
        mock_admin.return_value = None
        mock_deactivate.return_value = _make_template_response(is_active=False)

        from app.api.v1.corporate_ride_templates import deactivate_my_ride_template
        result = asyncio.get_event_loop().run_until_complete(
            deactivate_my_ride_template(template_id=TEMPLATE_ID, user=mock_user.return_value, db=AsyncMock())
        )
        assert result.is_active is False

    @patch(f"{_ROUTER}.deactivate_ride_template", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._resolve_account_id", new_callable=AsyncMock)
    @patch(f"{_ROUTER}.get_current_user")
    @patch(f"{_ROUTER}.get_db")
    def test_deactivate_409_already_inactive(self, mock_db, mock_user, mock_resolve, mock_admin, mock_deactivate):
        """Test 48: Returns 409 when already inactive."""
        import asyncio
        mock_user.return_value = _make_user(is_admin=True)
        mock_resolve.return_value = ACCOUNT_ID
        mock_admin.return_value = None
        mock_deactivate.side_effect = HTTPException(status_code=409)

        from app.api.v1.corporate_ride_templates import deactivate_my_ride_template
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                deactivate_my_ride_template(template_id=TEMPLATE_ID, user=mock_user.return_value, db=AsyncMock())
            )
        assert exc_info.value.status_code == 409


class TestApiReactivate:
    """API tests for POST /corporate/accounts/me/ride-templates/{id}/reactivate."""

    @patch(f"{_ROUTER}.reactivate_ride_template", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._resolve_account_id", new_callable=AsyncMock)
    @patch(f"{_ROUTER}.get_current_user")
    @patch(f"{_ROUTER}.get_db")
    def test_reactivate_200(self, mock_db, mock_user, mock_resolve, mock_admin, mock_reactivate):
        """Test 49: Admin can reactivate a template."""
        import asyncio
        mock_user.return_value = _make_user(is_admin=True)
        mock_resolve.return_value = ACCOUNT_ID
        mock_admin.return_value = None
        mock_reactivate.return_value = _TEMPLATE_RESP

        from app.api.v1.corporate_ride_templates import reactivate_my_ride_template
        result = asyncio.get_event_loop().run_until_complete(
            reactivate_my_ride_template(template_id=TEMPLATE_ID, user=mock_user.return_value, db=AsyncMock())
        )
        assert result.is_active is True

    @patch(f"{_ROUTER}.reactivate_ride_template", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._resolve_account_id", new_callable=AsyncMock)
    @patch(f"{_ROUTER}.get_current_user")
    @patch(f"{_ROUTER}.get_db")
    def test_reactivate_409_already_active(self, mock_db, mock_user, mock_resolve, mock_admin, mock_reactivate):
        """Test 50: Returns 409 when already active."""
        import asyncio
        mock_user.return_value = _make_user(is_admin=True)
        mock_resolve.return_value = ACCOUNT_ID
        mock_admin.return_value = None
        mock_reactivate.side_effect = HTTPException(status_code=409)

        from app.api.v1.corporate_ride_templates import reactivate_my_ride_template
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                reactivate_my_ride_template(template_id=TEMPLATE_ID, user=mock_user.return_value, db=AsyncMock())
            )
        assert exc_info.value.status_code == 409


class TestApiDelete:
    """API tests for DELETE /corporate/accounts/me/ride-templates/{template_id}."""

    @patch(f"{_ROUTER}.delete_ride_template", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._resolve_account_id", new_callable=AsyncMock)
    @patch(f"{_ROUTER}.get_current_user")
    @patch(f"{_ROUTER}.get_db")
    def test_delete_204(self, mock_db, mock_user, mock_resolve, mock_admin, mock_delete):
        """Test 51: Admin can delete a template (204)."""
        import asyncio
        mock_user.return_value = _make_user(is_admin=True)
        mock_resolve.return_value = ACCOUNT_ID
        mock_admin.return_value = None
        mock_delete.return_value = None

        from app.api.v1.corporate_ride_templates import delete_my_ride_template
        asyncio.get_event_loop().run_until_complete(
            delete_my_ride_template(template_id=TEMPLATE_ID, user=mock_user.return_value, db=AsyncMock())
        )
        mock_delete.assert_awaited_once()

    @patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._resolve_account_id", new_callable=AsyncMock)
    @patch(f"{_ROUTER}.get_current_user")
    @patch(f"{_ROUTER}.get_db")
    def test_delete_403_non_admin(self, mock_db, mock_user, mock_resolve, mock_admin):
        """Test 52: Non-admin cannot delete a template."""
        import asyncio
        mock_user.return_value = _make_user()
        mock_resolve.return_value = ACCOUNT_ID
        mock_admin.side_effect = HTTPException(status_code=403)

        from app.api.v1.corporate_ride_templates import delete_my_ride_template
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                delete_my_ride_template(template_id=TEMPLATE_ID, user=mock_user.return_value, db=AsyncMock())
            )
        assert exc_info.value.status_code == 403


class TestApiUse:
    """API tests for POST /corporate/accounts/me/ride-templates/{id}/use."""

    @patch(f"{_ROUTER}.record_template_use", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._resolve_account_id", new_callable=AsyncMock)
    @patch(f"{_ROUTER}.get_current_user")
    @patch(f"{_ROUTER}.get_db")
    def test_use_200(self, mock_db, mock_user, mock_resolve, mock_record):
        """Test 53: Member can record template use."""
        import asyncio
        mock_user.return_value = _make_user()
        mock_resolve.return_value = ACCOUNT_ID
        mock_record.return_value = _make_template_response(use_count=1)

        from app.api.v1.corporate_ride_templates import use_ride_template
        result = asyncio.get_event_loop().run_until_complete(
            use_ride_template(template_id=TEMPLATE_ID, user=mock_user.return_value, db=AsyncMock())
        )
        assert result.use_count == 1

    @patch(f"{_ROUTER}.record_template_use", new_callable=AsyncMock)
    @patch(f"{_ROUTER}._resolve_account_id", new_callable=AsyncMock)
    @patch(f"{_ROUTER}.get_current_user")
    @patch(f"{_ROUTER}.get_db")
    def test_use_409_inactive(self, mock_db, mock_user, mock_resolve, mock_record):
        """Test 54: Returns 409 for inactive template."""
        import asyncio
        mock_user.return_value = _make_user()
        mock_resolve.return_value = ACCOUNT_ID
        mock_record.side_effect = HTTPException(status_code=409)

        from app.api.v1.corporate_ride_templates import use_ride_template
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                use_ride_template(template_id=TEMPLATE_ID, user=mock_user.return_value, db=AsyncMock())
            )
        assert exc_info.value.status_code == 409


class TestApiPlatformAdmin:
    """API tests for platform-admin endpoints."""

    @patch(f"{_ROUTER}.list_all_platform", new_callable=AsyncMock)
    @patch(f"{_ROUTER}.require_admin")
    @patch(f"{_ROUTER}.get_db")
    def test_platform_list_all_200(self, mock_db, mock_admin, mock_list_all):
        """Test 55: Platform-admin can list all templates."""
        import asyncio
        mock_admin.return_value = _make_user(is_admin=True)
        mock_list_all.return_value = _LIST_RESP

        from app.api.v1.corporate_ride_templates import admin_list_all_ride_templates
        result = asyncio.get_event_loop().run_until_complete(
            admin_list_all_ride_templates(
                account_id=None,
                _admin=mock_admin.return_value,
                db=AsyncMock(),
            )
        )
        assert result.total == 1

    @patch(f"{_ROUTER}.list_ride_templates", new_callable=AsyncMock)
    @patch(f"{_ROUTER}.require_admin")
    @patch(f"{_ROUTER}.get_db")
    def test_platform_list_account_200(self, mock_db, mock_admin, mock_list):
        """Test 56: Platform-admin can list templates for a specific account."""
        import asyncio
        mock_admin.return_value = _make_user(is_admin=True)
        mock_list.return_value = _LIST_RESP

        from app.api.v1.corporate_ride_templates import admin_list_account_ride_templates
        result = asyncio.get_event_loop().run_until_complete(
            admin_list_account_ride_templates(
                account_id=ACCOUNT_ID,
                is_active=None,
                _admin=mock_admin.return_value,
                db=AsyncMock(),
            )
        )
        assert result.total == 1
        mock_list.assert_awaited_once()
