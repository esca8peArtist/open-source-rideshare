"""Unit tests for the driver referral program.

Coverage:
  Schema validation:
    1.  ApplyReferralRequest — valid code accepted
    2.  ApplyReferralRequest — code is stripped and uppercased
    3.  ApplyReferralRequest — empty code rejected
    4.  ApplyReferralRequest — code longer than 16 chars rejected

  _make_code / _unique_code:
    5.  _make_code returns 8-character string
    6.  _make_code only contains uppercase alphanumerics
    7.  Two calls produce different codes (probabilistic)

  get_or_create_referral_code:
    8.  Returns existing record when one exists
    9.  Creates a new record when none exists
    10. New record has the requested driver_profile_id
    11. db.add is called once when creating a new code
    12. db.flush is called after adding new record

  apply_referral_code:
    13. Returns success=False when driver already has a referral
    14. Returns success=False when code does not exist
    15. Returns success=False when driver uses their own code
    16. Returns success=True for a valid new referral
    17. Created referral has correct referrer_profile_id
    18. Created referral has correct referred_profile_id
    19. Created referral has PENDING status
    20. Created referral has bonus_amount = BONUS_AMOUNT
    21. Response includes referrer_driver_profile_id on success

  record_ride_completion:
    22. Increments rides_completed for pending referral
    23. Transitions to QUALIFIED when threshold is reached
    24. Sets qualified_at when qualifying
    25. Does nothing when driver has no pending referral
    26. Does not modify already QUALIFIED referrals

  get_referral_summary:
    27. Returns correct pending_count
    28. Returns correct qualified_count
    29. Returns correct bonus_paid_count
    30. total_bonus_earned sums only bonus_paid referrals
    31. Code is included in response

  get_my_referrals:
    32. Returned items have correct rides_needed constant
    33. Total count reflects all referrals (not just current page)
    34. Code is included in response

  get_admin_stats:
    35. Returns correct total_codes_issued
    36. Returns correct total_referrals
    37. pending/qualified/bonus_paid counts are correct
    38. total_bonus_paid_amount is 0.0 when no paid referrals

  Endpoint auth:
    39. GET /drivers/me/referral returns 403 for rider
    40. GET /drivers/me/referral returns 403 for admin
    41. POST /drivers/me/referral/apply returns 403 for rider
    42. GET /admin/referrals/stats returns 403 for driver
    43. GET /admin/referrals/stats returns 403 for rider
    44. GET /admin/referrals/stats without auth returns 401 or 403
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.driver_referral import DriverReferral, DriverReferralCode, ReferralStatus
from app.schemas.driver_referral import ApplyReferralRequest
from app.services.driver_referrals import (
    BONUS_AMOUNT,
    QUALIFICATION_RIDES,
    _make_code,
    apply_referral_code,
    get_admin_stats,
    get_my_referrals,
    get_or_create_referral_code,
    get_referral_summary,
    record_ride_completion,
)

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# DB mock helpers
# ---------------------------------------------------------------------------


def _one_result(item) -> MagicMock:
    """Simulate execute() → .scalar_one_or_none() returning item."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = item
    r.scalar_one.return_value = item
    scalars = MagicMock()
    scalars.all.return_value = [item] if item is not None else []
    r.scalars.return_value = scalars
    return r


def _list_result(items: list) -> MagicMock:
    """Simulate execute() → .scalars().all() returning items."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = items[0] if items else None
    r.scalar_one.return_value = len(items)
    scalars = MagicMock()
    scalars.all.return_value = items
    r.scalars.return_value = scalars
    return r


def _count_result(n: int) -> MagicMock:
    """Simulate execute() → .scalar_one() returning an integer count."""
    r = MagicMock()
    r.scalar_one.return_value = n
    r.scalar_one_or_none.return_value = n
    scalars = MagicMock()
    scalars.all.return_value = []
    r.scalars.return_value = scalars
    return r


def _none_result() -> MagicMock:
    """Simulate execute() returning no row."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    r.scalar_one.return_value = 0
    scalars = MagicMock()
    scalars.all.return_value = []
    r.scalars.return_value = scalars
    return r


