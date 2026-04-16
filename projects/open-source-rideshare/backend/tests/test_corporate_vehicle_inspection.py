"""Tests for the Corporate Vehicle Inspection Checklists feature.

Service tests (async, mocked DB):
  1.  create_template — success
  2.  create_template — 409 on duplicate name
  3.  get_template — 404 when not in account
  4.  list_templates — returns all account templates
  5.  list_templates — is_active filter returns only active
  6.  update_template — success
  7.  update_template — 409 on name collision with another template
  8.  deactivate_template — success
  9.  deactivate_template — 409 if already inactive
  10. create_inspection — success without template
  11. create_inspection — 404 when vehicle not found
  12. create_inspection — 409 when vehicle inactive
  13. create_inspection — pre-populates items_checked from template
  14. get_inspection — 404 when not found
  15. submit_inspection — passes when all required items pass
  16. submit_inspection — fails when required item fails
  17. submit_inspection — requires_attention when only optional item fails
  18. submit_inspection — 409 if already submitted
  19. submit_inspection — defects_noted populated on failure
  20. submit_inspection — defects_noted is None when all pass
  21. list_vehicle_inspections — returns all for account
  22. list_vehicle_inspections — vehicle filter works
  23. list_vehicle_inspections — type filter works
  24. list_vehicle_inspections — status filter works
  25. get_account_inspection_summary — returns correct structure
  26. list_all_platform — returns all inspections
  27. list_all_platform — account_id filter works
  28. list_all_platform — inspection_type filter works
  29. list_all_templates_platform — returns all templates

Schema tests (sync):
  30. InspectionTemplateCreateRequest — valid
  31. InspectionTemplateUpdateRequest — all fields optional
  32. InspectionTemplateResponse — from_attributes works
  33. InspectionCreateRequest — valid
  34. InspectionSubmitRequest — valid
  35. InspectionResponse — from_attributes works
  36. InspectionSummaryResponse — valid

API layer tests (services patched):
  37. GET  list templates → 200
  38. GET  get template → 200
  39. POST create template → 201
  40. PUT  update template → 200
  41. POST deactivate template → 200
  42. GET  list inspections → 200
  43. POST create inspection → 201
  44. GET  get inspection → 200
  45. POST submit inspection → 200
  46. GET  summary → 200
  47. GET  platform list inspections → 200
  48. GET  platform list templates → 200
  49. create_inspection — items_checked has None passed for each template item
  50. submit_inspection — sets inspected_at timestamp
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models.corporate_vehicle_inspection import (
    CorporateVehicleInspection,
    CorporateVehicleInspectionTemplate,
    InspectionStatus,
    InspectionType,
)
from app.schemas.corporate_vehicle_inspection import (
    InspectionCreateRequest,
    InspectionListResponse,
    InspectionResponse,
    InspectionSubmitRequest,
    InspectionSummaryResponse,
    InspectionTemplateCreateRequest,
    InspectionTemplateListResponse,
    InspectionTemplateResponse,
    InspectionTemplateUpdateRequest,
)
from app.services.corporate_vehicle_inspection_service import (
    create_inspection,
    create_template,
    deactivate_template,
    get_account_inspection_summary,
    get_inspection,
    get_template,
    list_all_platform,
    list_all_templates_platform,
    list_templates,
    list_vehicle_inspections,
    submit_inspection,
    update_template,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)
ACCOUNT_ID = 1
ADMIN_ID = 3
TEMPLATE_UUID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
VEHICLE_UUID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
INSPECTION_UUID = uuid.UUID("cccccccc-0000-0000-0000-000000000003")
RESERVATION_UUID = uuid.UUID("dddddddd-0000-0000-0000-000000000004")

_TEMPLATE_BASE = "/api/v1/corporate/vehicle-inspections/templates"
_INSP_BASE = "/api/v1/corporate/vehicle-inspections"
_MODULE_SVC = "app.api.v1.corporate_vehicle_inspection"


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

_SAMPLE_ITEMS = [
    {"item_name": "Front headlights", "category": "Lights", "is_required": True},
    {"item_name": "Tire pressure", "category": "Tires", "is_required": False},
]

_SAMPLE_ITEMS_CHECKED = [
    {"item_name": "Front headlights", "category": "Lights", "passed": True, "notes": None},
    {"item_name": "Tire pressure", "category": "Tires", "passed": True, "notes": None},
]


def _make_template(**kwargs) -> CorporateVehicleInspectionTemplate:
    defaults = dict(
        id=TEMPLATE_UUID,
        account_id=ACCOUNT_ID,
        name="Pre-trip Standard",
        description="Standard pre-trip checklist",
        inspection_items=_SAMPLE_ITEMS,
        is_active=True,
        created_by_id=ADMIN_ID,
        created_at=_NOW,
        updated_at=_NOW,
    )
    defaults.update(kwargs)
    obj = MagicMock(spec=CorporateVehicleInspectionTemplate)
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_inspection(**kwargs) -> CorporateVehicleInspection:
    defaults = dict(
        id=INSPECTION_UUID,
        template_id=TEMPLATE_UUID,
        fleet_vehicle_id=VEHICLE_UUID,
        account_id=ACCOUNT_ID,
        reservation_id=None,
        inspection_type=InspectionType.pre_trip,
        inspection_status=InspectionStatus.pending,
        inspected_by_id=ADMIN_ID,
        inspected_at=None,
        odometer_miles=None,
        fuel_level_pct=None,
        items_checked=_SAMPLE_ITEMS_CHECKED,
        defects_noted=None,
        overall_notes=None,
        maintenance_log_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    defaults.update(kwargs)
    obj = MagicMock(spec=CorporateVehicleInspection)
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _mock_db_single(value) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    db.execute.return_value = result
    return db


def _mock_db_scalars(values: list) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    db.execute.return_value = result
    return db


def _make_app_client() -> TestClient:
    from app.main import app
    from app.api.deps import get_current_user, get_db, require_admin
    from app.models.user import User

    mock_user = MagicMock(spec=User)
    mock_user.id = ADMIN_ID

    async def override_user():
        return mock_user

    async def override_admin():
        return mock_user

    async def override_db():
        yield AsyncMock()

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[require_admin] = override_admin
    app.dependency_overrides[get_db] = override_db
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _clear_dep_overrides():
    yield
    from app.main import app
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_template_success():
    """create_template creates and adds a template."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    tmpl = await create_template(
        db,
        account_id=ACCOUNT_ID,
        name="Pre-trip Standard",
        inspection_items=_SAMPLE_ITEMS,
        created_by_id=ADMIN_ID,
    )

    db.add.assert_called_once()
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_template_duplicate_name_409():
    """create_template raises 409 when name already exists."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = TEMPLATE_UUID
    db.execute.return_value = result

    with pytest.raises(HTTPException) as exc_info:
        await create_template(
            db,
            account_id=ACCOUNT_ID,
            name="Pre-trip Standard",
            inspection_items=[],
        )
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_get_template_404():
    """get_template raises 404 when template is not in account."""
    db = _mock_db_single(None)
    with pytest.raises(HTTPException) as exc_info:
        await get_template(db, template_id=TEMPLATE_UUID, account_id=ACCOUNT_ID)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_templates_returns_all():
    """list_templates returns all templates for an account."""
    tmpl = _make_template()
    db = _mock_db_scalars([tmpl])
    result = await list_templates(db, account_id=ACCOUNT_ID)
    assert len(result) == 1
    assert result[0].name == "Pre-trip Standard"


@pytest.mark.asyncio
async def test_list_templates_is_active_filter():
    """list_templates with is_active=True returns only active templates."""
    active = _make_template(is_active=True)
    db = _mock_db_scalars([active])
    result = await list_templates(db, account_id=ACCOUNT_ID, is_active=True)
    assert all(t.is_active for t in result)


@pytest.mark.asyncio
async def test_update_template_success():
    """update_template changes the template name."""
    tmpl = _make_template()
    db = AsyncMock()

    # First execute: name uniqueness check (none found)
    no_result = MagicMock()
    no_result.scalar_one_or_none.return_value = None
    # Second execute: fetch template
    tmpl_result = MagicMock()
    tmpl_result.scalar_one_or_none.return_value = tmpl

    db.execute.side_effect = [tmpl_result, no_result]

    updated = await update_template(
        db, template_id=TEMPLATE_UUID, account_id=ACCOUNT_ID, name="Updated Name"
    )
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_template_name_collision_409():
    """update_template raises 409 if the new name belongs to another template."""
    other_id = uuid.uuid4()
    tmpl = _make_template()
    db = AsyncMock()

    # First execute: fetch template
    tmpl_result = MagicMock()
    tmpl_result.scalar_one_or_none.return_value = tmpl
    # Second execute: name check finds another template
    collision_result = MagicMock()
    collision_result.scalar_one_or_none.return_value = other_id

    db.execute.side_effect = [tmpl_result, collision_result]

    with pytest.raises(HTTPException) as exc_info:
        await update_template(
            db,
            template_id=TEMPLATE_UUID,
            account_id=ACCOUNT_ID,
            name="Taken Name",
        )
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_deactivate_template_success():
    """deactivate_template marks is_active=False."""
    tmpl = _make_template(is_active=True)
    db = _mock_db_single(tmpl)

    result = await deactivate_template(db, template_id=TEMPLATE_UUID, account_id=ACCOUNT_ID)
    assert tmpl.is_active is False
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_deactivate_template_already_inactive_409():
    """deactivate_template raises 409 if already inactive."""
    tmpl = _make_template(is_active=False)
    db = _mock_db_single(tmpl)

    with pytest.raises(HTTPException) as exc_info:
        await deactivate_template(db, template_id=TEMPLATE_UUID, account_id=ACCOUNT_ID)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_create_inspection_success_no_template():
    """create_inspection creates a pending inspection without a template."""
    from app.models.corporate_fleet_vehicle import CorporateFleetVehicle
    vehicle = MagicMock(spec=CorporateFleetVehicle)
    vehicle.is_active = True

    db = AsyncMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = vehicle
    db.execute.return_value = vehicle_result

    await create_inspection(
        db,
        account_id=ACCOUNT_ID,
        fleet_vehicle_id=VEHICLE_UUID,
        inspection_type=InspectionType.pre_trip,
    )

    db.add.assert_called_once()
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_inspection_vehicle_not_found_404():
    """create_inspection raises 404 when vehicle is not found."""
    db = _mock_db_single(None)

    with pytest.raises(HTTPException) as exc_info:
        await create_inspection(
            db,
            account_id=ACCOUNT_ID,
            fleet_vehicle_id=VEHICLE_UUID,
            inspection_type=InspectionType.pre_trip,
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_create_inspection_vehicle_inactive_409():
    """create_inspection raises 409 when vehicle is inactive."""
    from app.models.corporate_fleet_vehicle import CorporateFleetVehicle
    vehicle = MagicMock(spec=CorporateFleetVehicle)
    vehicle.is_active = False

    db = _mock_db_single(vehicle)

    with pytest.raises(HTTPException) as exc_info:
        await create_inspection(
            db,
            account_id=ACCOUNT_ID,
            fleet_vehicle_id=VEHICLE_UUID,
            inspection_type=InspectionType.pre_trip,
        )
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_create_inspection_prepopulates_items_from_template():
    """create_inspection pre-populates items_checked from template with passed=None."""
    from app.models.corporate_fleet_vehicle import CorporateFleetVehicle
    vehicle = MagicMock(spec=CorporateFleetVehicle)
    vehicle.is_active = True

    tmpl = _make_template()

    db = AsyncMock()
    # First execute: vehicle lookup
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = vehicle
    # Second execute: template lookup
    tmpl_result = MagicMock()
    tmpl_result.scalar_one_or_none.return_value = tmpl

    db.execute.side_effect = [vehicle_result, tmpl_result]

    added_objects = []

    # db.add is a regular MagicMock (not async) — use side_effect to capture
    db.add = MagicMock(side_effect=added_objects.append)

    await create_inspection(
        db,
        account_id=ACCOUNT_ID,
        fleet_vehicle_id=VEHICLE_UUID,
        inspection_type=InspectionType.pre_trip,
        template_id=TEMPLATE_UUID,
    )

    assert len(added_objects) == 1
    added_inspection = added_objects[0]
    assert len(added_inspection.items_checked) == len(_SAMPLE_ITEMS)
    for item in added_inspection.items_checked:
        assert item["passed"] is None
        assert item["notes"] is None


@pytest.mark.asyncio
async def test_get_inspection_404():
    """get_inspection raises 404 when not found."""
    db = _mock_db_single(None)
    with pytest.raises(HTTPException) as exc_info:
        await get_inspection(db, inspection_id=INSPECTION_UUID, account_id=ACCOUNT_ID)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_submit_inspection_passes_when_all_required_pass():
    """submit_inspection yields 'passed' when all required items pass."""
    insp = _make_inspection(inspection_status=InspectionStatus.pending)

    db = AsyncMock()
    insp_result = MagicMock()
    insp_result.scalar_one_or_none.return_value = insp
    # Template lookup (no template_id set on inspection)
    insp.template_id = None

    db.execute.return_value = insp_result

    items = [
        {"item_name": "Front headlights", "category": "Lights", "passed": True, "notes": None},
    ]
    result = await submit_inspection(
        db,
        inspection_id=INSPECTION_UUID,
        account_id=ACCOUNT_ID,
        items_checked=items,
    )

    assert insp.inspection_status == InspectionStatus.passed
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_submit_inspection_fails_when_required_item_fails():
    """submit_inspection yields 'failed' when a required item fails."""
    insp = _make_inspection(inspection_status=InspectionStatus.pending)
    insp.template_id = TEMPLATE_UUID

    tmpl = _make_template()

    db = AsyncMock()
    insp_result = MagicMock()
    insp_result.scalar_one_or_none.return_value = insp
    tmpl_result = MagicMock()
    tmpl_result.scalar_one_or_none.return_value = tmpl

    db.execute.side_effect = [insp_result, tmpl_result]

    items = [
        {"item_name": "Front headlights", "category": "Lights", "passed": False, "notes": "Blown"},
        {"item_name": "Tire pressure", "category": "Tires", "passed": True, "notes": None},
    ]
    await submit_inspection(
        db,
        inspection_id=INSPECTION_UUID,
        account_id=ACCOUNT_ID,
        items_checked=items,
    )

    assert insp.inspection_status == InspectionStatus.failed


@pytest.mark.asyncio
async def test_submit_inspection_requires_attention_when_optional_fails():
    """submit_inspection yields 'requires_attention' when only optional item fails."""
    insp = _make_inspection(inspection_status=InspectionStatus.pending)
    insp.template_id = TEMPLATE_UUID

    # Template has front headlights as required, tire pressure as NOT required
    tmpl = _make_template(
        inspection_items=[
            {"item_name": "Front headlights", "category": "Lights", "is_required": True},
            {"item_name": "Tire pressure", "category": "Tires", "is_required": False},
        ]
    )

    db = AsyncMock()
    insp_result = MagicMock()
    insp_result.scalar_one_or_none.return_value = insp
    tmpl_result = MagicMock()
    tmpl_result.scalar_one_or_none.return_value = tmpl

    db.execute.side_effect = [insp_result, tmpl_result]

    items = [
        {"item_name": "Front headlights", "category": "Lights", "passed": True, "notes": None},
        {"item_name": "Tire pressure", "category": "Tires", "passed": False, "notes": "Low"},
    ]
    await submit_inspection(
        db,
        inspection_id=INSPECTION_UUID,
        account_id=ACCOUNT_ID,
        items_checked=items,
    )

    assert insp.inspection_status == InspectionStatus.requires_attention


@pytest.mark.asyncio
async def test_submit_inspection_already_submitted_409():
    """submit_inspection raises 409 if inspection is not pending."""
    insp = _make_inspection(inspection_status=InspectionStatus.passed)
    db = _mock_db_single(insp)

    with pytest.raises(HTTPException) as exc_info:
        await submit_inspection(
            db,
            inspection_id=INSPECTION_UUID,
            account_id=ACCOUNT_ID,
            items_checked=[],
        )
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_submit_inspection_defects_noted_on_failure():
    """submit_inspection populates defects_noted with failed item names."""
    insp = _make_inspection(inspection_status=InspectionStatus.pending)
    insp.template_id = None

    db = _mock_db_single(insp)

    items = [
        {"item_name": "Brakes", "category": "Safety", "passed": False, "notes": "Squeaking"},
        {"item_name": "Wipers", "category": "Visibility", "passed": True, "notes": None},
    ]
    await submit_inspection(
        db,
        inspection_id=INSPECTION_UUID,
        account_id=ACCOUNT_ID,
        items_checked=items,
    )

    assert insp.defects_noted == ["Brakes"]


@pytest.mark.asyncio
async def test_submit_inspection_defects_noted_none_when_all_pass():
    """submit_inspection sets defects_noted to None when all items pass."""
    insp = _make_inspection(inspection_status=InspectionStatus.pending)
    insp.template_id = None

    db = _mock_db_single(insp)

    items = [
        {"item_name": "Brakes", "category": "Safety", "passed": True, "notes": None},
    ]
    await submit_inspection(
        db,
        inspection_id=INSPECTION_UUID,
        account_id=ACCOUNT_ID,
        items_checked=items,
    )

    assert insp.defects_noted is None


@pytest.mark.asyncio
async def test_submit_inspection_sets_inspected_at():
    """submit_inspection sets inspected_at timestamp."""
    insp = _make_inspection(inspection_status=InspectionStatus.pending, inspected_at=None)
    insp.template_id = None

    db = _mock_db_single(insp)

    await submit_inspection(
        db,
        inspection_id=INSPECTION_UUID,
        account_id=ACCOUNT_ID,
        items_checked=[],
    )

    assert insp.inspected_at is not None


@pytest.mark.asyncio
async def test_list_vehicle_inspections_returns_all():
    """list_vehicle_inspections returns all inspections for account."""
    insp = _make_inspection()
    db = _mock_db_scalars([insp])
    result = await list_vehicle_inspections(db, account_id=ACCOUNT_ID)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_list_vehicle_inspections_vehicle_filter():
    """list_vehicle_inspections vehicle filter narrows results."""
    insp = _make_inspection()
    db = _mock_db_scalars([insp])
    result = await list_vehicle_inspections(
        db, account_id=ACCOUNT_ID, fleet_vehicle_id=VEHICLE_UUID
    )
    assert len(result) == 1


@pytest.mark.asyncio
async def test_list_vehicle_inspections_type_filter():
    """list_vehicle_inspections type filter narrows results."""
    insp = _make_inspection(inspection_type=InspectionType.post_trip)
    db = _mock_db_scalars([insp])
    result = await list_vehicle_inspections(
        db, account_id=ACCOUNT_ID, inspection_type=InspectionType.post_trip
    )
    assert len(result) == 1


@pytest.mark.asyncio
async def test_list_vehicle_inspections_status_filter():
    """list_vehicle_inspections status filter narrows results."""
    insp = _make_inspection(inspection_status=InspectionStatus.passed)
    db = _mock_db_scalars([insp])
    result = await list_vehicle_inspections(
        db, account_id=ACCOUNT_ID, inspection_status=InspectionStatus.passed
    )
    assert len(result) == 1


@pytest.mark.asyncio
async def test_get_account_inspection_summary_structure():
    """get_account_inspection_summary returns expected dict structure."""
    db = AsyncMock()

    # by_status rows
    status_result = MagicMock()
    status_result.__iter__ = MagicMock(
        return_value=iter([
            (InspectionStatus.passed, 3),
            (InspectionStatus.failed, 1),
            (InspectionStatus.pending, 2),
        ])
    )

    # by_type rows
    type_result = MagicMock()
    type_result.__iter__ = MagicMock(
        return_value=iter([
            (InspectionType.pre_trip, 4),
            (InspectionType.post_trip, 2),
        ])
    )

    # vehicles_with_pending count
    pending_result = MagicMock()
    pending_result.scalar_one.return_value = 2

    # recent failures
    failures_result = MagicMock()
    failures_result.scalars.return_value.all.return_value = []

    db.execute.side_effect = [status_result, type_result, pending_result, failures_result]

    summary = await get_account_inspection_summary(db, account_id=ACCOUNT_ID)

    assert "account_id" in summary
    assert "by_status" in summary
    assert "by_type" in summary
    assert "pass_rate_pct" in summary
    assert "vehicles_with_pending" in summary
    assert "recent_failures" in summary
    assert summary["account_id"] == ACCOUNT_ID


@pytest.mark.asyncio
async def test_list_all_platform_returns_all():
    """list_all_platform returns inspections across all accounts."""
    insp = _make_inspection()
    db = _mock_db_scalars([insp])
    result = await list_all_platform(db)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_list_all_platform_account_filter():
    """list_all_platform filters by account_id."""
    insp = _make_inspection()
    db = _mock_db_scalars([insp])
    result = await list_all_platform(db, account_id=ACCOUNT_ID)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_list_all_platform_type_filter():
    """list_all_platform filters by inspection_type."""
    insp = _make_inspection(inspection_type=InspectionType.scheduled)
    db = _mock_db_scalars([insp])
    result = await list_all_platform(db, inspection_type=InspectionType.scheduled)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_list_all_templates_platform_returns_all():
    """list_all_templates_platform returns templates across all accounts."""
    tmpl = _make_template()
    db = _mock_db_scalars([tmpl])
    result = await list_all_templates_platform(db)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_inspection_template_create_request_valid():
    """InspectionTemplateCreateRequest accepts valid input."""
    req = InspectionTemplateCreateRequest(
        name="Standard Pre-trip",
        description="A checklist",
        inspection_items=_SAMPLE_ITEMS,
    )
    assert req.name == "Standard Pre-trip"
    assert len(req.inspection_items) == 2


def test_inspection_template_update_request_all_optional():
    """InspectionTemplateUpdateRequest allows empty body."""
    req = InspectionTemplateUpdateRequest()
    assert req.name is None
    assert req.description is None
    assert req.inspection_items is None
    assert req.is_active is None


def test_inspection_template_response_from_attributes():
    """InspectionTemplateResponse.model_validate works with ORM-like object."""
    tmpl = _make_template()
    resp = InspectionTemplateResponse.model_validate(tmpl)
    assert resp.id == TEMPLATE_UUID
    assert resp.account_id == ACCOUNT_ID
    assert resp.name == "Pre-trip Standard"
    assert resp.is_active is True


def test_inspection_create_request_valid():
    """InspectionCreateRequest accepts valid input."""
    req = InspectionCreateRequest(
        fleet_vehicle_id=VEHICLE_UUID,
        inspection_type=InspectionType.pre_trip,
        template_id=TEMPLATE_UUID,
        reservation_id=None,
    )
    assert req.fleet_vehicle_id == VEHICLE_UUID
    assert req.inspection_type == InspectionType.pre_trip


def test_inspection_submit_request_valid():
    """InspectionSubmitRequest accepts valid input."""
    req = InspectionSubmitRequest(
        items_checked=_SAMPLE_ITEMS_CHECKED,
        odometer_miles=50000,
        fuel_level_pct=75,
        overall_notes="All good.",
    )
    assert len(req.items_checked) == 2
    assert req.fuel_level_pct == 75


def test_inspection_response_from_attributes():
    """InspectionResponse.model_validate works with ORM-like object."""
    insp = _make_inspection()
    resp = InspectionResponse.model_validate(insp)
    assert resp.id == INSPECTION_UUID
    assert resp.account_id == ACCOUNT_ID
    assert resp.inspection_status == InspectionStatus.pending


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------


def test_api_list_templates_200():
    """GET /templates returns 200 with template list."""
    client = _make_app_client()
    tmpl = _make_template()
    with (
        patch(f"{_MODULE_SVC}.get_user_account", new_callable=AsyncMock) as mock_acct,
        patch(f"{_MODULE_SVC}.list_templates", new_callable=AsyncMock) as mock_svc,
    ):
        mock_acct.return_value = MagicMock(id=ACCOUNT_ID)
        mock_svc.return_value = [tmpl]
        resp = client.get(_TEMPLATE_BASE)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1


def test_api_get_template_200():
    """GET /templates/{id} returns 200."""
    client = _make_app_client()
    tmpl = _make_template()
    with (
        patch(f"{_MODULE_SVC}.get_user_account", new_callable=AsyncMock) as mock_acct,
        patch(f"{_MODULE_SVC}.get_template", new_callable=AsyncMock) as mock_svc,
    ):
        mock_acct.return_value = MagicMock(id=ACCOUNT_ID)
        mock_svc.return_value = tmpl
        resp = client.get(f"{_TEMPLATE_BASE}/{TEMPLATE_UUID}")
    assert resp.status_code == 200


def test_api_create_template_201():
    """POST /templates returns 201."""
    client = _make_app_client()
    tmpl = _make_template()
    with (
        patch(f"{_MODULE_SVC}.get_user_account", new_callable=AsyncMock) as mock_acct,
        patch(f"{_MODULE_SVC}.create_template", new_callable=AsyncMock) as mock_svc,
    ):
        mock_acct.return_value = MagicMock(id=ACCOUNT_ID)
        mock_svc.return_value = tmpl
        resp = client.post(
            _TEMPLATE_BASE,
            json={"name": "New Template", "inspection_items": []},
        )
    assert resp.status_code == 201


def test_api_update_template_200():
    """PUT /templates/{id} returns 200."""
    client = _make_app_client()
    tmpl = _make_template()
    with (
        patch(f"{_MODULE_SVC}.get_user_account", new_callable=AsyncMock) as mock_acct,
        patch(f"{_MODULE_SVC}.update_template", new_callable=AsyncMock) as mock_svc,
    ):
        mock_acct.return_value = MagicMock(id=ACCOUNT_ID)
        mock_svc.return_value = tmpl
        resp = client.put(
            f"{_TEMPLATE_BASE}/{TEMPLATE_UUID}",
            json={"name": "Updated"},
        )
    assert resp.status_code == 200


def test_api_deactivate_template_200():
    """POST /templates/{id}/deactivate returns 200."""
    client = _make_app_client()
    tmpl = _make_template(is_active=False)
    with (
        patch(f"{_MODULE_SVC}.get_user_account", new_callable=AsyncMock) as mock_acct,
        patch(f"{_MODULE_SVC}.deactivate_template", new_callable=AsyncMock) as mock_svc,
    ):
        mock_acct.return_value = MagicMock(id=ACCOUNT_ID)
        mock_svc.return_value = tmpl
        resp = client.post(f"{_TEMPLATE_BASE}/{TEMPLATE_UUID}/deactivate")
    assert resp.status_code == 200


def test_api_list_inspections_200():
    """GET /corporate/vehicle-inspections returns 200."""
    client = _make_app_client()
    insp = _make_inspection()
    with (
        patch(f"{_MODULE_SVC}.get_user_account", new_callable=AsyncMock) as mock_acct,
        patch(f"{_MODULE_SVC}.list_vehicle_inspections", new_callable=AsyncMock) as mock_svc,
    ):
        mock_acct.return_value = MagicMock(id=ACCOUNT_ID)
        mock_svc.return_value = [insp]
        resp = client.get(_INSP_BASE)
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_api_create_inspection_201():
    """POST /corporate/vehicle-inspections returns 201."""
    client = _make_app_client()
    insp = _make_inspection()
    with (
        patch(f"{_MODULE_SVC}.get_user_account", new_callable=AsyncMock) as mock_acct,
        patch(f"{_MODULE_SVC}.create_inspection", new_callable=AsyncMock) as mock_svc,
    ):
        mock_acct.return_value = MagicMock(id=ACCOUNT_ID)
        mock_svc.return_value = insp
        resp = client.post(
            _INSP_BASE,
            json={
                "fleet_vehicle_id": str(VEHICLE_UUID),
                "inspection_type": "pre_trip",
            },
        )
    assert resp.status_code == 201


def test_api_get_inspection_200():
    """GET /corporate/vehicle-inspections/{id} returns 200."""
    client = _make_app_client()
    insp = _make_inspection()
    with (
        patch(f"{_MODULE_SVC}.get_user_account", new_callable=AsyncMock) as mock_acct,
        patch(f"{_MODULE_SVC}.get_inspection", new_callable=AsyncMock) as mock_svc,
    ):
        mock_acct.return_value = MagicMock(id=ACCOUNT_ID)
        mock_svc.return_value = insp
        resp = client.get(f"{_INSP_BASE}/{INSPECTION_UUID}")
    assert resp.status_code == 200


def test_api_submit_inspection_200():
    """POST /corporate/vehicle-inspections/{id}/submit returns 200."""
    client = _make_app_client()
    insp = _make_inspection(inspection_status=InspectionStatus.passed)
    with (
        patch(f"{_MODULE_SVC}.get_user_account", new_callable=AsyncMock) as mock_acct,
        patch(f"{_MODULE_SVC}.submit_inspection", new_callable=AsyncMock) as mock_svc,
    ):
        mock_acct.return_value = MagicMock(id=ACCOUNT_ID)
        mock_svc.return_value = insp
        resp = client.post(
            f"{_INSP_BASE}/{INSPECTION_UUID}/submit",
            json={"items_checked": []},
        )
    assert resp.status_code == 200


def test_api_get_summary_200():
    """GET /corporate/vehicle-inspections/summary returns 200."""
    client = _make_app_client()
    raw = {
        "account_id": ACCOUNT_ID,
        "by_status": {"passed": 3, "failed": 1},
        "by_type": {"pre_trip": 4},
        "pass_rate_pct": 75.0,
        "vehicles_with_pending": 2,
        "recent_failures": [],
    }
    with (
        patch(f"{_MODULE_SVC}.get_user_account", new_callable=AsyncMock) as mock_acct,
        patch(f"{_MODULE_SVC}.get_account_inspection_summary", new_callable=AsyncMock) as mock_svc,
    ):
        mock_acct.return_value = MagicMock(id=ACCOUNT_ID)
        mock_svc.return_value = raw
        resp = client.get(f"{_INSP_BASE}/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["account_id"] == ACCOUNT_ID
    assert data["pass_rate_pct"] == 75.0


def test_api_platform_list_inspections_200():
    """GET /platform/corporate/vehicle-inspections returns 200."""
    client = _make_app_client()
    insp = _make_inspection()
    with patch(f"{_MODULE_SVC}.list_all_platform", new_callable=AsyncMock) as mock_svc:
        mock_svc.return_value = [insp]
        resp = client.get("/api/v1/platform/corporate/vehicle-inspections")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_api_platform_list_templates_200():
    """GET /platform/corporate/vehicle-inspections/templates returns 200."""
    client = _make_app_client()
    tmpl = _make_template()
    with patch(
        f"{_MODULE_SVC}.list_all_templates_platform", new_callable=AsyncMock
    ) as mock_svc:
        mock_svc.return_value = [tmpl]
        resp = client.get("/api/v1/platform/corporate/vehicle-inspections/templates")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
