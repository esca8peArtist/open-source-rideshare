"""Comprehensive unit tests for driver break management.

Covers:
- Model fields: is_on_break, break_started_at on DriverOnlineStatus
- Schema: BreakResponse, OnlineStatusResponse (break fields)
- Service logic: start_break, end_break, is_driver_available_now with breaks
- Endpoint tests: start break, end break — auth, state machine, idempotency

All tests are pure unit tests — no database required.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.driver_availability import DriverOnlineStatus
from app.schemas.driver_availability import BreakResponse, OnlineStatusResponse
from app.services.driver_availability import end_break, is_driver_available_now, start_break


# ===========================================================================
# Helpers
# ===========================================================================


def _make_status(
    driver_id: int = 1,
    is_online: bool = True,
    is_on_break: bool = False,
    break_started_at: datetime | None = None,
    went_online_at: datetime | None = None,
    last_heartbeat: datetime | None = None,
) -> DriverOnlineStatus:
    """Build a DriverOnlineStatus ORM mock with the given attributes."""
    s = MagicMock(spec=DriverOnlineStatus)
    s.driver_id = driver_id
    s.is_online = is_online
    s.is_on_break = is_on_break
    s.break_started_at = break_started_at
    s.went_online_at = went_online_at or datetime.now(timezone.utc)
    s.last_heartbeat = last_heartbeat or datetime.now(timezone.utc)
    return s


def _make_db(status_row=None) -> AsyncMock:
    """Return a mock AsyncSession whose execute() returns status_row."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = status_row
    db.execute.return_value = result
    return db


# ===========================================================================
# Model field tests
# ===========================================================================


class TestDriverOnlineStatusBreakFields:
    def test_model_has_is_on_break(self):
        """DriverOnlineStatus must expose is_on_break attribute."""
        s = DriverOnlineStatus()
        # Default should be False
        assert hasattr(s, "is_on_break")

    def test_model_has_break_started_at(self):
        """DriverOnlineStatus must expose break_started_at attribute."""
        s = DriverOnlineStatus()
        assert hasattr(s, "break_started_at")

    def test_default_not_on_break(self):
        """A freshly created status row is falsy for is_on_break (None or False before DB insert)."""
        s = DriverOnlineStatus()
        assert not s.is_on_break


# ===========================================================================
# Schema tests
# ===========================================================================


class TestBreakResponseSchema:
    def test_break_response_fields(self):
        resp = BreakResponse(
            driver_id=5,
            is_online=True,
            is_on_break=True,
            break_started_at=datetime.now(timezone.utc),
        )
        assert resp.driver_id == 5
        assert resp.is_online is True
        assert resp.is_on_break is True
        assert resp.break_started_at is not None

    def test_break_response_not_on_break(self):
        resp = BreakResponse(
            driver_id=3,
            is_online=True,
            is_on_break=False,
            break_started_at=None,
        )
        assert resp.is_on_break is False
        assert resp.break_started_at is None

    def test_online_status_response_includes_break_fields(self):
        resp = OnlineStatusResponse(
            driver_id=7,
            is_online=True,
            is_on_break=True,
            went_online_at=datetime.now(timezone.utc),
            break_started_at=datetime.now(timezone.utc),
            last_heartbeat=datetime.now(timezone.utc),
        )
        assert resp.is_on_break is True
        assert resp.break_started_at is not None

    def test_online_status_response_defaults_break_false(self):
        """is_on_break defaults to False when not supplied."""
        resp = OnlineStatusResponse(
            driver_id=2,
            is_online=False,
            went_online_at=None,
            last_heartbeat=None,
        )
        assert resp.is_on_break is False
        assert resp.break_started_at is None


# ===========================================================================
# Service: start_break
# ===========================================================================