def _make_db(*results) -> AsyncMock:
    """Return a DB mock that yields results for successive execute() calls."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(results))
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def _make_code_record(
    profile_id: int = 1,
    code: str = "ABCD1234",
    record_id: int = 10,
) -> MagicMock:
    r = MagicMock(spec=DriverReferralCode)
    r.id = record_id
    r.driver_profile_id = profile_id
    r.code = code
    r.created_at = _NOW
    return r


def _make_referral(
    referral_id: int = 1,
    referrer_profile_id: int = 1,
    referred_profile_id: int = 2,
    code: str = "ABCD1234",
    status: ReferralStatus = ReferralStatus.PENDING,
    rides_completed: int = 0,
    bonus_amount: float = BONUS_AMOUNT,
    qualified_at=None,
) -> MagicMock:
    r = MagicMock(spec=DriverReferral)
    r.id = referral_id
    r.referrer_profile_id = referrer_profile_id
    r.referred_profile_id = referred_profile_id
    r.code_used = code
    r.status = status
    r.rides_completed = rides_completed
    r.bonus_amount = bonus_amount
    r.created_at = _NOW
    r.qualified_at = qualified_at
    return r


# ---------------------------------------------------------------------------
# 1-4: Schema validation
# ---------------------------------------------------------------------------


class TestApplyReferralRequestSchema:
    def test_valid_code_accepted(self):
        req = ApplyReferralRequest(code="ABCD1234")
        assert req.code == "ABCD1234"

    def test_code_is_stripped_and_uppercased(self):
        req = ApplyReferralRequest(code="  abcd1234  ")
        assert req.code == "ABCD1234"

    def test_empty_code_rejected(self):
        with pytest.raises(Exception):
            ApplyReferralRequest(code="")

    def test_code_over_16_chars_rejected(self):
        with pytest.raises(Exception):
            ApplyReferralRequest(code="A" * 17)


# ---------------------------------------------------------------------------
# 5-7: _make_code
# ---------------------------------------------------------------------------


class TestMakeCode:
    def test_returns_8_characters(self):
        assert len(_make_code()) == 8

    def test_only_uppercase_alphanumeric(self):
        code = _make_code()
        assert code.isalnum()
        assert code == code.upper()

    def test_two_calls_usually_differ(self):
        codes = {_make_code() for _ in range(20)}
        assert len(codes) > 1


# ---------------------------------------------------------------------------
# 8-12: get_or_create_referral_code
# ---------------------------------------------------------------------------


class TestGetOrCreateReferralCode:
    @pytest.mark.asyncio
    async def test_returns_existing_record(self):
        existing = _make_code_record(profile_id=5, code="EXIST123")
        db = _make_db(_one_result(existing))
        result = await get_or_create_referral_code(db, driver_profile_id=5)
        assert result.code == "EXIST123"

    @pytest.mark.asyncio
    async def test_creates_new_record_when_none_exists(self):
        # First execute → no existing record; second execute → code is unique
        db = _make_db(_none_result(), _none_result())
        result = await get_or_create_referral_code(db, driver_profile_id=7)
        assert db.add.called
        assert isinstance(db.add.call_args[0][0], DriverReferralCode)

    @pytest.mark.asyncio
    async def test_new_record_has_correct_profile_id(self):
        db = _make_db(_none_result(), _none_result())
        await get_or_create_referral_code(db, driver_profile_id=42)
        added = db.add.call_args[0][0]
        assert added.driver_profile_id == 42

    @pytest.mark.asyncio
    async def test_db_add_called_once(self):
        db = _make_db(_none_result(), _none_result())
        await get_or_create_referral_code(db, driver_profile_id=1)
        assert db.add.call_count == 1

    @pytest.mark.asyncio
    async def test_db_flush_called_after_add(self):
        db = _make_db(_none_result(), _none_result())
        await get_or_create_referral_code(db, driver_profile_id=1)
        assert db.flush.called


# ---------------------------------------------------------------------------
# 13-21: apply_referral_code
# ---------------------------------------------------------------------------


class TestApplyReferralCode:
    @pytest.mark.asyncio
    async def test_returns_failure_when_already_referred(self):
        existing_referral = _make_referral(referred_profile_id=10)
        db = _make_db(_one_result(existing_referral))
        result = await apply_referral_code(db, new_driver_profile_id=10, code="CODE0001")
        assert not result.success
        assert "already" in result.message.lower()

    @pytest.mark.asyncio
    async def test_returns_failure_when_code_does_not_exist(self):
        db = _make_db(_none_result(), _none_result())
        result = await apply_referral_code(db, new_driver_profile_id=10, code="BADCODE1")
        assert not result.success
        assert "invalid" in result.message.lower()

    @pytest.mark.asyncio
    async def test_returns_failure_when_using_own_code(self):
        code_record = _make_code_record(profile_id=10, code="MYCODE01")
        db = _make_db(_none_result(), _one_result(code_record))
        result = await apply_referral_code(db, new_driver_profile_id=10, code="MYCODE01")
        assert not result.success
        assert "own" in result.message.lower()

    @pytest.mark.asyncio
    async def test_returns_success_for_valid_referral(self):
        code_record = _make_code_record(profile_id=5, code="VALID001")
        db = _make_db(_none_result(), _one_result(code_record))
        result = await apply_referral_code(db, new_driver_profile_id=10, code="VALID001")
        assert result.success

    @pytest.mark.asyncio
    async def test_created_referral_has_correct_referrer(self):
        code_record = _make_code_record(profile_id=5, code="VALID001")
        db = _make_db(_none_result(), _one_result(code_record))
        await apply_referral_code(db, new_driver_profile_id=10, code="VALID001")
        added = db.add.call_args[0][0]
        assert added.referrer_profile_id == 5

    @pytest.mark.asyncio
    async def test_created_referral_has_correct_referred(self):
        code_record = _make_code_record(profile_id=5, code="VALID001")
        db = _make_db(_none_result(), _one_result(code_record))
        await apply_referral_code(db, new_driver_profile_id=10, code="VALID001")
        added = db.add.call_args[0][0]
        assert added.referred_profile_id == 10

    @pytest.mark.asyncio
    async def test_created_referral_has_pending_status(self):
        code_record = _make_code_record(profile_id=5, code="VALID001")
        db = _make_db(_none_result(), _one_result(code_record))
        await apply_referral_code(db, new_driver_profile_id=10, code="VALID001")
        added = db.add.call_args[0][0]
        assert added.status == ReferralStatus.PENDING

    @pytest.mark.asyncio
    async def test_created_referral_has_correct_bonus_amount(self):
        code_record = _make_code_record(profile_id=5, code="VALID001")
        db = _make_db(_none_result(), _one_result(code_record))
        await apply_referral_code(db, new_driver_profile_id=10, code="VALID001")
        added = db.add.call_args[0][0]
        assert added.bonus_amount == BONUS_AMOUNT

    @pytest.mark.asyncio
    async def test_response_includes_referrer_profile_id(self):
        code_record = _make_code_record(profile_id=5, code="VALID001")
        db = _make_db(_none_result(), _one_result(code_record))
        result = await apply_referral_code(db, new_driver_profile_id=10, code="VALID001")
        assert result.referrer_driver_profile_id == 5


# ---------------------------------------------------------------------------
# 22-26: record_ride_completion
# ---------------------------------------------------------------------------


class TestRecordRideCompletion:
    @pytest.mark.asyncio
    async def test_increments_rides_completed(self):
        referral = _make_referral(rides_completed=3, status=ReferralStatus.PENDING)
        db = _make_db(_one_result(referral))
        await record_ride_completion(db, driver_profile_id=2)
        assert referral.rides_completed == 4

    @pytest.mark.asyncio
    async def test_transitions_to_qualified_at_threshold(self):
        # rides_completed is at QUALIFICATION_RIDES - 1, so one more qualifies.
        referral = _make_referral(
            rides_completed=QUALIFICATION_RIDES - 1,
            status=ReferralStatus.PENDING,
        )
        db = _make_db(_one_result(referral))
        await record_ride_completion(db, driver_profile_id=2)
        assert referral.status == ReferralStatus.QUALIFIED

    @pytest.mark.asyncio
    async def test_sets_qualified_at_on_qualification(self):
        referral = _make_referral(
            rides_completed=QUALIFICATION_RIDES - 1,
            status=ReferralStatus.PENDING,
        )
        db = _make_db(_one_result(referral))
        await record_ride_completion(db, driver_profile_id=2)
        assert referral.qualified_at is not None

    @pytest.mark.asyncio
    async def test_does_nothing_when_no_pending_referral(self):
        db = _make_db(_none_result())
        # Should not raise and no mutations should occur
        await record_ride_completion(db, driver_profile_id=99)
        db.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_modify_already_qualified(self):
        # The query filters to PENDING, so QUALIFIED referrals return None.
        db = _make_db(_none_result())
        await record_ride_completion(db, driver_profile_id=2)
        # flush not called = no mutation
        db.flush.assert_not_called()


# ---------------------------------------------------------------------------
# 27-31: get_referral_summary
# ---------------------------------------------------------------------------


class TestGetReferralSummary:
    @pytest.mark.asyncio
    async def test_correct_pending_count(self):
        code_record = _make_code_record(profile_id=1)
        referrals = [
            _make_referral(status=ReferralStatus.PENDING),
            _make_referral(referral_id=2, status=ReferralStatus.PENDING),
            _make_referral(referral_id=3, status=ReferralStatus.QUALIFIED),
        ]
        db = _make_db(_one_result(code_record), _list_result(referrals))
        result = await get_referral_summary(db, driver_profile_id=1)
        assert result.pending_count == 2

    @pytest.mark.asyncio
    async def test_correct_qualified_count(self):
        code_record = _make_code_record(profile_id=1)
        referrals = [
            _make_referral(status=ReferralStatus.QUALIFIED),
            _make_referral(referral_id=2, status=ReferralStatus.QUALIFIED),
        ]
        db = _make_db(_one_result(code_record), _list_result(referrals))
        result = await get_referral_summary(db, driver_profile_id=1)
        assert result.qualified_count == 2

    @pytest.mark.asyncio
    async def test_correct_bonus_paid_count(self):
        code_record = _make_code_record(profile_id=1)
        referrals = [
            _make_referral(status=ReferralStatus.BONUS_PAID, bonus_amount=50.0),
        ]
        db = _make_db(_one_result(code_record), _list_result(referrals))
        result = await get_referral_summary(db, driver_profile_id=1)
        assert result.bonus_paid_count == 1

    @pytest.mark.asyncio
    async def test_total_bonus_earned_sums_only_paid(self):
        code_record = _make_code_record(profile_id=1)
        referrals = [
            _make_referral(status=ReferralStatus.BONUS_PAID, bonus_amount=50.0),
            _make_referral(referral_id=2, status=ReferralStatus.BONUS_PAID, bonus_amount=50.0),
            _make_referral(referral_id=3, status=ReferralStatus.QUALIFIED, bonus_amount=50.0),
        ]
        db = _make_db(_one_result(code_record), _list_result(referrals))
        result = await get_referral_summary(db, driver_profile_id=1)
        assert result.total_bonus_earned == 100.0

    @pytest.mark.asyncio
    async def test_code_included_in_response(self):
        code_record = _make_code_record(profile_id=1, code="MYCODE00")
        db = _make_db(_one_result(code_record), _list_result([]))
        result = await get_referral_summary(db, driver_profile_id=1)
        assert result.code == "MYCODE00"


# ---------------------------------------------------------------------------
# 32-34: get_my_referrals
# ---------------------------------------------------------------------------


class TestGetMyReferrals:
    @pytest.mark.asyncio
    async def test_items_have_correct_rides_needed(self):
        code_record = _make_code_record(profile_id=1)
        referrals = [_make_referral(rides_completed=3)]
        db = _make_db(
            _one_result(code_record),   # get_or_create
            _count_result(1),           # total count
            _list_result(referrals),    # paginated list
        )
        result = await get_my_referrals(db, driver_profile_id=1)
        assert result.referrals[0].rides_needed == QUALIFICATION_RIDES

    @pytest.mark.asyncio
    async def test_total_count_reflects_all_referrals(self):
        code_record = _make_code_record(profile_id=1)
        db = _make_db(
            _one_result(code_record),
            _count_result(42),
            _list_result([]),
        )
        result = await get_my_referrals(db, driver_profile_id=1)
        assert result.total == 42

    @pytest.mark.asyncio
    async def test_code_included_in_response(self):
        code_record = _make_code_record(profile_id=1, code="LISTCODE")
        db = _make_db(
            _one_result(code_record),
            _count_result(0),
            _list_result([]),
        )
        result = await get_my_referrals(db, driver_profile_id=1)
        assert result.code == "LISTCODE"


# ---------------------------------------------------------------------------
# 35-38: get_admin_stats
# ---------------------------------------------------------------------------


class TestGetAdminStats:
    @pytest.mark.asyncio
    async def test_returns_correct_total_codes_issued(self):
        db = _make_db(
            _count_result(7),   # total codes
            _count_result(15),  # total referrals
            _count_result(5),   # pending
            _count_result(8),   # qualified
            _count_result(2),   # bonus_paid
            _count_result(100), # total bonus sum
        )
        result = await get_admin_stats(db)
        assert result.total_codes_issued == 7

    @pytest.mark.asyncio
    async def test_returns_correct_total_referrals(self):
        db = _make_db(
            _count_result(3),
            _count_result(20),
            _count_result(10),
            _count_result(7),
            _count_result(3),
            _count_result(150),
        )
        result = await get_admin_stats(db)
        assert result.total_referrals == 20

    @pytest.mark.asyncio
    async def test_status_counts_are_correct(self):
        db = _make_db(
            _count_result(10),
            _count_result(30),
            _count_result(12),  # pending
            _count_result(14),  # qualified
            _count_result(4),   # bonus_paid
            _count_result(200),
        )
        result = await get_admin_stats(db)
        assert result.pending_count == 12
        assert result.qualified_count == 14
        assert result.bonus_paid_count == 4

    @pytest.mark.asyncio
    async def test_total_bonus_paid_amount_is_float(self):
        db = _make_db(
            _count_result(0),
            _count_result(0),
            _count_result(0),
            _count_result(0),
            _count_result(0),
            _count_result(0),
        )
        result = await get_admin_stats(db)
        assert result.total_bonus_paid_amount == 0.0


# ---------------------------------------------------------------------------
# 39-44: Endpoint auth (integration — skip if no test DB)
# ---------------------------------------------------------------------------


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
class TestDriverReferralEndpointAuth:
    async def test_get_referral_code_returns_403_for_rider(self, client, rider, rider_token):
        resp = await client.get(
            "/api/v1/drivers/me/referral",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403

    async def test_get_referral_code_returns_403_for_admin(self, client, admin_user, admin_token):
        resp = await client.get(
            "/api/v1/drivers/me/referral",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 403

    async def test_apply_referral_returns_403_for_rider(self, client, rider, rider_token):
        resp = await client.post(
            "/api/v1/drivers/me/referral/apply",
            json={"code": "ABCD1234"},
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403

    async def test_admin_stats_returns_403_for_driver(self, client, driver_user, driver_token):
        resp = await client.get(
            "/api/v1/admin/referrals/stats",
            headers=auth_header(driver_token),
        )
        assert resp.status_code == 403

    async def test_admin_stats_returns_403_for_rider(self, client, rider, rider_token):
        resp = await client.get(
            "/api/v1/admin/referrals/stats",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403

    async def test_admin_stats_without_auth_returns_401_or_403(self, client):
        resp = await client.get("/api/v1/admin/referrals/stats")
        assert resp.status_code in (401, 403)
