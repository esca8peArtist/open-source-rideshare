"""Tests for the driver-to-driver referral program.

Endpoints:
  GET  /drivers/me/referral-code
  POST /drivers/me/referral-code
  POST /drivers/me/referral/apply
  GET  /drivers/me/referral/bonuses
  GET  /admin/driver-referrals

Coverage
--------
Schemas
  - DriverReferralStatus: PENDING, AWARDED, PAID
  - DriverReferralCodeResponse: all fields, defaults
  - DriverReferralApplyRequest: valid code, empty code rejected
  - DriverReferralBonusEntry: all fields
  - AdminDriverReferralEntry: all fields
  - AdminDriverReferralListResponse: total + referrals list

Service: create_or_get_driver_referral_code
  - generates unique code starting with 'D'
  - idempotent: second call returns same code
  - raises ValueError if no driver profile exists

Service: apply_driver_referral_code
  - creates DriverReferral record with PENDING status
  - raises ValueError on unknown code
  - raises ValueError on self-referral
  - raises ValueError if referee already applied a code

Service: check_and_award_driver_referral_bonus
  - returns None when no PENDING referral exists for driver
  - returns None when trip count below milestone
  - awards bonus (AWARDED status) when milestone reached exactly
  - awards bonus when trip count exceeds milestone
  - idempotent: second call (already AWARDED) returns None

Service: get_driver_referral_stats
  - total_referrals counts all statuses
  - pending_bonus sums AWARDED only
  - total_paid sums PAID only

Service: get_driver_referral_bonuses
  - returns empty list for driver with no referrals
  - returns list newest-first

Service: mark_driver_referral_bonuses_paid
  - marks all AWARDED bonuses PAID with payout_id
  - returns correct total
  - skips already-PAID records

Router: GET /drivers/me/referral-code
  - 200 returns code and stats

Router: POST /drivers/me/referral-code
  - 200 idempotent; second call same code

Router: POST /drivers/me/referral/apply
  - 200 on success
  - 400 on unknown code
  - 400 on self-referral
  - 409 on duplicate apply

Router: GET /drivers/me/referral/bonuses
  - 200 returns list

Router: GET /admin/driver-referrals
  - 200 returns list with total

End-to-end: generate code → apply → milestone reached → bonus AWARDED
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError

from app.models.driver_referral import DriverReferralStatus, generate_driver_referral_code
from app.schemas.driver_referral import (
    AdminDriverReferralEntry,
    AdminDriverReferralListResponse,
    DriverReferralApplyRequest,
    DriverReferralBonusEntry,
    DriverReferralCodeResponse,
)
from app.services.driver_referral import (
    DRIVER_REFERRAL_BONUS,
    DRIVER_REFERRAL_MILESTONE,
    apply_driver_referral_code,
    check_and_award_driver_referral_bonus,
    create_or_get_driver_referral_code,
    get_driver_referral_bonuses,
    get_driver_referral_stats,
    mark_driver_referral_bonuses_paid,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _mock_db() -> AsyncMock:
    return AsyncMock()


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestDriverReferralStatusEnum:
    def test_values(self):
        assert DriverReferralStatus.PENDING == "pending"
        assert DriverReferralStatus.AWARDED == "awarded"
        assert DriverReferralStatus.PAID == "paid"


class TestDriverReferralCodeResponse:
    def test_all_fields(self):
        r = DriverReferralCodeResponse(
            referral_code="DABC12345",
            total_referrals=3,
            pending_bonus=50.0,
            total_paid=100.0,
        )
        assert r.referral_code == "DABC12345"
        assert r.total_referrals == 3
        assert r.pending_bonus == 50.0
        assert r.total_paid == 100.0

    def test_null_code_allowed(self):
        r = DriverReferralCodeResponse(
            referral_code=None,
            total_referrals=0,
            pending_bonus=0.0,
            total_paid=0.0,
        )
        assert r.referral_code is None


class TestDriverReferralApplyRequest:
    def test_valid(self):
        req = DriverReferralApplyRequest(code="DABC1234")
        assert req.code == "DABC1234"

    def test_empty_code_rejected(self):
        with pytest.raises(ValidationError):
            DriverReferralApplyRequest(code="")


class TestDriverReferralBonusEntry:
    def test_from_attributes(self):
        ref = MagicMock()
        ref.id = 1
        ref.referee_driver_id = 42
        ref.milestone_rides = 10
        ref.bonus_amount = 50.0
        ref.status = DriverReferralStatus.AWARDED
        ref.awarded_at = _utc_now()
        ref.paid_at = None
        ref.created_at = _utc_now()
        entry = DriverReferralBonusEntry.model_validate(ref)
        assert entry.bonus_amount == 50.0
        assert entry.status == DriverReferralStatus.AWARDED


class TestAdminDriverReferralListResponse:
    def test_structure(self):
        resp = AdminDriverReferralListResponse(total=0, referrals=[])
        assert resp.total == 0
        assert resp.referrals == []


# ---------------------------------------------------------------------------
# Service: generate_driver_referral_code helper
# ---------------------------------------------------------------------------


class TestGenerateDriverReferralCode:
    def test_starts_with_D(self):
        code = generate_driver_referral_code()
        assert code.startswith("D")

    def test_uppercase(self):
        code = generate_driver_referral_code()
        assert code == code.upper()

    def test_length(self):
        code = generate_driver_referral_code()
        assert 5 <= len(code) <= 20


# ---------------------------------------------------------------------------
# Service: create_or_get_driver_referral_code
# ---------------------------------------------------------------------------


class TestCreateOrGetDriverReferralCode:
    @pytest.mark.asyncio
    async def test_generates_code_when_none(self):
        db = _mock_db()
        profile = MagicMock()
        profile.user_id = 1
        profile.driver_referral_code = None

        result_with_profile = MagicMock()
        result_with_profile.scalar_one_or_none = MagicMock(return_value=profile)
        result_no_collision = MagicMock()
        result_no_collision.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(side_effect=[result_with_profile, result_no_collision])

        code = await create_or_get_driver_referral_code(1, db)
        assert isinstance(code, str)
        assert code.startswith("D")
        assert profile.driver_referral_code == code

    @pytest.mark.asyncio
    async def test_returns_existing_code(self):
        db = _mock_db()
        profile = MagicMock()
        profile.user_id = 1
        profile.driver_referral_code = "DEXISTING"

        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=profile)
        db.execute = AsyncMock(return_value=result)

        code = await create_or_get_driver_referral_code(1, db)
        assert code == "DEXISTING"

    @pytest.mark.asyncio
    async def test_raises_if_no_profile(self):
        db = _mock_db()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(ValueError, match="No driver profile"):
            await create_or_get_driver_referral_code(99, db)


# ---------------------------------------------------------------------------
# Service: apply_driver_referral_code
# ---------------------------------------------------------------------------


class TestApplyDriverReferralCode:
    @pytest.mark.asyncio
    async def test_creates_referral_record(self):
        db = _mock_db()
        referrer_profile = MagicMock()
        referrer_profile.user_id = 10

        result_referrer = MagicMock()
        result_referrer.scalar_one_or_none = MagicMock(return_value=referrer_profile)
        result_existing = MagicMock()
        result_existing.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(side_effect=[result_referrer, result_existing])

        referral = await apply_driver_referral_code("DABC1234", referee_user_id=20, db=db)

        db.add.assert_called_once()
        assert referral.referrer_driver_id == 10
        assert referral.referee_driver_id == 20
        assert referral.milestone_rides == DRIVER_REFERRAL_MILESTONE
        assert referral.bonus_amount == DRIVER_REFERRAL_BONUS

    @pytest.mark.asyncio
    async def test_raises_on_unknown_code(self):
        db = _mock_db()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(ValueError, match="not found"):
            await apply_driver_referral_code("DNOTEXIST", referee_user_id=20, db=db)

    @pytest.mark.asyncio
    async def test_raises_on_self_referral(self):
        db = _mock_db()
        referrer_profile = MagicMock()
        referrer_profile.user_id = 20  # same as referee

        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=referrer_profile)
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(ValueError, match="own referral"):
            await apply_driver_referral_code("DABC1234", referee_user_id=20, db=db)

    @pytest.mark.asyncio
    async def test_raises_if_already_applied(self):
        db = _mock_db()
        referrer_profile = MagicMock()
        referrer_profile.user_id = 10

        existing_referral = MagicMock()
        result_referrer = MagicMock()
        result_referrer.scalar_one_or_none = MagicMock(return_value=referrer_profile)
        result_existing = MagicMock()
        result_existing.scalar_one_or_none = MagicMock(return_value=existing_referral)
        db.execute = AsyncMock(side_effect=[result_referrer, result_existing])

        with pytest.raises(ValueError, match="already applied"):
            await apply_driver_referral_code("DABC1234", referee_user_id=20, db=db)

    @pytest.mark.asyncio
    async def test_code_normalized_to_uppercase(self):
        db = _mock_db()
        referrer_profile = MagicMock()
        referrer_profile.user_id = 10

        result_referrer = MagicMock()
        result_referrer.scalar_one_or_none = MagicMock(return_value=referrer_profile)
        result_existing = MagicMock()
        result_existing.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(side_effect=[result_referrer, result_existing])

        referral = await apply_driver_referral_code("dabc1234", referee_user_id=20, db=db)
        assert referral.referrer_driver_id == 10


# ---------------------------------------------------------------------------
# Service: check_and_award_driver_referral_bonus
# ---------------------------------------------------------------------------


class TestCheckAndAwardDriverReferralBonus:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_referral(self):
        db = _mock_db()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=result)

        outcome = await check_and_award_driver_referral_bonus(42, 10, db)
        assert outcome is None

    @pytest.mark.asyncio
    async def test_returns_none_below_milestone(self):
        db = _mock_db()
        referral = MagicMock()
        referral.milestone_rides = 10
        referral.status = DriverReferralStatus.PENDING

        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=referral)
        db.execute = AsyncMock(return_value=result)

        outcome = await check_and_award_driver_referral_bonus(42, 9, db)
        assert outcome is None
        assert referral.status == DriverReferralStatus.PENDING

    @pytest.mark.asyncio
    async def test_awards_at_exact_milestone(self):
        db = _mock_db()
        referral = MagicMock()
        referral.milestone_rides = 10
        referral.bonus_amount = 50.0
        referral.referrer_driver_id = 1
        referral.status = DriverReferralStatus.PENDING

        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=referral)
        db.execute = AsyncMock(return_value=result)

        outcome = await check_and_award_driver_referral_bonus(42, 10, db)
        assert outcome is referral
        assert referral.status == DriverReferralStatus.AWARDED
        assert referral.awarded_at is not None

    @pytest.mark.asyncio
    async def test_awards_above_milestone(self):
        db = _mock_db()
        referral = MagicMock()
        referral.milestone_rides = 10
        referral.status = DriverReferralStatus.PENDING
        referral.bonus_amount = 50.0
        referral.referrer_driver_id = 1

        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=referral)
        db.execute = AsyncMock(return_value=result)

        outcome = await check_and_award_driver_referral_bonus(42, 15, db)
        assert outcome is referral
        assert referral.status == DriverReferralStatus.AWARDED

    @pytest.mark.asyncio
    async def test_idempotent_already_awarded_returns_none(self):
        """Once AWARDED the query filters for PENDING so returns None."""
        db = _mock_db()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=result)

        outcome = await check_and_award_driver_referral_bonus(42, 15, db)
        assert outcome is None


# ---------------------------------------------------------------------------
# Service: get_driver_referral_stats
# ---------------------------------------------------------------------------


class TestGetDriverReferralStats:
    @pytest.mark.asyncio
    async def test_counts_all_statuses(self):
        db = _mock_db()
        r1 = MagicMock(status=DriverReferralStatus.PENDING, bonus_amount=50.0)
        r2 = MagicMock(status=DriverReferralStatus.AWARDED, bonus_amount=50.0)
        r3 = MagicMock(status=DriverReferralStatus.PAID, bonus_amount=50.0)
        result = MagicMock()
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[r1, r2, r3])))
        db.execute = AsyncMock(return_value=result)

        stats = await get_driver_referral_stats(1, db)
        assert stats["total_referrals"] == 3
        assert stats["pending_bonus"] == 50.0  # only AWARDED
        assert stats["total_paid"] == 50.0     # only PAID

    @pytest.mark.asyncio
    async def test_empty_for_new_driver(self):
        db = _mock_db()
        result = MagicMock()
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        db.execute = AsyncMock(return_value=result)

        stats = await get_driver_referral_stats(1, db)
        assert stats["total_referrals"] == 0
        assert stats["pending_bonus"] == 0.0
        assert stats["total_paid"] == 0.0


# ---------------------------------------------------------------------------
# Service: get_driver_referral_bonuses
# ---------------------------------------------------------------------------


class TestGetDriverReferralBonuses:
    @pytest.mark.asyncio
    async def test_returns_empty_list(self):
        db = _mock_db()
        result = MagicMock()
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        db.execute = AsyncMock(return_value=result)

        bonuses = await get_driver_referral_bonuses(1, db)
        assert bonuses == []

    @pytest.mark.asyncio
    async def test_returns_referrals(self):
        db = _mock_db()
        ref = MagicMock()
        result = MagicMock()
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[ref])))
        db.execute = AsyncMock(return_value=result)

        bonuses = await get_driver_referral_bonuses(1, db)
        assert len(bonuses) == 1


# ---------------------------------------------------------------------------
# Service: mark_driver_referral_bonuses_paid
# ---------------------------------------------------------------------------


class TestMarkDriverReferralBonusesPaid:
    @pytest.mark.asyncio
    async def test_marks_awarded_as_paid(self):
        db = _mock_db()
        ref = MagicMock()
        ref.status = DriverReferralStatus.AWARDED
        ref.bonus_amount = 50.0

        result = MagicMock()
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[ref])))
        db.execute = AsyncMock(return_value=result)

        total = await mark_driver_referral_bonuses_paid(1, payout_id=99, db=db)
        assert total == 50.0
        assert ref.status == DriverReferralStatus.PAID
        assert ref.paid_on_payout_id == 99
        assert ref.paid_at is not None

    @pytest.mark.asyncio
    async def test_returns_zero_when_none(self):
        db = _mock_db()
        result = MagicMock()
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        db.execute = AsyncMock(return_value=result)

        total = await mark_driver_referral_bonuses_paid(1, payout_id=99, db=db)
        assert total == 0.0

    @pytest.mark.asyncio
    async def test_sums_multiple_bonuses(self):
        db = _mock_db()
        ref1 = MagicMock(status=DriverReferralStatus.AWARDED, bonus_amount=50.0)
        ref2 = MagicMock(status=DriverReferralStatus.AWARDED, bonus_amount=50.0)

        result = MagicMock()
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[ref1, ref2])))
        db.execute = AsyncMock(return_value=result)

        total = await mark_driver_referral_bonuses_paid(1, payout_id=99, db=db)
        assert total == 100.0


# ---------------------------------------------------------------------------
# Router tests (handler-direct, dependency-injected)
# ---------------------------------------------------------------------------


class TestRouterGetReferralCode:
    @pytest.mark.asyncio
    async def test_200_returns_code_and_stats(self):
        from app.api.v1.driver_referral import get_driver_referral_code

        driver = MagicMock()
        driver.id = 1
        db = AsyncMock()

        with (
            patch(
                "app.api.v1.driver_referral.create_or_get_driver_referral_code",
                new=AsyncMock(return_value="DABC12345"),
            ),
            patch(
                "app.api.v1.driver_referral.get_driver_referral_stats",
                new=AsyncMock(return_value={"total_referrals": 0, "pending_bonus": 0.0, "total_paid": 0.0}),
            ),
        ):
            response = await get_driver_referral_code(current_user=driver, db=db)

        assert response.referral_code == "DABC12345"
        assert response.total_referrals == 0


class TestRouterPostReferralCode:
    @pytest.mark.asyncio
    async def test_200_idempotent(self):
        from app.api.v1.driver_referral import generate_driver_referral_code_endpoint

        driver = MagicMock()
        driver.id = 1
        db = AsyncMock()

        with (
            patch(
                "app.api.v1.driver_referral.create_or_get_driver_referral_code",
                new=AsyncMock(return_value="DABC12345"),
            ),
            patch(
                "app.api.v1.driver_referral.get_driver_referral_stats",
                new=AsyncMock(return_value={"total_referrals": 1, "pending_bonus": 0.0, "total_paid": 0.0}),
            ),
        ):
            response = await generate_driver_referral_code_endpoint(current_user=driver, db=db)

        assert response.referral_code == "DABC12345"
        assert response.total_referrals == 1

    @pytest.mark.asyncio
    async def test_400_on_service_error(self):
        from fastapi import HTTPException
        from app.api.v1.driver_referral import generate_driver_referral_code_endpoint

        driver = MagicMock()
        driver.id = 99
        db = AsyncMock()

        with patch(
            "app.api.v1.driver_referral.create_or_get_driver_referral_code",
            new=AsyncMock(side_effect=ValueError("No driver profile")),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await generate_driver_referral_code_endpoint(current_user=driver, db=db)

        assert exc_info.value.status_code == 400


class TestRouterApplyReferralCode:
    @pytest.mark.asyncio
    async def test_200_on_success(self):
        from app.api.v1.driver_referral import apply_referral_code

        driver = MagicMock()
        driver.id = 20
        db = AsyncMock()
        req = DriverReferralApplyRequest(code="DABC1234")

        fake_referral = MagicMock()
        fake_referral.referrer_driver_id = 10
        fake_referral.milestone_rides = 10
        fake_referral.bonus_amount = 50.0

        with patch(
            "app.api.v1.driver_referral.apply_driver_referral_code",
            new=AsyncMock(return_value=fake_referral),
        ):
            response = await apply_referral_code(req=req, current_user=driver, db=db)

        assert response["status"] == "applied"
        assert response["referrer_driver_id"] == 10

    @pytest.mark.asyncio
    async def test_400_on_unknown_code(self):
        from fastapi import HTTPException
        from app.api.v1.driver_referral import apply_referral_code

        driver = MagicMock()
        driver.id = 20
        db = AsyncMock()
        req = DriverReferralApplyRequest(code="DNOTEXIST")

        with patch(
            "app.api.v1.driver_referral.apply_driver_referral_code",
            new=AsyncMock(side_effect=ValueError("Referral code not found")),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await apply_referral_code(req=req, current_user=driver, db=db)

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_409_on_duplicate_apply(self):
        from fastapi import HTTPException
        from app.api.v1.driver_referral import apply_referral_code

        driver = MagicMock()
        driver.id = 20
        db = AsyncMock()
        req = DriverReferralApplyRequest(code="DABC1234")

        with patch(
            "app.api.v1.driver_referral.apply_driver_referral_code",
            new=AsyncMock(side_effect=ValueError("You have already applied a driver referral code")),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await apply_referral_code(req=req, current_user=driver, db=db)

        assert exc_info.value.status_code == 409


class TestRouterGetBonuses:
    @pytest.mark.asyncio
    async def test_200_returns_list(self):
        from app.api.v1.driver_referral import get_my_driver_referral_bonuses

        driver = MagicMock()
        driver.id = 1
        db = AsyncMock()

        with patch(
            "app.api.v1.driver_referral.get_driver_referral_bonuses",
            new=AsyncMock(return_value=[]),
        ):
            response = await get_my_driver_referral_bonuses(current_user=driver, db=db)

        assert response == []


class TestRouterAdminListReferrals:
    @pytest.mark.asyncio
    async def test_200_returns_list_with_total(self):
        from app.api.v1.driver_referral import admin_list_driver_referrals

        db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar = MagicMock(return_value=0)
        list_result = MagicMock()
        list_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        db.execute = AsyncMock(side_effect=[count_result, list_result])

        response = await admin_list_driver_referrals(db=db, limit=50, offset=0)
        assert response.total == 0
        assert response.referrals == []


# ---------------------------------------------------------------------------
# End-to-end: generate → apply → milestone → awarded
# ---------------------------------------------------------------------------


class TestDriverReferralEndToEnd:
    @pytest.mark.asyncio
    async def test_full_referral_flow(self):
        """Simulate: referrer gets code, referee applies, milestone hit → AWARDED."""
        db = _mock_db()

        # Step 1: referrer generates code
        profile = MagicMock()
        profile.user_id = 10
        profile.driver_referral_code = None
        result_profile = MagicMock()
        result_profile.scalar_one_or_none = MagicMock(return_value=profile)
        result_no_collision = MagicMock()
        result_no_collision.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(side_effect=[result_profile, result_no_collision])

        code = await create_or_get_driver_referral_code(10, db)
        assert code.startswith("D")
        profile.driver_referral_code = code  # simulate DB save

        # Step 2: referee applies code
        result_referrer = MagicMock()
        result_referrer.scalar_one_or_none = MagicMock(return_value=profile)
        result_existing = MagicMock()
        result_existing.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(side_effect=[result_referrer, result_existing])

        referral = await apply_driver_referral_code(code, referee_user_id=20, db=db)
        assert referral.referrer_driver_id == 10
        assert referral.referee_driver_id == 20
        assert referral.status == DriverReferralStatus.PENDING

        # Step 3: referee completes milestone rides → bonus awarded
        referral.milestone_rides = 10
        result_pending = MagicMock()
        result_pending.scalar_one_or_none = MagicMock(return_value=referral)
        db.execute = AsyncMock(return_value=result_pending)

        outcome = await check_and_award_driver_referral_bonus(20, 10, db)
        assert outcome is referral
        assert referral.status == DriverReferralStatus.AWARDED
        assert referral.awarded_at is not None