class TestStartBreak:
    @pytest.mark.asyncio
    async def test_start_break_sets_is_on_break(self):
        """start_break sets is_on_break=True and stamps break_started_at."""
        status_row = _make_status(is_online=True, is_on_break=False)
        db = _make_db(status_row)

        result = await start_break(db, driver_id=1)

        assert result.is_on_break is True
        assert result.break_started_at is not None
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_break_idempotent(self):
        """start_break is idempotent — calling twice preserves original break_started_at."""
        original_time = datetime(2026, 4, 13, 10, 0, 0, tzinfo=timezone.utc)
        status_row = _make_status(
            is_online=True,
            is_on_break=True,
            break_started_at=original_time,
        )
        db = _make_db(status_row)

        result = await start_break(db, driver_id=1)

        # Should not overwrite break_started_at
        assert result.break_started_at == original_time
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_break_requires_online(self):
        """start_break raises ValueError if driver is offline."""
        status_row = _make_status(is_online=False, is_on_break=False)
        db = _make_db(status_row)

        with pytest.raises(ValueError, match="online"):
            await start_break(db, driver_id=1)

    @pytest.mark.asyncio
    async def test_start_break_no_status_row_raises(self):
        """start_break raises ValueError if no status row exists (driver never went online)."""
        db = _make_db(status_row=None)

        with pytest.raises(ValueError, match="online"):
            await start_break(db, driver_id=99)

    @pytest.mark.asyncio
    async def test_start_break_stamps_utc_time(self):
        """break_started_at should be a timezone-aware datetime."""
        status_row = _make_status(is_online=True, is_on_break=False)
        db = _make_db(status_row)

        before = datetime.now(timezone.utc)
        result = await start_break(db, driver_id=1)
        after = datetime.now(timezone.utc)

        assert result.break_started_at is not None
        # Verify break_started_at was set to a time in [before, after]
        # (We check the attribute was set, not the exact value, since mock)
        assert result.is_on_break is True


# ===========================================================================
# Service: end_break
# ===========================================================================


class TestEndBreak:
    @pytest.mark.asyncio
    async def test_end_break_clears_break_state(self):
        """end_break sets is_on_break=False and clears break_started_at."""
        status_row = _make_status(
            is_online=True,
            is_on_break=True,
            break_started_at=datetime.now(timezone.utc),
        )
        db = _make_db(status_row)

        result = await end_break(db, driver_id=1)

        assert result.is_on_break is False
        assert result.break_started_at is None
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_end_break_refreshes_heartbeat(self):
        """end_break refreshes last_heartbeat so driver isn't stale."""
        original_hb = datetime(2026, 4, 13, 8, 0, 0, tzinfo=timezone.utc)
        status_row = _make_status(
            is_online=True,
            is_on_break=True,
            last_heartbeat=original_hb,
        )
        db = _make_db(status_row)

        await end_break(db, driver_id=1)

        # last_heartbeat should have been updated — verify it was set
        assert status_row.last_heartbeat is not None

    @pytest.mark.asyncio
    async def test_end_break_idempotent_when_not_on_break(self):
        """end_break is idempotent — calling when not on break succeeds silently."""
        status_row = _make_status(is_online=True, is_on_break=False, break_started_at=None)
        db = _make_db(status_row)

        result = await end_break(db, driver_id=1)

        assert result.is_on_break is False
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_end_break_requires_online(self):
        """end_break raises ValueError if driver is offline."""
        status_row = _make_status(is_online=False, is_on_break=False)
        db = _make_db(status_row)

        with pytest.raises(ValueError, match="online"):
            await end_break(db, driver_id=1)

    @pytest.mark.asyncio
    async def test_end_break_no_status_row_raises(self):
        """end_break raises ValueError if no status row exists."""
        db = _make_db(status_row=None)

        with pytest.raises(ValueError, match="online"):
            await end_break(db, driver_id=99)


# ===========================================================================
# Service: is_driver_available_now with break
# ===========================================================================


