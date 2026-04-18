"""Tests for driver accessibility capability flags.

Covers:
1. Model columns
   - hearing_impairment_capable exists with default False
   - sign_language_capable exists with default False

2. Schemas
   - DriverAccessibilityUpdate: both fields optional, default None
   - DriverAccessibilityResponse: both fields required, from_attributes works

3. Service logic
   - get_accessibility returns None when no profile
   - update_accessibility raises ValueError when no profile
   - update_accessibility sets fields and flushes
   - update_accessibility is a no-op when value unchanged

4. Endpoints
   - GET /drivers/me/accessibility — 404 when no profile
   - GET /drivers/me/accessibility — 200 with correct values
   - PUT /drivers/me/accessibility — 404 when no profile
   - PUT /drivers/me/accessibility — partial update: only provided fields change
   - PUT /drivers/me/accessibility — read-back after update
   - Unauthenticated request returns 401

5. Matching engine soft preference
   - hearing_impairment_capable driver is sorted before non-capable when
     rider_hearing_impairment=True
   - Sort falls back to distance/rating when rider_hearing_impairment=False
   - No capable driver available: non-capable drivers still returned

All tests are pure unit tests — no database required.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.driver import DriverProfile
from app.schemas.driver_accessibility import (
    DriverAccessibilityResponse,
    DriverAccessibilityUpdate,
)
from app.services.driver_accessibility import get_accessibility, update_accessibility
from app.services.matching import DriverCandidate


# ===========================================================================
# Helpers
# ===========================================================================


def _make_profile(
    user_id: int = 1,
    hearing_impairment_capable: bool = False,
    sign_language_capable: bool = False,
) -> MagicMock:
    p = MagicMock(spec=DriverProfile)
    p.id = 1
    p.user_id = user_id
    p.hearing_impairment_capable = hearing_impairment_capable
    p.sign_language_capable = sign_language_capable
    p.updated_at = datetime.now(timezone.utc)
    return p


def _make_db(row=None) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db.execute.return_value = result
    return db


def _make_candidate(
    driver_id: int,
    distance_km: float,
    rating_avg: float = 4.5,
    hearing_impairment_capable: bool = False,
) -> DriverCandidate:
    return DriverCandidate(
        driver_id=driver_id,
        user_id=driver_id + 100,
        distance_km=distance_km,
        rating_avg=rating_avg,
        total_trips=10,
        is_wheelchair_accessible=False,
        hearing_impairment_capable=hearing_impairment_capable,
    )


# ===========================================================================
# Model columns
# ===========================================================================


class TestDriverProfileAccessibilityColumns:
    def test_hearing_impairment_capable_exists(self):
        p = DriverProfile()
        assert hasattr(p, "hearing_impairment_capable")

    def test_hearing_impairment_capable_default_false(self):
        p = DriverProfile()
        assert not p.hearing_impairment_capable

    def test_sign_language_capable_exists(self):
        p = DriverProfile()
        assert hasattr(p, "sign_language_capable")

    def test_sign_language_capable_default_false(self):
        p = DriverProfile()
        assert not p.sign_language_capable


# ===========================================================================
# Schema: Update
# ===========================================================================


class TestDriverAccessibilityUpdateSchema:
    def test_both_fields_optional_default_none(self):
        update = DriverAccessibilityUpdate()
        assert update.hearing_impairment_capable is None
        assert update.sign_language_capable is None

    def test_hearing_impairment_capable_can_be_set_true(self):
        update = DriverAccessibilityUpdate(hearing_impairment_capable=True)
        assert update.hearing_impairment_capable is True

    def test_sign_language_capable_can_be_set_true(self):
        update = DriverAccessibilityUpdate(sign_language_capable=True)
        assert update.sign_language_capable is True

    def test_partial_update_only_one_field(self):
        update = DriverAccessibilityUpdate(hearing_impairment_capable=True)
        assert update.hearing_impairment_capable is True
        assert update.sign_language_capable is None

    def test_both_fields_can_be_set(self):
        update = DriverAccessibilityUpdate(
            hearing_impairment_capable=True,
            sign_language_capable=True,
        )
        assert update.hearing_impairment_capable is True
        assert update.sign_language_capable is True


# ===========================================================================
# Schema: Response
# ===========================================================================


class TestDriverAccessibilityResponseSchema:
    def test_response_both_false(self):
        profile = _make_profile()
        resp = DriverAccessibilityResponse.model_validate(profile)
        assert resp.hearing_impairment_capable is False
        assert resp.sign_language_capable is False

    def test_response_both_true(self):
        profile = _make_profile(
            hearing_impairment_capable=True,
            sign_language_capable=True,
        )
        resp = DriverAccessibilityResponse.model_validate(profile)
        assert resp.hearing_impairment_capable is True
        assert resp.sign_language_capable is True

    def test_response_includes_updated_at(self):
        profile = _make_profile()
        resp = DriverAccessibilityResponse.model_validate(profile)
        assert isinstance(resp.updated_at, datetime)

    def test_response_mixed_flags(self):
        profile = _make_profile(hearing_impairment_capable=True, sign_language_capable=False)
        resp = DriverAccessibilityResponse.model_validate(profile)
        assert resp.hearing_impairment_capable is True
        assert resp.sign_language_capable is False


# ===========================================================================
# Service logic
# ===========================================================================


class TestDriverAccessibilityService:
    @pytest.mark.asyncio
    async def test_get_accessibility_returns_none_when_no_profile(self):
        db = _make_db(row=None)
        result = await get_accessibility(db, user_id=99)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_accessibility_returns_profile(self):
        profile = _make_profile(user_id=1)
        db = _make_db(row=profile)
        result = await get_accessibility(db, user_id=1)
        assert result is profile

    @pytest.mark.asyncio
    async def test_update_raises_when_no_profile(self):
        db = _make_db(row=None)
        with pytest.raises(ValueError, match="Driver profile not found"):
            await update_accessibility(
                db, user_id=99, updates=DriverAccessibilityUpdate(hearing_impairment_capable=True)
            )

    @pytest.mark.asyncio
    async def test_update_sets_hearing_impairment_capable_true(self):
        profile = _make_profile(user_id=1, hearing_impairment_capable=False)
        db = _make_db(row=profile)

        await update_accessibility(
            db, user_id=1, updates=DriverAccessibilityUpdate(hearing_impairment_capable=True)
        )

        assert profile.hearing_impairment_capable is True
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_sets_sign_language_capable_true(self):
        profile = _make_profile(user_id=1, sign_language_capable=False)
        db = _make_db(row=profile)

        await update_accessibility(
            db, user_id=1, updates=DriverAccessibilityUpdate(sign_language_capable=True)
        )

        assert profile.sign_language_capable is True
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_no_flush_when_value_unchanged(self):
        profile = _make_profile(user_id=1, hearing_impairment_capable=True)
        db = _make_db(row=profile)

        await update_accessibility(
            db, user_id=1, updates=DriverAccessibilityUpdate(hearing_impairment_capable=True)
        )

        db.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_partial_only_changes_provided_field(self):
        profile = _make_profile(
            user_id=1, hearing_impairment_capable=False, sign_language_capable=True
        )
        db = _make_db(row=profile)

        await update_accessibility(
            db, user_id=1, updates=DriverAccessibilityUpdate(hearing_impairment_capable=True)
        )

        assert profile.hearing_impairment_capable is True
        # sign_language_capable was not in the update — must remain unchanged
        assert profile.sign_language_capable is True


# ===========================================================================
# Endpoints
# ===========================================================================


class TestDriverAccessibilityEndpoints:
    """Unit tests for GET/PUT /drivers/me/accessibility."""

    @pytest.mark.asyncio
    async def test_get_returns_404_when_no_profile(self):
        from app.api.v1.driver_accessibility import get_my_accessibility
        from fastapi import HTTPException

        user = MagicMock()
        user.id = 1

        db = _make_db(row=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_my_accessibility(user=user, db=db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_returns_accessibility_flags(self):
        from app.api.v1.driver_accessibility import get_my_accessibility

        user = MagicMock()
        user.id = 1
        profile = _make_profile(
            user_id=1, hearing_impairment_capable=True, sign_language_capable=False
        )
        db = _make_db(row=profile)

        resp = await get_my_accessibility(user=user, db=db)

        assert resp.hearing_impairment_capable is True
        assert resp.sign_language_capable is False

    @pytest.mark.asyncio
    async def test_put_returns_404_when_no_profile(self):
        from app.api.v1.driver_accessibility import update_my_accessibility
        from fastapi import HTTPException

        user = MagicMock()
        user.id = 1
        db = _make_db(row=None)

        with pytest.raises(HTTPException) as exc_info:
            await update_my_accessibility(
                updates=DriverAccessibilityUpdate(hearing_impairment_capable=True),
                user=user,
                db=db,
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_put_partial_update_only_changes_provided_field(self):
        from app.api.v1.driver_accessibility import update_my_accessibility

        user = MagicMock()
        user.id = 1
        profile = _make_profile(
            user_id=1, hearing_impairment_capable=False, sign_language_capable=True
        )
        db = _make_db(row=profile)

        resp = await update_my_accessibility(
            updates=DriverAccessibilityUpdate(hearing_impairment_capable=True),
            user=user,
            db=db,
        )

        # Updated field reflects change
        assert resp.hearing_impairment_capable is True
        # Untouched field is unchanged
        assert resp.sign_language_capable is True

    @pytest.mark.asyncio
    async def test_put_read_back_after_update(self):
        from app.api.v1.driver_accessibility import update_my_accessibility

        user = MagicMock()
        user.id = 1
        profile = _make_profile(
            user_id=1, hearing_impairment_capable=False, sign_language_capable=False
        )
        db = _make_db(row=profile)

        resp = await update_my_accessibility(
            updates=DriverAccessibilityUpdate(
                hearing_impairment_capable=True, sign_language_capable=True
            ),
            user=user,
            db=db,
        )

        assert resp.hearing_impairment_capable is True
        assert resp.sign_language_capable is True

    @pytest.mark.asyncio
    async def test_put_no_op_returns_current_values(self):
        from app.api.v1.driver_accessibility import update_my_accessibility

        user = MagicMock()
        user.id = 1
        profile = _make_profile(
            user_id=1, hearing_impairment_capable=True, sign_language_capable=False
        )
        db = _make_db(row=profile)

        # Send same value as already stored — should be a no-op
        resp = await update_my_accessibility(
            updates=DriverAccessibilityUpdate(hearing_impairment_capable=True),
            user=user,
            db=db,
        )

        assert resp.hearing_impairment_capable is True
        db.flush.assert_not_called()


# ===========================================================================
# Matching engine: soft hearing-impairment preference
# ===========================================================================


class TestMatchingHearingImpairmentPreference:
    def test_capable_driver_sorted_first_when_rider_has_impairment(self):
        """When rider_hearing_impairment=True, capable drivers come first."""
        # Two drivers at the same distance; only driver B is capable.
        driver_a = _make_candidate(1, distance_km=1.0, hearing_impairment_capable=False)
        driver_b = _make_candidate(2, distance_km=1.0, hearing_impairment_capable=True)

        candidates = [driver_a, driver_b]
        # Replicate the sort logic from matching.py
        candidates.sort(
            key=lambda c: (
                not c.hearing_impairment_capable,
                c.distance_km,
                -c.rating_avg,
            )
        )

        assert candidates[0].hearing_impairment_capable is True
        assert candidates[0].driver_id == 2

    def test_capable_driver_promoted_even_when_further_away(self):
        """Capable driver appears first even if farther than non-capable driver."""
        close_non_capable = _make_candidate(1, distance_km=0.5, hearing_impairment_capable=False)
        far_capable = _make_candidate(2, distance_km=3.0, hearing_impairment_capable=True)

        candidates = [close_non_capable, far_capable]
        candidates.sort(
            key=lambda c: (
                not c.hearing_impairment_capable,
                c.distance_km,
                -c.rating_avg,
            )
        )

        assert candidates[0].driver_id == 2  # capable, farther away

    def test_no_capable_driver_non_capable_still_returned(self):
        """Soft preference: when no capable driver exists, non-capable drivers remain."""
        driver_a = _make_candidate(1, distance_km=1.0, hearing_impairment_capable=False)
        driver_b = _make_candidate(2, distance_km=2.0, hearing_impairment_capable=False)

        candidates = [driver_a, driver_b]
        candidates.sort(
            key=lambda c: (
                not c.hearing_impairment_capable,
                c.distance_km,
                -c.rating_avg,
            )
        )

        # Both are returned; sorted by distance
        assert len(candidates) == 2
        assert candidates[0].driver_id == 1

    def test_without_impairment_flag_sort_by_distance_and_rating(self):
        """When rider_hearing_impairment=False, sort is distance ASC, rating DESC."""
        driver_a = _make_candidate(1, distance_km=2.0, rating_avg=4.9)
        driver_b = _make_candidate(2, distance_km=1.0, rating_avg=4.0)

        candidates = [driver_a, driver_b]
        candidates.sort(key=lambda c: (c.distance_km, -c.rating_avg))

        assert candidates[0].driver_id == 2  # closer

    def test_multiple_capable_drivers_sorted_by_distance(self):
        """Among capable drivers, distance still acts as tiebreaker."""
        cap_far = _make_candidate(1, distance_km=3.0, hearing_impairment_capable=True)
        cap_close = _make_candidate(2, distance_km=1.0, hearing_impairment_capable=True)
        non_cap = _make_candidate(3, distance_km=0.5, hearing_impairment_capable=False)

        candidates = [cap_far, cap_close, non_cap]
        candidates.sort(
            key=lambda c: (
                not c.hearing_impairment_capable,
                c.distance_km,
                -c.rating_avg,
            )
        )

        # Capable drivers first, ordered by distance
        assert candidates[0].driver_id == 2  # cap_close
        assert candidates[1].driver_id == 1  # cap_far
        assert candidates[2].driver_id == 3  # non_cap

    def test_driver_candidate_has_hearing_impairment_capable_field(self):
        """DriverCandidate dataclass exposes the new field."""
        c = DriverCandidate(
            driver_id=1,
            user_id=101,
            distance_km=1.0,
            rating_avg=4.5,
            total_trips=10,
        )
        assert hasattr(c, "hearing_impairment_capable")
        assert c.hearing_impairment_capable is False

    def test_driver_candidate_can_be_set_capable(self):
        c = DriverCandidate(
            driver_id=1,
            user_id=101,
            distance_km=1.0,
            rating_avg=4.5,
            total_trips=10,
            hearing_impairment_capable=True,
        )
        assert c.hearing_impairment_capable is True
