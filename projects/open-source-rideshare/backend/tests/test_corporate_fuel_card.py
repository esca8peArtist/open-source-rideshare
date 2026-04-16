"""Tests for the Corporate Fuel Card Management feature.

Service tests (async, mocked DB):
  1.  issue_card — success
  2.  issue_card — 409 on duplicate nickname
  3.  get_card — 404 when not in account
  4.  list_cards — returns all account cards
  5.  list_cards — is_active filter works
  6.  list_cards — vehicle filter works
  7.  list_cards — driver filter works
  8.  update_card — success
  9.  update_card — 409 on nickname collision
  10. assign_to_vehicle — success
  11. assign_to_vehicle — 409 if already assigned to same vehicle
  12. assign_to_driver — success
  13. assign_to_driver — 409 if already assigned to same driver
  14. unassign — clears both vehicle and driver
  15. deactivate_card — success
  16. deactivate_card — 409 if already inactive
  17. reactivate_card — success
  18. reactivate_card — 409 if already active
  19. record_transaction — success
  20. record_transaction — 409 if card inactive
  21. list_card_transactions — returns transactions
  22. list_card_transactions — date filter works
  23. get_card_summary — returns correct structure with utilization
  24. get_card_summary — no utilization when no limit
  25. get_account_fuel_summary — returns correct structure
  26. list_all_platform — returns all cards
  27. list_all_platform — account filter works
  28. list_all_platform — is_active filter works

Schema tests (sync):
  29. FuelCardCreateRequest — valid
  30. FuelCardCreateRequest — invalid card_last_four (non-digit)
  31. FuelCardCreateRequest — invalid card_last_four (wrong length)
  32. FuelTransactionCreateRequest — valid
  33. FuelTransactionCreateRequest — amount_usd must be > 0
  34. FuelCardResponse — from_attributes works
  35. FuelTransactionResponse — from_attributes works
  36. FuelCardSummaryResponse — valid

API layer tests (services patched):
  37. GET  list cards → 200
  38. GET  account summary → 200
  39. GET  card by id → 200
  40. GET  transactions → 200
  41. POST issue card → 201
  42. PUT  update card → 200
  43. POST assign-vehicle → 200
  44. POST assign-driver → 200
  45. POST unassign → 200
  46. POST deactivate → 200
  47. POST reactivate → 200
  48. POST record transaction → 201
  49. GET  card summary → 200
  50. GET  platform admin list → 200
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models.corporate_fuel_card import (
    CardNetwork,
    CorporateFuelCard,
    CorporateFuelCardTransaction,
    FuelType,
)
from app.schemas.corporate_fuel_card import (
    AccountFuelSummaryResponse,
    FuelCardCreateRequest,
    FuelCardListResponse,
    FuelCardResponse,
    FuelCardSummaryResponse,
    FuelTransactionCreateRequest,
    FuelTransactionResponse,
)
from app.services.corporate_fuel_card_service import (
    assign_to_driver,
    assign_to_vehicle,
    deactivate_card,
    get_account_fuel_summary,
    get_card,
    get_card_summary,
    issue_card,
    list_all_platform,
    list_card_transactions,
    list_cards,
    reactivate_card,
    record_transaction,
    unassign,
    update_card,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)
_TODAY = date(2026, 4, 16)
_VEHICLE_UUID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

ACCOUNT_ID = 1
CARD_ID = 10
MEMBER_ID = 5
ADMIN_ID = 3
DRIVER_ID = 7

_BASE = "/api/v1/corporate/accounts/me/fuel-cards"
_MODULE = "app.api.v1.corporate_fuel_card"


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_card(**kwargs) -> CorporateFuelCard:
    defaults = dict(
        id=CARD_ID,
        account_id=ACCOUNT_ID,
        card_last_four="1234",
        card_network=CardNetwork.WEX,
        nickname="Fleet Card 1",
        assigned_vehicle_id=None,
        assigned_driver_id=None,
        monthly_limit_usd=None,
        is_active=True,
        issued_by_id=MEMBER_ID,
        notes=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    defaults.update(kwargs)
    obj = MagicMock(spec=CorporateFuelCard)
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_txn(**kwargs) -> CorporateFuelCardTransaction:
    defaults = dict(
        id=1,
        fuel_card_id=CARD_ID,
        account_id=ACCOUNT_ID,
        transaction_date=_TODAY,
        merchant_name="Shell Station",
        fuel_type=FuelType.DIESEL,
        gallons=Decimal("10.500"),
        amount_usd=Decimal("45.00"),
        odometer_miles=50000,
        notes=None,
        recorded_by_id=MEMBER_ID,
        created_at=_NOW,
    )
    defaults.update(kwargs)
    obj = MagicMock(spec=CorporateFuelCardTransaction)
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _mock_db_single(value) -> AsyncMock:
    """Return a db mock where execute → scalar_one_or_none → value."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    db.execute.return_value = result
    return db


