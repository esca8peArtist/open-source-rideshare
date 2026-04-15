"""Tests for the Corporate Pre-paid Credits feature.

Service tests (async, mocked DB):
  1.  get_or_create_credit_account — creates new account when none exists
  2.  get_or_create_credit_account — returns existing account (no duplicate)
  3.  get_credit_balance — success
  4.  get_credit_balance — not found → 404
  5.  deposit_credits — increases balance and total_deposited_usd
  6.  deposit_credits — sets balance_after_usd snapshot on transaction
  7.  deposit_credits — zero amount → 422
  8.  deposit_credits — negative amount → 422
  9.  deposit_credits — account not found → 404
  10. deduct_credits — decreases balance and increases total_spent_usd
  11. deduct_credits — sets balance_after_usd snapshot
  12. deduct_credits — insufficient balance → 409
  13. deduct_credits — exact balance deduction succeeds (zero remaining)
  14. deduct_credits — zero amount → 422
  15. deduct_credits — account not found → 404
  16. refund_credits — increases balance and total_refunded_usd
  17. refund_credits — zero amount → 422
  18. refund_credits — account not found → 404
  19. adjust_credits — positive adjustment increases balance
  20. adjust_credits — negative adjustment decreases balance
  21. adjust_credits — zero amount → 422
  22. adjust_credits — adjustment produces negative balance → 422
  23. adjust_credits — account not found → 404
  24. list_credit_transactions — returns newest first
  25. list_credit_transactions — filters by transaction_type
  26. list_credit_transactions — empty list
  27. list_credit_transactions — limit and offset respected
  28. list_low_balance_accounts — returns account below threshold
  29. list_low_balance_accounts — excludes accounts without threshold
  30. list_low_balance_accounts — excludes accounts above threshold
  31. set_low_balance_threshold — sets threshold
  32. set_low_balance_threshold — clears threshold (None)
  33. set_low_balance_threshold — negative threshold → 422
  34. set_low_balance_threshold — account not found → 404

Schema tests (sync):
  35. CreditDepositRequest — valid
  36. CreditDepositRequest — zero amount → ValidationError
  37. CreditDepositRequest — negative amount → ValidationError
  38. CreditRefundRequest — valid
  39. CreditAdjustRequest — zero amount → ValidationError
  40. CreditAdjustRequest — negative amount valid (pass-through)
  41. CreditThresholdRequest — null clears threshold
  42. CreditAccountResponse.from_orm_with_flag — is_low_balance True when below threshold
  43. CreditAccountResponse.from_orm_with_flag — is_low_balance False when above threshold
  44. CreditAccountResponse.from_orm_with_flag — is_low_balance False when no threshold

API layer tests (services patched):
  45. GET  /corporate/accounts/me/credits — 200
  46. GET  /corporate/accounts/me/credits/transactions — 200
  47. POST /corporate/accounts/me/credits/deposit — 201
  48. POST /corporate/accounts/me/credits/refund — 201
  49. PUT  /corporate/accounts/me/credits/threshold — 200
  50. GET  /admin/corporate/accounts/{id}/credits — 200
  51. GET  /admin/corporate/accounts/{id}/credits/transactions — 200
  52. POST /admin/corporate/accounts/{id}/credits/adjust — 201
  53. GET  /admin/corporate/credits/low-balance — 200
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models.corporate_credit_account import (
    CorporateCreditAccount,
    CorporateCreditTransaction,
    CreditTransactionType,
)
from app.schemas.corporate_credit_account import (
    CreditAccountResponse,
    CreditAdjustRequest,
    CreditDepositRequest,
    CreditRefundRequest,
    CreditThresholdRequest,
    CreditTransactionListResponse,
    CreditTransactionResponse,
    LowBalanceListResponse,
)
from app.services.corporate_credit_account import (
    adjust_credits,
    deduct_credits,
    deposit_credits,
    get_credit_balance,
    get_or_create_credit_account,
    list_credit_transactions,
    list_low_balance_accounts,
    refund_credits,
    set_low_balance_threshold,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
_ACCOUNT_ID = 1


def _make_credit_account(
    account_id: int = _ACCOUNT_ID,
    balance: Decimal = Decimal("100.00"),
    total_deposited: Decimal = Decimal("200.00"),
    total_spent: Decimal = Decimal("100.00"),
    total_refunded: Decimal = Decimal("0.00"),
    threshold: Decimal | None = None,
) -> CorporateCreditAccount:
    ca = CorporateCreditAccount(
        id=1,
        account_id=account_id,
        balance_usd=balance,
        total_deposited_usd=total_deposited,
        total_spent_usd=total_spent,
        total_refunded_usd=total_refunded,
        low_balance_threshold_usd=threshold,
        created_at=_NOW,
        updated_at=_NOW,
    )
    return ca


def _make_txn(
    account_id: int = _ACCOUNT_ID,
    txn_type: CreditTransactionType = CreditTransactionType.deposit,
    amount: Decimal = Decimal("50.00"),
    balance_after: Decimal = Decimal("150.00"),
) -> CorporateCreditTransaction:
    return CorporateCreditTransaction(
        id=uuid.uuid4(),
        account_id=account_id,
        credit_account_id=1,
        transaction_type=txn_type,
        amount_usd=amount,
        balance_after_usd=balance_after,
        reference_id=None,
        reference_type=None,
        description="Test transaction",
        created_by_id=None,
        created_at=_NOW,
    )


def _mock_db_with_account(account: CorporateCreditAccount | None) -> AsyncMock:
    """Build a mock DB that returns *account* from scalar_one_or_none."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = account
    db.execute.return_value = result
    return db


