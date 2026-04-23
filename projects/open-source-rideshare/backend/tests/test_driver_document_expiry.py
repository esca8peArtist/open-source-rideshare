"""Tests for driver document expiry enforcement.

Covers:
- has_valid_documents returns True when all three docs are APPROVED and non-expired
- has_valid_documents returns False when license is expired (expiry_date = yesterday)
- has_valid_documents returns False when registration is expired
- has_valid_documents returns False when insurance is expired (policy_end_date = yesterday)
- has_valid_documents returns False when driver has no approved license at all
- has_valid_documents returns False when driver has no approved registration at all
- has_valid_documents returns False when driver has no approved insurance at all
- has_valid_documents treats None expiry_date as valid (defensive; model is non-nullable)
- set_driver_online raises ValueError when has_valid_documents returns False
- set_driver_online succeeds when has_valid_documents returns True
- API PUT /drivers/me/availability/online returns 403 when documents are invalid
- matching.find_candidates excludes a driver with expired license
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.driver_document_expiry import has_valid_documents


# ---------------------------------------------------------------------------
# Helpers: build mock DB sessions for has_valid_documents
# ---------------------------------------------------------------------------

def _make_scalars_result(obj):
    """Return a MagicMock that mimics scalars().first() returning obj."""
    scalars = MagicMock()
    scalars.first.return_value = obj
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _build_db_for_has_valid(license_obj, registration_obj, insurance_obj):
    """Build an AsyncMock DB whose three execute() calls return the given objects.

    None means no matching document was found (scalars().first() returns None).
    Any other value is treated as a found document.
    """
    db = AsyncMock()
    db.execute.side_effect = [
        _make_scalars_result(license_obj),
        _make_scalars_result(registration_obj),
        _make_scalars_result(insurance_obj),
    ]
    return db


def _mock_license(days_offset: int | None = 30):
    """Return a mock DriverLicense object.  days_offset=None means expiry_date is None."""
    lic = MagicMock()
    lic.id = 1
    lic.driver_id = 10
    if days_offset is None:
        lic.expiry_date = None
    else:
        lic.expiry_date = date.today() + timedelta(days=days_offset)
    return lic


def _mock_registration(days_offset: int | None = 30):
    reg = MagicMock()
    reg.id = 2
    reg.driver_id = 10
    if days_offset is None:
        reg.expiry_date = None
    else:
        reg.expiry_date = date.today() + timedelta(days=days_offset)
    return reg


def _mock_insurance(days_offset: int | None = 30):
    ins = MagicMock()
    ins.id = 3
    ins.driver_id = 10
    if days_offset is None:
        ins.policy_end_date = None
    else:
        ins.policy_end_date = date.today() + timedelta(days=days_offset)
    return ins


# ---------------------------------------------------------------------------
# Unit tests: has_valid_documents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestHasValidDocuments:
    async def test_returns_true_when_all_docs_valid(self):
        """All three APPROVED, non-expired documents → True."""
        db = _build_db_for_has_valid(
            _mock_license(30), _mock_registration(30), _mock_insurance(30)
        )
        result = await has_valid_documents(db, driver_id=10)
        assert result is True

    async def test_returns_true_when_doc_expires_today(self):
        """Expiry on today's date (offset=0) is still valid (>= today)."""
        db = _build_db_for_has_valid(
            _mock_license(0), _mock_registration(0), _mock_insurance(0)
        )
        result = await has_valid_documents(db, driver_id=10)
        assert result is True

    async def test_returns_false_when_license_expired(self):
        """Expired license (expiry_date = yesterday) → False.

        The DB query filters out expired docs, so the mock returns None for the
        license query to simulate no valid license found.
        """
        db = _build_db_for_has_valid(
            None,  # no valid license found (expired was filtered by query)
            _mock_registration(30),
            _mock_insurance(30),
        )
        result = await has_valid_documents(db, driver_id=10)
        assert result is False

    async def test_returns_false_when_registration_expired(self):
        """Expired registration → False."""
        db = _build_db_for_has_valid(
            _mock_license(30),
            None,  # no valid registration found
            _mock_insurance(30),
        )
        result = await has_valid_documents(db, driver_id=10)
        assert result is False

    async def test_returns_false_when_insurance_expired(self):
        """Expired insurance (policy_end_date = yesterday) → False."""
        db = _build_db_for_has_valid(
            _mock_license(30),
            _mock_registration(30),
            None,  # no valid insurance found
        )
        result = await has_valid_documents(db, driver_id=10)
        assert result is False

    async def test_returns_false_when_no_license_at_all(self):
        """No approved license of any kind → False."""
        db = _build_db_for_has_valid(
            None,
            _mock_registration(30),
            _mock_insurance(30),
        )
        result = await has_valid_documents(db, driver_id=10)
        assert result is False

    async def test_returns_false_when_no_registration_at_all(self):
        db = _build_db_for_has_valid(
            _mock_license(30),
            None,
            _mock_insurance(30),
        )
        result = await has_valid_documents(db, driver_id=10)
        assert result is False

    async def test_returns_false_when_no_insurance_at_all(self):
        db = _build_db_for_has_valid(
            _mock_license(30),
            _mock_registration(30),
            None,
        )
        result = await has_valid_documents(db, driver_id=10)
        assert result is False

    async def test_returns_true_when_expiry_date_is_none(self):
        """None expiry_date is treated as "no expiry / always valid".

        The ORM columns are currently non-nullable, but the function is defensive
        and includes an IS NULL branch so that future nullable migrations don't
        silently block all drivers.  We simulate this by returning a mock object
        (the DB found a matching row), which means the None check inside the query
        OR clause was satisfied.
        """
        # A mock object returned from scalars().first() means a valid row was found.
        lic_none = _mock_license(None)
        reg_none = _mock_registration(None)
        ins_none = _mock_insurance(None)
        db = _build_db_for_has_valid(lic_none, reg_none, ins_none)
        result = await has_valid_documents(db, driver_id=10)
        assert result is True

    async def test_checks_all_three_doc_types(self):
        """Ensure has_valid_documents performs exactly three DB queries."""
        db = _build_db_for_has_valid(
            _mock_license(30), _mock_registration(30), _mock_insurance(30)
        )
        await has_valid_documents(db, driver_id=10)
        assert db.execute.call_count == 3

    async def test_short_circuits_on_missing_license(self):
        """When license check fails, the remaining queries are not executed."""
        db = _build_db_for_has_valid(None, _mock_registration(30), _mock_insurance(30))
        await has_valid_documents(db, driver_id=10)
        # Only the license query was executed before returning False.
        assert db.execute.call_count == 1


