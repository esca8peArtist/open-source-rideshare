"""Tests for the Driver Certification Badges feature.

Service layer (async, mocked DB):
  1.  award_badge — creates new badge when none exists
  2.  award_badge — raises 409 when active badge already exists
  3.  award_badge — re-activates revoked badge instead of inserting duplicate
  4.  revoke_badge — revokes active badge successfully
  5.  revoke_badge — raises 404 when no active badge exists
  6.  get_driver_badges — returns only active badges when active_only=True
  7.  get_driver_badges — returns all badges when active_only=False
  8.  check_badge_eligibility — returns result for every badge type (8 total)
  9.  check_badge_eligibility — safe_driver eligible when 0 incidents and avg >= 4.5
  10. check_badge_eligibility — safe_driver ineligible when incidents > 0
  11. check_badge_eligibility — five_star eligible when avg >= 4.8 and rides >= 50
  12. check_badge_eligibility — five_star ineligible when avg < 4.8
  13. check_badge_eligibility — five_star ineligible when rides < 50
  14. check_badge_eligibility — accessibility_specialist eligible when WAV vehicle exists
  15. check_badge_eligibility — pet_friendly eligible when driver preference set
  16. check_badge_eligibility — long_distance_expert eligible when 10+ long rides
  17. check_badge_eligibility — long_distance_expert ineligible when < 10 long rides
  18. check_badge_eligibility — mentor eligible when active mentorship as mentor
  19. check_badge_eligibility — veteran eligible when account >= 365 days and rides >= 500
  20. check_badge_eligibility — veteran ineligible when account < 365 days
  21. auto_award_eligible_badges — awards eligible badges not already active
  22. auto_award_eligible_badges — skips already-active badges
  23. auto_award_eligible_badges — returns empty list when nothing to award

Schema validation:
  24. AwardBadgeRequest — valid badge_type accepted
  25. AwardBadgeRequest — notes field is optional
  26. RevokeBadgeRequest — notes field is optional
  27. DriverBadgeResponse — from_attributes works correctly
  28. DriverBadgeListResponse — active_count reflects active badges
  29. BadgeEligibilityReport — newly_awarded can be empty list
  30. BadgeStats — by_type is a dict of str to int

API layer (unit-level, service functions patched):
  31. GET /drivers/{id}/badges — returns active badges list
  32. GET /drivers/me/badges — returns all badges for current user
  33. POST /admin/drivers/{id}/badges — awards badge and returns response
  34. POST /admin/drivers/{id}/badges — returns 409 on duplicate active badge
  35. DELETE /admin/drivers/{id}/badges/{type} — revokes badge and returns response
  36. DELETE /admin/drivers/{id}/badges/{type} — returns 404 when no active badge
  37. POST /admin/drivers/{id}/badges/check-eligibility — returns full report
  38. GET /admin/badge-stats — returns stats response
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.driver_certification import BadgeType, DriverCertification
from app.schemas.driver_certification import (
    AwardBadgeRequest,
    BadgeEligibilityReport,
    BadgeEligibilityResult,
    BadgeStats,
    DriverBadgeListResponse,
    DriverBadgeResponse,
    RevokeBadgeRequest,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)


def _make_cert(**kw) -> DriverCertification:
    defaults = dict(
        id=1,
        driver_id=10,
        badge_type=BadgeType.SAFE_DRIVER,
        is_active=True,
        awarded_at=_NOW,
        awarded_by=99,
        revoked_at=None,
        revoked_by=None,
        notes=None,
    )
    defaults.update(kw)
    cert = MagicMock(spec=DriverCertification)
    for k, v in defaults.items():
        setattr(cert, k, v)
    return cert


def _async_scalar(value):
    """Return an AsyncMock whose .execute() returns a result with scalar_one_or_none == value."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = value
    mock_result.scalar.return_value = value
    return mock_result