def _mock_db_scalars(values: list) -> AsyncMock:
    """Return a db mock where execute → scalars().all() → values."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    db.execute.return_value = result
    return db


def _make_app_client() -> TestClient:
    """Return a TestClient with auth dependencies overridden."""
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
async def test_issue_card_success():
    """issue_card creates a new fuel card."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    await issue_card(
        db,
        account_id=ACCOUNT_ID,
        card_last_four="1234",
        card_network=CardNetwork.WEX,
        nickname="Fleet Card 1",
        issued_by_id=MEMBER_ID,
    )

    db.add.assert_called_once()
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_issue_card_duplicate_nickname_409():
    """issue_card raises 409 when nickname already exists."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = CARD_ID  # collision
    db.execute.return_value = result

    with pytest.raises(HTTPException) as exc_info:
        await issue_card(
            db,
            account_id=ACCOUNT_ID,
            card_last_four="5678",
            card_network=CardNetwork.VISA,
            nickname="Fleet Card 1",
            issued_by_id=MEMBER_ID,
        )
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_get_card_404():
    """get_card raises 404 when card not found."""
    db = _mock_db_single(None)

    with pytest.raises(HTTPException) as exc_info:
        await get_card(db, account_id=ACCOUNT_ID, card_id=999)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_cards_returns_all():
    """list_cards returns all cards for the account."""
    cards = [_make_card(), _make_card(id=11, nickname="Fleet Card 2")]
    db = _mock_db_scalars(cards)

    result = await list_cards(db, account_id=ACCOUNT_ID)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_cards_is_active_filter():
    """list_cards filters by is_active without error."""
    db = _mock_db_scalars([])
    await list_cards(db, account_id=ACCOUNT_ID, is_active=True)
    db.execute.assert_awaited()


@pytest.mark.asyncio
async def test_list_cards_vehicle_filter():
    """list_cards filters by assigned_vehicle_id without error."""
    db = _mock_db_scalars([])
    await list_cards(db, account_id=ACCOUNT_ID, assigned_vehicle_id=_VEHICLE_UUID)
    db.execute.assert_awaited()


@pytest.mark.asyncio
async def test_list_cards_driver_filter():
    """list_cards filters by assigned_driver_id without error."""
    db = _mock_db_scalars([])
    await list_cards(db, account_id=ACCOUNT_ID, assigned_driver_id=DRIVER_ID)
    db.execute.assert_awaited()


@pytest.mark.asyncio
async def test_update_card_success():
    """update_card updates the nickname field."""
    card = _make_card()
    db = AsyncMock()
    result = MagicMock()
    # First call: _get_card_or_404 → card
    # Second call: _nickname_exists → None (no collision)
    result.scalar_one_or_none.side_effect = [card, None]
    db.execute.return_value = result

    updated = await update_card(
        db, account_id=ACCOUNT_ID, card_id=CARD_ID, nickname="Updated Name"
    )
    assert updated.nickname == "Updated Name"
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_card_409_nickname_collision():
    """update_card raises 409 when new nickname already taken."""
    card = _make_card()
    db = AsyncMock()
    result = MagicMock()
    # _get_card_or_404 → card, _nickname_exists → collision id
    result.scalar_one_or_none.side_effect = [card, 99]
    db.execute.return_value = result

    with pytest.raises(HTTPException) as exc_info:
        await update_card(
            db, account_id=ACCOUNT_ID, card_id=CARD_ID, nickname="Other Card"
        )
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_assign_to_vehicle_success():
    """assign_to_vehicle sets assigned_vehicle_id."""
    card = _make_card(assigned_vehicle_id=None)
    db = _mock_db_single(card)

    result = await assign_to_vehicle(
        db, account_id=ACCOUNT_ID, card_id=CARD_ID, vehicle_id=_VEHICLE_UUID
    )
    assert result.assigned_vehicle_id == _VEHICLE_UUID
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_assign_to_vehicle_409_same_vehicle():
    """assign_to_vehicle raises 409 if already assigned to same vehicle."""
    card = _make_card(assigned_vehicle_id=_VEHICLE_UUID)
    db = _mock_db_single(card)

    with pytest.raises(HTTPException) as exc_info:
        await assign_to_vehicle(
            db, account_id=ACCOUNT_ID, card_id=CARD_ID, vehicle_id=_VEHICLE_UUID
        )
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_assign_to_driver_success():
    """assign_to_driver sets assigned_driver_id."""
    card = _make_card(assigned_driver_id=None)
    db = _mock_db_single(card)

    result = await assign_to_driver(
        db, account_id=ACCOUNT_ID, card_id=CARD_ID, driver_id=DRIVER_ID
    )
    assert result.assigned_driver_id == DRIVER_ID
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_assign_to_driver_409_same_driver():
    """assign_to_driver raises 409 if already assigned to same driver."""
    card = _make_card(assigned_driver_id=DRIVER_ID)
    db = _mock_db_single(card)

    with pytest.raises(HTTPException) as exc_info:
        await assign_to_driver(
            db, account_id=ACCOUNT_ID, card_id=CARD_ID, driver_id=DRIVER_ID
        )
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_unassign_clears_both():
    """unassign clears both vehicle and driver assignment."""
    card = _make_card(
        assigned_vehicle_id=_VEHICLE_UUID,
        assigned_driver_id=DRIVER_ID,
    )
    db = _mock_db_single(card)

    result = await unassign(
        db, account_id=ACCOUNT_ID, card_id=CARD_ID,
        unassign_vehicle=True, unassign_driver=True,
    )
    assert result.assigned_vehicle_id is None
    assert result.assigned_driver_id is None


@pytest.mark.asyncio
async def test_deactivate_card_success():
    """deactivate_card sets is_active=False."""
    card = _make_card(is_active=True)
    db = _mock_db_single(card)

    result = await deactivate_card(db, account_id=ACCOUNT_ID, card_id=CARD_ID)
    assert result.is_active is False
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_deactivate_card_409_already_inactive():
    """deactivate_card raises 409 if already inactive."""
    card = _make_card(is_active=False)
    db = _mock_db_single(card)

    with pytest.raises(HTTPException) as exc_info:
        await deactivate_card(db, account_id=ACCOUNT_ID, card_id=CARD_ID)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_reactivate_card_success():
    """reactivate_card sets is_active=True."""
    card = _make_card(is_active=False)
    db = _mock_db_single(card)

    result = await reactivate_card(db, account_id=ACCOUNT_ID, card_id=CARD_ID)
    assert result.is_active is True
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_reactivate_card_409_already_active():
    """reactivate_card raises 409 if already active."""
    card = _make_card(is_active=True)
    db = _mock_db_single(card)

    with pytest.raises(HTTPException) as exc_info:
        await reactivate_card(db, account_id=ACCOUNT_ID, card_id=CARD_ID)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_record_transaction_success():
    """record_transaction creates a transaction."""
    card = _make_card(is_active=True)
    db = _mock_db_single(card)

    await record_transaction(
        db,
        account_id=ACCOUNT_ID,
        card_id=CARD_ID,
        recorded_by_id=MEMBER_ID,
        transaction_date=_TODAY,
        merchant_name="Shell",
        fuel_type=FuelType.DIESEL,
        amount_usd=Decimal("50.00"),
        gallons=Decimal("12.5"),
    )
    db.add.assert_called_once()
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_transaction_409_inactive_card():
    """record_transaction raises 409 when card is inactive."""
    card = _make_card(is_active=False)
    db = _mock_db_single(card)

    with pytest.raises(HTTPException) as exc_info:
        await record_transaction(
            db,
            account_id=ACCOUNT_ID,
            card_id=CARD_ID,
            recorded_by_id=MEMBER_ID,
            transaction_date=_TODAY,
            merchant_name="Shell",
            fuel_type=FuelType.DIESEL,
            amount_usd=Decimal("50.00"),
        )
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_list_card_transactions_returns_transactions():
    """list_card_transactions returns transaction list."""
    card = _make_card()
    txns = [_make_txn(), _make_txn(id=2)]

    db = AsyncMock()
    card_result = MagicMock()
    card_result.scalar_one_or_none.return_value = card
    txn_result = MagicMock()
    txn_result.scalars.return_value.all.return_value = txns
    db.execute.side_effect = [card_result, txn_result]

    result = await list_card_transactions(db, account_id=ACCOUNT_ID, card_id=CARD_ID)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_card_transactions_date_filter():
    """list_card_transactions applies date filter without error."""
    card = _make_card()
    db = AsyncMock()
    card_result = MagicMock()
    card_result.scalar_one_or_none.return_value = card
    txn_result = MagicMock()
    txn_result.scalars.return_value.all.return_value = []
    db.execute.side_effect = [card_result, txn_result]

    await list_card_transactions(
        db,
        account_id=ACCOUNT_ID,
        card_id=CARD_ID,
        from_date=date(2026, 1, 1),
        to_date=date(2026, 4, 30),
    )
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_get_card_summary_with_limit():
    """get_card_summary returns correct structure including utilization."""
    card = _make_card(monthly_limit_usd=Decimal("200.00"))
    db = AsyncMock()

    card_result = MagicMock()
    card_result.scalar_one_or_none.return_value = card

    by_fuel_result = MagicMock()
    by_fuel_result.__iter__ = MagicMock(
        return_value=iter(
            [(FuelType.DIESEL, 3, Decimal("30.000"), Decimal("120.00"))]
        )
    )

    month_result = MagicMock()
    month_result.scalar_one.return_value = Decimal("120.00")

    db.execute.side_effect = [card_result, by_fuel_result, month_result]

    result = await get_card_summary(db, account_id=ACCOUNT_ID, card_id=CARD_ID)
    assert result["total_transactions"] == 3
    assert result["total_amount_usd"] == Decimal("120.00")
    assert result["current_month_amount_usd"] == Decimal("120.00")
    assert result["monthly_limit_utilization_pct"] == Decimal("60.00")


@pytest.mark.asyncio
async def test_get_card_summary_no_limit():
    """get_card_summary returns None utilization when no monthly limit."""
    card = _make_card(monthly_limit_usd=None)
    db = AsyncMock()

    card_result = MagicMock()
    card_result.scalar_one_or_none.return_value = card

    by_fuel_result = MagicMock()
    by_fuel_result.__iter__ = MagicMock(return_value=iter([]))

    month_result = MagicMock()
    month_result.scalar_one.return_value = Decimal("0")

    db.execute.side_effect = [card_result, by_fuel_result, month_result]

    result = await get_card_summary(db, account_id=ACCOUNT_ID, card_id=CARD_ID)
    assert result["monthly_limit_utilization_pct"] is None


@pytest.mark.asyncio
async def test_get_account_fuel_summary_structure():
    """get_account_fuel_summary returns expected keys."""
    db = AsyncMock()

    total_result = MagicMock()
    total_result.scalar_one.return_value = 5

    active_result = MagicMock()
    active_result.scalar_one.return_value = 4

    by_fuel_result = MagicMock()
    by_fuel_result.__iter__ = MagicMock(
        return_value=iter(
            [(FuelType.DIESEL, 10, Decimal("100.000"), Decimal("400.00"))]
        )
    )

    month_result = MagicMock()
    month_result.scalar_one.return_value = Decimal("100.00")

    db.execute.side_effect = [total_result, active_result, by_fuel_result, month_result]

    result = await get_account_fuel_summary(db, account_id=ACCOUNT_ID)
    assert result["total_cards"] == 5
    assert result["active_cards"] == 4
    assert result["total_transactions"] == 10
    assert result["total_amount_usd"] == Decimal("400.00")
    assert len(result["by_fuel_type"]) == 1


@pytest.mark.asyncio
async def test_list_all_platform_returns_cards():
    """list_all_platform returns cards across accounts."""
    cards = [_make_card(), _make_card(id=11, account_id=2)]
    db = _mock_db_scalars(cards)

    result = await list_all_platform(db)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_all_platform_account_filter():
    """list_all_platform filters by account_id without error."""
    db = _mock_db_scalars([])
    await list_all_platform(db, account_id=ACCOUNT_ID)
    db.execute.assert_awaited()


@pytest.mark.asyncio
async def test_list_all_platform_is_active_filter():
    """list_all_platform filters by is_active without error."""
    db = _mock_db_scalars([])
    await list_all_platform(db, is_active=True)
    db.execute.assert_awaited()


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_fuel_card_create_request_valid():
    req = FuelCardCreateRequest(
        card_last_four="1234",
        card_network=CardNetwork.WEX,
        nickname="Van 2 Card",
        monthly_limit_usd=Decimal("300.00"),
    )
    assert req.card_last_four == "1234"
    assert req.card_network == CardNetwork.WEX


def test_fuel_card_create_request_invalid_last_four_non_digit():
    with pytest.raises(ValidationError):
        FuelCardCreateRequest(
            card_last_four="12AB",
            nickname="Test Card",
        )


def test_fuel_card_create_request_invalid_last_four_length():
    with pytest.raises(ValidationError):
        FuelCardCreateRequest(
            card_last_four="123",
            nickname="Test Card",
        )


def test_fuel_transaction_create_request_valid():
    req = FuelTransactionCreateRequest(
        transaction_date=_TODAY,
        merchant_name="Shell",
        fuel_type=FuelType.DIESEL,
        gallons=Decimal("12.500"),
        amount_usd=Decimal("55.00"),
        odometer_miles=50000,
    )
    assert req.amount_usd == Decimal("55.00")


def test_fuel_transaction_create_request_zero_amount_rejected():
    with pytest.raises(ValidationError):
        FuelTransactionCreateRequest(
            transaction_date=_TODAY,
            merchant_name="Shell",
            fuel_type=FuelType.DIESEL,
            amount_usd=Decimal("0.00"),
        )


def test_fuel_card_response_from_attributes():
    card = _make_card()
    resp = FuelCardResponse.model_validate(card)
    assert resp.id == CARD_ID
    assert resp.account_id == ACCOUNT_ID
    assert resp.card_last_four == "1234"
    assert resp.card_network == CardNetwork.WEX


def test_fuel_transaction_response_from_attributes():
    txn = _make_txn()
    resp = FuelTransactionResponse.model_validate(txn)
    assert resp.id == 1
    assert resp.fuel_card_id == CARD_ID
    assert resp.amount_usd == Decimal("45.00")


def test_fuel_card_summary_response_valid():
    summary = FuelCardSummaryResponse(
        card_id=CARD_ID,
        nickname="Fleet Card 1",
        is_active=True,
        monthly_limit_usd=Decimal("200.00"),
        total_transactions=5,
        total_amount_usd=Decimal("250.00"),
        current_month_amount_usd=Decimal("100.00"),
        monthly_limit_utilization_pct=Decimal("50.00"),
        by_fuel_type=[],
    )
    assert summary.total_transactions == 5


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------

_DUMMY_CARD = _make_card()
_DUMMY_TXN = _make_txn()


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=ACCOUNT_ID)
@patch(f"{_MODULE}.list_cards", new_callable=AsyncMock)
def test_api_list_cards(mock_list, mock_resolve):
    mock_list.return_value = [_DUMMY_CARD]
    client = _make_app_client()
    r = client.get(_BASE)
    assert r.status_code == 200
    assert r.json()["total"] == 1


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=ACCOUNT_ID)
@patch(f"{_MODULE}.get_account_fuel_summary", new_callable=AsyncMock)
def test_api_account_summary(mock_summary, mock_resolve):
    mock_summary.return_value = {
        "account_id": ACCOUNT_ID,
        "total_cards": 3,
        "active_cards": 2,
        "total_transactions": 10,
        "total_amount_usd": Decimal("400.00"),
        "current_month_amount_usd": Decimal("100.00"),
        "by_fuel_type": [],
    }
    client = _make_app_client()
    r = client.get(f"{_BASE}/summary")
    assert r.status_code == 200


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=ACCOUNT_ID)
@patch(f"{_MODULE}.get_card", new_callable=AsyncMock)
def test_api_get_card(mock_get, mock_resolve):
    mock_get.return_value = _DUMMY_CARD
    client = _make_app_client()
    r = client.get(f"{_BASE}/{CARD_ID}")
    assert r.status_code == 200


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=ACCOUNT_ID)
@patch(f"{_MODULE}.list_card_transactions", new_callable=AsyncMock)
def test_api_list_transactions(mock_list, mock_resolve):
    mock_list.return_value = [_DUMMY_TXN]
    client = _make_app_client()
    r = client.get(f"{_BASE}/{CARD_ID}/transactions")
    assert r.status_code == 200
    assert r.json()["total"] == 1


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=ACCOUNT_ID)
@patch(f"{_MODULE}.issue_card", new_callable=AsyncMock)
def test_api_issue_card(mock_issue, mock_resolve):
    mock_issue.return_value = _DUMMY_CARD
    payload = {
        "card_last_four": "1234",
        "card_network": "wex",
        "nickname": "Fleet Card 1",
    }
    client = _make_app_client()
    r = client.post(_BASE, json=payload)
    assert r.status_code == 201


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=ACCOUNT_ID)
@patch(f"{_MODULE}.update_card", new_callable=AsyncMock)
def test_api_update_card(mock_update, mock_resolve):
    mock_update.return_value = _make_card(nickname="Updated")
    client = _make_app_client()
    r = client.put(f"{_BASE}/{CARD_ID}", json={"nickname": "Updated"})
    assert r.status_code == 200


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=ACCOUNT_ID)
@patch(f"{_MODULE}.assign_to_vehicle", new_callable=AsyncMock)
def test_api_assign_vehicle(mock_assign, mock_resolve):
    mock_assign.return_value = _make_card(assigned_vehicle_id=_VEHICLE_UUID)
    client = _make_app_client()
    r = client.post(
        f"{_BASE}/{CARD_ID}/assign-vehicle",
        json={"vehicle_id": str(_VEHICLE_UUID)},
    )
    assert r.status_code == 200


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=ACCOUNT_ID)
@patch(f"{_MODULE}.assign_to_driver", new_callable=AsyncMock)
def test_api_assign_driver(mock_assign, mock_resolve):
    mock_assign.return_value = _make_card(assigned_driver_id=DRIVER_ID)
    client = _make_app_client()
    r = client.post(
        f"{_BASE}/{CARD_ID}/assign-driver",
        json={"driver_id": DRIVER_ID},
    )
    assert r.status_code == 200


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=ACCOUNT_ID)
@patch(f"{_MODULE}.unassign", new_callable=AsyncMock)
def test_api_unassign(mock_unassign, mock_resolve):
    mock_unassign.return_value = _make_card(
        assigned_vehicle_id=None, assigned_driver_id=None
    )
    client = _make_app_client()
    r = client.post(f"{_BASE}/{CARD_ID}/unassign")
    assert r.status_code == 200


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=ACCOUNT_ID)
@patch(f"{_MODULE}.deactivate_card", new_callable=AsyncMock)
def test_api_deactivate(mock_deactivate, mock_resolve):
    mock_deactivate.return_value = _make_card(is_active=False)
    client = _make_app_client()
    r = client.post(f"{_BASE}/{CARD_ID}/deactivate")
    assert r.status_code == 200


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=ACCOUNT_ID)
@patch(f"{_MODULE}.reactivate_card", new_callable=AsyncMock)
def test_api_reactivate(mock_reactivate, mock_resolve):
    mock_reactivate.return_value = _make_card(is_active=True)
    client = _make_app_client()
    r = client.post(f"{_BASE}/{CARD_ID}/reactivate")
    assert r.status_code == 200


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=ACCOUNT_ID)
@patch(f"{_MODULE}.record_transaction", new_callable=AsyncMock)
def test_api_record_transaction(mock_record, mock_resolve):
    mock_record.return_value = _DUMMY_TXN
    payload = {
        "transaction_date": _TODAY.isoformat(),
        "merchant_name": "Shell",
        "fuel_type": "diesel",
        "amount_usd": "55.00",
    }
    client = _make_app_client()
    r = client.post(f"{_BASE}/{CARD_ID}/transactions", json=payload)
    assert r.status_code == 201


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=ACCOUNT_ID)
@patch(f"{_MODULE}.get_card_summary", new_callable=AsyncMock)
def test_api_card_summary(mock_summary, mock_resolve):
    mock_summary.return_value = {
        "card_id": CARD_ID,
        "nickname": "Fleet Card 1",
        "is_active": True,
        "monthly_limit_usd": None,
        "total_transactions": 5,
        "total_amount_usd": Decimal("250.00"),
        "current_month_amount_usd": Decimal("50.00"),
        "monthly_limit_utilization_pct": None,
        "by_fuel_type": [],
    }
    client = _make_app_client()
    r = client.get(f"{_BASE}/{CARD_ID}/summary")
    assert r.status_code == 200


@patch(f"{_MODULE}.list_all_platform", new_callable=AsyncMock)
def test_api_platform_admin_list(mock_list):
    mock_list.return_value = [_DUMMY_CARD]
    client = _make_app_client()
    r = client.get(f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/fuel-cards")
    assert r.status_code == 200
    assert r.json()["total"] == 1
