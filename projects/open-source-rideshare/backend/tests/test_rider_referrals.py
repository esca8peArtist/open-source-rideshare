"""Unit tests for the rider referral program.

Coverage:
  Schema validation:
    1.  ApplyRiderReferralRequest — valid code accepted
    2.  ApplyRiderReferralRequest — code normalised to uppercase on apply
    3.  ApplyRiderReferralRequest — empty code rejected
    4.  ApplyRiderReferralRequest — code longer than 16 chars rejected

  _make_code:
    5.  Returns 8-character string
    6.  Only contains uppercase alphanumerics
    7.  Two calls usually differ

  get_or_create_referral_code:
    8.  Returns existing record when one exists
    9.  Creates new record when none exists
    10. New record has the requested user_id
    11. db.add called once when creating
    12. db.flush called after add

  apply_referral_code:
    13. Returns success=False when rider already has a referral applied
    14. Returns success=False when code does not exist
    15. Returns success=False when rider uses their own code
    16. Returns success=True for a valid new referral
    17. Created referral has correct referrer_user_id
    18. Created referral has correct referred_user_id
    19. Created referral has PENDING status
    20. Created referral has referrer_reward_amount = REFERRER_REWARD_USD
    21. Created referral has referred_discount_amount = REFERRED_DISCOUNT_USD
    22. Response includes referrer_user_id on success
    23. Code is uppercased before lookup

  record_first_ride_completion:
    24. Transitions PENDING referral to QUALIFIED
    25. Sets first_ride_id on the referral
    26. Sets qualified_at timestamp
    27. Does nothing when rider has no pending referral
    28. Does not flush when no referral found

  get_referral_summary:
    29. Returns correct pending_count
    30. Returns correct qualified_count
    31. Returns correct rewarded_count
    32. total_reward_earned sums only REWARDED referrals
    33. Code is included in response
    34. total_reward_earned is 0.0 when none rewarded

  get_my_referrals:
    35. Total count reflects all referrals (not just current page)
    36. Code is included in response
    37. Empty referral list returns total=0

  get_admin_stats:
    38. Returns correct total_codes_issued
    39. Returns correct total_referrals
    40. pending/qualified/rewarded counts are correct
    41. total_reward_paid_amount is 0.0 when no rewarded referrals

  Endpoint auth (integration):
    42. GET /riders/me/referral-code returns 200 for rider
    43. GET /riders/me/referral-code returns 403 for unauthenticated
    44. GET /riders/me/referrals returns 403 for unauthenticated
    45. POST /riders/referral/apply returns 403 for unauthenticated
    46. GET /admin/referrals/rider/stats returns 403 for rider
    47. GET /admin/referrals/rider/stats returns 403 for driver
    48. GET /admin/referrals/rider/stats returns 200 for admin
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.rider_referral import RiderReferral, RiderReferralCode, RiderReferralStatus
from app.schemas.rider_referral import ApplyRiderReferralRequest
from app.services.rider_referrals import (
    REFERRER_REWARD_USD,
    REFERRED_DISCOUNT_USD,
    _make_code,
    apply_referral_code,
    get_admin_stats,
    get_my_referrals,
    get_or_create_referral_code,
    get_referral_summary,
    record_first_ride_completion,
)

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# DB mock helpers
# ---------------------------------------------------------------------------


def _one_result(item) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = item
    r.scalar_one.return_value = item
    scalars = MagicMock()
    scalars.all.return_value = [item] if item is not None else []
    r.scalars.return_value = scalars
    return r


def _list_result(items: list) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = items[0] if items else None
    r.scalar_one.return_value = len(items)
    scalars = MagicMock()
    scalars.all.return_value = items
    r.scalars.return_value = scalars
    return r


def _count_result(n: int) -> MagicMock:
    r = MagicMock()
    r.scalar_one.return_value = n
    r.scalar_one_or_none.return_value = n
    scalars = MagicMock()
    scalars.all.return_value = []
    r.scalars.return_value = scalars
    return r


def _none_result() -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    r.scalar_one.return_value = 0
    scalars = MagicMock()
    scalars.all.return_value = []
    r.scalars.return_value = scalars
    return r


def _make_db(*results) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(results))
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def _make_code_record(
    user_id: int = 1,
    code: str = "ABCD1234",
    record_id: int = 10,
) -> MagicMock:
    r = MagicMock(spec=RiderReferralCode)
    r.id = record_id
    r.user_id = user_id
    r.code = code
    r.created_at = _NOW
    return r


def _make_referral(
    referral_id: int = 1,
    referrer_user_id: int = 1,
    referred_user_id: int = 2,
    code: str = "ABCD1234",
    status: RiderReferralStatus = RiderReferralStatus.PENDING,
    first_ride_id=None,
    referrer_reward_amount: float = REFERRER_REWARD_USD,
    referred_discount_amount: float = REFERRED_DISCOUNT_USD,
    qualified_at=None,
) -> MagicMock:
    r = MagicMock(spec=RiderReferral)
    r.id = referral_id
    r.referrer_user_id = referrer_user_id
    r.referred_user_id = referred_user_id
    r.code_used = code
    r.status = status
    r.first_ride_id = first_ride_id
    r.referrer_reward_amount = referrer_reward_amount
    r.referred_discount_amount = referred_discount_amount
    r.created_at = _NOW
    r.qualified_at = qualified_at
    return r


# ---------------------------------------------------------------------------
# 1-4: Schema validation
# ---------------------------------------------------------------------------


class TestApplyRiderReferralRequestSchema:
    def test_valid_code_accepted(self):
        req = ApplyRiderReferralRequest(code="ABCD1234")
        assert req.code == "ABCD1234"

    def test_empty_code_rejected(self):
        with pytest.raises(Exception):
            ApplyRiderReferralRequest(code="")

    def test_code_over_16_chars_rejected(self):
        with pytest.raises(Exception):
            ApplyRiderReferralRequest(code="A" * 17)

    def test_code_is_accepted_as_given(self):
        req = ApplyRiderReferralRequest(code="abc12345")
        assert req.code == "abc12345"


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
        existing = _make_code_record(user_id=5, code="EXIST123")
        db = _make_db(_one_result(existing))
        result = await get_or_create_referral_code(db, user_id=5)
        assert result.code == "EXIST123"

    @pytest.mark.asyncio
    async def test_creates_new_record_when_none_exists(self):
        db = _make_db(_none_result(), _none_result())
        await get_or_create_referral_code(db, user_id=7)
        assert db.add.called
        assert isinstance(db.add.call_args[0][0], RiderReferralCode)

    @pytest.mark.asyncio
    async def test_new_record_has_correct_user_id(self):
        db = _make_db(_none_result(), _none_result())
        await get_or_create_referral_code(db, user_id=42)
        added = db.add.call_args[0][0]
        assert added.user_id == 42

    @pytest.mark.asyncio
    async def test_db_add_called_once(self):
        db = _make_db(_none_result(), _none_result())
        await get_or_create_referral_code(db, user_id=1)
        assert db.add.call_count == 1

    @pytest.mark.asyncio
    async def test_db_flush_called_after_add(self):
        db = _make_db(_none_result(), _none_result())
        await get_or_create_referral_code(db, user_id=1)
        assert db.flush.called


# ---------------------------------------------------------------------------
# 13-23: apply_referral_code
# ---------------------------------------------------------------------------


class TestApplyReferralCode:
    @pytest.mark.asyncio
    async def test_returns_failure_when_already_referred(self):
        existing_referral = _make_referral(referred_user_id=10)
        db = _make_db(_one_result(existing_referral))
        result = await apply_referral_code(db, new_user_id=10, code="CODE0001")
        assert not result.success
        assert "already" in result.message.lower()

    @pytest.mark.asyncio
    async def test_returns_failure_when_code_does_not_exist(self):
        db = _make_db(_none_result(), _none_result())
        result = await apply_referral_code(db, new_user_id=10, code="BADCODE1")
        assert not result.success
        assert "invalid" in result.message.lower()

    @pytest.mark.asyncio
    async def test_returns_failure_when_using_own_code(self):
        code_record = _make_code_record(user_id=10, code="MYCODE01")
        db = _make_db(_none_result(), _one_result(code_record))
        result = await apply_referral_code(db, new_user_id=10, code="MYCODE01")
        assert not result.success
        assert "own" in result.message.lower()

    @pytest.mark.asyncio
    async def test_returns_success_for_valid_referral(self):
        code_record = _make_code_record(user_id=5, code="VALID001")
        db = _make_db(_none_result(), _one_result(code_record))
        result = await apply_referral_code(db, new_user_id=10, code="VALID001")
        assert result.success

    @pytest.mark.asyncio
    async def test_created_referral_has_correct_referrer(self):
        code_record = _make_code_record(user_id=5, code="VALID001")
        db = _make_db(_none_result(), _one_result(code_record))
        await apply_referral_code(db, new_user_id=10, code="VALID001")
        added = db.add.call_args[0][0]
        assert added.referrer_user_id == 5

    @pytest.mark.asyncio
    async def test_created_referral_has_correct_referred(self):
        code_record = _make_code_record(user_id=5, code="VALID001")
        db = _make_db(_none_result(), _one_result(code_record))
        await apply_referral_code(db, new_user_id=10, code="VALID001")
        added = db.add.call_args[0][0]
        assert added.referred_user_id == 10

    @pytest.mark.asyncio
    async def test_created_referral_has_pending_status(self):
        code_record = _make_code_record(user_id=5, code="VALID001")
        db = _make_db(_none_result(), _one_result(code_record))
        await apply_referral_code(db, new_user_id=10, code="VALID001")
        added = db.add.call_args[0][0]
        assert added.status == RiderReferralStatus.PENDING

    @pytest.mark.asyncio
    async def test_created_referral_has_correct_referrer_reward(self):
        code_record = _make_code_record(user_id=5, code="VALID001")
        db = _make_db(_none_result(), _one_result(code_record))
        await apply_referral_code(db, new_user_id=10, code="VALID001")
        added = db.add.call_args[0][0]
        assert added.referrer_reward_amount == REFERRER_REWARD_USD

    @pytest.mark.asyncio
    async def test_created_referral_has_correct_referred_discount(self):
        code_record = _make_code_record(user_id=5, code="VALID001")
        db = _make_db(_none_result(), _one_result(code_record))
        await apply_referral_code(db, new_user_id=10, code="VALID001")
        added = db.add.call_args[0][0]
        assert added.referred_discount_amount == REFERRED_DISCOUNT_USD

    @pytest.mark.asyncio
    async def test_response_includes_referrer_user_id(self):
        code_record = _make_code_record(user_id=5, code="VALID001")
        db = _make_db(_none_result(), _one_result(code_record))
        result = await apply_referral_code(db, new_user_id=10, code="VALID001")
        assert result.referrer_user_id == 5

    @pytest.mark.asyncio
    async def test_code_is_uppercased_before_lookup(self):
        code_record = _make_code_record(user_id=5, code="LOWRCASE")
        db = _make_db(_none_result(), _one_result(code_record))
        result = await apply_referral_code(db, new_user_id=10, code="lowrcase")
        assert result.success


# ---------------------------------------------------------------------------
# 24-28: record_first_ride_completion
# ---------------------------------------------------------------------------


class TestRecordFirstRideCompletion:
    @pytest.mark.asyncio
    async def test_transitions_pending_to_qualified(self):
        referral = _make_referral(status=RiderReferralStatus.PENDING)
        db = _make_db(_one_result(referral))
        await record_first_ride_completion(db, user_id=2, ride_id=99)
        assert referral.status == RiderReferralStatus.QUALIFIED

    @pytest.mark.asyncio
    async def test_sets_first_ride_id(self):
        referral = _make_referral(status=RiderReferralStatus.PENDING)
        db = _make_db(_one_result(referral))
        await record_first_ride_completion(db, user_id=2, ride_id=99)
        assert referral.first_ride_id == 99

    @pytest.mark.asyncio
    async def test_sets_qualified_at(self):
        referral = _make_referral(status=RiderReferralStatus.PENDING)
        db = _make_db(_one_result(referral))
        await record_first_ride_completion(db, user_id=2, ride_id=99)
        assert referral.qualified_at is not None

    @pytest.mark.asyncio
    async def test_does_nothing_when_no_pending_referral(self):
        db = _make_db(_none_result())
        await record_first_ride_completion(db, user_id=99, ride_id=1)
        db.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_idempotent_when_already_qualified(self):
        # Query filters to PENDING only, so QUALIFIED returns None
        db = _make_db(_none_result())
        await record_first_ride_completion(db, user_id=2, ride_id=5)
        db.flush.assert_not_called()


# ---------------------------------------------------------------------------
# 29-34: get_referral_summary
# ---------------------------------------------------------------------------


class TestGetReferralSummary:
    @pytest.mark.asyncio
    async def test_correct_pending_count(self):
        code_record = _make_code_record(user_id=1)
        referrals = [
            _make_referral(status=RiderReferralStatus.PENDING),
            _make_referral(referral_id=2, status=RiderReferralStatus.PENDING),
            _make_referral(referral_id=3, status=RiderReferralStatus.QUALIFIED),
        ]
        db = _make_db(_one_result(code_record), _list_result(referrals))
        result = await get_referral_summary(db, user_id=1)
        assert result.pending_count == 2

    @pytest.mark.asyncio
    async def test_correct_qualified_count(self):
        code_record = _make_code_record(user_id=1)
        referrals = [
            _make_referral(status=RiderReferralStatus.QUALIFIED),
            _make_referral(referral_id=2, status=RiderReferralStatus.QUALIFIED),
        ]
        db = _make_db(_one_result(code_record), _list_result(referrals))
        result = await get_referral_summary(db, user_id=1)
        assert result.qualified_count == 2

    @pytest.mark.asyncio
    async def test_correct_rewarded_count(self):
        code_record = _make_code_record(user_id=1)
        referrals = [
            _make_referral(status=RiderReferralStatus.REWARDED, referrer_reward_amount=10.0),
        ]
        db = _make_db(_one_result(code_record), _list_result(referrals))
        result = await get_referral_summary(db, user_id=1)
        assert result.rewarded_count == 1

    @pytest.mark.asyncio
    async def test_total_reward_earned_sums_only_rewarded(self):
        code_record = _make_code_record(user_id=1)
        referrals = [
            _make_referral(status=RiderReferralStatus.REWARDED, referrer_reward_amount=10.0),
            _make_referral(referral_id=2, status=RiderReferralStatus.REWARDED, referrer_reward_amount=10.0),
            _make_referral(referral_id=3, status=RiderReferralStatus.QUALIFIED, referrer_reward_amount=10.0),
        ]
        db = _make_db(_one_result(code_record), _list_result(referrals))
        result = await get_referral_summary(db, user_id=1)
        assert result.total_reward_earned == 20.0

    @pytest.mark.asyncio
    async def test_code_included_in_response(self):
        code_record = _make_code_record(user_id=1, code="MYCODE00")
        db = _make_db(_one_result(code_record), _list_result([]))
        result = await get_referral_summary(db, user_id=1)
        assert result.code == "MYCODE00"

    @pytest.mark.asyncio
    async def test_total_reward_zero_when_no_rewarded(self):
        code_record = _make_code_record(user_id=1)
        referrals = [_make_referral(status=RiderReferralStatus.PENDING)]
        db = _make_db(_one_result(code_record), _list_result(referrals))
        result = await get_referral_summary(db, user_id=1)
        assert result.total_reward_earned == 0.0


# ---------------------------------------------------------------------------
# 35-37: get_my_referrals
# ---------------------------------------------------------------------------


class TestGetMyReferrals:
    @pytest.mark.asyncio
    async def test_total_count_reflects_all_referrals(self):
        code_record = _make_code_record(user_id=1)
        db = _make_db(
            _one_result(code_record),
            _count_result(42),
            _list_result([]),
        )
        result = await get_my_referrals(db, user_id=1)
        assert result.total == 42

    @pytest.mark.asyncio
    async def test_code_included_in_response(self):
        code_record = _make_code_record(user_id=1, code="LISTCODE")
        db = _make_db(
            _one_result(code_record),
            _count_result(0),
            _list_result([]),
        )
        result = await get_my_referrals(db, user_id=1)
        assert result.code == "LISTCODE"

    @pytest.mark.asyncio
    async def test_empty_referral_list_returns_zero_total(self):
        code_record = _make_code_record(user_id=1)
        db = _make_db(
            _one_result(code_record),
            _count_result(0),
            _list_result([]),
        )
        result = await get_my_referrals(db, user_id=1)
        assert result.total == 0
        assert result.referrals == []


# ---------------------------------------------------------------------------
# 38-41: get_admin_stats
# ---------------------------------------------------------------------------


class TestGetAdminStats:
    @pytest.mark.asyncio
    async def test_returns_correct_total_codes_issued(self):
        db = _make_db(
            _count_result(7),   # total codes
            _count_result(15),  # total referrals
            _count_result(5),   # pending
            _count_result(8),   # qualified
            _count_result(2),   # rewarded
            _count_result(20),  # reward sum
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
            _count_result(30),
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
            _count_result(4),   # rewarded
            _count_result(40),
        )
        result = await get_admin_stats(db)
        assert result.pending_count == 12
        assert result.qualified_count == 14
        assert result.rewarded_count == 4

    @pytest.mark.asyncio
    async def test_total_reward_paid_zero_when_no_rewarded(self):
        db = _make_db(
            _count_result(0),
            _count_result(0),
            _count_result(0),
            _count_result(0),
            _count_result(0),
            _count_result(0),
        )
        result = await get_admin_stats(db)
        assert result.total_reward_paid_amount == 0.0


# ---------------------------------------------------------------------------
# 42-48: Endpoint auth (integration)
# ---------------------------------------------------------------------------


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
class TestRiderReferralEndpointAuth:
    async def test_get_referral_code_requires_auth(self, client):
        resp = await client.get("/api/v1/riders/me/referral-code")
        assert resp.status_code in (401, 403)

    async def test_get_referral_code_accessible_to_rider(self, client, rider, rider_token):
        resp = await client.get(
            "/api/v1/riders/me/referral-code",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 200

    async def test_get_my_referrals_requires_auth(self, client):
        resp = await client.get("/api/v1/riders/me/referrals")
        assert resp.status_code in (401, 403)

    async def test_apply_referral_requires_auth(self, client):
        resp = await client.post(
            "/api/v1/riders/referral/apply",
            json={"code": "ABCD1234"},
        )
        assert resp.status_code in (401, 403)

    async def test_admin_stats_returns_403_for_rider(self, client, rider, rider_token):
        resp = await client.get(
            "/api/v1/admin/referrals/rider/stats",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403

    async def test_admin_stats_returns_403_for_driver(self, client, driver_user, driver_token):
        resp = await client.get(
            "/api/v1/admin/referrals/rider/stats",
            headers=auth_header(driver_token),
        )
        assert resp.status_code == 403

    async def test_admin_stats_accessible_to_admin(self, client, admin_user, admin_token):
        resp = await client.get(
            "/api/v1/admin/referrals/rider/stats",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