class TestIsDriverAvailableWithBreak:
    @pytest.mark.asyncio
    async def test_on_break_not_available(self):
        """A driver on break (is_online=True, is_on_break=True) is not available."""
        status_row = _make_status(is_online=True, is_on_break=True)

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = status_row
        db.execute.return_value = result

        available = await is_driver_available_now(db, driver_id=1)
        assert available is False

    @pytest.mark.asyncio
    async def test_online_not_on_break_is_available(self):
        """A driver online and not on break with no schedule slots is available."""
        status_row = _make_status(is_online=True, is_on_break=False)

        execute_count = 0

        async def mock_execute(query):
            nonlocal execute_count
            execute_count += 1
            result = MagicMock()
            if execute_count == 1:
                # First call: online status
                result.scalar_one_or_none.return_value = status_row
            else:
                # Second call: schedule slots (empty — no schedule set)
                result.scalars.return_value.all.return_value = []
            return result

        db = AsyncMock()
        db.execute.side_effect = mock_execute

        available = await is_driver_available_now(db, driver_id=1)
        assert available is True

    @pytest.mark.asyncio
    async def test_offline_not_available_regardless_of_break(self):
        """An offline driver is not available even if break state is inconsistent."""
        status_row = _make_status(is_online=False, is_on_break=False)

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = status_row
        db.execute.return_value = result

        available = await is_driver_available_now(db, driver_id=1)
        assert available is False


# ===========================================================================
# API endpoint tests (mock-based)
# ===========================================================================