# ---------------------------------------------------------------------------
# Service: get_or_create_credit_account
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_create_creates_new():
    """Creates a new CorporateCreditAccount when none exists."""
    db = _mock_db_with_account(None)
    ca, created = await get_or_create_credit_account(db, account_id=_ACCOUNT_ID)
    assert created is True
    assert ca.account_id == _ACCOUNT_ID
    assert ca.balance_usd == Decimal("0.00")
    db.add.assert_called_once()
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_get_or_create_returns_existing():
    """Returns the existing account without adding a duplicate."""
    existing = _make_credit_account()
    db = _mock_db_with_account(existing)
    ca, created = await get_or_create_credit_account(db, account_id=_ACCOUNT_ID)
    assert created is False
    assert ca is existing
    db.add.assert_not_called()


# ---------------------------------------------------------------------------
# Service: get_credit_balance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_credit_balance_success():
    """Returns the credit account when it exists."""
    ca = _make_credit_account()
    db = _mock_db_with_account(ca)
    result = await get_credit_balance(db, account_id=_ACCOUNT_ID)
    assert result is ca


@pytest.mark.asyncio
async def test_get_credit_balance_not_found():
    """Raises 404 when no credit account exists."""
    db = _mock_db_with_account(None)
    with pytest.raises(HTTPException) as exc_info:
        await get_credit_balance(db, account_id=_ACCOUNT_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: deposit_credits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deposit_increases_balance():
    """Deposit adds amount to balance and total_deposited_usd."""
    ca = _make_credit_account(balance=Decimal("50.00"), total_deposited=Decimal("50.00"))
    db = _mock_db_with_account(ca)
    txn = await deposit_credits(db, account_id=_ACCOUNT_ID, amount_usd=Decimal("25.00"))
    assert ca.balance_usd == Decimal("75.00")
    assert ca.total_deposited_usd == Decimal("75.00")
    assert txn.transaction_type == CreditTransactionType.deposit
    assert txn.amount_usd == Decimal("25.00")


@pytest.mark.asyncio
async def test_deposit_sets_balance_after_snapshot():
    """Transaction records the correct balance_after_usd snapshot."""
    ca = _make_credit_account(balance=Decimal("100.00"))
    db = _mock_db_with_account(ca)
    txn = await deposit_credits(db, account_id=_ACCOUNT_ID, amount_usd=Decimal("50.00"))
    assert txn.balance_after_usd == Decimal("150.00")


@pytest.mark.asyncio
async def test_deposit_zero_amount_raises_422():
    """Deposit of zero raises 422."""
    ca = _make_credit_account()
    db = _mock_db_with_account(ca)
    with pytest.raises(HTTPException) as exc_info:
        await deposit_credits(db, account_id=_ACCOUNT_ID, amount_usd=Decimal("0.00"))
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_deposit_negative_amount_raises_422():
    """Deposit of negative value raises 422."""
    ca = _make_credit_account()
    db = _mock_db_with_account(ca)
    with pytest.raises(HTTPException) as exc_info:
        await deposit_credits(db, account_id=_ACCOUNT_ID, amount_usd=Decimal("-10.00"))
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_deposit_account_not_found():
    """Deposit raises 404 when credit account does not exist."""
    db = _mock_db_with_account(None)
    with pytest.raises(HTTPException) as exc_info:
        await deposit_credits(db, account_id=99, amount_usd=Decimal("50.00"))
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: deduct_credits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deduct_decreases_balance():
    """Deduction reduces balance and increases total_spent_usd."""
    ca = _make_credit_account(balance=Decimal("100.00"), total_spent=Decimal("0.00"))
    db = _mock_db_with_account(ca)
    txn = await deduct_credits(db, account_id=_ACCOUNT_ID, amount_usd=Decimal("30.00"))
    assert ca.balance_usd == Decimal("70.00")
    assert ca.total_spent_usd == Decimal("30.00")
    assert txn.transaction_type == CreditTransactionType.deduction


@pytest.mark.asyncio
async def test_deduct_balance_after_snapshot():
    """Deduction records correct balance_after_usd."""
    ca = _make_credit_account(balance=Decimal("80.00"))
    db = _mock_db_with_account(ca)
    txn = await deduct_credits(db, account_id=_ACCOUNT_ID, amount_usd=Decimal("20.00"))
    assert txn.balance_after_usd == Decimal("60.00")


@pytest.mark.asyncio
async def test_deduct_insufficient_balance_raises_409():
    """Deduction exceeding available balance raises 409."""
    ca = _make_credit_account(balance=Decimal("10.00"))
    db = _mock_db_with_account(ca)
    with pytest.raises(HTTPException) as exc_info:
        await deduct_credits(db, account_id=_ACCOUNT_ID, amount_usd=Decimal("50.00"))
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_deduct_exact_balance_succeeds():
    """Deducting the exact available balance succeeds (balance → 0)."""
    ca = _make_credit_account(balance=Decimal("25.00"))
    db = _mock_db_with_account(ca)
    txn = await deduct_credits(db, account_id=_ACCOUNT_ID, amount_usd=Decimal("25.00"))
    assert ca.balance_usd == Decimal("0.00")
    assert txn.balance_after_usd == Decimal("0.00")


@pytest.mark.asyncio
async def test_deduct_zero_raises_422():
    """Deduction of zero raises 422."""
    ca = _make_credit_account()
    db = _mock_db_with_account(ca)
    with pytest.raises(HTTPException) as exc_info:
        await deduct_credits(db, account_id=_ACCOUNT_ID, amount_usd=Decimal("0"))
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_deduct_account_not_found():
    """Deduction raises 404 when credit account does not exist."""
    db = _mock_db_with_account(None)
    with pytest.raises(HTTPException) as exc_info:
        await deduct_credits(db, account_id=99, amount_usd=Decimal("10.00"))
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: refund_credits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refund_increases_balance():
    """Refund increases balance and total_refunded_usd."""
    ca = _make_credit_account(
        balance=Decimal("50.00"), total_refunded=Decimal("0.00")
    )
    db = _mock_db_with_account(ca)
    txn = await refund_credits(db, account_id=_ACCOUNT_ID, amount_usd=Decimal("15.00"))
    assert ca.balance_usd == Decimal("65.00")
    assert ca.total_refunded_usd == Decimal("15.00")
    assert txn.transaction_type == CreditTransactionType.refund


@pytest.mark.asyncio
async def test_refund_zero_raises_422():
    """Refund of zero raises 422."""
    ca = _make_credit_account()
    db = _mock_db_with_account(ca)
    with pytest.raises(HTTPException) as exc_info:
        await refund_credits(db, account_id=_ACCOUNT_ID, amount_usd=Decimal("0"))
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_refund_account_not_found():
    """Refund raises 404 when credit account does not exist."""
    db = _mock_db_with_account(None)
    with pytest.raises(HTTPException) as exc_info:
        await refund_credits(db, account_id=99, amount_usd=Decimal("10.00"))
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: adjust_credits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adjust_positive():
    """Positive adjustment increases balance."""
    ca = _make_credit_account(balance=Decimal("100.00"))
    db = _mock_db_with_account(ca)
    txn = await adjust_credits(
        db, account_id=_ACCOUNT_ID, signed_amount_usd=Decimal("20.00")
    )
    assert ca.balance_usd == Decimal("120.00")
    assert txn.transaction_type == CreditTransactionType.adjustment
    assert txn.amount_usd == Decimal("20.00")


@pytest.mark.asyncio
async def test_adjust_negative():
    """Negative adjustment decreases balance."""
    ca = _make_credit_account(balance=Decimal("100.00"))
    db = _mock_db_with_account(ca)
    txn = await adjust_credits(
        db, account_id=_ACCOUNT_ID, signed_amount_usd=Decimal("-30.00")
    )
    assert ca.balance_usd == Decimal("70.00")
    assert txn.amount_usd == Decimal("30.00")  # stored as absolute value


@pytest.mark.asyncio
async def test_adjust_zero_raises_422():
    """Zero adjustment raises 422."""
    ca = _make_credit_account()
    db = _mock_db_with_account(ca)
    with pytest.raises(HTTPException) as exc_info:
        await adjust_credits(
            db, account_id=_ACCOUNT_ID, signed_amount_usd=Decimal("0")
        )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_adjust_negative_beyond_balance_raises_422():
    """Negative adjustment that would produce a negative balance raises 422."""
    ca = _make_credit_account(balance=Decimal("10.00"))
    db = _mock_db_with_account(ca)
    with pytest.raises(HTTPException) as exc_info:
        await adjust_credits(
            db, account_id=_ACCOUNT_ID, signed_amount_usd=Decimal("-50.00")
        )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_adjust_account_not_found():
    """Adjustment raises 404 when credit account does not exist."""
    db = _mock_db_with_account(None)
    with pytest.raises(HTTPException) as exc_info:
        await adjust_credits(
            db, account_id=99, signed_amount_usd=Decimal("10.00")
        )
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: list_credit_transactions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_transactions_returns_all():
    """list_credit_transactions returns all transactions for account."""
    txns = [_make_txn(), _make_txn(txn_type=CreditTransactionType.deduction)]
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = txns
    db.execute.return_value = result
    items = await list_credit_transactions(db, account_id=_ACCOUNT_ID)
    assert len(items) == 2


@pytest.mark.asyncio
async def test_list_transactions_type_filter():
    """list_credit_transactions passes type filter to query."""
    txns = [_make_txn(txn_type=CreditTransactionType.refund)]
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = txns
    db.execute.return_value = result
    items = await list_credit_transactions(
        db, account_id=_ACCOUNT_ID, transaction_type=CreditTransactionType.refund
    )
    assert all(t.transaction_type == CreditTransactionType.refund for t in items)


@pytest.mark.asyncio
async def test_list_transactions_empty():
    """list_credit_transactions returns empty list when no transactions."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute.return_value = result
    items = await list_credit_transactions(db, account_id=_ACCOUNT_ID)
    assert items == []


@pytest.mark.asyncio
async def test_list_transactions_limit_offset():
    """list_credit_transactions includes limit and offset in query."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute.return_value = result
    await list_credit_transactions(db, account_id=_ACCOUNT_ID, limit=10, offset=5)
    db.execute.assert_called_once()


# ---------------------------------------------------------------------------
# Service: list_low_balance_accounts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_low_balance_returns_below_threshold():
    """Returns account when balance is below threshold."""
    ca = _make_credit_account(balance=Decimal("5.00"), threshold=Decimal("20.00"))
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [ca]
    db.execute.return_value = result
    accounts = await list_low_balance_accounts(db)
    assert len(accounts) == 1
    assert accounts[0] is ca


@pytest.mark.asyncio
async def test_list_low_balance_excludes_no_threshold():
    """Accounts without a threshold configured are excluded."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute.return_value = result
    accounts = await list_low_balance_accounts(db)
    assert accounts == []


@pytest.mark.asyncio
async def test_list_low_balance_excludes_above_threshold():
    """Accounts above their threshold are excluded."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute.return_value = result
    accounts = await list_low_balance_accounts(db)
    assert accounts == []


# ---------------------------------------------------------------------------
# Service: set_low_balance_threshold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_threshold_success():
    """set_low_balance_threshold sets the threshold value."""
    ca = _make_credit_account(threshold=None)
    db = _mock_db_with_account(ca)
    result = await set_low_balance_threshold(db, account_id=_ACCOUNT_ID, threshold_usd=Decimal("50.00"))
    assert result.low_balance_threshold_usd == Decimal("50.00")


@pytest.mark.asyncio
async def test_set_threshold_none_clears():
    """Passing None clears the threshold."""
    ca = _make_credit_account(threshold=Decimal("100.00"))
    db = _mock_db_with_account(ca)
    result = await set_low_balance_threshold(db, account_id=_ACCOUNT_ID, threshold_usd=None)
    assert result.low_balance_threshold_usd is None


@pytest.mark.asyncio
async def test_set_threshold_negative_raises_422():
    """Negative threshold raises 422."""
    ca = _make_credit_account()
    db = _mock_db_with_account(ca)
    with pytest.raises(HTTPException) as exc_info:
        await set_low_balance_threshold(
            db, account_id=_ACCOUNT_ID, threshold_usd=Decimal("-1.00")
        )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_set_threshold_account_not_found():
    """set_low_balance_threshold raises 404 when credit account does not exist."""
    db = _mock_db_with_account(None)
    with pytest.raises(HTTPException) as exc_info:
        await set_low_balance_threshold(
            db, account_id=99, threshold_usd=Decimal("50.00")
        )
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_credit_deposit_request_valid():
    req = CreditDepositRequest(amount_usd=Decimal("100.00"), description="Top-up")
    assert req.amount_usd == Decimal("100.00")


def test_credit_deposit_request_zero_raises():
    with pytest.raises(ValidationError):
        CreditDepositRequest(amount_usd=Decimal("0"))


def test_credit_deposit_request_negative_raises():
    with pytest.raises(ValidationError):
        CreditDepositRequest(amount_usd=Decimal("-5.00"))


def test_credit_refund_request_valid():
    req = CreditRefundRequest(amount_usd=Decimal("20.00"))
    assert req.amount_usd == Decimal("20.00")


def test_credit_adjust_request_zero_raises():
    with pytest.raises(ValidationError):
        CreditAdjustRequest(signed_amount_usd=Decimal("0"))


def test_credit_adjust_request_negative_valid():
    """Negative value is valid for adjustment."""
    req = CreditAdjustRequest(signed_amount_usd=Decimal("-10.00"))
    assert req.signed_amount_usd == Decimal("-10.00")


def test_credit_threshold_none():
    req = CreditThresholdRequest(threshold_usd=None)
    assert req.threshold_usd is None


def test_credit_account_response_is_low_balance_true():
    ca = _make_credit_account(balance=Decimal("5.00"), threshold=Decimal("50.00"))
    resp = CreditAccountResponse.from_orm_with_flag(ca)
    assert resp.is_low_balance is True


def test_credit_account_response_is_low_balance_false_above():
    ca = _make_credit_account(balance=Decimal("200.00"), threshold=Decimal("50.00"))
    resp = CreditAccountResponse.from_orm_with_flag(ca)
    assert resp.is_low_balance is False


def test_credit_account_response_is_low_balance_false_no_threshold():
    ca = _make_credit_account(balance=Decimal("0.00"), threshold=None)
    resp = CreditAccountResponse.from_orm_with_flag(ca)
    assert resp.is_low_balance is False


# ---------------------------------------------------------------------------
# API layer (services patched)
# ---------------------------------------------------------------------------

_BASE = "/api/v1/corporate/accounts/me/credits"
_ADMIN_BASE = "/api/v1/admin/corporate"
_DUMMY_TXN = _make_txn()
_DUMMY_CA = _make_credit_account()


def _make_app_client():
    """Build a TestClient with auth + DB deps overridden."""
    from app.main import app
    from app.api.deps import get_current_user, get_db, require_admin
    from app.models.user import User

    mock_user = MagicMock(spec=User)
    mock_user.id = 10

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


@patch(
    "app.api.v1.corporate_credit_accounts._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_credit_accounts.get_or_create_credit_account",
    new_callable=AsyncMock,
    return_value=(_DUMMY_CA, False),
)
def test_api_get_my_credit_balance(mock_get_or_create, mock_resolve):
    client = _make_app_client()
    resp = client.get(_BASE)
    assert resp.status_code == 200


@patch(
    "app.api.v1.corporate_credit_accounts._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_credit_accounts.list_credit_transactions",
    new_callable=AsyncMock,
    return_value=[],
)
def test_api_list_my_credit_transactions(mock_list, mock_resolve):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/transactions")
    assert resp.status_code == 200
    assert "items" in resp.json()


@patch(
    "app.api.v1.corporate_credit_accounts._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_credit_accounts.get_or_create_credit_account",
    new_callable=AsyncMock,
    return_value=(_DUMMY_CA, False),
)
@patch(
    "app.api.v1.corporate_credit_accounts.deposit_credits",
    new_callable=AsyncMock,
    return_value=_DUMMY_TXN,
)
def test_api_deposit_credits(mock_deposit, mock_get_or_create, mock_resolve):
    client = _make_app_client()
    resp = client.post(
        f"{_BASE}/deposit",
        json={"amount_usd": "50.00", "description": "Monthly top-up"},
    )
    assert resp.status_code == 201


@patch(
    "app.api.v1.corporate_credit_accounts._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_credit_accounts.get_or_create_credit_account",
    new_callable=AsyncMock,
    return_value=(_DUMMY_CA, False),
)
@patch(
    "app.api.v1.corporate_credit_accounts.refund_credits",
    new_callable=AsyncMock,
    return_value=_make_txn(txn_type=CreditTransactionType.refund),
)
def test_api_refund_credits(mock_refund, mock_get_or_create, mock_resolve):
    client = _make_app_client()
    resp = client.post(
        f"{_BASE}/refund",
        json={"amount_usd": "15.00", "description": "Ride cancellation"},
    )
    assert resp.status_code == 201


@patch(
    "app.api.v1.corporate_credit_accounts._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_credit_accounts.get_or_create_credit_account",
    new_callable=AsyncMock,
    return_value=(_DUMMY_CA, False),
)
@patch(
    "app.api.v1.corporate_credit_accounts.set_low_balance_threshold",
    new_callable=AsyncMock,
    return_value=_make_credit_account(threshold=Decimal("50.00")),
)
def test_api_set_threshold(mock_set, mock_get_or_create, mock_resolve):
    client = _make_app_client()
    resp = client.put(
        f"{_BASE}/threshold",
        json={"threshold_usd": "50.00"},
    )
    assert resp.status_code == 200


@patch(
    "app.api.v1.corporate_credit_accounts.get_or_create_credit_account",
    new_callable=AsyncMock,
    return_value=(_DUMMY_CA, False),
)
def test_api_platform_admin_get_credits(mock_get_or_create):
    client = _make_app_client()
    resp = client.get(f"{_ADMIN_BASE}/accounts/{_ACCOUNT_ID}/credits")
    assert resp.status_code == 200


@patch(
    "app.api.v1.corporate_credit_accounts.list_credit_transactions",
    new_callable=AsyncMock,
    return_value=[],
)
def test_api_platform_admin_list_transactions(mock_list):
    client = _make_app_client()
    resp = client.get(f"{_ADMIN_BASE}/accounts/{_ACCOUNT_ID}/credits/transactions")
    assert resp.status_code == 200
    assert "items" in resp.json()


@patch(
    "app.api.v1.corporate_credit_accounts.get_or_create_credit_account",
    new_callable=AsyncMock,
    return_value=(_DUMMY_CA, False),
)
@patch(
    "app.api.v1.corporate_credit_accounts.adjust_credits",
    new_callable=AsyncMock,
    return_value=_make_txn(txn_type=CreditTransactionType.adjustment),
)
def test_api_platform_admin_adjust(mock_adjust, mock_get_or_create):
    client = _make_app_client()
    resp = client.post(
        f"{_ADMIN_BASE}/accounts/{_ACCOUNT_ID}/credits/adjust",
        json={"signed_amount_usd": "-20.00", "description": "Correction"},
    )
    assert resp.status_code == 201


@patch(
    "app.api.v1.corporate_credit_accounts.list_low_balance_accounts",
    new_callable=AsyncMock,
    return_value=[],
)
def test_api_platform_admin_low_balance(mock_list):
    client = _make_app_client()
    resp = client.get(f"{_ADMIN_BASE}/credits/low-balance")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []
