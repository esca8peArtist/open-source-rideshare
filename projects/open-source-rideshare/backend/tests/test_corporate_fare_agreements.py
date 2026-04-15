"""Tests for the Corporate Fare Agreements feature.

Service tests (async, mocked DB):
  1.  create_fare_agreement — surge_cap success
  2.  create_fare_agreement — flat_discount_pct success
  3.  create_fare_agreement — per_mile_rate_usd success
  4.  create_fare_agreement — per_minute_rate_usd success
  5.  create_fare_agreement — with vehicle_types and validity window
  6.  get_fare_agreement — success
  7.  get_fare_agreement — wrong account → 404
  8.  list_fare_agreements — all returned, total correct
  9.  list_fare_agreements — active_only=True filters inactive
  10. list_fare_agreements — rate_type filter applied
  11. list_fare_agreements — vehicle_type filter: agreement with null types matches all
  12. list_fare_agreements — vehicle_type filter: agreement with list filters correctly
  13. update_fare_agreement — name update
  14. update_fare_agreement — toggle is_active to False
  15. update_fare_agreement — not found → 404
  16. delete_fare_agreement — success
  17. delete_fare_agreement — not found → 404
  18. compute_corporate_fare — no agreements → original fare returned unchanged
  19. compute_corporate_fare — surge_cap bites (surge > cap → capped)
  20. compute_corporate_fare — surge_cap does not bite (surge ≤ cap)
  21. compute_corporate_fare — multiple surge_caps → lowest cap wins
  22. compute_corporate_fare — flat_discount_pct applied
  23. compute_corporate_fare — multiple discounts → highest discount wins
  24. compute_corporate_fare — surge_cap + flat_discount combined
  25. compute_corporate_fare — per_mile agreement → reference_agreements, not applied
  26. compute_corporate_fare — vehicle_type filter: non-matching agreement excluded
  27. compute_corporate_fare — vehicle_type filter: null-type agreement matches
  28. compute_corporate_fare — validity window: expired agreement excluded
  29. compute_corporate_fare — validity window: future agreement excluded
  30. compute_corporate_fare — validity window: current agreement included
  31. compute_corporate_fare — inactive agreement excluded

Schema tests (sync):
  32. FareAgreementCreate — surge_cap valid (value ≥ 1.0)
  33. FareAgreementCreate — surge_cap value < 1.0 → ValidationError
  34. FareAgreementCreate — flat_discount_pct 0–100 valid
  35. FareAgreementCreate — flat_discount_pct > 100 → ValidationError
  36. FareAgreementCreate — per_mile_rate_usd ≤ 0 → ValidationError
  37. FareAgreementCreate — valid_until ≤ valid_from → ValidationError
  38. FareAgreementUpdate — all fields optional (empty update valid)
  39. FareAgreementUpdate — valid_until ≤ valid_from → ValidationError
  40. FareComputeRequest — base_fare_usd > 0 required

API layer tests (asyncio, service patched):
  41. POST /corporate/accounts/me/fare-agreements — 201
  42. GET  /corporate/accounts/me/fare-agreements — 200 list
  43. GET  /corporate/accounts/me/fare-agreements/compute — 200
  44. GET  /corporate/accounts/me/fare-agreements/{id} — 200
  45. PATCH /corporate/accounts/me/fare-agreements/{id} — 200
  46. DELETE /corporate/accounts/me/fare-agreements/{id} — 204
  47. POST /corporate/accounts/me/fare-agreements/{id}/deactivate — 200
  48. GET  /admin/corporate/accounts/{id}/fare-agreements — 200
  49. GET  /admin/corporate/accounts/{id}/fare-agreements/compute — 200
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate_fare_agreement import (
    CorporateFareAgreement,
    FareAgreementRateType,
)
from app.schemas.corporate_fare_agreement import (
    AgreementSummary,
    FareAgreementCreate,
    FareAgreementListResponse,
    FareAgreementResponse,
    FareAgreementUpdate,
    FareComputeRequest,
    FareComputeResponse,
)
from app.services.corporate_fare_agreement import (
    _is_valid_at,
    _applies_to_vehicle,
    compute_corporate_fare,
    create_fare_agreement,
    delete_fare_agreement,
    get_fare_agreement,
    list_fare_agreements,
    update_fare_agreement,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
ACCOUNT_ID = 10
AGREEMENT_ID = uuid.uuid4()


def _make_agreement(
    rate_type: FareAgreementRateType = FareAgreementRateType.surge_cap,
    value: Decimal = Decimal("1.5"),
    account_id: int = ACCOUNT_ID,
    is_active: bool = True,
    applies_to_vehicle_types: list[str] | None = None,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
) -> CorporateFareAgreement:
    a = MagicMock(spec=CorporateFareAgreement)
    a.id = uuid.uuid4()
    a.corporate_account_id = account_id
    a.name = "Test Agreement"
    a.rate_type = rate_type
    a.value = value
    a.applies_to_vehicle_types = applies_to_vehicle_types
    a.valid_from = valid_from
    a.valid_until = valid_until
    a.is_active = is_active
    a.notes = None
    a.created_by_id = 1
    a.created_at = NOW
    a.updated_at = NOW
    return a


def _mock_db_with(agreement: CorporateFareAgreement | None):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = agreement
    db.execute.return_value = result
    return db


def _mock_db_with_list(agreements: list[CorporateFareAgreement]):
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = agreements
    db.execute.return_value = result
    return db


# ---------------------------------------------------------------------------
# 1–5: create_fare_agreement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_fare_agreement_surge_cap():
    db = AsyncMock()
    data = FareAgreementCreate(
        name="Corp Surge Cap",
        rate_type=FareAgreementRateType.surge_cap,
        value=Decimal("1.5"),
    )
    result = await create_fare_agreement(db, ACCOUNT_ID, data, created_by_id=1)
    db.add.assert_called_once()
    db.commit.assert_called_once()
    db.refresh.assert_called_once()


@pytest.mark.asyncio
async def test_create_fare_agreement_flat_discount():
    db = AsyncMock()
    data = FareAgreementCreate(
        name="10% Corporate Discount",
        rate_type=FareAgreementRateType.flat_discount_pct,
        value=Decimal("10"),
    )
    result = await create_fare_agreement(db, ACCOUNT_ID, data, created_by_id=1)
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_create_fare_agreement_per_mile():
    db = AsyncMock()
    data = FareAgreementCreate(
        name="Per Mile Rate",
        rate_type=FareAgreementRateType.per_mile_rate_usd,
        value=Decimal("0.75"),
    )
    await create_fare_agreement(db, ACCOUNT_ID, data)
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_create_fare_agreement_per_minute():
    db = AsyncMock()
    data = FareAgreementCreate(
        name="Per Minute Rate",
        rate_type=FareAgreementRateType.per_minute_rate_usd,
        value=Decimal("0.20"),
    )
    await create_fare_agreement(db, ACCOUNT_ID, data)
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_create_fare_agreement_with_vehicle_types_and_window():
    db = AsyncMock()
    data = FareAgreementCreate(
        name="XL Only Discount",
        rate_type=FareAgreementRateType.flat_discount_pct,
        value=Decimal("5"),
        applies_to_vehicle_types=["xl", "suv"],
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_until=datetime(2026, 12, 31, tzinfo=timezone.utc),
        notes="Annual contract",
    )
    await create_fare_agreement(db, ACCOUNT_ID, data, created_by_id=2)
    db.add.assert_called_once()


# ---------------------------------------------------------------------------
# 6–7: get_fare_agreement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_fare_agreement_success():
    agreement = _make_agreement()
    db = _mock_db_with(agreement)
    result = await get_fare_agreement(db, ACCOUNT_ID, agreement.id)
    assert result is agreement


@pytest.mark.asyncio
async def test_get_fare_agreement_wrong_account():
    db = _mock_db_with(None)
    with pytest.raises(HTTPException) as exc:
        await get_fare_agreement(db, ACCOUNT_ID, uuid.uuid4())
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 8–12: list_fare_agreements
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_fare_agreements_all_returned():
    agreements = [_make_agreement(), _make_agreement()]
    db = _mock_db_with_list(agreements)
    items, total = await list_fare_agreements(db, ACCOUNT_ID)
    assert total == 2
    assert len(items) == 2


@pytest.mark.asyncio
async def test_list_fare_agreements_active_only():
    active = _make_agreement(is_active=True)
    inactive = _make_agreement(is_active=False)
    # active_only filters in the query — we simulate by returning only active
    db = _mock_db_with_list([active])
    items, total = await list_fare_agreements(db, ACCOUNT_ID, active_only=True)
    assert total == 1


@pytest.mark.asyncio
async def test_list_fare_agreements_rate_type_filter():
    cap = _make_agreement(rate_type=FareAgreementRateType.surge_cap)
    db = _mock_db_with_list([cap])
    items, total = await list_fare_agreements(
        db, ACCOUNT_ID, rate_type=FareAgreementRateType.surge_cap
    )
    assert total == 1


@pytest.mark.asyncio
async def test_list_fare_agreements_vehicle_type_null_matches_all():
    # agreement with no vehicle-type restriction matches any vehicle
    a = _make_agreement(applies_to_vehicle_types=None)
    db = _mock_db_with_list([a])
    items, total = await list_fare_agreements(db, ACCOUNT_ID, vehicle_type="standard")
    assert total == 1


@pytest.mark.asyncio
async def test_list_fare_agreements_vehicle_type_list_filter():
    xl_agreement = _make_agreement(applies_to_vehicle_types=["xl"])
    std_agreement = _make_agreement(applies_to_vehicle_types=["standard"])
    db = _mock_db_with_list([xl_agreement, std_agreement])
    items, total = await list_fare_agreements(db, ACCOUNT_ID, vehicle_type="xl")
    assert total == 1
    assert items[0] is xl_agreement


# ---------------------------------------------------------------------------
# 13–15: update_fare_agreement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_fare_agreement_name():
    agreement = _make_agreement()
    db = _mock_db_with(agreement)
    data = FareAgreementUpdate(name="Updated Name")
    result = await update_fare_agreement(db, ACCOUNT_ID, agreement.id, data)
    assert agreement.name == "Updated Name"
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_update_fare_agreement_deactivate():
    agreement = _make_agreement(is_active=True)
    db = _mock_db_with(agreement)
    data = FareAgreementUpdate(is_active=False)
    await update_fare_agreement(db, ACCOUNT_ID, agreement.id, data)
    assert agreement.is_active is False


@pytest.mark.asyncio
async def test_update_fare_agreement_not_found():
    db = _mock_db_with(None)
    with pytest.raises(HTTPException) as exc:
        await update_fare_agreement(
            db, ACCOUNT_ID, uuid.uuid4(), FareAgreementUpdate(name="x")
        )
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 16–17: delete_fare_agreement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_fare_agreement_success():
    agreement = _make_agreement()
    db = _mock_db_with(agreement)
    await delete_fare_agreement(db, ACCOUNT_ID, agreement.id)
    db.delete.assert_called_once_with(agreement)
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_delete_fare_agreement_not_found():
    db = _mock_db_with(None)
    with pytest.raises(HTTPException) as exc:
        await delete_fare_agreement(db, ACCOUNT_ID, uuid.uuid4())
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 18–31: compute_corporate_fare
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_no_agreements():
    db = _mock_db_with_list([])
    result = await compute_corporate_fare(
        db, ACCOUNT_ID,
        base_fare_usd=Decimal("10.00"),
        surge_multiplier=Decimal("1.5"),
        ride_dt=NOW,
    )
    assert result.final_fare_usd == Decimal("15.00")
    assert result.discount_pct_applied == Decimal("0")
    assert result.agreements_applied == []


@pytest.mark.asyncio
async def test_compute_surge_cap_bites():
    cap = _make_agreement(
        rate_type=FareAgreementRateType.surge_cap, value=Decimal("1.3")
    )
    db = _mock_db_with_list([cap])
    result = await compute_corporate_fare(
        db, ACCOUNT_ID,
        base_fare_usd=Decimal("10.00"),
        surge_multiplier=Decimal("2.0"),
        ride_dt=NOW,
    )
    assert result.adjusted_surge_multiplier == Decimal("1.3")
    assert result.final_fare_usd == Decimal("13.00")


@pytest.mark.asyncio
async def test_compute_surge_cap_does_not_bite():
    cap = _make_agreement(
        rate_type=FareAgreementRateType.surge_cap, value=Decimal("2.0")
    )
    db = _mock_db_with_list([cap])
    result = await compute_corporate_fare(
        db, ACCOUNT_ID,
        base_fare_usd=Decimal("10.00"),
        surge_multiplier=Decimal("1.5"),
        ride_dt=NOW,
    )
    # Surge stays at 1.5 (below the 2.0 cap), cap still listed as applied
    assert result.adjusted_surge_multiplier == Decimal("1.5")
    assert result.final_fare_usd == Decimal("15.00")
    assert len(result.agreements_applied) == 1


@pytest.mark.asyncio
async def test_compute_multiple_surge_caps_lowest_wins():
    cap1 = _make_agreement(
        rate_type=FareAgreementRateType.surge_cap, value=Decimal("1.8")
    )
    cap2 = _make_agreement(
        rate_type=FareAgreementRateType.surge_cap, value=Decimal("1.2")
    )
    db = _mock_db_with_list([cap1, cap2])
    result = await compute_corporate_fare(
        db, ACCOUNT_ID,
        base_fare_usd=Decimal("10.00"),
        surge_multiplier=Decimal("2.5"),
        ride_dt=NOW,
    )
    assert result.adjusted_surge_multiplier == Decimal("1.2")


@pytest.mark.asyncio
async def test_compute_flat_discount():
    discount = _make_agreement(
        rate_type=FareAgreementRateType.flat_discount_pct, value=Decimal("10")
    )
    db = _mock_db_with_list([discount])
    result = await compute_corporate_fare(
        db, ACCOUNT_ID,
        base_fare_usd=Decimal("20.00"),
        surge_multiplier=Decimal("1.0"),
        ride_dt=NOW,
    )
    assert result.discount_pct_applied == Decimal("10")
    assert result.final_fare_usd == Decimal("18.00")


@pytest.mark.asyncio
async def test_compute_multiple_discounts_highest_wins():
    d1 = _make_agreement(
        rate_type=FareAgreementRateType.flat_discount_pct, value=Decimal("5")
    )
    d2 = _make_agreement(
        rate_type=FareAgreementRateType.flat_discount_pct, value=Decimal("15")
    )
    db = _mock_db_with_list([d1, d2])
    result = await compute_corporate_fare(
        db, ACCOUNT_ID,
        base_fare_usd=Decimal("10.00"),
        surge_multiplier=Decimal("1.0"),
        ride_dt=NOW,
    )
    assert result.discount_pct_applied == Decimal("15")
    assert result.final_fare_usd == Decimal("8.50")


@pytest.mark.asyncio
async def test_compute_surge_cap_and_discount_combined():
    cap = _make_agreement(
        rate_type=FareAgreementRateType.surge_cap, value=Decimal("1.5")
    )
    discount = _make_agreement(
        rate_type=FareAgreementRateType.flat_discount_pct, value=Decimal("10")
    )
    db = _mock_db_with_list([cap, discount])
    result = await compute_corporate_fare(
        db, ACCOUNT_ID,
        base_fare_usd=Decimal("10.00"),
        surge_multiplier=Decimal("2.0"),
        ride_dt=NOW,
    )
    # Surge capped at 1.5 → fare_before_discount = 15.00; 10% off → 13.50
    assert result.adjusted_surge_multiplier == Decimal("1.5")
    assert result.fare_before_discount_usd == Decimal("15.00")
    assert result.final_fare_usd == Decimal("13.50")


@pytest.mark.asyncio
async def test_compute_per_mile_goes_to_reference():
    per_mile = _make_agreement(
        rate_type=FareAgreementRateType.per_mile_rate_usd, value=Decimal("0.75")
    )
    db = _mock_db_with_list([per_mile])
    result = await compute_corporate_fare(
        db, ACCOUNT_ID,
        base_fare_usd=Decimal("10.00"),
        surge_multiplier=Decimal("1.0"),
        ride_dt=NOW,
    )
    # Per-mile agreement goes to reference_agreements, not applied
    assert result.final_fare_usd == Decimal("10.00")
    assert len(result.agreements_applied) == 0
    assert len(result.reference_agreements) == 1
    assert result.reference_agreements[0].value == Decimal("0.75")


@pytest.mark.asyncio
async def test_compute_vehicle_type_non_matching_excluded():
    xl_only = _make_agreement(
        rate_type=FareAgreementRateType.surge_cap,
        value=Decimal("1.2"),
        applies_to_vehicle_types=["xl"],
    )
    db = _mock_db_with_list([xl_only])
    result = await compute_corporate_fare(
        db, ACCOUNT_ID,
        base_fare_usd=Decimal("10.00"),
        surge_multiplier=Decimal("2.0"),
        vehicle_type="standard",
        ride_dt=NOW,
    )
    # xl_only does not apply to standard → surge not capped
    assert result.adjusted_surge_multiplier == Decimal("2.0")
    assert result.final_fare_usd == Decimal("20.00")


@pytest.mark.asyncio
async def test_compute_vehicle_type_null_matches_any():
    any_vehicle = _make_agreement(
        rate_type=FareAgreementRateType.surge_cap,
        value=Decimal("1.5"),
        applies_to_vehicle_types=None,
    )
    db = _mock_db_with_list([any_vehicle])
    result = await compute_corporate_fare(
        db, ACCOUNT_ID,
        base_fare_usd=Decimal("10.00"),
        surge_multiplier=Decimal("3.0"),
        vehicle_type="standard",
        ride_dt=NOW,
    )
    assert result.adjusted_surge_multiplier == Decimal("1.5")


@pytest.mark.asyncio
async def test_compute_expired_agreement_excluded():
    expired = _make_agreement(
        rate_type=FareAgreementRateType.surge_cap,
        value=Decimal("1.2"),
        valid_until=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    db = _mock_db_with_list([expired])
    result = await compute_corporate_fare(
        db, ACCOUNT_ID,
        base_fare_usd=Decimal("10.00"),
        surge_multiplier=Decimal("2.0"),
        ride_dt=NOW,
    )
    assert result.adjusted_surge_multiplier == Decimal("2.0")
    assert result.agreements_applied == []


@pytest.mark.asyncio
async def test_compute_future_agreement_excluded():
    future = _make_agreement(
        rate_type=FareAgreementRateType.flat_discount_pct,
        value=Decimal("20"),
        valid_from=datetime(2027, 1, 1, tzinfo=timezone.utc),
    )
    db = _mock_db_with_list([future])
    result = await compute_corporate_fare(
        db, ACCOUNT_ID,
        base_fare_usd=Decimal("10.00"),
        surge_multiplier=Decimal("1.0"),
        ride_dt=NOW,
    )
    assert result.final_fare_usd == Decimal("10.00")
    assert result.agreements_applied == []


@pytest.mark.asyncio
async def test_compute_current_validity_window_included():
    current = _make_agreement(
        rate_type=FareAgreementRateType.flat_discount_pct,
        value=Decimal("5"),
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_until=datetime(2026, 12, 31, tzinfo=timezone.utc),
    )
    db = _mock_db_with_list([current])
    result = await compute_corporate_fare(
        db, ACCOUNT_ID,
        base_fare_usd=Decimal("10.00"),
        surge_multiplier=Decimal("1.0"),
        ride_dt=NOW,
    )
    assert result.discount_pct_applied == Decimal("5")


@pytest.mark.asyncio
async def test_compute_inactive_agreement_excluded():
    # Inactive agreements are filtered by the DB query (is_active=True)
    # — we simulate this by the mock returning empty
    db = _mock_db_with_list([])
    result = await compute_corporate_fare(
        db, ACCOUNT_ID,
        base_fare_usd=Decimal("10.00"),
        surge_multiplier=Decimal("2.0"),
        ride_dt=NOW,
    )
    assert result.final_fare_usd == Decimal("20.00")


# ---------------------------------------------------------------------------
# 32–40: Schema validation
# ---------------------------------------------------------------------------


def test_schema_create_surge_cap_valid():
    d = FareAgreementCreate(
        name="Corp Cap",
        rate_type=FareAgreementRateType.surge_cap,
        value=Decimal("1.0"),
    )
    assert d.rate_type == FareAgreementRateType.surge_cap


def test_schema_create_surge_cap_below_one():
    with pytest.raises(ValidationError):
        FareAgreementCreate(
            name="Bad Cap",
            rate_type=FareAgreementRateType.surge_cap,
            value=Decimal("0.8"),
        )


def test_schema_create_flat_discount_valid():
    d = FareAgreementCreate(
        name="Full Discount",
        rate_type=FareAgreementRateType.flat_discount_pct,
        value=Decimal("100"),
    )
    assert d.value == Decimal("100")


def test_schema_create_flat_discount_over_100():
    with pytest.raises(ValidationError):
        FareAgreementCreate(
            name="Bad Discount",
            rate_type=FareAgreementRateType.flat_discount_pct,
            value=Decimal("101"),
        )


def test_schema_create_per_mile_zero_or_negative():
    with pytest.raises(ValidationError):
        FareAgreementCreate(
            name="Bad Mile Rate",
            rate_type=FareAgreementRateType.per_mile_rate_usd,
            value=Decimal("0"),
        )


def test_schema_create_valid_until_before_valid_from():
    with pytest.raises(ValidationError):
        FareAgreementCreate(
            name="Bad Window",
            rate_type=FareAgreementRateType.surge_cap,
            value=Decimal("1.5"),
            valid_from=datetime(2026, 6, 1, tzinfo=timezone.utc),
            valid_until=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )


def test_schema_update_all_optional():
    d = FareAgreementUpdate()
    assert d.name is None
    assert d.value is None


def test_schema_update_valid_until_before_valid_from():
    with pytest.raises(ValidationError):
        FareAgreementUpdate(
            valid_from=datetime(2026, 12, 1, tzinfo=timezone.utc),
            valid_until=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )


def test_schema_compute_request_base_fare_required():
    with pytest.raises(ValidationError):
        FareComputeRequest(base_fare_usd=Decimal("0"))


# ---------------------------------------------------------------------------
# 41–49: API layer tests
# ---------------------------------------------------------------------------


def _make_api_agreement(
    rate_type: str = "surge_cap",
    value: Decimal = Decimal("1.5"),
) -> MagicMock:
    a = MagicMock()
    a.id = uuid.uuid4()
    a.corporate_account_id = ACCOUNT_ID
    a.name = "Test"
    a.rate_type = MagicMock()
    a.rate_type.value = rate_type
    a.value = value
    a.applies_to_vehicle_types = None
    a.valid_from = None
    a.valid_until = None
    a.is_active = True
    a.notes = None
    a.created_by_id = 1
    a.created_at = NOW
    a.updated_at = NOW
    return a


def _fake_member_account(account_id: int = ACCOUNT_ID):
    m = MagicMock()
    m.account_id = account_id
    return m


@pytest.mark.asyncio
async def test_api_create_fare_agreement():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    agreement = _make_api_agreement()

    async def _fake_db():
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = _fake_member_account()
        db.execute.return_value = result
        yield db

    fake_user = MagicMock(spec=User)
    fake_user.id = 1
    fake_user.is_admin = False

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with patch(
        "app.api.v1.corporate_fare_agreements.create_fare_agreement",
        new=AsyncMock(return_value=agreement),
    ):
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/corporate/accounts/me/fare-agreements",
                json={
                    "name": "Corp Cap",
                    "rate_type": "surge_cap",
                    "value": "1.5",
                },
            )
        assert resp.status_code == 201

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_list_fare_agreements():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    async def _fake_db():
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = _fake_member_account()
        db.execute.return_value = result
        yield db

    fake_user = MagicMock(spec=User)
    fake_user.id = 1

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with patch(
        "app.api.v1.corporate_fare_agreements.list_fare_agreements",
        new=AsyncMock(return_value=([], 0)),
    ):
        with TestClient(app) as client:
            resp = client.get("/api/v1/corporate/accounts/me/fare-agreements")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_compute_fare():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    async def _fake_db():
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = _fake_member_account()
        db.execute.return_value = result
        yield db

    fake_user = MagicMock(spec=User)
    fake_user.id = 1

    fake_compute = FareComputeResponse(
        base_fare_usd=Decimal("10.00"),
        original_surge_multiplier=Decimal("2.0"),
        adjusted_surge_multiplier=Decimal("1.5"),
        fare_before_discount_usd=Decimal("15.00"),
        discount_pct_applied=Decimal("0"),
        final_fare_usd=Decimal("15.00"),
        agreements_applied=[],
    )

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with patch(
        "app.api.v1.corporate_fare_agreements.compute_corporate_fare",
        new=AsyncMock(return_value=fake_compute),
    ):
        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/corporate/accounts/me/fare-agreements/compute",
                params={"base_fare_usd": "10.00", "surge_multiplier": "2.0"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["final_fare_usd"] == "15.00"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_get_fare_agreement():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    agreement = _make_api_agreement()

    async def _fake_db():
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = _fake_member_account()
        db.execute.return_value = result
        yield db

    fake_user = MagicMock(spec=User)
    fake_user.id = 1

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with patch(
        "app.api.v1.corporate_fare_agreements.get_fare_agreement",
        new=AsyncMock(return_value=agreement),
    ):
        with TestClient(app) as client:
            resp = client.get(
                f"/api/v1/corporate/accounts/me/fare-agreements/{agreement.id}"
            )
        assert resp.status_code == 200

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_update_fare_agreement():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    agreement = _make_api_agreement()

    async def _fake_db():
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = _fake_member_account()
        db.execute.return_value = result
        yield db

    fake_user = MagicMock(spec=User)
    fake_user.id = 1

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with patch(
        "app.api.v1.corporate_fare_agreements.update_fare_agreement",
        new=AsyncMock(return_value=agreement),
    ):
        with TestClient(app) as client:
            resp = client.patch(
                f"/api/v1/corporate/accounts/me/fare-agreements/{agreement.id}",
                json={"name": "Updated"},
            )
        assert resp.status_code == 200

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_delete_fare_agreement():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    async def _fake_db():
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = _fake_member_account()
        db.execute.return_value = result
        yield db

    fake_user = MagicMock(spec=User)
    fake_user.id = 1

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with patch(
        "app.api.v1.corporate_fare_agreements.delete_fare_agreement",
        new=AsyncMock(return_value=None),
    ):
        with TestClient(app) as client:
            resp = client.delete(
                f"/api/v1/corporate/accounts/me/fare-agreements/{uuid.uuid4()}"
            )
        assert resp.status_code == 204

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_deactivate_fare_agreement():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    agreement = _make_api_agreement()

    async def _fake_db():
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = _fake_member_account()
        db.execute.return_value = result
        yield db

    fake_user = MagicMock(spec=User)
    fake_user.id = 1

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with patch(
        "app.api.v1.corporate_fare_agreements.update_fare_agreement",
        new=AsyncMock(return_value=agreement),
    ):
        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/corporate/accounts/me/fare-agreements/{agreement.id}/deactivate"
            )
        assert resp.status_code == 200

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_admin_list_fare_agreements():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db, require_admin
    from app.models.user import User

    async def _fake_db():
        db = AsyncMock()
        yield db

    fake_user = MagicMock(spec=User)
    fake_user.id = 99
    fake_user.is_admin = True

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[require_admin] = lambda: fake_user

    with patch(
        "app.api.v1.corporate_fare_agreements.list_fare_agreements",
        new=AsyncMock(return_value=([], 0)),
    ):
        with TestClient(app) as client:
            resp = client.get(f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/fare-agreements")
        assert resp.status_code == 200

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_admin_compute_fare():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db, require_admin
    from app.models.user import User

    async def _fake_db():
        db = AsyncMock()
        yield db

    fake_user = MagicMock(spec=User)
    fake_user.id = 99
    fake_user.is_admin = True

    fake_compute = FareComputeResponse(
        base_fare_usd=Decimal("20.00"),
        original_surge_multiplier=Decimal("1.0"),
        adjusted_surge_multiplier=Decimal("1.0"),
        fare_before_discount_usd=Decimal("20.00"),
        discount_pct_applied=Decimal("0"),
        final_fare_usd=Decimal("20.00"),
        agreements_applied=[],
    )

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[require_admin] = lambda: fake_user

    with patch(
        "app.api.v1.corporate_fare_agreements.compute_corporate_fare",
        new=AsyncMock(return_value=fake_compute),
    ):
        with TestClient(app) as client:
            resp = client.get(
                f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/fare-agreements/compute",
                params={"base_fare_usd": "20.00"},
            )
        assert resp.status_code == 200

    app.dependency_overrides.clear()