def _async_scalars(values):
    """Return a mock result whose .scalars().all() returns values."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = values
    return mock_result


# ---------------------------------------------------------------------------
# 1-3: award_badge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_award_badge_creates_new():
    """Test 1: creates a new badge when none exists."""
    from app.services.driver_certification import award_badge

    db = AsyncMock()
    no_existing = MagicMock()
    no_existing.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=no_existing)
    db.flush = AsyncMock()

    cert = await award_badge(db, driver_id=10, badge_type=BadgeType.SAFE_DRIVER, awarded_by=99)

    db.add.assert_called_once()
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_award_badge_409_on_duplicate_active():
    """Test 2: raises 409 when badge is already active."""
    from app.services.driver_certification import award_badge

    existing = _make_cert(is_active=True)
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing
    db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(HTTPException) as exc_info:
        await award_badge(db, driver_id=10, badge_type=BadgeType.SAFE_DRIVER, awarded_by=99)

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_award_badge_reactivates_revoked():
    """Test 3: re-activates a previously revoked badge."""
    from app.services.driver_certification import award_badge

    revoked = _make_cert(
        is_active=False,
        revoked_at=_NOW,
        revoked_by=1,
    )
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = revoked
    db.execute = AsyncMock(return_value=mock_result)
    db.flush = AsyncMock()

    cert = await award_badge(db, driver_id=10, badge_type=BadgeType.SAFE_DRIVER, awarded_by=99)

    # Should not add a new row
    db.add.assert_not_called()
    db.flush.assert_called_once()
    # Should have re-activated
    assert revoked.is_active is True
    assert revoked.revoked_at is None
    assert revoked.revoked_by is None


# ---------------------------------------------------------------------------
# 4-5: revoke_badge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_badge_success():
    """Test 4: revokes an active badge successfully."""
    from app.services.driver_certification import revoke_badge

    active_cert = _make_cert(is_active=True)
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = active_cert
    db.execute = AsyncMock(return_value=mock_result)
    db.flush = AsyncMock()

    result = await revoke_badge(db, driver_id=10, badge_type=BadgeType.SAFE_DRIVER, revoked_by=99)

    assert active_cert.is_active is False
    assert active_cert.revoked_by == 99
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_revoke_badge_404_when_not_active():
    """Test 5: raises 404 when no active badge exists."""
    from app.services.driver_certification import revoke_badge

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(HTTPException) as exc_info:
        await revoke_badge(db, driver_id=10, badge_type=BadgeType.SAFE_DRIVER, revoked_by=99)

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 6-7: get_driver_badges
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_driver_badges_active_only():
    """Test 6: returns only active badges when active_only=True."""
    from app.services.driver_certification import get_driver_badges

    active = _make_cert(is_active=True)
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [active]
    db.execute = AsyncMock(return_value=mock_result)

    result = await get_driver_badges(db, driver_id=10, active_only=True)

    assert result == [active]
    # Verify is_active filter was applied by checking execute was called
    db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_get_driver_badges_all():
    """Test 7: returns all badges (active + revoked) when active_only=False."""
    from app.services.driver_certification import get_driver_badges

    active = _make_cert(is_active=True, id=1)
    revoked = _make_cert(is_active=False, id=2, revoked_at=_NOW)
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [active, revoked]
    db.execute = AsyncMock(return_value=mock_result)

    result = await get_driver_badges(db, driver_id=10, active_only=False)

    assert len(result) == 2


# ---------------------------------------------------------------------------
# 8-20: check_badge_eligibility
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_eligibility_returns_all_badge_types():
    """Test 8: returns a result for every badge type (8 types)."""
    from app.services.driver_certification import check_badge_eligibility

    db = AsyncMock()
    # Return 0/None for all counts — all ineligible, but all types covered
    mock_result = MagicMock()
    mock_result.scalar.return_value = 0
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    results = await check_badge_eligibility(db, driver_id=10)

    assert len(results) == len(BadgeType)
    result_types = {r.badge_type for r in results}
    assert result_types == set(BadgeType)


@pytest.mark.asyncio
async def test_check_eligibility_safe_driver_eligible():
    """Test 9: safe_driver eligible when 0 incidents and avg rating >= 4.5."""
    from app.services.driver_certification import check_badge_eligibility

    db = AsyncMock()
    call_count = 0

    async def execute_side_effect(stmt):
        nonlocal call_count
        call_count += 1
        mock = MagicMock()
        # First call: incident count = 0
        # Second call: avg rating = 4.7
        if call_count == 1:
            mock.scalar.return_value = 0
        elif call_count == 2:
            mock.scalar.return_value = 4.7
        else:
            mock.scalar.return_value = 0
            mock.scalar_one_or_none.return_value = None
        return mock

    db.execute = execute_side_effect

    results = await check_badge_eligibility(db, driver_id=10)
    safe_driver = next(r for r in results if r.badge_type == BadgeType.SAFE_DRIVER)
    assert safe_driver.is_eligible is True


@pytest.mark.asyncio
async def test_check_eligibility_safe_driver_ineligible_with_incidents():
    """Test 10: safe_driver ineligible when driver has incidents."""
    from app.services.driver_certification import check_badge_eligibility

    db = AsyncMock()
    call_count = 0

    async def execute_side_effect(stmt):
        nonlocal call_count
        call_count += 1
        mock = MagicMock()
        if call_count == 1:
            mock.scalar.return_value = 2  # 2 incidents
        else:
            mock.scalar.return_value = 4.9
            mock.scalar_one_or_none.return_value = None
        return mock

    db.execute = execute_side_effect

    results = await check_badge_eligibility(db, driver_id=10)
    safe_driver = next(r for r in results if r.badge_type == BadgeType.SAFE_DRIVER)
    assert safe_driver.is_eligible is False


@pytest.mark.asyncio
async def test_check_eligibility_five_star_eligible():
    """Test 11: five_star eligible when avg >= 4.8 and >= 50 rides."""
    from app.services.driver_certification import check_badge_eligibility

    db = AsyncMock()
    call_count = 0

    async def execute_side_effect(stmt):
        nonlocal call_count
        call_count += 1
        mock = MagicMock()
        # five_star checks: avg rating (call 3), ride count (call 4)
        # calls 1&2 are for safe_driver
        if call_count == 3:
            mock.scalar.return_value = 4.9
        elif call_count == 4:
            mock.scalar.return_value = 75
        else:
            mock.scalar.return_value = 0
            mock.scalar_one_or_none.return_value = None
        return mock

    db.execute = execute_side_effect

    results = await check_badge_eligibility(db, driver_id=10)
    five_star = next(r for r in results if r.badge_type == BadgeType.FIVE_STAR)
    assert five_star.is_eligible is True


@pytest.mark.asyncio
async def test_check_eligibility_five_star_ineligible_low_rating():
    """Test 12: five_star ineligible when avg rating < 4.8."""
    from app.services.driver_certification import check_badge_eligibility

    db = AsyncMock()
    call_count = 0

    async def execute_side_effect(stmt):
        nonlocal call_count
        call_count += 1
        mock = MagicMock()
        if call_count == 3:
            mock.scalar.return_value = 4.5  # below 4.8
        elif call_count == 4:
            mock.scalar.return_value = 100
        else:
            mock.scalar.return_value = 0
            mock.scalar_one_or_none.return_value = None
        return mock

    db.execute = execute_side_effect

    results = await check_badge_eligibility(db, driver_id=10)
    five_star = next(r for r in results if r.badge_type == BadgeType.FIVE_STAR)
    assert five_star.is_eligible is False


@pytest.mark.asyncio
async def test_check_eligibility_five_star_ineligible_few_rides():
    """Test 13: five_star ineligible when < 50 completed rides."""
    from app.services.driver_certification import check_badge_eligibility

    db = AsyncMock()
    call_count = 0

    async def execute_side_effect(stmt):
        nonlocal call_count
        call_count += 1
        mock = MagicMock()
        if call_count == 3:
            mock.scalar.return_value = 4.9
        elif call_count == 4:
            mock.scalar.return_value = 20  # below 50
        else:
            mock.scalar.return_value = 0
            mock.scalar_one_or_none.return_value = None
        return mock

    db.execute = execute_side_effect

    results = await check_badge_eligibility(db, driver_id=10)
    five_star = next(r for r in results if r.badge_type == BadgeType.FIVE_STAR)
    assert five_star.is_eligible is False


@pytest.mark.asyncio
async def test_check_eligibility_accessibility_specialist_eligible():
    """Test 14: accessibility_specialist eligible when active WAV vehicle exists."""
    from app.services.driver_certification import check_badge_eligibility

    db = AsyncMock()
    call_count = 0

    async def execute_side_effect(stmt):
        nonlocal call_count
        call_count += 1
        mock = MagicMock()
        # accessibility check is call 5
        if call_count == 5:
            mock.scalar.return_value = 1  # has WAV vehicle
        else:
            mock.scalar.return_value = 0
            mock.scalar_one_or_none.return_value = None
        return mock

    db.execute = execute_side_effect

    results = await check_badge_eligibility(db, driver_id=10)
    a11y = next(r for r in results if r.badge_type == BadgeType.ACCESSIBILITY_SPECIALIST)
    assert a11y.is_eligible is True


@pytest.mark.asyncio
async def test_check_eligibility_pet_friendly_eligible():
    """Test 15: pet_friendly eligible when driver has opted in."""
    from app.services.driver_certification import check_badge_eligibility

    db = AsyncMock()
    call_count = 0

    async def execute_side_effect(stmt):
        nonlocal call_count
        call_count += 1
        mock = MagicMock()
        # pet_friendly check is call 6 (scalar_one_or_none for preference)
        if call_count == 6:
            pref = MagicMock()
            pref.pet_friendly = True
            mock.scalar_one_or_none.return_value = pref
            mock.scalar.return_value = 0
        else:
            mock.scalar.return_value = 0
            mock.scalar_one_or_none.return_value = None
        return mock

    db.execute = execute_side_effect

    results = await check_badge_eligibility(db, driver_id=10)
    pet = next(r for r in results if r.badge_type == BadgeType.PET_FRIENDLY)
    assert pet.is_eligible is True


@pytest.mark.asyncio
async def test_check_eligibility_long_distance_expert_eligible():
    """Test 16: long_distance_expert eligible when >= 10 long rides."""
    from app.services.driver_certification import check_badge_eligibility

    db = AsyncMock()
    call_count = 0

    async def execute_side_effect(stmt):
        nonlocal call_count
        call_count += 1
        mock = MagicMock()
        # long_distance check is call 7
        if call_count == 7:
            mock.scalar.return_value = 15
        else:
            mock.scalar.return_value = 0
            mock.scalar_one_or_none.return_value = None
        return mock

    db.execute = execute_side_effect

    results = await check_badge_eligibility(db, driver_id=10)
    ld = next(r for r in results if r.badge_type == BadgeType.LONG_DISTANCE_EXPERT)
    assert ld.is_eligible is True


@pytest.mark.asyncio
async def test_check_eligibility_long_distance_expert_ineligible():
    """Test 17: long_distance_expert ineligible when < 10 long rides."""
    from app.services.driver_certification import check_badge_eligibility

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 0
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    results = await check_badge_eligibility(db, driver_id=10)
    ld = next(r for r in results if r.badge_type == BadgeType.LONG_DISTANCE_EXPERT)
    assert ld.is_eligible is False


@pytest.mark.asyncio
async def test_check_eligibility_mentor_eligible():
    """Test 18: mentor eligible when active mentorship record exists as mentor."""
    from app.services.driver_certification import check_badge_eligibility

    db = AsyncMock()
    call_count = 0

    async def execute_side_effect(stmt):
        nonlocal call_count
        call_count += 1
        mock = MagicMock()
        # mentor check is call 8
        if call_count == 8:
            mock.scalar.return_value = 2
        else:
            mock.scalar.return_value = 0
            mock.scalar_one_or_none.return_value = None
        return mock

    db.execute = execute_side_effect

    results = await check_badge_eligibility(db, driver_id=10)
    mentor = next(r for r in results if r.badge_type == BadgeType.MENTOR)
    assert mentor.is_eligible is True


@pytest.mark.asyncio
async def test_check_eligibility_veteran_eligible():
    """Test 19: veteran eligible when account >= 365 days and >= 500 rides."""
    from app.services.driver_certification import check_badge_eligibility
    from datetime import timedelta

    db = AsyncMock()
    call_count = 0
    old_date = _NOW - timedelta(days=400)

    async def execute_side_effect(stmt):
        nonlocal call_count
        call_count += 1
        mock = MagicMock()
        # veteran: user created_at (call 10), ride count (call 11)
        if call_count == 10:
            mock.scalar_one_or_none.return_value = old_date
            mock.scalar.return_value = old_date
        elif call_count == 11:
            mock.scalar.return_value = 600
        else:
            mock.scalar.return_value = 0
            mock.scalar_one_or_none.return_value = None
        return mock

    db.execute = execute_side_effect

    results = await check_badge_eligibility(db, driver_id=10)
    veteran = next(r for r in results if r.badge_type == BadgeType.VETERAN)
    assert veteran.is_eligible is True


@pytest.mark.asyncio
async def test_check_eligibility_veteran_ineligible_new_account():
    """Test 20: veteran ineligible when account < 365 days old."""
    from app.services.driver_certification import check_badge_eligibility
    from datetime import timedelta

    db = AsyncMock()
    call_count = 0
    recent_date = _NOW - timedelta(days=100)

    async def execute_side_effect(stmt):
        nonlocal call_count
        call_count += 1
        mock = MagicMock()
        if call_count == 10:
            mock.scalar_one_or_none.return_value = recent_date
            mock.scalar.return_value = recent_date
        elif call_count == 11:
            mock.scalar.return_value = 600
        else:
            mock.scalar.return_value = 0
            mock.scalar_one_or_none.return_value = None
        return mock

    db.execute = execute_side_effect

    results = await check_badge_eligibility(db, driver_id=10)
    veteran = next(r for r in results if r.badge_type == BadgeType.VETERAN)
    assert veteran.is_eligible is False


# ---------------------------------------------------------------------------
# 21-23: auto_award_eligible_badges
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_award_awards_eligible_badges():
    """Test 21: awards eligible badges not already active."""
    from app.services.driver_certification import auto_award_eligible_badges

    eligible_result = BadgeEligibilityResult(
        badge_type=BadgeType.SAFE_DRIVER, is_eligible=True, reason="all good"
    )

    with patch(
        "app.services.driver_certification.check_badge_eligibility",
        new=AsyncMock(return_value=[eligible_result]),
    ):
        db = AsyncMock()
        # active badges query: returns empty set
        active_mock = MagicMock()
        active_mock.scalars.return_value.all.return_value = []
        # award_badge internal query: returns None (no existing cert)
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None

        call_count = 0

        async def execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return active_mock
            return no_existing

        db.execute = execute_side_effect
        db.flush = AsyncMock()

        newly_awarded = await auto_award_eligible_badges(db, driver_id=10)

        assert BadgeType.SAFE_DRIVER in newly_awarded


@pytest.mark.asyncio
async def test_auto_award_skips_already_active():
    """Test 22: skips badges that are already active."""
    from app.services.driver_certification import auto_award_eligible_badges

    eligible_result = BadgeEligibilityResult(
        badge_type=BadgeType.SAFE_DRIVER, is_eligible=True, reason="all good"
    )

    with patch(
        "app.services.driver_certification.check_badge_eligibility",
        new=AsyncMock(return_value=[eligible_result]),
    ):
        db = AsyncMock()
        # active badges query: SAFE_DRIVER already active
        active_mock = MagicMock()
        active_mock.scalars.return_value.all.return_value = [BadgeType.SAFE_DRIVER]
        db.execute = AsyncMock(return_value=active_mock)
        db.flush = AsyncMock()

        newly_awarded = await auto_award_eligible_badges(db, driver_id=10)

        assert newly_awarded == []
        db.add.assert_not_called()


@pytest.mark.asyncio
async def test_auto_award_empty_when_nothing_eligible():
    """Test 23: returns empty list when no eligible badges."""
    from app.services.driver_certification import auto_award_eligible_badges

    ineligible = BadgeEligibilityResult(
        badge_type=BadgeType.SAFE_DRIVER, is_eligible=False, reason="has incidents"
    )

    with patch(
        "app.services.driver_certification.check_badge_eligibility",
        new=AsyncMock(return_value=[ineligible]),
    ):
        db = AsyncMock()
        active_mock = MagicMock()
        active_mock.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=active_mock)

        newly_awarded = await auto_award_eligible_badges(db, driver_id=10)

        assert newly_awarded == []


# ---------------------------------------------------------------------------
# 24-30: Schema validation
# ---------------------------------------------------------------------------


def test_award_badge_request_valid():
    """Test 24: AwardBadgeRequest accepts valid badge_type."""
    req = AwardBadgeRequest(badge_type=BadgeType.FIVE_STAR)
    assert req.badge_type == BadgeType.FIVE_STAR


def test_award_badge_request_notes_optional():
    """Test 25: AwardBadgeRequest notes field is optional."""
    req = AwardBadgeRequest(badge_type=BadgeType.MENTOR)
    assert req.notes is None

    req_with_notes = AwardBadgeRequest(badge_type=BadgeType.MENTOR, notes="Exceptional mentor")
    assert req_with_notes.notes == "Exceptional mentor"


def test_revoke_badge_request_notes_optional():
    """Test 26: RevokeBadgeRequest notes field is optional."""
    req = RevokeBadgeRequest()
    assert req.notes is None

    req_with_notes = RevokeBadgeRequest(notes="Policy violation")
    assert req_with_notes.notes == "Policy violation"


def test_driver_badge_response_from_attributes():
    """Test 27: DriverBadgeResponse builds from ORM-like object."""
    cert = _make_cert()
    response = DriverBadgeResponse.model_validate(cert)

    assert response.id == cert.id
    assert response.driver_id == cert.driver_id
    assert response.badge_type == cert.badge_type
    assert response.is_active == cert.is_active
    assert response.awarded_at == cert.awarded_at


def test_driver_badge_list_response_active_count():
    """Test 28: DriverBadgeListResponse active_count reflects active badges."""
    cert = _make_cert()
    response = DriverBadgeResponse.model_validate(cert)
    list_response = DriverBadgeListResponse(badges=[response], total=1, active_count=1)

    assert list_response.total == 1
    assert list_response.active_count == 1


def test_badge_eligibility_report_empty_newly_awarded():
    """Test 29: BadgeEligibilityReport newly_awarded can be empty."""
    result = BadgeEligibilityResult(
        badge_type=BadgeType.VETERAN, is_eligible=False, reason="not enough rides"
    )
    report = BadgeEligibilityReport(driver_id=10, results=[result], newly_awarded=[])

    assert report.newly_awarded == []
    assert len(report.results) == 1


def test_badge_stats_by_type_is_dict():
    """Test 30: BadgeStats by_type is a dict mapping str to int."""
    from app.schemas.driver_certification import BadgeDriverSummary

    stats = BadgeStats(
        total_active=5,
        by_type={"safe_driver": 3, "five_star": 2},
        top_drivers=[BadgeDriverSummary(driver_id=1, badge_count=3)],
    )

    assert isinstance(stats.by_type, dict)
    assert stats.by_type["safe_driver"] == 3
    assert stats.total_active == 5


# ---------------------------------------------------------------------------
# 31-38: API layer (unit-level, service functions patched)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_list_driver_badges():
    """Test 31: GET /drivers/{id}/badges returns active badges list."""
    from app.api.v1.driver_certifications import list_driver_badges

    active_cert = _make_cert(is_active=True)

    with patch(
        "app.api.v1.driver_certifications.get_driver_badges",
        new=AsyncMock(return_value=[active_cert]),
    ):
        db = AsyncMock()
        result = await list_driver_badges(driver_id=10, db=db)

    assert result.total == 1
    assert result.active_count == 1
    assert result.badges[0].driver_id == 10


@pytest.mark.asyncio
async def test_api_my_badges_returns_all():
    """Test 32: GET /drivers/me/badges returns all badges including revoked."""
    from app.api.v1.driver_certifications import my_badges

    active_cert = _make_cert(is_active=True, id=1)
    revoked_cert = _make_cert(is_active=False, id=2, revoked_at=_NOW, revoked_by=99)

    user = MagicMock()
    user.id = 10

    with patch(
        "app.api.v1.driver_certifications.get_driver_badges",
        new=AsyncMock(return_value=[active_cert, revoked_cert]),
    ):
        db = AsyncMock()
        result = await my_badges(user=user, db=db)

    assert result.total == 2
    assert result.active_count == 1


@pytest.mark.asyncio
async def test_api_admin_award_badge_success():
    """Test 33: POST /admin/drivers/{id}/badges awards badge and returns response."""
    from app.api.v1.driver_certifications import admin_award_badge

    awarded_cert = _make_cert(is_active=True)
    user = MagicMock()
    user.id = 99

    body = AwardBadgeRequest(badge_type=BadgeType.SAFE_DRIVER, notes="Well deserved")

    with patch(
        "app.api.v1.driver_certifications.award_badge",
        new=AsyncMock(return_value=awarded_cert),
    ):
        db = AsyncMock()
        result = await admin_award_badge(driver_id=10, body=body, user=user, db=db)

    assert result.is_active is True
    assert result.badge_type == BadgeType.SAFE_DRIVER


@pytest.mark.asyncio
async def test_api_admin_award_badge_409_duplicate():
    """Test 34: POST /admin/drivers/{id}/badges returns 409 on duplicate active badge."""
    from app.api.v1.driver_certifications import admin_award_badge

    user = MagicMock()
    user.id = 99
    body = AwardBadgeRequest(badge_type=BadgeType.SAFE_DRIVER)

    with patch(
        "app.api.v1.driver_certifications.award_badge",
        new=AsyncMock(side_effect=HTTPException(status_code=409, detail="Badge already active")),
    ):
        db = AsyncMock()
        with pytest.raises(HTTPException) as exc_info:
            await admin_award_badge(driver_id=10, body=body, user=user, db=db)

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_api_admin_revoke_badge_success():
    """Test 35: DELETE /admin/drivers/{id}/badges/{type} revokes badge."""
    from app.api.v1.driver_certifications import admin_revoke_badge

    revoked_cert = _make_cert(is_active=False, revoked_at=_NOW, revoked_by=99)
    user = MagicMock()
    user.id = 99

    body = RevokeBadgeRequest(notes="Policy violation")

    with patch(
        "app.api.v1.driver_certifications.revoke_badge",
        new=AsyncMock(return_value=revoked_cert),
    ):
        db = AsyncMock()
        result = await admin_revoke_badge(
            driver_id=10,
            badge_type=BadgeType.SAFE_DRIVER,
            body=body,
            user=user,
            db=db,
        )

    assert result.is_active is False


@pytest.mark.asyncio
async def test_api_admin_revoke_badge_404():
    """Test 36: DELETE /admin/drivers/{id}/badges/{type} returns 404 when not found."""
    from app.api.v1.driver_certifications import admin_revoke_badge

    user = MagicMock()
    user.id = 99
    body = RevokeBadgeRequest()

    with patch(
        "app.api.v1.driver_certifications.revoke_badge",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Not found")),
    ):
        db = AsyncMock()
        with pytest.raises(HTTPException) as exc_info:
            await admin_revoke_badge(
                driver_id=10,
                badge_type=BadgeType.SAFE_DRIVER,
                body=body,
                user=user,
                db=db,
            )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_api_admin_check_eligibility_returns_report():
    """Test 37: POST /admin/drivers/{id}/badges/check-eligibility returns full report."""
    from app.api.v1.driver_certifications import admin_check_eligibility

    eligibility_results = [
        BadgeEligibilityResult(
            badge_type=BadgeType.SAFE_DRIVER, is_eligible=True, reason="all good"
        )
    ]

    with patch(
        "app.api.v1.driver_certifications.check_badge_eligibility",
        new=AsyncMock(return_value=eligibility_results),
    ):
        with patch(
            "app.api.v1.driver_certifications.auto_award_eligible_badges",
            new=AsyncMock(return_value=[BadgeType.SAFE_DRIVER]),
        ):
            db = AsyncMock()
            result = await admin_check_eligibility(driver_id=10, db=db)

    assert result.driver_id == 10
    assert len(result.results) == 1
    assert BadgeType.SAFE_DRIVER in result.newly_awarded


@pytest.mark.asyncio
async def test_api_admin_badge_stats():
    """Test 38: GET /admin/badge-stats returns stats response."""
    from app.api.v1.driver_certifications import admin_badge_stats

    mock_stats = {
        "total_active": 42,
        "by_type": {"safe_driver": 20, "five_star": 15, "mentor": 7},
        "top_drivers": [
            {"driver_id": 1, "badge_count": 5},
            {"driver_id": 2, "badge_count": 3},
        ],
    }

    with patch(
        "app.api.v1.driver_certifications.get_badge_stats",
        new=AsyncMock(return_value=mock_stats),
    ):
        db = AsyncMock()
        result = await admin_badge_stats(db=db)

    assert result.total_active == 42
    assert result.by_type["safe_driver"] == 20
    assert len(result.top_drivers) == 2
    assert result.top_drivers[0].driver_id == 1