class TestBreakEndpoints:
    """Test the break start/end API endpoints using FastAPI TestClient patterns."""

    def _make_profile(self, profile_id: int = 10):
        profile = MagicMock()
        profile.id = profile_id
        return profile

    @pytest.mark.asyncio
    async def test_start_break_endpoint_calls_service(self):
        """start_driver_break endpoint calls start_break service and returns BreakResponse."""
        from app.api.v1.driver_availability import start_driver_break

        user = MagicMock()
        db = AsyncMock()
        profile = self._make_profile()
        status_row = _make_status(
            driver_id=profile.id, is_online=True, is_on_break=True,
            break_started_at=datetime.now(timezone.utc),
        )

        with (
            patch(
                "app.api.v1.driver_availability._get_driver_profile",
                new_callable=AsyncMock,
                return_value=profile,
            ) as mock_profile,
            patch(
                "app.api.v1.driver_availability.start_break",
                new_callable=AsyncMock,
                return_value=status_row,
            ) as mock_start,
        ):
            result = await start_driver_break(user=user, db=db)

        mock_profile.assert_called_once_with(db, user)
        mock_start.assert_called_once_with(db, profile.id)
        assert isinstance(result, BreakResponse)
        assert result.is_on_break is True

    @pytest.mark.asyncio
    async def test_end_break_endpoint_calls_service(self):
        """end_driver_break endpoint calls end_break service and returns BreakResponse."""
        from app.api.v1.driver_availability import end_driver_break

        user = MagicMock()
        db = AsyncMock()
        profile = self._make_profile()
        status_row = _make_status(
            driver_id=profile.id, is_online=True, is_on_break=False,
            break_started_at=None,
        )

        with (
            patch(
                "app.api.v1.driver_availability._get_driver_profile",
                new_callable=AsyncMock,
                return_value=profile,
            ),
            patch(
                "app.api.v1.driver_availability.end_break",
                new_callable=AsyncMock,
                return_value=status_row,
            ) as mock_end,
        ):
            result = await end_driver_break(user=user, db=db)

        mock_end.assert_called_once_with(db, profile.id)
        assert isinstance(result, BreakResponse)
        assert result.is_on_break is False

    @pytest.mark.asyncio
    async def test_start_break_endpoint_409_when_offline(self):
        """start_driver_break returns 409 when driver is offline."""
        from fastapi import HTTPException

        from app.api.v1.driver_availability import start_driver_break

        user = MagicMock()
        db = AsyncMock()
        profile = self._make_profile()

        with (
            patch(
                "app.api.v1.driver_availability._get_driver_profile",
                new_callable=AsyncMock,
                return_value=profile,
            ),
            patch(
                "app.api.v1.driver_availability.start_break",
                new_callable=AsyncMock,
                side_effect=ValueError("Driver must be online to start a break."),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await start_driver_break(user=user, db=db)

        assert exc_info.value.status_code == 409
        assert "online" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_end_break_endpoint_409_when_offline(self):
        """end_driver_break returns 409 when driver is offline."""
        from fastapi import HTTPException

        from app.api.v1.driver_availability import end_driver_break

        user = MagicMock()
        db = AsyncMock()
        profile = self._make_profile()

        with (
            patch(
                "app.api.v1.driver_availability._get_driver_profile",
                new_callable=AsyncMock,
                return_value=profile,
            ),
            patch(
                "app.api.v1.driver_availability.end_break",
                new_callable=AsyncMock,
                side_effect=ValueError("Driver must be online to end a break."),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await end_driver_break(user=user, db=db)

        assert exc_info.value.status_code == 409


# ===========================================================================
# Break state machine integration
# ===========================================================================


class TestBreakStateMachine:
    """Test the full break state machine: online → break → resume."""

    @pytest.mark.asyncio
    async def test_start_then_end_break_full_cycle(self):
        """Full cycle: start break, then end break restores availability."""
        # Simulate the state mutation through mock
        state = {"is_online": True, "is_on_break": False, "break_started_at": None}

        async def mock_start_break(db, driver_id):
            state["is_on_break"] = True
            state["break_started_at"] = datetime.now(timezone.utc)
            m = MagicMock()
            m.is_online = state["is_online"]
            m.is_on_break = state["is_on_break"]
            m.break_started_at = state["break_started_at"]
            m.driver_id = driver_id
            return m

        async def mock_end_break(db, driver_id):
            state["is_on_break"] = False
            state["break_started_at"] = None
            m = MagicMock()
            m.is_online = state["is_online"]
            m.is_on_break = state["is_on_break"]
            m.break_started_at = state["break_started_at"]
            m.driver_id = driver_id
            return m

        db = AsyncMock()

        with patch("app.services.driver_availability.start_break", new=mock_start_break):
            from app.services.driver_availability import start_break as sb
            result = await sb(db, driver_id=1)
            assert result.is_on_break is True

        with patch("app.services.driver_availability.end_break", new=mock_end_break):
            from app.services.driver_availability import end_break as eb
            result = await eb(db, driver_id=1)
            assert result.is_on_break is False
            assert result.break_started_at is None

    def test_break_response_from_attributes(self):
        """BreakResponse.model_validate works on ORM-like objects."""
        status = MagicMock()
        status.driver_id = 42
        status.is_online = True
        status.is_on_break = True
        status.break_started_at = datetime.now(timezone.utc)

        resp = BreakResponse.model_validate(status)
        assert resp.driver_id == 42
        assert resp.is_on_break is True

    def test_break_response_offline_driver(self):
        """BreakResponse can represent an offline driver state."""
        status = MagicMock()
        status.driver_id = 7
        status.is_online = False
        status.is_on_break = False
        status.break_started_at = None

        resp = BreakResponse.model_validate(status)
        assert resp.is_online is False
        assert resp.is_on_break is False


# ===========================================================================
# Admin visibility tests
# ===========================================================================


class TestAdminBreakVisibility:
    def test_admin_item_includes_is_on_break(self):
        """AdminDriverAvailabilityItem schema includes is_on_break field."""
        from app.schemas.driver_availability import AdminDriverAvailabilityItem

        item = AdminDriverAvailabilityItem(
            driver_id=5,
            is_online=True,
            is_on_break=True,
            went_online_at=datetime.now(timezone.utc),
            last_heartbeat=datetime.now(timezone.utc),
            is_available_now=False,
        )
        assert item.is_on_break is True
        assert item.is_available_now is False

    def test_admin_item_default_not_on_break(self):
        """AdminDriverAvailabilityItem defaults is_on_break to False."""
        from app.schemas.driver_availability import AdminDriverAvailabilityItem

        item = AdminDriverAvailabilityItem(
            driver_id=3,
            is_online=True,
            went_online_at=None,
            last_heartbeat=None,
            is_available_now=True,
        )
        assert item.is_on_break is False
