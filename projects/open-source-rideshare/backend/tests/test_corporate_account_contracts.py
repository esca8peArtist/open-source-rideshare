"""Tests for the Corporate Account Contract Management feature.

Service layer (async, mocked DB):
  1.  create_contract — success, auto-generates contract number when omitted
  2.  create_contract — uses supplied contract_number when provided
  3.  create_contract — 409 when active contract already exists
  4.  get_contract — success returns ContractResponse
  5.  get_contract — 404 when not found
  6.  get_active_contract — returns response when active contract exists
  7.  get_active_contract — returns None when no active contract
  8.  list_contracts — returns all contracts for account
  9.  list_contracts — filtered by status
  10. update_contract — success updates fields
  11. update_contract — 404 when not found
  12. update_contract — 409 when status is terminated
  13. update_contract — 409 when status is expired
  14. activate_contract — success moves draft to active
  15. activate_contract — deactivates prior active contract
  16. activate_contract — 404 when not found
  17. activate_contract — 409 when not in draft status
  18. terminate_contract — success moves active to terminated
  19. terminate_contract — 404 when not found
  20. terminate_contract — 409 when not in active status
  21. list_expiring_contracts — returns contracts within window
  22. list_expiring_contracts — empty when none expiring

Schema validation:
  23. ContractCreate — valid construction
  24. ContractCreate — end_date must be after start_date
  25. ContractUpdate — all fields optional
  26. TerminateRequest — reason cannot be empty
  27. ContractResponse — from_attributes model config

API layer (service functions patched):
  28. GET /corporate/accounts/me/contract — 200 found
  29. GET /corporate/accounts/me/contract — 404 not a member
  30. GET /corporate/accounts/me/contract — 404 no active contract
  31. GET /admin/corporate/accounts/{id}/contracts — 200 success
  32. POST /admin/corporate/accounts/{id}/contracts — 201 created
  33. GET /admin/corporate/contracts/expiring — 200 success
  34. GET /admin/corporate/contracts/{id} — 200 success
  35. GET /admin/corporate/contracts/{id} — 404
  36. PATCH /admin/corporate/contracts/{id} — 200 success
  37. POST /admin/corporate/contracts/{id}/activate — 200 success
  38. POST /admin/corporate/contracts/{id}/terminate — 200 success
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate_account_contract import ContractStatus, CorporateAccountContract
from app.schemas.corporate_account_contract import (
    ContractCreate,
    ContractListResponse,
    ContractResponse,
    ContractUpdate,
    TerminateRequest,
)
from app.services.corporate_account_contract import (
    activate_contract,
    create_contract,
    get_active_contract,
    get_contract,
    list_contracts,
    list_expiring_contracts,
    terminate_contract,
    update_contract,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 10
CONTRACT_ID = 1
ADMIN_ID = 99
USER_ID = 7

START_DATE = date(2025, 1, 1)
END_DATE = date(2025, 12, 31)

_ROUTER = "app.api.v1.corporate_account_contracts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_contract(
    contract_id: int = CONTRACT_ID,
    account_id: int = ACCOUNT_ID,
    status: ContractStatus = ContractStatus.draft,
    contract_number: str = "CONTRACT-0010-202501-1",
    end_date: date | None = END_DATE,
) -> CorporateAccountContract:
    """Build a minimal CorporateAccountContract model instance."""
    c = CorporateAccountContract()
    c.id = contract_id
    c.account_id = account_id
    c.contract_number = contract_number
    c.status = status
    c.contract_start_date = START_DATE
    c.contract_end_date = end_date
    c.auto_renews = False
    c.renewal_term_days = None
    c.renewal_notice_days = 30
    c.committed_monthly_rides = None
    c.committed_monthly_spend_usd = None
    c.negotiated_discount_pct = None
    c.account_manager_name = None
    c.account_manager_email = None
    c.contract_document_url = None
    c.notes = None
    c.signed_by_name = None
    c.signed_at = None
    c.activated_at = None
    c.terminated_at = None
    c.termination_reason = None
    c.created_by_id = ADMIN_ID
    c.updated_by_id = ADMIN_ID
    c.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    c.updated_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return c


def _make_response(
    contract_id: int = CONTRACT_ID,
    account_id: int = ACCOUNT_ID,
    status: str = "draft",
    contract_number: str = "CONTRACT-0010-202501-1",
) -> ContractResponse:
    return ContractResponse(
        id=contract_id,
        account_id=account_id,
        contract_number=contract_number,
        status=status,
        contract_start_date=START_DATE,
        contract_end_date=END_DATE,
        auto_renews=False,
        renewal_term_days=None,
        renewal_notice_days=30,
        committed_monthly_rides=None,
        committed_monthly_spend_usd=None,
        negotiated_discount_pct=None,
        account_manager_name=None,
        account_manager_email=None,
        contract_document_url=None,
        notes=None,
        signed_by_name=None,
        signed_at=None,
        activated_at=None,
        terminated_at=None,
        termination_reason=None,
        created_by_id=ADMIN_ID,
        updated_by_id=ADMIN_ID,
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


def _make_list_response(count: int = 1) -> ContractListResponse:
    return ContractListResponse(
        contracts=[_make_response()],
        total=count,
    )


def _make_db_with_scalars(scalar_values: list) -> AsyncMock:
    """Return a mock AsyncSession whose scalar() calls return values in order."""
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=scalar_values)
    return db


def _mock_user(user_id: int = USER_ID) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    return u


def _make_execute_result(items: list) -> MagicMock:
    result = MagicMock()
    scalars = MagicMock()
    scalars.first.return_value = items[0] if items else None
    scalars.all.return_value = items
    result.scalars.return_value = scalars
    return result


# ---------------------------------------------------------------------------
# 1. create_contract — success, auto-generates contract_number
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_contract_success_auto_number():
    db = AsyncMock()
    # scalar calls: active count=0, then auto-number count=0
    db.scalar = AsyncMock(side_effect=[0, 0])
    db.commit = AsyncMock()

    added = []

    def _side_effect_add(x):
        added.append(x)

    db.add = _side_effect_add

    async def _fake_refresh(obj):
        # Simulate DB populating server-generated fields after flush.
        obj.id = CONTRACT_ID
        obj.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        obj.updated_at = datetime(2025, 1, 1, tzinfo=timezone.utc)

    db.refresh = _fake_refresh

    data = ContractCreate(contract_start_date=START_DATE, contract_end_date=END_DATE)

    result = await create_contract(db, ACCOUNT_ID, data, ADMIN_ID)

    assert len(added) == 1
    contract_obj = added[0]
    assert contract_obj.account_id == ACCOUNT_ID
    assert contract_obj.contract_number.startswith("CONTRACT-0010-")
    assert contract_obj.status == ContractStatus.draft
    assert result.id == CONTRACT_ID


# ---------------------------------------------------------------------------
# 2. create_contract — uses supplied contract_number
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_contract_with_supplied_number():
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=0)
    db.commit = AsyncMock()

    added = []
    db.add = lambda x: added.append(x)

    async def _fake_refresh(obj):
        obj.id = CONTRACT_ID
        obj.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        obj.updated_at = datetime(2025, 1, 1, tzinfo=timezone.utc)

    db.refresh = _fake_refresh

    data = ContractCreate(
        contract_number="CUSTOM-001",
        contract_start_date=START_DATE,
        contract_end_date=END_DATE,
    )

    await create_contract(db, ACCOUNT_ID, data, ADMIN_ID)

    assert added[0].contract_number == "CUSTOM-001"


# ---------------------------------------------------------------------------
# 3. create_contract — 409 when active contract already exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_contract_409_active_exists():
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=1)  # one active already

    data = ContractCreate(contract_start_date=START_DATE, contract_end_date=END_DATE)

    with pytest.raises(HTTPException) as exc_info:
        await create_contract(db, ACCOUNT_ID, data, ADMIN_ID)

    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 4. get_contract — success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_contract_success():
    db = AsyncMock()
    contract = _make_contract()
    db.execute = AsyncMock(return_value=_make_execute_result([contract]))

    result = await get_contract(db, CONTRACT_ID)

    assert result.id == CONTRACT_ID
    assert result.account_id == ACCOUNT_ID


# ---------------------------------------------------------------------------
# 5. get_contract — 404 when not found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_contract_404():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_execute_result([]))

    with pytest.raises(HTTPException) as exc_info:
        await get_contract(db, 9999)

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 6. get_active_contract — returns response when found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_active_contract_found():
    db = AsyncMock()
    contract = _make_contract(status=ContractStatus.active)
    db.execute = AsyncMock(return_value=_make_execute_result([contract]))

    result = await get_active_contract(db, ACCOUNT_ID)

    assert result is not None
    assert result.status == "active"


# ---------------------------------------------------------------------------
# 7. get_active_contract — returns None when no active contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_active_contract_none():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_execute_result([]))

    result = await get_active_contract(db, ACCOUNT_ID)

    assert result is None


# ---------------------------------------------------------------------------
# 8. list_contracts — returns all contracts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_contracts_all():
    db = AsyncMock()
    contracts = [_make_contract(), _make_contract(contract_id=2, contract_number="C-2")]
    db.scalar = AsyncMock(return_value=2)
    db.execute = AsyncMock(return_value=_make_execute_result(contracts))

    result = await list_contracts(db, ACCOUNT_ID)

    assert result.total == 2
    assert len(result.contracts) == 2


# ---------------------------------------------------------------------------
# 9. list_contracts — filtered by status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_contracts_filtered_by_status():
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=1)
    active_contract = _make_contract(status=ContractStatus.active)
    db.execute = AsyncMock(return_value=_make_execute_result([active_contract]))

    result = await list_contracts(db, ACCOUNT_ID, status_filter=ContractStatus.active)

    assert result.total == 1
    assert result.contracts[0].status == "active"


# ---------------------------------------------------------------------------
# 10. update_contract — success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_contract_success():
    db = AsyncMock()
    contract = _make_contract(status=ContractStatus.draft)
    db.execute = AsyncMock(return_value=_make_execute_result([contract]))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    data = ContractUpdate(notes="Updated note")
    result = await update_contract(db, CONTRACT_ID, data, ADMIN_ID)

    assert contract.notes == "Updated note"
    assert contract.updated_by_id == ADMIN_ID


# ---------------------------------------------------------------------------
# 11. update_contract — 404 when not found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_contract_404():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_execute_result([]))

    with pytest.raises(HTTPException) as exc_info:
        await update_contract(db, 9999, ContractUpdate(), ADMIN_ID)

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 12. update_contract — 409 when terminated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_contract_409_terminated():
    db = AsyncMock()
    contract = _make_contract(status=ContractStatus.terminated)
    db.execute = AsyncMock(return_value=_make_execute_result([contract]))

    with pytest.raises(HTTPException) as exc_info:
        await update_contract(db, CONTRACT_ID, ContractUpdate(), ADMIN_ID)

    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 13. update_contract — 409 when expired
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_contract_409_expired():
    db = AsyncMock()
    contract = _make_contract(status=ContractStatus.expired)
    db.execute = AsyncMock(return_value=_make_execute_result([contract]))

    with pytest.raises(HTTPException) as exc_info:
        await update_contract(db, CONTRACT_ID, ContractUpdate(), ADMIN_ID)

    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 14. activate_contract — success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activate_contract_success():
    db = AsyncMock()
    contract = _make_contract(status=ContractStatus.draft)

    # First execute: find the contract. Second execute: find prior active (none).
    no_prior = _make_execute_result([])
    db.execute = AsyncMock(side_effect=[_make_execute_result([contract]), no_prior])
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    result = await activate_contract(db, CONTRACT_ID, ADMIN_ID)

    assert contract.status == ContractStatus.active
    assert contract.activated_at is not None


# ---------------------------------------------------------------------------
# 15. activate_contract — deactivates prior active contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activate_contract_deactivates_prior_active():
    db = AsyncMock()
    contract = _make_contract(status=ContractStatus.draft)
    prior_active = _make_contract(contract_id=2, status=ContractStatus.active, contract_number="C-2")

    db.execute = AsyncMock(
        side_effect=[
            _make_execute_result([contract]),
            _make_execute_result([prior_active]),
        ]
    )
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    await activate_contract(db, CONTRACT_ID, ADMIN_ID)

    assert prior_active.status == ContractStatus.expired
    assert contract.status == ContractStatus.active


# ---------------------------------------------------------------------------
# 16. activate_contract — 404 when not found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activate_contract_404():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_execute_result([]))

    with pytest.raises(HTTPException) as exc_info:
        await activate_contract(db, 9999, ADMIN_ID)

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 17. activate_contract — 409 when not draft
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activate_contract_409_not_draft():
    db = AsyncMock()
    contract = _make_contract(status=ContractStatus.active)
    db.execute = AsyncMock(return_value=_make_execute_result([contract]))

    with pytest.raises(HTTPException) as exc_info:
        await activate_contract(db, CONTRACT_ID, ADMIN_ID)

    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 18. terminate_contract — success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_terminate_contract_success():
    db = AsyncMock()
    contract = _make_contract(status=ContractStatus.active)
    db.execute = AsyncMock(return_value=_make_execute_result([contract]))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    result = await terminate_contract(db, CONTRACT_ID, ADMIN_ID, "Business closure")

    assert contract.status == ContractStatus.terminated
    assert contract.termination_reason == "Business closure"
    assert contract.terminated_at is not None


# ---------------------------------------------------------------------------
# 19. terminate_contract — 404 when not found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_terminate_contract_404():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_execute_result([]))

    with pytest.raises(HTTPException) as exc_info:
        await terminate_contract(db, 9999, ADMIN_ID, "reason")

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 20. terminate_contract — 409 when not active
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_terminate_contract_409_not_active():
    db = AsyncMock()
    contract = _make_contract(status=ContractStatus.draft)
    db.execute = AsyncMock(return_value=_make_execute_result([contract]))

    with pytest.raises(HTTPException) as exc_info:
        await terminate_contract(db, CONTRACT_ID, ADMIN_ID, "reason")

    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 21. list_expiring_contracts — returns contracts within window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_expiring_contracts_within_window():
    db = AsyncMock()
    contract = _make_contract(status=ContractStatus.active)
    db.scalar = AsyncMock(return_value=1)
    db.execute = AsyncMock(return_value=_make_execute_result([contract]))

    result = await list_expiring_contracts(db, within_days=30)

    assert result.total == 1
    assert len(result.contracts) == 1


# ---------------------------------------------------------------------------
# 22. list_expiring_contracts — empty when none expiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_expiring_contracts_empty():
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=0)
    db.execute = AsyncMock(return_value=_make_execute_result([]))

    result = await list_expiring_contracts(db, within_days=7)

    assert result.total == 0
    assert result.contracts == []


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def test_contract_create_valid():
    c = ContractCreate(
        contract_start_date=START_DATE,
        contract_end_date=END_DATE,
        auto_renews=True,
        renewal_term_days=365,
        renewal_notice_days=30,
        committed_monthly_rides=100,
        committed_monthly_spend_usd=Decimal("5000.00"),
        negotiated_discount_pct=Decimal("10.00"),
        account_manager_name="Jane Smith",
        account_manager_email="jane@example.com",
    )
    assert c.contract_start_date == START_DATE
    assert c.auto_renews is True
    assert c.renewal_term_days == 365


def test_contract_create_end_date_must_be_after_start_date():
    with pytest.raises(ValidationError):
        ContractCreate(
            contract_start_date=END_DATE,
            contract_end_date=START_DATE,  # before start — invalid
        )


def test_contract_update_all_optional():
    u = ContractUpdate()
    assert u.contract_number is None
    assert u.renewal_notice_days is None
    assert u.notes is None


def test_terminate_request_empty_reason_invalid():
    with pytest.raises(ValidationError):
        TerminateRequest(reason="   ")


def test_contract_response_from_attributes():
    resp = _make_response()
    assert resp.id == CONTRACT_ID
    assert resp.status == "draft"
    assert isinstance(resp.contract_start_date, date)


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------


# 28. GET /corporate/accounts/me/contract — 200 found
@pytest.mark.asyncio
async def test_api_get_my_active_contract_200():
    from app.api.v1.corporate_account_contracts import get_my_active_contract

    user = _mock_user()
    db = AsyncMock()
    mock_response = _make_response(status="active")

    with patch(f"{_ROUTER}._get_member_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.get_active_contract", new=AsyncMock(return_value=mock_response)):
        result = await get_my_active_contract(user=user, db=db)

    assert result.status == "active"
    assert result.account_id == ACCOUNT_ID


# 29. GET /corporate/accounts/me/contract — 404 not a member
@pytest.mark.asyncio
async def test_api_get_my_active_contract_404_not_member():
    from app.api.v1.corporate_account_contracts import get_my_active_contract

    user = _mock_user()
    db = AsyncMock()

    with patch(
        f"{_ROUTER}._get_member_account_id",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Not a member")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await get_my_active_contract(user=user, db=db)

    assert exc_info.value.status_code == 404


# 30. GET /corporate/accounts/me/contract — 404 no active contract
@pytest.mark.asyncio
async def test_api_get_my_active_contract_404_no_contract():
    from app.api.v1.corporate_account_contracts import get_my_active_contract

    user = _mock_user()
    db = AsyncMock()

    with patch(f"{_ROUTER}._get_member_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.get_active_contract", new=AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc_info:
            await get_my_active_contract(user=user, db=db)

    assert exc_info.value.status_code == 404


# 31. GET /admin/corporate/accounts/{id}/contracts — 200
@pytest.mark.asyncio
async def test_api_admin_list_contracts_200():
    from app.api.v1.corporate_account_contracts import admin_list_contracts

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    mock_list = _make_list_response()

    with patch(f"{_ROUTER}.list_contracts", new=AsyncMock(return_value=mock_list)):
        result = await admin_list_contracts(
            account_id=ACCOUNT_ID,
            status=None,
            skip=0,
            limit=50,
            _admin=admin,
            db=db,
        )

    assert result.total == 1


# 32. POST /admin/corporate/accounts/{id}/contracts — 201
@pytest.mark.asyncio
async def test_api_admin_create_contract_201():
    from app.api.v1.corporate_account_contracts import admin_create_contract

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    body = ContractCreate(contract_start_date=START_DATE, contract_end_date=END_DATE)
    mock_response = _make_response()

    with patch(f"{_ROUTER}.create_contract", new=AsyncMock(return_value=mock_response)):
        result = await admin_create_contract(
            account_id=ACCOUNT_ID,
            body=body,
            _admin=admin,
            db=db,
        )

    assert result.id == CONTRACT_ID


# 33. GET /admin/corporate/contracts/expiring — 200
@pytest.mark.asyncio
async def test_api_admin_list_expiring_contracts_200():
    from app.api.v1.corporate_account_contracts import admin_list_expiring_contracts

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    mock_list = _make_list_response()

    with patch(f"{_ROUTER}.list_expiring_contracts", new=AsyncMock(return_value=mock_list)):
        result = await admin_list_expiring_contracts(
            within_days=30,
            skip=0,
            limit=50,
            _admin=admin,
            db=db,
        )

    assert result.total == 1


# 34. GET /admin/corporate/contracts/{id} — 200
@pytest.mark.asyncio
async def test_api_admin_get_contract_200():
    from app.api.v1.corporate_account_contracts import admin_get_contract

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    mock_response = _make_response()

    with patch(f"{_ROUTER}.get_contract", new=AsyncMock(return_value=mock_response)):
        result = await admin_get_contract(
            contract_id=CONTRACT_ID,
            _admin=admin,
            db=db,
        )

    assert result.id == CONTRACT_ID


# 35. GET /admin/corporate/contracts/{id} — 404
@pytest.mark.asyncio
async def test_api_admin_get_contract_404():
    from app.api.v1.corporate_account_contracts import admin_get_contract

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()

    with patch(
        f"{_ROUTER}.get_contract",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Not found")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await admin_get_contract(contract_id=9999, _admin=admin, db=db)

    assert exc_info.value.status_code == 404


# 36. PATCH /admin/corporate/contracts/{id} — 200
@pytest.mark.asyncio
async def test_api_admin_update_contract_200():
    from app.api.v1.corporate_account_contracts import admin_update_contract

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    body = ContractUpdate(notes="New notes")
    mock_response = _make_response()

    with patch(f"{_ROUTER}.update_contract", new=AsyncMock(return_value=mock_response)):
        result = await admin_update_contract(
            contract_id=CONTRACT_ID,
            body=body,
            _admin=admin,
            db=db,
        )

    assert result.id == CONTRACT_ID


# 37. POST /admin/corporate/contracts/{id}/activate — 200
@pytest.mark.asyncio
async def test_api_admin_activate_contract_200():
    from app.api.v1.corporate_account_contracts import admin_activate_contract

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    mock_response = _make_response(status="active")

    with patch(f"{_ROUTER}.activate_contract", new=AsyncMock(return_value=mock_response)):
        result = await admin_activate_contract(
            contract_id=CONTRACT_ID,
            _admin=admin,
            db=db,
        )

    assert result.status == "active"


# 38. POST /admin/corporate/contracts/{id}/terminate — 200
@pytest.mark.asyncio
async def test_api_admin_terminate_contract_200():
    from app.api.v1.corporate_account_contracts import admin_terminate_contract

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    body = TerminateRequest(reason="Company dissolved")
    mock_response = _make_response(status="terminated")

    with patch(f"{_ROUTER}.terminate_contract", new=AsyncMock(return_value=mock_response)):
        result = await admin_terminate_contract(
            contract_id=CONTRACT_ID,
            body=body,
            _admin=admin,
            db=db,
        )

    assert result.status == "terminated"
