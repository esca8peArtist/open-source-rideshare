"""Tests for the driver dispute resolution feature.

POST   /drivers/me/disputes
GET    /drivers/me/disputes
GET    /drivers/me/disputes/{dispute_id}
POST   /drivers/me/disputes/{dispute_id}/appeal
DELETE /drivers/me/disputes/{dispute_id}
GET    /admin/disputes
POST   /admin/disputes/{dispute_id}/resolve

Coverage
--------
Schemas (DisputeType, DisputeStatus, FileDisputeRequest, AppealDecisionRequest,
         ResolveDisputeRequest, DisputeResponse, DisputeListResponse)
  - All enum values present
  - FileDisputeRequest: valid, description too short, description too long,
    negative amount_disputed_usd
  - AppealDecisionRequest: valid, appeal_reason too short/too long
  - ResolveDisputeRequest: valid, with admin_notes
  - DisputeResponse: all fields, is_overdue present
  - DisputeListResponse: total and items

Service (file_dispute, list_driver_disputes, get_dispute, appeal_decision,
         withdraw_dispute, admin_list_disputes, admin_resolve_dispute)
  - file_dispute: all DisputeTypes, with ride_id, with amount, minimal fields
  - list_driver_disputes: empty, multiple, status filter, pagination
  - get_dispute: found, not found (wrong ID), wrong driver returns None
  - appeal_decision: success RESOLVED_AGAINST_DRIVER -> PENDING_APPEAL
  - appeal_decision: wrong status raises ValueError
  - appeal_decision: wrong driver raises PermissionError
  - withdraw_dispute: OPEN -> WITHDRAWN
  - withdraw_dispute: UNDER_REVIEW -> WITHDRAWN
  - withdraw_dispute: wrong status raises ValueError
  - withdraw_dispute: wrong driver raises PermissionError
  - is_overdue: True when filed 15 days ago and OPEN
  - is_overdue: True when filed 15 days ago and UNDER_REVIEW
  - is_overdue: False when filed 1 day ago and OPEN
  - is_overdue: False when filed 15 days ago and RESOLVED_IN_DRIVER_FAVOR
  - admin_list_disputes: all disputes, filtered by status, filtered by type, pagination
  - admin_resolve_dispute: RESOLVED_IN_DRIVER_FAVOR, DISMISSED
  - admin_resolve_dispute: RESOLVED_AGAINST_DRIVER on normal OPEN dispute
  - admin_resolve_dispute: RESOLVED_AGAINST_DRIVER on PENDING_APPEAL raises ValueError
  - admin_resolve_dispute: nonexistent dispute raises KeyError
  - admin_resolve_dispute: invalid resolution raises ValueError

Router (post_file_dispute, get_list_driver_disputes, get_one_dispute,
        post_appeal_dispute, delete_withdraw_dispute, admin_get_disputes,
        admin_post_resolve_dispute)
  - Each endpoint delegates to the correct service function
  - 404 returned for not-found / wrong-owner cases
  - 400 returned for invalid status transitions
  - 422 returned for invalid resolution in admin resolve
"""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError

from app.schemas.driver_dispute import (
    AppealDecisionRequest,
    DisputeListResponse,
    DisputeResponse,
    DisputeStatus,
    DisputeType,
    FileDisputeRequest,
    ResolveDisputeRequest,
)
from app.services.driver_dispute import (
    _is_overdue,
    _reset_store,
    admin_list_disputes,
    admin_resolve_dispute,
    appeal_decision,
    file_dispute,
    get_dispute,
    list_driver_disputes,
    withdraw_dispute,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _make_dispute_dict(
    id: int = 1,
    driver_id: int = 10,
    dispute_type: DisputeType = DisputeType.OTHER,
    status: DisputeStatus = DisputeStatus.OPEN,
    description: str = "This is a test dispute description.",
    ride_id: Optional[int] = None,
    amount_disputed_usd: Optional[Decimal] = None,
    filed_at: Optional[datetime] = None,
    updated_at: Optional[datetime] = None,
    resolution_at: Optional[datetime] = None,
    admin_notes: Optional[str] = None,
    appeal_reason: Optional[str] = None,
    appeal_filed_at: Optional[datetime] = None,
    is_overdue: bool = False,
) -> dict:
    now = _utc_now()
    return dict(
        id=id,
        driver_id=driver_id,
        dispute_type=dispute_type,
        status=status,
        description=description,
        ride_id=ride_id,
        amount_disputed_usd=amount_disputed_usd,
        filed_at=filed_at or now,
        updated_at=updated_at or now,
        resolution_at=resolution_at,
        admin_notes=admin_notes,
        appeal_reason=appeal_reason,
        appeal_filed_at=appeal_filed_at,
        is_overdue=is_overdue,
    )


@pytest.fixture(autouse=True)
def reset_dispute_store():
    """Reset the in-memory store before each test."""
    _reset_store()
    yield
    _reset_store()


@pytest.fixture
def mock_db():
    return AsyncMock()


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestDisputeTypeEnum:
    def test_all_values_present(self):
        values = {d.value for d in DisputeType}
        assert "FARE_ADJUSTMENT" in values
        assert "DEACTIVATION_APPEAL" in values
        assert "FALSE_COMPLAINT" in values
        assert "PAYMENT_MISSING" in values
        assert "OTHER" in values

    def test_count(self):
        assert len(DisputeType) == 5


class TestDisputeStatusEnum:
    def test_all_values_present(self):
        values = {d.value for d in DisputeStatus}
        assert "OPEN" in values
        assert "UNDER_REVIEW" in values
        assert "PENDING_APPEAL" in values
        assert "RESOLVED_IN_DRIVER_FAVOR" in values
        assert "RESOLVED_AGAINST_DRIVER" in values
        assert "DISMISSED" in values
        assert "WITHDRAWN" in values

    def test_count(self):
        assert len(DisputeStatus) == 7


class TestFileDisputeRequest:
    def test_valid_minimal(self):
        req = FileDisputeRequest(
            dispute_type=DisputeType.OTHER,
            description="A" * 20,
        )
        assert req.dispute_type == DisputeType.OTHER
        assert req.ride_id is None
        assert req.amount_disputed_usd is None

    def test_valid_full(self):
        req = FileDisputeRequest(
            dispute_type=DisputeType.FARE_ADJUSTMENT,
            description="The platform reduced my fare without explanation.",
            ride_id=42,
            amount_disputed_usd=Decimal("12.50"),
        )
        assert req.ride_id == 42
        assert req.amount_disputed_usd == Decimal("12.50")

    def test_description_too_short(self):
        with pytest.raises(ValidationError):
            FileDisputeRequest(
                dispute_type=DisputeType.OTHER,
                description="Too short",
            )

    def test_description_too_long(self):
        with pytest.raises(ValidationError):
            FileDisputeRequest(
                dispute_type=DisputeType.OTHER,
                description="A" * 2001,
            )

    def test_description_exactly_20_chars(self):
        req = FileDisputeRequest(
            dispute_type=DisputeType.OTHER,
            description="A" * 20,
        )
        assert len(req.description) == 20

    def test_description_exactly_2000_chars(self):
        req = FileDisputeRequest(
            dispute_type=DisputeType.OTHER,
            description="A" * 2000,
        )
        assert len(req.description) == 2000

    def test_negative_amount_rejected(self):
        with pytest.raises(ValidationError):
            FileDisputeRequest(
                dispute_type=DisputeType.PAYMENT_MISSING,
                description="My payment was not received for last ride.",
                amount_disputed_usd=Decimal("-1.00"),
            )

    def test_zero_amount_allowed(self):
        req = FileDisputeRequest(
            dispute_type=DisputeType.PAYMENT_MISSING,
            description="My payment was not received for last ride.",
            amount_disputed_usd=Decimal("0.00"),
        )
        assert req.amount_disputed_usd == Decimal("0.00")

    def test_all_dispute_types(self):
        for dtype in DisputeType:
            req = FileDisputeRequest(
                dispute_type=dtype,
                description="Testing this dispute type for validity here.",
            )
            assert req.dispute_type == dtype


class TestAppealDecisionRequest:
    def test_valid(self):
        req = AppealDecisionRequest(
            appeal_reason="The decision was unfair because the rider fabricated the complaint."
        )
        assert len(req.appeal_reason) >= 20

    def test_too_short(self):
        with pytest.raises(ValidationError):
            AppealDecisionRequest(appeal_reason="Too short")

    def test_too_long(self):
        with pytest.raises(ValidationError):
            AppealDecisionRequest(appeal_reason="A" * 1001)

    def test_exactly_20_chars(self):
        req = AppealDecisionRequest(appeal_reason="A" * 20)
        assert len(req.appeal_reason) == 20

    def test_exactly_1000_chars(self):
        req = AppealDecisionRequest(appeal_reason="A" * 1000)
        assert len(req.appeal_reason) == 1000


class TestResolveDisputeRequest:
    def test_valid_resolved_in_favor(self):
        req = ResolveDisputeRequest(resolution=DisputeStatus.RESOLVED_IN_DRIVER_FAVOR)
        assert req.resolution == DisputeStatus.RESOLVED_IN_DRIVER_FAVOR
        assert req.admin_notes is None

    def test_valid_with_admin_notes(self):
        req = ResolveDisputeRequest(
            resolution=DisputeStatus.DISMISSED,
            admin_notes="Insufficient evidence provided.",
        )
        assert req.admin_notes == "Insufficient evidence provided."

    def test_valid_resolved_against(self):
        req = ResolveDisputeRequest(resolution=DisputeStatus.RESOLVED_AGAINST_DRIVER)
        assert req.resolution == DisputeStatus.RESOLVED_AGAINST_DRIVER


class TestDisputeResponseSchema:
    def test_all_fields_present(self):
        d = _make_dispute_dict()
        resp = DisputeResponse(**d)
        assert hasattr(resp, "id")
        assert hasattr(resp, "driver_id")
        assert hasattr(resp, "dispute_type")
        assert hasattr(resp, "status")
        assert hasattr(resp, "description")
        assert hasattr(resp, "ride_id")
        assert hasattr(resp, "amount_disputed_usd")
        assert hasattr(resp, "filed_at")
        assert hasattr(resp, "updated_at")
        assert hasattr(resp, "resolution_at")
        assert hasattr(resp, "admin_notes")
        assert hasattr(resp, "appeal_reason")
        assert hasattr(resp, "appeal_filed_at")
        assert hasattr(resp, "is_overdue")

    def test_optional_fields_can_be_none(self):
        d = _make_dispute_dict()
        resp = DisputeResponse(**d)
        assert resp.ride_id is None
        assert resp.amount_disputed_usd is None
        assert resp.resolution_at is None
        assert resp.admin_notes is None
        assert resp.appeal_reason is None
        assert resp.appeal_filed_at is None


class TestDisputeListResponseSchema:
    def test_empty(self):
        r = DisputeListResponse(total=0, items=[])
        assert r.total == 0
        assert r.items == []

    def test_with_items(self):
        d = _make_dispute_dict()
        r = DisputeListResponse(total=1, items=[DisputeResponse(**d)])
        assert r.total == 1
        assert len(r.items) == 1


# ---------------------------------------------------------------------------
# Service: _is_overdue helper
# ---------------------------------------------------------------------------


class TestIsOverdue:
    def test_overdue_when_open_and_filed_15_days_ago(self):
        dispute = _make_dispute_dict(
            status=DisputeStatus.OPEN,
            filed_at=_utc_now() - timedelta(days=15),
        )
        assert _is_overdue(dispute) is True

    def test_overdue_when_under_review_and_filed_15_days_ago(self):
        dispute = _make_dispute_dict(
            status=DisputeStatus.UNDER_REVIEW,
            filed_at=_utc_now() - timedelta(days=15),
        )
        assert _is_overdue(dispute) is True

    def test_not_overdue_when_filed_1_day_ago(self):
        dispute = _make_dispute_dict(
            status=DisputeStatus.OPEN,
            filed_at=_utc_now() - timedelta(days=1),
        )
        assert _is_overdue(dispute) is False

    def test_not_overdue_when_filed_13_days_ago(self):
        dispute = _make_dispute_dict(
            status=DisputeStatus.OPEN,
            filed_at=_utc_now() - timedelta(days=13),
        )
        assert _is_overdue(dispute) is False

    def test_not_overdue_when_resolved(self):
        dispute = _make_dispute_dict(
            status=DisputeStatus.RESOLVED_IN_DRIVER_FAVOR,
            filed_at=_utc_now() - timedelta(days=15),
        )
        assert _is_overdue(dispute) is False

    def test_not_overdue_when_pending_appeal(self):
        dispute = _make_dispute_dict(
            status=DisputeStatus.PENDING_APPEAL,
            filed_at=_utc_now() - timedelta(days=15),
        )
        assert _is_overdue(dispute) is False

    def test_not_overdue_when_withdrawn(self):
        dispute = _make_dispute_dict(
            status=DisputeStatus.WITHDRAWN,
            filed_at=_utc_now() - timedelta(days=15),
        )
        assert _is_overdue(dispute) is False

    def test_not_overdue_when_dismissed(self):
        dispute = _make_dispute_dict(
            status=DisputeStatus.DISMISSED,
            filed_at=_utc_now() - timedelta(days=20),
        )
        assert _is_overdue(dispute) is False


# ---------------------------------------------------------------------------
# Service: file_dispute
# ---------------------------------------------------------------------------


class TestFileDispute:
    @pytest.mark.asyncio
    async def test_file_dispute_returns_dict_with_open_status(self, mock_db):
        result = await file_dispute(
            db=mock_db,
            driver_id=1,
            dispute_type=DisputeType.OTHER,
            description="This is a test dispute description.",
            ride_id=None,
            amount_disputed_usd=None,
        )
        assert result["status"] == DisputeStatus.OPEN
        assert result["driver_id"] == 1
        assert result["dispute_type"] == DisputeType.OTHER

    @pytest.mark.asyncio
    async def test_file_dispute_assigns_unique_ids(self, mock_db):
        r1 = await file_dispute(mock_db, 1, DisputeType.OTHER, "A" * 25, None, None)
        r2 = await file_dispute(mock_db, 1, DisputeType.OTHER, "B" * 25, None, None)
        assert r1["id"] != r2["id"]

    @pytest.mark.asyncio
    async def test_file_dispute_with_ride_id(self, mock_db):
        result = await file_dispute(mock_db, 1, DisputeType.FARE_ADJUSTMENT, "A" * 30, 99, None)
        assert result["ride_id"] == 99

    @pytest.mark.asyncio
    async def test_file_dispute_with_amount(self, mock_db):
        result = await file_dispute(mock_db, 1, DisputeType.PAYMENT_MISSING, "A" * 30, None, Decimal("25.00"))
        assert result["amount_disputed_usd"] == Decimal("25.00")

    @pytest.mark.asyncio
    async def test_file_dispute_all_types(self, mock_db):
        for dtype in DisputeType:
            result = await file_dispute(mock_db, 1, dtype, "Testing all dispute types here.", None, None)
            assert result["dispute_type"] == dtype

    @pytest.mark.asyncio
    async def test_file_dispute_includes_is_overdue_false(self, mock_db):
        result = await file_dispute(mock_db, 1, DisputeType.OTHER, "A" * 25, None, None)
        assert result["is_overdue"] is False

    @pytest.mark.asyncio
    async def test_file_dispute_sets_filed_at_and_updated_at(self, mock_db):
        before = _utc_now()
        result = await file_dispute(mock_db, 1, DisputeType.OTHER, "A" * 25, None, None)
        after = _utc_now()
        assert before <= result["filed_at"] <= after
        assert before <= result["updated_at"] <= after


# ---------------------------------------------------------------------------
# Service: list_driver_disputes
# ---------------------------------------------------------------------------


class TestListDriverDisputes:
    @pytest.mark.asyncio
    async def test_empty_for_new_driver(self, mock_db):
        total, items = await list_driver_disputes(mock_db, driver_id=99, status_filter=None, skip=0, limit=10)
        assert total == 0
        assert items == []

    @pytest.mark.asyncio
    async def test_returns_own_disputes(self, mock_db):
        await file_dispute(mock_db, 1, DisputeType.OTHER, "A" * 25, None, None)
        await file_dispute(mock_db, 1, DisputeType.FARE_ADJUSTMENT, "B" * 25, None, None)
        total, items = await list_driver_disputes(mock_db, driver_id=1, status_filter=None, skip=0, limit=10)
        assert total == 2
        assert all(d["driver_id"] == 1 for d in items)

    @pytest.mark.asyncio
    async def test_does_not_return_other_driver_disputes(self, mock_db):
        await file_dispute(mock_db, 1, DisputeType.OTHER, "A" * 25, None, None)
        await file_dispute(mock_db, 2, DisputeType.OTHER, "B" * 25, None, None)
        total, items = await list_driver_disputes(mock_db, driver_id=1, status_filter=None, skip=0, limit=10)
        assert total == 1
        assert items[0]["driver_id"] == 1

    @pytest.mark.asyncio
    async def test_status_filter(self, mock_db):
        d = await file_dispute(mock_db, 1, DisputeType.OTHER, "A" * 25, None, None)
        await withdraw_dispute(mock_db, 1, d["id"])
        await file_dispute(mock_db, 1, DisputeType.OTHER, "B" * 25, None, None)

        total, items = await list_driver_disputes(mock_db, driver_id=1, status_filter=DisputeStatus.OPEN, skip=0, limit=10)
        assert total == 1
        assert items[0]["status"] == DisputeStatus.OPEN

    @pytest.mark.asyncio
    async def test_pagination_skip(self, mock_db):
        for i in range(5):
            await file_dispute(mock_db, 1, DisputeType.OTHER, f"Dispute number {i} needs resolution.", None, None)
        total, items = await list_driver_disputes(mock_db, driver_id=1, status_filter=None, skip=3, limit=10)
        assert total == 5
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_pagination_limit(self, mock_db):
        for i in range(5):
            await file_dispute(mock_db, 1, DisputeType.OTHER, f"Dispute number {i} needs resolution.", None, None)
        total, items = await list_driver_disputes(mock_db, driver_id=1, status_filter=None, skip=0, limit=2)
        assert total == 5
        assert len(items) == 2


# ---------------------------------------------------------------------------
# Service: get_dispute
# ---------------------------------------------------------------------------


class TestGetDispute:
    @pytest.mark.asyncio
    async def test_found(self, mock_db):
        created = await file_dispute(mock_db, 1, DisputeType.OTHER, "A" * 25, None, None)
        result = await get_dispute(mock_db, driver_id=1, dispute_id=created["id"])
        assert result is not None
        assert result["id"] == created["id"]

    @pytest.mark.asyncio
    async def test_not_found_wrong_id(self, mock_db):
        result = await get_dispute(mock_db, driver_id=1, dispute_id=9999)
        assert result is None

    @pytest.mark.asyncio
    async def test_wrong_driver_returns_none(self, mock_db):
        created = await file_dispute(mock_db, 1, DisputeType.OTHER, "A" * 25, None, None)
        result = await get_dispute(mock_db, driver_id=2, dispute_id=created["id"])
        assert result is None


# ---------------------------------------------------------------------------
# Service: appeal_decision
# ---------------------------------------------------------------------------


class TestAppealDecision:
    @pytest.mark.asyncio
    async def test_appeal_success(self, mock_db):
        d = await file_dispute(mock_db, 1, DisputeType.FALSE_COMPLAINT, "A" * 30, None, None)
        # Manually set status to RESOLVED_AGAINST_DRIVER
        from app.services.driver_dispute import _disputes
        _disputes[d["id"]]["status"] = DisputeStatus.RESOLVED_AGAINST_DRIVER

        result = await appeal_decision(mock_db, driver_id=1, dispute_id=d["id"], appeal_reason="A" * 30)
        assert result["status"] == DisputeStatus.PENDING_APPEAL
        assert result["appeal_reason"] is not None
        assert result["appeal_filed_at"] is not None

    @pytest.mark.asyncio
    async def test_appeal_wrong_status_raises_value_error(self, mock_db):
        d = await file_dispute(mock_db, 1, DisputeType.OTHER, "A" * 25, None, None)
        # Still OPEN — cannot appeal
        with pytest.raises(ValueError, match="RESOLVED_AGAINST_DRIVER"):
            await appeal_decision(mock_db, driver_id=1, dispute_id=d["id"], appeal_reason="A" * 30)

    @pytest.mark.asyncio
    async def test_appeal_wrong_driver_raises_permission_error(self, mock_db):
        d = await file_dispute(mock_db, 1, DisputeType.OTHER, "A" * 25, None, None)
        with pytest.raises(PermissionError):
            await appeal_decision(mock_db, driver_id=2, dispute_id=d["id"], appeal_reason="A" * 30)

    @pytest.mark.asyncio
    async def test_appeal_nonexistent_dispute_raises_permission_error(self, mock_db):
        with pytest.raises(PermissionError):
            await appeal_decision(mock_db, driver_id=1, dispute_id=9999, appeal_reason="A" * 30)

    @pytest.mark.asyncio
    async def test_appeal_sets_updated_at(self, mock_db):
        d = await file_dispute(mock_db, 1, DisputeType.FALSE_COMPLAINT, "A" * 30, None, None)
        from app.services.driver_dispute import _disputes
        _disputes[d["id"]]["status"] = DisputeStatus.RESOLVED_AGAINST_DRIVER

        before = _utc_now()
        result = await appeal_decision(mock_db, driver_id=1, dispute_id=d["id"], appeal_reason="A" * 30)
        after = _utc_now()
        assert before <= result["updated_at"] <= after


# ---------------------------------------------------------------------------
# Service: withdraw_dispute
# ---------------------------------------------------------------------------


class TestWithdrawDispute:
    @pytest.mark.asyncio
    async def test_withdraw_open_dispute(self, mock_db):
        d = await file_dispute(mock_db, 1, DisputeType.OTHER, "A" * 25, None, None)
        result = await withdraw_dispute(mock_db, driver_id=1, dispute_id=d["id"])
        assert result["status"] == DisputeStatus.WITHDRAWN

    @pytest.mark.asyncio
    async def test_withdraw_under_review_dispute(self, mock_db):
        d = await file_dispute(mock_db, 1, DisputeType.OTHER, "A" * 25, None, None)
        from app.services.driver_dispute import _disputes
        _disputes[d["id"]]["status"] = DisputeStatus.UNDER_REVIEW

        result = await withdraw_dispute(mock_db, driver_id=1, dispute_id=d["id"])
        assert result["status"] == DisputeStatus.WITHDRAWN

    @pytest.mark.asyncio
    async def test_withdraw_resolved_raises_value_error(self, mock_db):
        d = await file_dispute(mock_db, 1, DisputeType.OTHER, "A" * 25, None, None)
        from app.services.driver_dispute import _disputes
        _disputes[d["id"]]["status"] = DisputeStatus.RESOLVED_IN_DRIVER_FAVOR

        with pytest.raises(ValueError, match="OPEN or UNDER_REVIEW"):
            await withdraw_dispute(mock_db, driver_id=1, dispute_id=d["id"])

    @pytest.mark.asyncio
    async def test_withdraw_pending_appeal_raises_value_error(self, mock_db):
        d = await file_dispute(mock_db, 1, DisputeType.OTHER, "A" * 25, None, None)
        from app.services.driver_dispute import _disputes
        _disputes[d["id"]]["status"] = DisputeStatus.PENDING_APPEAL

        with pytest.raises(ValueError):
            await withdraw_dispute(mock_db, driver_id=1, dispute_id=d["id"])

    @pytest.mark.asyncio
    async def test_withdraw_wrong_driver_raises_permission_error(self, mock_db):
        d = await file_dispute(mock_db, 1, DisputeType.OTHER, "A" * 25, None, None)
        with pytest.raises(PermissionError):
            await withdraw_dispute(mock_db, driver_id=2, dispute_id=d["id"])

    @pytest.mark.asyncio
    async def test_withdraw_nonexistent_raises_permission_error(self, mock_db):
        with pytest.raises(PermissionError):
            await withdraw_dispute(mock_db, driver_id=1, dispute_id=9999)


# ---------------------------------------------------------------------------
# Service: admin_list_disputes
# ---------------------------------------------------------------------------


class TestAdminListDisputes:
    @pytest.mark.asyncio
    async def test_empty_store(self, mock_db):
        total, items = await admin_list_disputes(mock_db, None, None, 0, 20)
        assert total == 0
        assert items == []

    @pytest.mark.asyncio
    async def test_returns_all_disputes(self, mock_db):
        await file_dispute(mock_db, 1, DisputeType.OTHER, "A" * 25, None, None)
        await file_dispute(mock_db, 2, DisputeType.FARE_ADJUSTMENT, "B" * 25, None, None)
        total, items = await admin_list_disputes(mock_db, None, None, 0, 20)
        assert total == 2

    @pytest.mark.asyncio
    async def test_filter_by_status(self, mock_db):
        d1 = await file_dispute(mock_db, 1, DisputeType.OTHER, "A" * 25, None, None)
        await withdraw_dispute(mock_db, 1, d1["id"])
        await file_dispute(mock_db, 2, DisputeType.OTHER, "B" * 25, None, None)

        total, items = await admin_list_disputes(mock_db, DisputeStatus.OPEN, None, 0, 20)
        assert total == 1
        assert items[0]["status"] == DisputeStatus.OPEN

    @pytest.mark.asyncio
    async def test_filter_by_type(self, mock_db):
        await file_dispute(mock_db, 1, DisputeType.FARE_ADJUSTMENT, "A" * 30, None, None)
        await file_dispute(mock_db, 2, DisputeType.OTHER, "B" * 25, None, None)
        await file_dispute(mock_db, 3, DisputeType.FARE_ADJUSTMENT, "C" * 30, None, None)

        total, items = await admin_list_disputes(mock_db, None, DisputeType.FARE_ADJUSTMENT, 0, 20)
        assert total == 2
        assert all(d["dispute_type"] == DisputeType.FARE_ADJUSTMENT for d in items)

    @pytest.mark.asyncio
    async def test_filter_by_status_and_type(self, mock_db):
        d1 = await file_dispute(mock_db, 1, DisputeType.FARE_ADJUSTMENT, "A" * 30, None, None)
        await file_dispute(mock_db, 2, DisputeType.FARE_ADJUSTMENT, "B" * 30, None, None)
        await withdraw_dispute(mock_db, 1, d1["id"])

        total, items = await admin_list_disputes(
            mock_db, DisputeStatus.OPEN, DisputeType.FARE_ADJUSTMENT, 0, 20
        )
        assert total == 1
        assert items[0]["status"] == DisputeStatus.OPEN

    @pytest.mark.asyncio
    async def test_pagination(self, mock_db):
        for i in range(5):
            await file_dispute(mock_db, i, DisputeType.OTHER, f"Dispute {i} needs resolution.", None, None)
        total, items = await admin_list_disputes(mock_db, None, None, 2, 2)
        assert total == 5
        assert len(items) == 2


# ---------------------------------------------------------------------------
# Service: admin_resolve_dispute
# ---------------------------------------------------------------------------


class TestAdminResolveDispute:
    @pytest.mark.asyncio
    async def test_resolve_in_driver_favor(self, mock_db):
        d = await file_dispute(mock_db, 1, DisputeType.FALSE_COMPLAINT, "A" * 30, None, None)
        result = await admin_resolve_dispute(
            mock_db, d["id"], DisputeStatus.RESOLVED_IN_DRIVER_FAVOR, "Rider complaint unverified.", admin_id=99
        )
        assert result["status"] == DisputeStatus.RESOLVED_IN_DRIVER_FAVOR
        assert result["admin_notes"] == "Rider complaint unverified."
        assert result["resolution_at"] is not None

    @pytest.mark.asyncio
    async def test_resolve_dismissed(self, mock_db):
        d = await file_dispute(mock_db, 1, DisputeType.OTHER, "A" * 25, None, None)
        result = await admin_resolve_dispute(
            mock_db, d["id"], DisputeStatus.DISMISSED, None, admin_id=99
        )
        assert result["status"] == DisputeStatus.DISMISSED

    @pytest.mark.asyncio
    async def test_resolve_against_driver_on_open_dispute(self, mock_db):
        d = await file_dispute(mock_db, 1, DisputeType.FARE_ADJUSTMENT, "A" * 30, None, None)
        result = await admin_resolve_dispute(
            mock_db, d["id"], DisputeStatus.RESOLVED_AGAINST_DRIVER, "Evidence reviewed.", admin_id=99
        )
        assert result["status"] == DisputeStatus.RESOLVED_AGAINST_DRIVER

    @pytest.mark.asyncio
    async def test_resolve_against_driver_on_pending_appeal_raises_value_error(self, mock_db):
        d = await file_dispute(mock_db, 1, DisputeType.OTHER, "A" * 25, None, None)
        from app.services.driver_dispute import _disputes
        _disputes[d["id"]]["status"] = DisputeStatus.PENDING_APPEAL

        with pytest.raises(ValueError, match="PENDING_APPEAL"):
            await admin_resolve_dispute(
                mock_db, d["id"], DisputeStatus.RESOLVED_AGAINST_DRIVER, None, admin_id=99
            )

    @pytest.mark.asyncio
    async def test_resolve_pending_appeal_in_driver_favor(self, mock_db):
        d = await file_dispute(mock_db, 1, DisputeType.OTHER, "A" * 25, None, None)
        from app.services.driver_dispute import _disputes
        _disputes[d["id"]]["status"] = DisputeStatus.PENDING_APPEAL

        result = await admin_resolve_dispute(
            mock_db, d["id"], DisputeStatus.RESOLVED_IN_DRIVER_FAVOR, "Appeal upheld.", admin_id=99
        )
        assert result["status"] == DisputeStatus.RESOLVED_IN_DRIVER_FAVOR

    @pytest.mark.asyncio
    async def test_resolve_nonexistent_raises_key_error(self, mock_db):
        with pytest.raises(KeyError):
            await admin_resolve_dispute(mock_db, 9999, DisputeStatus.DISMISSED, None, admin_id=99)

    @pytest.mark.asyncio
    async def test_invalid_resolution_raises_value_error(self, mock_db):
        d = await file_dispute(mock_db, 1, DisputeType.OTHER, "A" * 25, None, None)
        with pytest.raises(ValueError):
            await admin_resolve_dispute(
                mock_db, d["id"], DisputeStatus.OPEN, None, admin_id=99
            )

    @pytest.mark.asyncio
    async def test_resolve_sets_resolution_at(self, mock_db):
        d = await file_dispute(mock_db, 1, DisputeType.OTHER, "A" * 25, None, None)
        before = _utc_now()
        result = await admin_resolve_dispute(
            mock_db, d["id"], DisputeStatus.DISMISSED, None, admin_id=99
        )
        after = _utc_now()
        assert before <= result["resolution_at"] <= after


# ---------------------------------------------------------------------------
# Router tests
# ---------------------------------------------------------------------------


class TestFileDisputeRouter:
    @pytest.mark.asyncio
    async def test_router_delegates_to_service(self):
        mock_user = MagicMock()
        mock_user.id = 5

        expected = _make_dispute_dict(id=1, driver_id=5)

        with patch(
            "app.api.v1.driver_dispute.file_dispute",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_svc:
            from app.api.v1.driver_dispute import post_file_dispute

            body = FileDisputeRequest(
                dispute_type=DisputeType.FARE_ADJUSTMENT,
                description="The fare was adjusted without notice or explanation.",
            )
            result = await post_file_dispute(body=body, driver=mock_user, db=AsyncMock())

        mock_svc.assert_called_once()
        assert result.driver_id == 5


class TestListDisputesRouter:
    @pytest.mark.asyncio
    async def test_router_returns_list_response(self):
        mock_user = MagicMock()
        mock_user.id = 7

        with patch(
            "app.api.v1.driver_dispute.list_driver_disputes",
            new_callable=AsyncMock,
            return_value=(0, []),
        ):
            from app.api.v1.driver_dispute import get_list_driver_disputes

            result = await get_list_driver_disputes(
                status=None, skip=0, limit=20, driver=mock_user, db=AsyncMock()
            )

        assert isinstance(result, DisputeListResponse)
        assert result.total == 0


class TestGetOneDisputeRouter:
    @pytest.mark.asyncio
    async def test_found_returns_response(self):
        mock_user = MagicMock()
        mock_user.id = 1
        d = _make_dispute_dict(id=10, driver_id=1)

        with patch(
            "app.api.v1.driver_dispute.get_dispute",
            new_callable=AsyncMock,
            return_value=d,
        ):
            from app.api.v1.driver_dispute import get_one_dispute

            result = await get_one_dispute(dispute_id=10, driver=mock_user, db=AsyncMock())

        assert result.id == 10

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        from fastapi import HTTPException

        mock_user = MagicMock()
        mock_user.id = 1

        with patch(
            "app.api.v1.driver_dispute.get_dispute",
            new_callable=AsyncMock,
            return_value=None,
        ):
            from app.api.v1.driver_dispute import get_one_dispute

            with pytest.raises(HTTPException) as exc_info:
                await get_one_dispute(dispute_id=999, driver=mock_user, db=AsyncMock())

        assert exc_info.value.status_code == 404


class TestAppealDisputeRouter:
    @pytest.mark.asyncio
    async def test_appeal_success(self):
        mock_user = MagicMock()
        mock_user.id = 1
        d = _make_dispute_dict(
            id=1,
            driver_id=1,
            status=DisputeStatus.PENDING_APPEAL,
            appeal_reason="The decision was wrong.",
        )

        with patch(
            "app.api.v1.driver_dispute.appeal_decision",
            new_callable=AsyncMock,
            return_value=d,
        ):
            from app.api.v1.driver_dispute import post_appeal_dispute

            body = AppealDecisionRequest(appeal_reason="The decision was unfair and unsupported.")
            result = await post_appeal_dispute(
                dispute_id=1, body=body, driver=mock_user, db=AsyncMock()
            )

        assert result.status == DisputeStatus.PENDING_APPEAL

    @pytest.mark.asyncio
    async def test_wrong_status_returns_400(self):
        from fastapi import HTTPException

        mock_user = MagicMock()
        mock_user.id = 1

        with patch(
            "app.api.v1.driver_dispute.appeal_decision",
            new_callable=AsyncMock,
            side_effect=ValueError("Cannot appeal"),
        ):
            from app.api.v1.driver_dispute import post_appeal_dispute

            body = AppealDecisionRequest(appeal_reason="A" * 30)
            with pytest.raises(HTTPException) as exc_info:
                await post_appeal_dispute(dispute_id=1, body=body, driver=mock_user, db=AsyncMock())

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_wrong_owner_returns_404(self):
        from fastapi import HTTPException

        mock_user = MagicMock()
        mock_user.id = 2

        with patch(
            "app.api.v1.driver_dispute.appeal_decision",
            new_callable=AsyncMock,
            side_effect=PermissionError("Not owner"),
        ):
            from app.api.v1.driver_dispute import post_appeal_dispute

            body = AppealDecisionRequest(appeal_reason="A" * 30)
            with pytest.raises(HTTPException) as exc_info:
                await post_appeal_dispute(dispute_id=1, body=body, driver=mock_user, db=AsyncMock())

        assert exc_info.value.status_code == 404


class TestWithdrawDisputeRouter:
    @pytest.mark.asyncio
    async def test_withdraw_success(self):
        mock_user = MagicMock()
        mock_user.id = 1
        d = _make_dispute_dict(id=1, driver_id=1, status=DisputeStatus.WITHDRAWN)

        with patch(
            "app.api.v1.driver_dispute.withdraw_dispute",
            new_callable=AsyncMock,
            return_value=d,
        ):
            from app.api.v1.driver_dispute import delete_withdraw_dispute

            result = await delete_withdraw_dispute(dispute_id=1, driver=mock_user, db=AsyncMock())

        assert result.status == DisputeStatus.WITHDRAWN

    @pytest.mark.asyncio
    async def test_wrong_status_returns_400(self):
        from fastapi import HTTPException

        mock_user = MagicMock()
        mock_user.id = 1

        with patch(
            "app.api.v1.driver_dispute.withdraw_dispute",
            new_callable=AsyncMock,
            side_effect=ValueError("Cannot withdraw"),
        ):
            from app.api.v1.driver_dispute import delete_withdraw_dispute

            with pytest.raises(HTTPException) as exc_info:
                await delete_withdraw_dispute(dispute_id=1, driver=mock_user, db=AsyncMock())

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_wrong_owner_returns_404(self):
        from fastapi import HTTPException

        mock_user = MagicMock()
        mock_user.id = 2

        with patch(
            "app.api.v1.driver_dispute.withdraw_dispute",
            new_callable=AsyncMock,
            side_effect=PermissionError("Not owner"),
        ):
            from app.api.v1.driver_dispute import delete_withdraw_dispute

            with pytest.raises(HTTPException) as exc_info:
                await delete_withdraw_dispute(dispute_id=1, driver=mock_user, db=AsyncMock())

        assert exc_info.value.status_code == 404


class TestAdminListDisputesRouter:
    @pytest.mark.asyncio
    async def test_returns_list_response(self):
        mock_admin = MagicMock()
        mock_admin.id = 99
        d = _make_dispute_dict()

        with patch(
            "app.api.v1.driver_dispute.admin_list_disputes",
            new_callable=AsyncMock,
            return_value=(1, [d]),
        ):
            from app.api.v1.driver_dispute import admin_get_disputes

            result = await admin_get_disputes(
                status=None, dispute_type=None, skip=0, limit=20,
                admin=mock_admin, db=AsyncMock()
            )

        assert isinstance(result, DisputeListResponse)
        assert result.total == 1

    @pytest.mark.asyncio
    async def test_passes_filters_to_service(self):
        mock_admin = MagicMock()
        mock_admin.id = 99

        with patch(
            "app.api.v1.driver_dispute.admin_list_disputes",
            new_callable=AsyncMock,
            return_value=(0, []),
        ) as mock_svc:
            from app.api.v1.driver_dispute import admin_get_disputes

            await admin_get_disputes(
                status=DisputeStatus.OPEN,
                dispute_type=DisputeType.FARE_ADJUSTMENT,
                skip=0,
                limit=20,
                admin=mock_admin,
                db=AsyncMock(),
            )

        mock_svc.assert_called_once()
        call_kwargs = mock_svc.call_args.kwargs
        assert call_kwargs["status_filter"] == DisputeStatus.OPEN
        assert call_kwargs["dispute_type_filter"] == DisputeType.FARE_ADJUSTMENT


class TestAdminResolveDisputeRouter:
    @pytest.mark.asyncio
    async def test_resolve_success(self):
        mock_admin = MagicMock()
        mock_admin.id = 99
        d = _make_dispute_dict(status=DisputeStatus.RESOLVED_IN_DRIVER_FAVOR)

        with patch(
            "app.api.v1.driver_dispute.admin_resolve_dispute",
            new_callable=AsyncMock,
            return_value=d,
        ):
            from app.api.v1.driver_dispute import admin_post_resolve_dispute

            body = ResolveDisputeRequest(resolution=DisputeStatus.RESOLVED_IN_DRIVER_FAVOR)
            result = await admin_post_resolve_dispute(
                dispute_id=1, body=body, admin=mock_admin, db=AsyncMock()
            )

        assert result.status == DisputeStatus.RESOLVED_IN_DRIVER_FAVOR

    @pytest.mark.asyncio
    async def test_invalid_resolution_returns_422(self):
        from fastapi import HTTPException

        mock_admin = MagicMock()
        mock_admin.id = 99

        with patch(
            "app.api.v1.driver_dispute.admin_resolve_dispute",
            new_callable=AsyncMock,
        ):
            from app.api.v1.driver_dispute import admin_post_resolve_dispute

            # OPEN is not a valid resolution status
            body = ResolveDisputeRequest(resolution=DisputeStatus.OPEN)
            with pytest.raises(HTTPException) as exc_info:
                await admin_post_resolve_dispute(
                    dispute_id=1, body=body, admin=mock_admin, db=AsyncMock()
                )

        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_nonexistent_dispute_returns_404(self):
        from fastapi import HTTPException

        mock_admin = MagicMock()
        mock_admin.id = 99

        with patch(
            "app.api.v1.driver_dispute.admin_resolve_dispute",
            new_callable=AsyncMock,
            side_effect=KeyError("not found"),
        ):
            from app.api.v1.driver_dispute import admin_post_resolve_dispute

            body = ResolveDisputeRequest(resolution=DisputeStatus.DISMISSED)
            with pytest.raises(HTTPException) as exc_info:
                await admin_post_resolve_dispute(
                    dispute_id=9999, body=body, admin=mock_admin, db=AsyncMock()
                )

        assert exc_info.value.status_code == 404