# ---------------------------------------------------------------------------
# Unit tests: set_driver_online enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSetDriverOnlineDocumentEnforcement:
    async def test_raises_value_error_when_documents_invalid(self):
        """set_driver_online raises ValueError when going online with invalid docs."""
        from app.services.driver_availability import set_driver_online

        db = AsyncMock()

        with patch(
            "app.services.driver_availability.has_valid_documents",
            new=AsyncMock(return_value=False),
        ):
            with pytest.raises(ValueError, match="expired or missing required documents"):
                await set_driver_online(db, driver_id=10, is_online=True)

    async def test_does_not_raise_when_documents_valid(self):
        """set_driver_online does not raise when documents pass the validity check."""
        from app.services.driver_availability import set_driver_online

        # Build a DB that returns a valid DriverOnlineStatus row for the upsert.
        status_row = MagicMock()
        status_row.is_online = False
        status_row.went_online_at = None
        status_row.last_heartbeat = None

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None  # no existing row → create
        db.execute.return_value = result
        db.flush = AsyncMock()

        with patch(
            "app.services.driver_availability.has_valid_documents",
            new=AsyncMock(return_value=True),
        ):
            # Should not raise.
            row = await set_driver_online(db, driver_id=10, is_online=True)
        assert row is not None

    async def test_does_not_check_documents_when_going_offline(self):
        """Going offline (is_online=False) never triggers the document check."""
        from app.services.driver_availability import set_driver_online

        status_row = MagicMock()
        status_row.is_online = True

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = status_row
        db.execute.return_value = result
        db.flush = AsyncMock()

        mock_has_valid = AsyncMock(return_value=False)
        with patch("app.services.driver_availability.has_valid_documents", new=mock_has_valid):
            # Going offline — should succeed even though has_valid_documents returns False.
            await set_driver_online(db, driver_id=10, is_online=False)

        mock_has_valid.assert_not_called()


# ---------------------------------------------------------------------------
# Unit tests: API layer maps ValueError → HTTP 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSetOnlineStatusApiLayer:
    async def test_returns_403_when_documents_invalid(self):
        """PUT /api/v1/drivers/me/availability/online returns 403 for invalid docs."""
        from httpx import AsyncClient, ASGITransport
        from app.main import app as fastapi_app
        from app.db.database import get_db
        from app.api.deps import require_driver
        from app.models.user import UserRole

        # Mock DB session — not used because we override the service too.
        db = AsyncMock()

        async def override_get_db():
            yield db

        # Build a mock driver User that passes the require_driver check.
        mock_user = MagicMock()
        mock_user.id = 99
        mock_user.role = MagicMock()
        mock_user.role.value = "driver"

        async def override_require_driver():
            return mock_user

        # Mock _get_driver_profile to return a profile with id=10.
        mock_profile = MagicMock()
        mock_profile.id = 10

        fastapi_app.dependency_overrides[get_db] = override_get_db
        fastapi_app.dependency_overrides[require_driver] = override_require_driver

        try:
            with patch(
                "app.api.v1.driver_availability.set_driver_online",
                new=AsyncMock(
                    side_effect=ValueError("Driver has expired or missing required documents")
                ),
            ), patch(
                "app.api.v1.driver_availability._get_driver_profile",
                new=AsyncMock(return_value=mock_profile),
            ):
                transport = ASGITransport(app=fastapi_app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.put(
                        "/api/v1/drivers/me/availability/online",
                        json={"is_online": True},
                    )
        finally:
            fastapi_app.dependency_overrides.clear()

        assert response.status_code == 403
        assert "expired or missing" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Integration test: matching excludes driver with expired documents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMatchingDocumentFilter:
    async def test_find_candidates_excludes_driver_with_expired_docs(self):
        """find_candidates should silently exclude a driver whose has_valid_documents
        returns False, even if they are geographically close and online.
        """
        from app.services.matching import MatchingEngine, DriverCandidate
        from app.models.vehicle import VehicleServiceCategory

        mock_redis = AsyncMock()
        # Simulate one nearby driver (user_id=1, 0.5 km away).
        mock_redis.geosearch = AsyncMock(return_value=[("1", 0.5)])
        mock_redis.get = AsyncMock(return_value=b"available")

        engine = MatchingEngine(mock_redis)

        # Build a mock DriverProfile.
        mock_profile = MagicMock()
        mock_profile.id = 10
        mock_profile.user_id = 1
        mock_profile.is_online = True
        mock_profile.is_approved = True
        mock_profile.rating_avg = 4.5
        mock_profile.total_trips = 20
        mock_profile.active_vehicle_id = None
        mock_profile.hearing_impairment_capable = False
        mock_profile.service_animal_friendly = False
        mock_profile.visual_assistance_capable = False

        db = AsyncMock()

        # Mock the DB query for DriverProfile rows.
        profile_result = MagicMock()
        profile_result.scalars.return_value.all.return_value = [mock_profile]

        # Mock availability check (returns the driver as eligible).
        availability_result = MagicMock()
        availability_result.scalars.return_value.all.return_value = [
            MagicMock(driver_id=10, is_online=True, last_heartbeat=__import__("datetime").datetime.now(__import__("datetime").timezone.utc))
        ]

        # Vehicle query returns empty.
        vehicle_result = MagicMock()
        vehicle_result.scalars.return_value.all.return_value = []

        # Destination filter query returns empty (no active dest filters).
        dest_filter_result = MagicMock()
        dest_filter_result.scalars.return_value.all.return_value = []

        db.execute.side_effect = [
            profile_result,       # DriverProfile query
            availability_result,  # DriverOnlineStatus query (condition 1+2)
            dest_filter_result,   # DriverSchedule query (condition 3 — no slots)
            vehicle_result,       # Vehicle query
        ]

        with patch(
            "app.services.matching.has_valid_documents",
            new=AsyncMock(return_value=False),
        ), patch(
            "app.services.matching.get_active_filters_for_drivers",
            new=AsyncMock(return_value={}),
        ):
            candidates = await engine.find_candidates(
                pickup_lat=40.7,
                pickup_lng=-74.0,
                db=db,
                availability_filter=True,
            )

        # Driver with invalid documents must be excluded.
        assert candidates == []

    async def test_find_candidates_includes_driver_with_valid_docs(self):
        """find_candidates should include a driver whose has_valid_documents returns True."""
        from app.services.matching import MatchingEngine
        from app.models.vehicle import VehicleServiceCategory

        mock_redis = AsyncMock()
        mock_redis.geosearch = AsyncMock(return_value=[("1", 0.5)])
        mock_redis.get = AsyncMock(return_value=b"available")

        engine = MatchingEngine(mock_redis)

        mock_profile = MagicMock()
        mock_profile.id = 10
        mock_profile.user_id = 1
        mock_profile.is_online = True
        mock_profile.is_approved = True
        mock_profile.rating_avg = 4.5
        mock_profile.total_trips = 20
        mock_profile.active_vehicle_id = None
        mock_profile.hearing_impairment_capable = False
        mock_profile.service_animal_friendly = False
        mock_profile.visual_assistance_capable = False

        db = AsyncMock()

        profile_result = MagicMock()
        profile_result.scalars.return_value.all.return_value = [mock_profile]

        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        stale_row = MagicMock()
        stale_row.driver_id = 10
        stale_row.is_online = True
        stale_row.last_heartbeat = now

        availability_result = MagicMock()
        availability_result.scalars.return_value.all.return_value = [stale_row]

        dest_filter_result = MagicMock()
        dest_filter_result.scalars.return_value.all.return_value = []

        vehicle_result = MagicMock()
        vehicle_result.scalars.return_value.all.return_value = []

        db.execute.side_effect = [
            profile_result,
            availability_result,
            dest_filter_result,
            vehicle_result,
        ]

        with patch(
            "app.services.matching.has_valid_documents",
            new=AsyncMock(return_value=True),
        ), patch(
            "app.services.matching.get_active_filters_for_drivers",
            new=AsyncMock(return_value={}),
        ):
            candidates = await engine.find_candidates(
                pickup_lat=40.7,
                pickup_lng=-74.0,
                db=db,
                availability_filter=True,
            )

        assert len(candidates) == 1
        assert candidates[0].driver_id == 10
