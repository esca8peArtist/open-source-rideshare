"""Tests for fare splitting — splitting ride costs between multiple participants."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.fare_split import FareSplit, SplitStatus
from app.models.ride import Ride, RideStatus
from app.models.user import User, UserRole
from app.schemas.fare_split import (
    CreateFareSplitRequest,
    FareSplitDetailResponse,
    FareSplitResponse,
    RespondToSplitRequest,
    SplitParticipant,
    SplitPaymentResponse,
)
from app.services.fare_splitting import (
    MAX_SPLIT_PARTICIPANTS,
    cancel_fare_split,
    create_fare_split,
    create_split_payment,
    expire_pending_splits,
    get_fare_split,
    handle_split_payment_succeeded,
    respond_to_split,
    update_split_amounts_for_actual_fare,
    _split_to_dict,
)


# ===========================================================================
# FareSplit Model Tests
# ===========================================================================


class TestFareSplitModel:
    def test_table_name(self):
        assert FareSplit.__tablename__ == "fare_splits"

    def test_has_id_column(self):
        cols = {c.name for c in FareSplit.__table__.columns}
        assert "id" in cols

    def test_has_ride_id_column(self):
        cols = {c.name for c in FareSplit.__table__.columns}
        assert "ride_id" in cols

    def test_has_user_id_column(self):
        cols = {c.name for c in FareSplit.__table__.columns}
        assert "user_id" in cols

    def test_has_invite_phone_column(self):
        cols = {c.name for c in FareSplit.__table__.columns}
        assert "invite_phone" in cols

    def test_has_invite_email_column(self):
        cols = {c.name for c in FareSplit.__table__.columns}
        assert "invite_email" in cols

    def test_has_is_initiator_column(self):
        cols = {c.name for c in FareSplit.__table__.columns}
        assert "is_initiator" in cols

    def test_has_status_column(self):
        cols = {c.name for c in FareSplit.__table__.columns}
        assert "status" in cols

    def test_has_share_amount_column(self):
        cols = {c.name for c in FareSplit.__table__.columns}
        assert "share_amount" in cols

    def test_has_share_percentage_column(self):
        cols = {c.name for c in FareSplit.__table__.columns}
        assert "share_percentage" in cols

    def test_has_stripe_payment_intent_id_column(self):
        cols = {c.name for c in FareSplit.__table__.columns}
        assert "stripe_payment_intent_id" in cols

    def test_has_created_at_column(self):
        cols = {c.name for c in FareSplit.__table__.columns}
        assert "created_at" in cols

    def test_has_responded_at_column(self):
        cols = {c.name for c in FareSplit.__table__.columns}
        assert "responded_at" in cols

    def test_ride_id_is_indexed(self):
        col = FareSplit.__table__.columns["ride_id"]
        assert col.index is True

    def test_user_id_is_indexed(self):
        col = FareSplit.__table__.columns["user_id"]
        assert col.index is True

    def test_ride_id_has_fk(self):
        col = FareSplit.__table__.columns["ride_id"]
        fk_targets = [fk.target_fullname for fk in col.foreign_keys]
        assert "rides.id" in fk_targets

    def test_user_id_has_fk(self):
        col = FareSplit.__table__.columns["user_id"]
        fk_targets = [fk.target_fullname for fk in col.foreign_keys]
        assert "users.id" in fk_targets

    def test_user_id_nullable(self):
        col = FareSplit.__table__.columns["user_id"]
        assert col.nullable is True

    def test_invite_phone_nullable(self):
        col = FareSplit.__table__.columns["invite_phone"]
        assert col.nullable is True

    def test_invite_email_nullable(self):
        col = FareSplit.__table__.columns["invite_email"]
        assert col.nullable is True


# ===========================================================================
# SplitStatus Enum Tests
# ===========================================================================


class TestSplitStatusEnum:
    def test_pending_value(self):
        assert SplitStatus.PENDING.value == "pending"

    def test_accepted_value(self):
        assert SplitStatus.ACCEPTED.value == "accepted"

    def test_declined_value(self):
        assert SplitStatus.DECLINED.value == "declined"

    def test_paid_value(self):
        assert SplitStatus.PAID.value == "paid"

    def test_expired_value(self):
        assert SplitStatus.EXPIRED.value == "expired"

    def test_cancelled_value(self):
        assert SplitStatus.CANCELLED.value == "cancelled"

    def test_all_statuses_present(self):
        expected = {"pending", "accepted", "declined", "paid", "expired", "cancelled"}
        actual = {s.value for s in SplitStatus}
        assert actual == expected

    def test_status_is_str_enum(self):
        assert isinstance(SplitStatus.PENDING, str)
        assert SplitStatus.PENDING == "pending"


# ===========================================================================
# Schema Tests
# ===========================================================================


class TestSplitParticipantSchema:
    def test_valid_with_user_id(self):
        p = SplitParticipant(user_id=1)
        assert p.user_id == 1

    def test_valid_with_phone(self):
        p = SplitParticipant(phone="+15551234567")
        assert p.phone == "+15551234567"

    def test_valid_with_email(self):
        p = SplitParticipant(email="test@example.com")
        assert p.email == "test@example.com"

    def test_valid_with_custom_percentage(self):
        p = SplitParticipant(user_id=1, share_percentage=33.33)
        assert p.share_percentage == 33.33

    def test_percentage_zero_rejected(self):
        with pytest.raises(Exception):
            SplitParticipant(user_id=1, share_percentage=0)

    def test_percentage_negative_rejected(self):
        with pytest.raises(Exception):
            SplitParticipant(user_id=1, share_percentage=-10)

    def test_percentage_over_100_rejected(self):
        with pytest.raises(Exception):
            SplitParticipant(user_id=1, share_percentage=101)

    def test_percentage_100_is_valid(self):
        p = SplitParticipant(user_id=1, share_percentage=100)
        assert p.share_percentage == 100

    def test_none_percentage_is_valid(self):
        p = SplitParticipant(user_id=1, share_percentage=None)
        assert p.share_percentage is None


class TestCreateFareSplitRequestSchema:
    def test_valid_equal_split(self):
        req = CreateFareSplitRequest(
            participants=[SplitParticipant(user_id=2)],
            split_equally=True,
        )
        assert req.split_equally is True
        assert len(req.participants) == 1

    def test_valid_multiple_participants(self):
        req = CreateFareSplitRequest(
            participants=[
                SplitParticipant(user_id=2),
                SplitParticipant(user_id=3),
            ],
        )
        assert len(req.participants) == 2

    def test_empty_participants_rejected(self):
        with pytest.raises(Exception):
            CreateFareSplitRequest(participants=[])

    def test_too_many_participants_rejected(self):
        with pytest.raises(Exception):
            CreateFareSplitRequest(
                participants=[SplitParticipant(user_id=i) for i in range(5)]
            )

    def test_participant_without_identifier_rejected(self):
        with pytest.raises(Exception):
            CreateFareSplitRequest(
                participants=[SplitParticipant()]
            )

    def test_default_split_equally_true(self):
        req = CreateFareSplitRequest(
            participants=[SplitParticipant(user_id=2)],
        )
        assert req.split_equally is True

    def test_four_participants_valid(self):
        req = CreateFareSplitRequest(
            participants=[SplitParticipant(user_id=i) for i in range(2, 6)],
        )
        assert len(req.participants) == 4


class TestFareSplitResponseSchema:
    def test_from_attributes(self):
        assert FareSplitResponse.model_config.get("from_attributes") is True


class TestRespondToSplitRequestSchema:
    def test_accept(self):
        req = RespondToSplitRequest(accept=True)
        assert req.accept is True

    def test_decline(self):
        req = RespondToSplitRequest(accept=False)
        assert req.accept is False


class TestSplitPaymentResponseSchema:
    def test_valid(self):
        resp = SplitPaymentResponse(
            split_id=1,
            share_amount=10.50,
            client_secret="cs_test_123",
            payment_intent_id="pi_test_123",
            status="pending",
        )
        assert resp.split_id == 1
        assert resp.share_amount == 10.50


# ===========================================================================
# Service Tests — create_fare_split
# ===========================================================================


def _make_ride(ride_id=1, rider_id=1, status=RideStatus.IN_PROGRESS,
               estimated_fare=20.0, actual_fare=None):
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.status = status
    ride.estimated_fare = estimated_fare
    ride.actual_fare = actual_fare
    return ride


def _make_user(user_id=1, phone="+15551111111", email="user@test.com"):
    user = MagicMock(spec=User)
    user.id = user_id
    user.phone = phone
    user.email = email
    return user


def _make_db_session(ride=None, existing_splits=None, found_user=None):
    """Create a mock async DB session with configurable query results."""
    db = AsyncMock()
    call_count = 0

    async def mock_execute(stmt):
        nonlocal call_count
        result = MagicMock()

        # First query: ride lookup
        if call_count == 0:
            result.scalar_one_or_none.return_value = ride
            call_count += 1
            return result

        # Second query: existing splits check
        if call_count == 1:
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = existing_splits or []
            result.scalars.return_value = mock_scalars
            call_count += 1
            return result

        # Subsequent queries: user lookups
        result.scalar_one_or_none.return_value = found_user
        call_count += 1
        return result

    db.execute = AsyncMock(side_effect=mock_execute)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


class TestCreateFareSplit:
    @pytest.mark.asyncio
    async def test_ride_not_found(self):
        db = _make_db_session(ride=None)
        result = await create_fare_split(1, 1, [{"user_id": 2}], True, db)
        assert result == {"error": "Ride not found"}

    @pytest.mark.asyncio
    async def test_not_ride_initiator(self):
        ride = _make_ride(rider_id=99)
        db = _make_db_session(ride=ride)
        result = await create_fare_split(1, 1, [{"user_id": 2}], True, db)
        assert result == {"error": "Only the ride initiator can create a fare split"}

    @pytest.mark.asyncio
    async def test_cancelled_ride_rejected(self):
        ride = _make_ride(status=RideStatus.CANCELLED)
        db = _make_db_session(ride=ride)
        result = await create_fare_split(1, 1, [{"user_id": 2}], True, db)
        assert "Cannot split fare" in result["error"]

    @pytest.mark.asyncio
    async def test_existing_split_rejected(self):
        ride = _make_ride()
        existing = [MagicMock()]
        db = _make_db_session(ride=ride, existing_splits=existing)
        result = await create_fare_split(1, 1, [{"user_id": 2}], True, db)
        assert "already exists" in result["error"]

    @pytest.mark.asyncio
    async def test_too_many_participants(self):
        ride = _make_ride()
        db = _make_db_session(ride=ride)
        participants = [{"user_id": i} for i in range(2, 7)]  # 5 + initiator = 6 > 5
        result = await create_fare_split(1, 1, participants, True, db)
        assert "Cannot split with more than" in result["error"]

    @pytest.mark.asyncio
    async def test_equal_split_two_people(self):
        ride = _make_ride(estimated_fare=20.0)
        db = _make_db_session(ride=ride)
        result = await create_fare_split(1, 1, [{"user_id": 2}], True, db)
        assert "error" not in result
        assert result["split_count"] == 2
        assert result["total_fare"] == 20.0

    @pytest.mark.asyncio
    async def test_equal_split_three_people(self):
        ride = _make_ride(estimated_fare=30.0)
        db = _make_db_session(ride=ride)
        result = await create_fare_split(
            1, 1, [{"user_id": 2}, {"user_id": 3}], True, db
        )
        assert result["split_count"] == 3

    @pytest.mark.asyncio
    async def test_uses_actual_fare_when_available(self):
        ride = _make_ride(estimated_fare=20.0, actual_fare=25.0)
        db = _make_db_session(ride=ride)
        result = await create_fare_split(1, 1, [{"user_id": 2}], True, db)
        assert result["total_fare"] == 25.0

    @pytest.mark.asyncio
    async def test_custom_split_percentages(self):
        ride = _make_ride(estimated_fare=100.0)
        db = _make_db_session(ride=ride)
        participants = [
            {"user_id": 2, "share_percentage": 30},
            {"user_id": 3, "share_percentage": 20},
        ]
        result = await create_fare_split(1, 1, participants, False, db)
        assert "error" not in result
        assert result["split_count"] == 3

    @pytest.mark.asyncio
    async def test_custom_split_exceeding_100_rejected(self):
        ride = _make_ride(estimated_fare=100.0)
        db = _make_db_session(ride=ride)
        participants = [
            {"user_id": 2, "share_percentage": 60},
            {"user_id": 3, "share_percentage": 50},
        ]
        result = await create_fare_split(1, 1, participants, False, db)
        assert "exceed 100%" in result["error"]

    @pytest.mark.asyncio
    async def test_custom_split_zero_initiator_rejected(self):
        ride = _make_ride(estimated_fare=100.0)
        db = _make_db_session(ride=ride)
        participants = [{"user_id": 2, "share_percentage": 100}]
        result = await create_fare_split(1, 1, participants, False, db)
        assert "greater than 0%" in result["error"]

    @pytest.mark.asyncio
    async def test_custom_split_missing_percentage_rejected(self):
        ride = _make_ride(estimated_fare=100.0)
        db = _make_db_session(ride=ride)
        participants = [{"user_id": 2, "share_percentage": None}]
        result = await create_fare_split(1, 1, participants, False, db)
        assert "valid share_percentage" in result["error"]

    @pytest.mark.asyncio
    async def test_initiator_auto_accepted(self):
        ride = _make_ride(estimated_fare=20.0)
        db = _make_db_session(ride=ride)
        result = await create_fare_split(1, 1, [{"user_id": 2}], True, db)
        initiator = next(s for s in result["splits"] if s["is_initiator"])
        assert initiator["status"] == "accepted"

    @pytest.mark.asyncio
    async def test_participant_starts_pending(self):
        ride = _make_ride(estimated_fare=20.0)
        db = _make_db_session(ride=ride)
        result = await create_fare_split(1, 1, [{"user_id": 2}], True, db)
        participant = next(s for s in result["splits"] if not s["is_initiator"])
        assert participant["status"] == "pending"

    @pytest.mark.asyncio
    async def test_split_with_phone_invite(self):
        ride = _make_ride(estimated_fare=20.0)
        db = _make_db_session(ride=ride)
        result = await create_fare_split(
            1, 1, [{"phone": "+15559999999"}], True, db
        )
        assert "error" not in result
        assert result["split_count"] == 2

    @pytest.mark.asyncio
    async def test_split_with_email_invite(self):
        ride = _make_ride(estimated_fare=20.0)
        db = _make_db_session(ride=ride)
        result = await create_fare_split(
            1, 1, [{"email": "friend@test.com"}], True, db
        )
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_phone_resolved_to_user(self):
        ride = _make_ride(estimated_fare=20.0)
        found_user = _make_user(user_id=5)
        db = _make_db_session(ride=ride, found_user=found_user)
        result = await create_fare_split(
            1, 1, [{"phone": "+15559999999"}], True, db
        )
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_allowed_status_requested(self):
        ride = _make_ride(status=RideStatus.REQUESTED)
        db = _make_db_session(ride=ride)
        result = await create_fare_split(1, 1, [{"user_id": 2}], True, db)
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_allowed_status_completed(self):
        ride = _make_ride(status=RideStatus.COMPLETED, actual_fare=22.0)
        db = _make_db_session(ride=ride)
        result = await create_fare_split(1, 1, [{"user_id": 2}], True, db)
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_all_accepted_false_when_pending(self):
        ride = _make_ride(estimated_fare=20.0)
        db = _make_db_session(ride=ride)
        result = await create_fare_split(1, 1, [{"user_id": 2}], True, db)
        assert result["all_accepted"] is False

    @pytest.mark.asyncio
    async def test_all_paid_false_on_creation(self):
        ride = _make_ride(estimated_fare=20.0)
        db = _make_db_session(ride=ride)
        result = await create_fare_split(1, 1, [{"user_id": 2}], True, db)
        assert result["all_paid"] is False

    @pytest.mark.asyncio
    async def test_max_four_participants_valid(self):
        ride = _make_ride(estimated_fare=50.0)
        db = _make_db_session(ride=ride)
        participants = [{"user_id": i} for i in range(2, 6)]  # 4 participants
        result = await create_fare_split(1, 1, participants, True, db)
        assert "error" not in result
        assert result["split_count"] == 5

    @pytest.mark.asyncio
    async def test_scheduled_ride_rejected(self):
        ride = _make_ride(status=RideStatus.SCHEDULED)
        db = _make_db_session(ride=ride)
        result = await create_fare_split(1, 1, [{"user_id": 2}], True, db)
        assert "Cannot split fare" in result["error"]


# ===========================================================================
# Service Tests — get_fare_split
# ===========================================================================


class TestGetFareSplit:
    @pytest.mark.asyncio
    async def test_ride_not_found(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)
        result = await get_fare_split(1, 1, db)
        assert result == {"error": "Ride not found"}

    @pytest.mark.asyncio
    async def test_no_split_found(self):
        ride = _make_ride()
        db = AsyncMock()
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                result.scalar_one_or_none.return_value = ride
            else:
                mock_scalars = MagicMock()
                mock_scalars.all.return_value = []
                result.scalars.return_value = mock_scalars
            call_count += 1
            return result

        db.execute = AsyncMock(side_effect=mock_execute)
        result = await get_fare_split(1, 1, db)
        assert result == {"error": "No fare split found for this ride"}

    @pytest.mark.asyncio
    async def test_unauthorized_user(self):
        ride = _make_ride(rider_id=1)
        split = MagicMock(spec=FareSplit)
        split.user_id = 1
        split.is_initiator = True
        split.status = SplitStatus.ACCEPTED

        db = AsyncMock()
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                result.scalar_one_or_none.return_value = ride
            else:
                mock_scalars = MagicMock()
                mock_scalars.all.return_value = [split]
                result.scalars.return_value = mock_scalars
            call_count += 1
            return result

        db.execute = AsyncMock(side_effect=mock_execute)
        result = await get_fare_split(1, 999, db)
        assert "Not authorized" in result["error"]


# ===========================================================================
# Service Tests — respond_to_split
# ===========================================================================


class TestRespondToSplit:
    @pytest.mark.asyncio
    async def test_split_not_found(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)
        result = await respond_to_split(1, 1, True, db)
        assert result == {"error": "Fare split not found"}

    @pytest.mark.asyncio
    async def test_not_authorized(self):
        split = MagicMock(spec=FareSplit)
        split.id = 1
        split.user_id = 2
        split.is_initiator = False
        split.status = SplitStatus.PENDING

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = split
        db.execute = AsyncMock(return_value=result_mock)

        result = await respond_to_split(1, 999, True, db)
        assert result == {"error": "Not authorized to respond to this split"}

    @pytest.mark.asyncio
    async def test_initiator_cannot_respond(self):
        split = MagicMock(spec=FareSplit)
        split.id = 1
        split.user_id = 1
        split.is_initiator = True
        split.status = SplitStatus.PENDING

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = split
        db.execute = AsyncMock(return_value=result_mock)

        result = await respond_to_split(1, 1, True, db)
        assert result == {"error": "Initiator cannot respond to their own split"}

    @pytest.mark.asyncio
    async def test_already_accepted_rejected(self):
        split = MagicMock(spec=FareSplit)
        split.id = 1
        split.user_id = 2
        split.is_initiator = False
        split.status = SplitStatus.ACCEPTED

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = split
        db.execute = AsyncMock(return_value=result_mock)

        result = await respond_to_split(1, 2, True, db)
        assert "Cannot respond" in result["error"]

    @pytest.mark.asyncio
    async def test_accept_success(self):
        split = MagicMock(spec=FareSplit)
        split.id = 1
        split.ride_id = 1
        split.user_id = 2
        split.is_initiator = False
        split.status = SplitStatus.PENDING
        split.share_amount = 10.0
        split.share_percentage = 50.0
        split.invite_phone = None
        split.invite_email = None
        split.created_at = datetime(2026, 4, 12, tzinfo=timezone.utc)
        split.responded_at = None

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = split
        db.execute = AsyncMock(return_value=result_mock)
        db.commit = AsyncMock()

        result = await respond_to_split(1, 2, True, db)
        assert result["status"] == "accepted"

    @pytest.mark.asyncio
    async def test_decline_redistributes_to_initiator(self):
        split = MagicMock(spec=FareSplit)
        split.id = 2
        split.ride_id = 1
        split.user_id = 3
        split.is_initiator = False
        split.status = SplitStatus.PENDING
        split.share_amount = 10.0
        split.share_percentage = 50.0
        split.invite_phone = None
        split.invite_email = None
        split.created_at = datetime(2026, 4, 12, tzinfo=timezone.utc)
        split.responded_at = None

        initiator = MagicMock(spec=FareSplit)
        initiator.share_amount = 10.0
        initiator.share_percentage = 50.0

        db = AsyncMock()
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                result.scalar_one_or_none.return_value = split
            else:
                result.scalar_one_or_none.return_value = initiator
            call_count += 1
            return result

        db.execute = AsyncMock(side_effect=mock_execute)
        db.commit = AsyncMock()

        result = await respond_to_split(2, 3, False, db)
        assert result["status"] == "declined"
        assert initiator.share_amount == 20.0
        assert initiator.share_percentage == 100.0


# ===========================================================================
# Service Tests — create_split_payment
# ===========================================================================


class TestCreateSplitPayment:
    @pytest.mark.asyncio
    async def test_split_not_found(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)
        result = await create_split_payment(1, 1, db)
        assert result == {"error": "Fare split not found"}

    @pytest.mark.asyncio
    async def test_not_authorized(self):
        split = MagicMock(spec=FareSplit)
        split.user_id = 2
        split.status = SplitStatus.ACCEPTED

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = split
        db.execute = AsyncMock(return_value=result_mock)

        result = await create_split_payment(1, 999, db)
        assert result == {"error": "Not authorized to pay this split"}

    @pytest.mark.asyncio
    async def test_pending_split_cannot_pay(self):
        split = MagicMock(spec=FareSplit)
        split.user_id = 2
        split.status = SplitStatus.PENDING

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = split
        db.execute = AsyncMock(return_value=result_mock)

        result = await create_split_payment(1, 2, db)
        assert "must be accepted first" in result["error"]

    @pytest.mark.asyncio
    async def test_zero_amount_rejected(self):
        split = MagicMock(spec=FareSplit)
        split.user_id = 2
        split.status = SplitStatus.ACCEPTED
        split.share_amount = 0.0

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = split
        db.execute = AsyncMock(return_value=result_mock)

        result = await create_split_payment(1, 2, db)
        assert result == {"error": "No amount to pay"}

    @pytest.mark.asyncio
    async def test_existing_intent_returned(self):
        split = MagicMock(spec=FareSplit)
        split.id = 1
        split.user_id = 2
        split.status = SplitStatus.ACCEPTED
        split.share_amount = 10.0
        split.stripe_payment_intent_id = "pi_existing"

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = split
        db.execute = AsyncMock(return_value=result_mock)

        result = await create_split_payment(1, 2, db)
        assert result["payment_intent_id"] == "pi_existing"
        assert result["client_secret"] is None

    @pytest.mark.asyncio
    @patch("app.services.fare_splitting.stripe")
    async def test_payment_intent_created(self, mock_stripe):
        mock_stripe.PaymentIntent.create.return_value = MagicMock(
            id="pi_new", client_secret="cs_new"
        )

        split = MagicMock(spec=FareSplit)
        split.id = 1
        split.ride_id = 1
        split.user_id = 2
        split.status = SplitStatus.ACCEPTED
        split.share_amount = 10.0
        split.stripe_payment_intent_id = None

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = split
        db.execute = AsyncMock(return_value=result_mock)
        db.commit = AsyncMock()

        result = await create_split_payment(1, 2, db)
        assert result["payment_intent_id"] == "pi_new"
        assert result["client_secret"] == "cs_new"
        assert result["share_amount"] == 10.0
        mock_stripe.PaymentIntent.create.assert_called_once()


# ===========================================================================
# Service Tests — cancel_fare_split
# ===========================================================================


class TestCancelFareSplit:
    @pytest.mark.asyncio
    async def test_ride_not_found(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)
        result = await cancel_fare_split(1, 1, db)
        assert result == {"error": "Ride not found"}

    @pytest.mark.asyncio
    async def test_not_initiator(self):
        ride = _make_ride(rider_id=1)
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=result_mock)
        result = await cancel_fare_split(1, 999, db)
        assert "Only the ride initiator" in result["error"]

    @pytest.mark.asyncio
    async def test_no_active_split(self):
        ride = _make_ride(rider_id=1)
        db = AsyncMock()
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                result.scalar_one_or_none.return_value = ride
            else:
                mock_scalars = MagicMock()
                mock_scalars.all.return_value = []
                result.scalars.return_value = mock_scalars
            call_count += 1
            return result

        db.execute = AsyncMock(side_effect=mock_execute)
        result = await cancel_fare_split(1, 1, db)
        assert result == {"error": "No active fare split found for this ride"}

    @pytest.mark.asyncio
    async def test_cannot_cancel_if_paid(self):
        ride = _make_ride(rider_id=1)
        paid_split = MagicMock(spec=FareSplit)
        paid_split.status = SplitStatus.PAID

        db = AsyncMock()
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                result.scalar_one_or_none.return_value = ride
            else:
                mock_scalars = MagicMock()
                mock_scalars.all.return_value = [paid_split]
                result.scalars.return_value = mock_scalars
            call_count += 1
            return result

        db.execute = AsyncMock(side_effect=mock_execute)
        result = await cancel_fare_split(1, 1, db)
        assert "already paid" in result["error"]

    @pytest.mark.asyncio
    async def test_cancel_success(self):
        ride = _make_ride(rider_id=1)
        split1 = MagicMock(spec=FareSplit)
        split1.status = SplitStatus.ACCEPTED
        split2 = MagicMock(spec=FareSplit)
        split2.status = SplitStatus.PENDING

        db = AsyncMock()
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                result.scalar_one_or_none.return_value = ride
            else:
                mock_scalars = MagicMock()
                mock_scalars.all.return_value = [split1, split2]
                result.scalars.return_value = mock_scalars
            call_count += 1
            return result

        db.execute = AsyncMock(side_effect=mock_execute)
        db.commit = AsyncMock()

        result = await cancel_fare_split(1, 1, db)
        assert result["status"] == "cancelled"
        assert result["splits_cancelled"] == 2
        assert split1.status == SplitStatus.CANCELLED
        assert split2.status == SplitStatus.CANCELLED


# ===========================================================================
# Service Tests — expire_pending_splits
# ===========================================================================


class TestExpirePendingSplits:
    @pytest.mark.asyncio
    async def test_no_pending_splits(self):
        db = AsyncMock()
        result_mock = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        result_mock.scalars.return_value = mock_scalars
        db.execute = AsyncMock(return_value=result_mock)

        count = await expire_pending_splits(1, db)
        assert count == 0

    @pytest.mark.asyncio
    async def test_expires_pending_and_redistributes(self):
        pending = MagicMock(spec=FareSplit)
        pending.status = SplitStatus.PENDING
        pending.share_amount = 10.0
        pending.share_percentage = 33.33

        initiator = MagicMock(spec=FareSplit)
        initiator.share_amount = 10.0
        initiator.share_percentage = 33.33

        db = AsyncMock()
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                mock_scalars = MagicMock()
                mock_scalars.all.return_value = [pending]
                result.scalars.return_value = mock_scalars
            else:
                result.scalar_one_or_none.return_value = initiator
            call_count += 1
            return result

        db.execute = AsyncMock(side_effect=mock_execute)
        db.commit = AsyncMock()

        count = await expire_pending_splits(1, db)
        assert count == 1
        assert pending.status == SplitStatus.EXPIRED
        assert pending.share_amount == 0.0
        assert initiator.share_amount == 20.0


# ===========================================================================
# Service Tests — update_split_amounts_for_actual_fare
# ===========================================================================


class TestUpdateSplitAmountsForActualFare:
    @pytest.mark.asyncio
    async def test_no_splits_found(self):
        db = AsyncMock()
        result_mock = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        result_mock.scalars.return_value = mock_scalars
        db.execute = AsyncMock(return_value=result_mock)

        await update_split_amounts_for_actual_fare(1, 25.0, db)
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_updates_unpaid_splits(self):
        split1 = MagicMock(spec=FareSplit)
        split1.is_initiator = True
        split1.status = SplitStatus.ACCEPTED
        split1.share_percentage = 50.0
        split1.share_amount = 10.0  # old amount based on $20 fare

        split2 = MagicMock(spec=FareSplit)
        split2.is_initiator = False
        split2.status = SplitStatus.ACCEPTED
        split2.share_percentage = 50.0
        split2.share_amount = 10.0

        db = AsyncMock()
        result_mock = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [split1, split2]
        result_mock.scalars.return_value = mock_scalars
        db.execute = AsyncMock(return_value=result_mock)
        db.commit = AsyncMock()

        await update_split_amounts_for_actual_fare(1, 30.0, db)

        assert split1.share_amount == 15.0
        assert split2.share_amount == 15.0

    @pytest.mark.asyncio
    async def test_does_not_update_paid_splits(self):
        split1 = MagicMock(spec=FareSplit)
        split1.is_initiator = True
        split1.status = SplitStatus.ACCEPTED
        split1.share_percentage = 50.0
        split1.share_amount = 10.0

        split2 = MagicMock(spec=FareSplit)
        split2.is_initiator = False
        split2.status = SplitStatus.PAID
        split2.share_percentage = 50.0
        split2.share_amount = 10.0  # Already paid at old amount

        db = AsyncMock()
        result_mock = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [split1, split2]
        result_mock.scalars.return_value = mock_scalars
        db.execute = AsyncMock(return_value=result_mock)
        db.commit = AsyncMock()

        await update_split_amounts_for_actual_fare(1, 30.0, db)

        # split2 stays at paid amount ($10). The remaining $20 goes to split1
        # because: unpaid_fare = 30 - 10 = 20, split1 gets 50% of 30 = 15,
        # then rounding fix adds diff (20 - 15 = 5) to initiator → $20
        assert split1.share_amount == 20.0
        assert split2.share_amount == 10.0  # unchanged — already paid


# ===========================================================================
# Service Tests — _split_to_dict
# ===========================================================================


class TestSplitToDict:
    def test_basic_conversion(self):
        split = MagicMock(spec=FareSplit)
        split.id = 1
        split.ride_id = 10
        split.user_id = 5
        split.invite_phone = None
        split.invite_email = None
        split.is_initiator = True
        split.status = SplitStatus.ACCEPTED
        split.share_amount = 12.50
        split.share_percentage = 50.0
        split.created_at = datetime(2026, 4, 12, 10, 0, tzinfo=timezone.utc)
        split.responded_at = None

        result = _split_to_dict(split)
        assert result["id"] == 1
        assert result["ride_id"] == 10
        assert result["user_id"] == 5
        assert result["is_initiator"] is True
        assert result["status"] == "accepted"
        assert result["share_amount"] == 12.50
        assert result["share_percentage"] == 50.0
        assert result["invite_phone"] is None

    def test_with_invite_phone(self):
        split = MagicMock(spec=FareSplit)
        split.id = 2
        split.ride_id = 10
        split.user_id = None
        split.invite_phone = "+15551234567"
        split.invite_email = None
        split.is_initiator = False
        split.status = SplitStatus.PENDING
        split.share_amount = 12.50
        split.share_percentage = 50.0
        split.created_at = datetime(2026, 4, 12, 10, 0, tzinfo=timezone.utc)
        split.responded_at = None

        result = _split_to_dict(split)
        assert result["user_id"] is None
        assert result["invite_phone"] == "+15551234567"

    def test_with_responded_at(self):
        split = MagicMock(spec=FareSplit)
        split.id = 3
        split.ride_id = 10
        split.user_id = 5
        split.invite_phone = None
        split.invite_email = None
        split.is_initiator = False
        split.status = SplitStatus.ACCEPTED
        split.share_amount = 12.50
        split.share_percentage = 50.0
        split.created_at = datetime(2026, 4, 12, 10, 0, tzinfo=timezone.utc)
        split.responded_at = datetime(2026, 4, 12, 11, 0, tzinfo=timezone.utc)

        result = _split_to_dict(split)
        assert result["responded_at"] is not None


# ===========================================================================
# API Endpoint Tests
# ===========================================================================


class TestFareSplitEndpoints:
    """Test API endpoint routing and error handling."""

    def test_router_prefix(self):
        from app.api.v1.fare_splits import router
        assert router.prefix == "/fare-splits"

    def test_router_tags(self):
        from app.api.v1.fare_splits import router
        assert "fare-splits" in router.tags

    def test_routes_registered(self):
        from app.api.v1.fare_splits import router
        paths = [r.path for r in router.routes]
        assert any("rides/{ride_id}" in p for p in paths)
        assert any("{split_id}/respond" in p for p in paths)
        assert any("{split_id}/pay" in p for p in paths)
        assert any("my-splits" in p for p in paths)

    def test_create_route_is_post(self):
        from app.api.v1.fare_splits import router
        methods_found = set()
        for route in router.routes:
            if hasattr(route, "path") and "rides/{ride_id}" in route.path and hasattr(route, "methods"):
                methods_found.update(route.methods)
        assert "POST" in methods_found

    def test_get_route_exists(self):
        from app.api.v1.fare_splits import router
        methods_found = set()
        for route in router.routes:
            if hasattr(route, "path") and "rides/{ride_id}" in route.path and hasattr(route, "methods"):
                methods_found.update(route.methods)
        assert "GET" in methods_found

    def test_delete_route_exists(self):
        from app.api.v1.fare_splits import router
        methods_found = set()
        for route in router.routes:
            if hasattr(route, "path") and "rides/{ride_id}" in route.path and hasattr(route, "methods"):
                methods_found.update(route.methods)
        assert "DELETE" in methods_found

    def test_respond_route_is_post(self):
        from app.api.v1.fare_splits import router
        for route in router.routes:
            if hasattr(route, "path") and "{split_id}/respond" in route.path and hasattr(route, "methods"):
                assert "POST" in route.methods
                return
        pytest.fail("respond route not found")

    def test_pay_route_is_post(self):
        from app.api.v1.fare_splits import router
        for route in router.routes:
            if hasattr(route, "path") and "{split_id}/pay" in route.path and hasattr(route, "methods"):
                assert "POST" in route.methods
                return
        pytest.fail("pay route not found")

    def test_my_splits_route_is_get(self):
        from app.api.v1.fare_splits import router
        for route in router.routes:
            if hasattr(route, "path") and "my-splits" in route.path and hasattr(route, "methods"):
                assert "GET" in route.methods
                return
        pytest.fail("my-splits route not found")


# ===========================================================================
# App Registration Tests
# ===========================================================================


class TestAppRegistration:
    def test_fare_split_model_registered(self):
        from app.models import FareSplit as ImportedModel
        assert ImportedModel.__tablename__ == "fare_splits"

    def test_fare_split_router_in_main(self):
        from app.main import app
        paths = [r.path for r in app.routes]
        fare_split_paths = [p for p in paths if "fare-split" in p]
        assert len(fare_split_paths) > 0

    def test_router_prefix_in_app(self):
        from app.main import app
        paths = [r.path for r in app.routes]
        assert any("/api/v1/fare-splits" in p for p in paths)


# ===========================================================================
# Edge Case Tests
# ===========================================================================


class TestFareSplitEdgeCases:
    @pytest.mark.asyncio
    async def test_split_with_one_cent_fare(self):
        """Splitting a very small fare between 2 people."""
        ride = _make_ride(estimated_fare=0.01)
        db = _make_db_session(ride=ride)
        result = await create_fare_split(1, 1, [{"user_id": 2}], True, db)
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_split_with_large_fare(self):
        """Splitting a large fare."""
        ride = _make_ride(estimated_fare=999.99)
        db = _make_db_session(ride=ride)
        result = await create_fare_split(1, 1, [{"user_id": 2}], True, db)
        assert "error" not in result
        assert result["total_fare"] == 999.99

    @pytest.mark.asyncio
    async def test_split_with_odd_three_way(self):
        """$10 three-way split — tests rounding."""
        ride = _make_ride(estimated_fare=10.0)
        db = _make_db_session(ride=ride)
        result = await create_fare_split(
            1, 1, [{"user_id": 2}, {"user_id": 3}], True, db
        )
        assert "error" not in result
        assert result["split_count"] == 3

    def test_max_participants_constant(self):
        assert MAX_SPLIT_PARTICIPANTS == 5

    @pytest.mark.asyncio
    async def test_split_matched_ride(self):
        ride = _make_ride(status=RideStatus.MATCHED)
        db = _make_db_session(ride=ride)
        result = await create_fare_split(1, 1, [{"user_id": 2}], True, db)
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_split_driver_en_route(self):
        ride = _make_ride(status=RideStatus.DRIVER_EN_ROUTE)
        db = _make_db_session(ride=ride)
        result = await create_fare_split(1, 1, [{"user_id": 2}], True, db)
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_split_arrived(self):
        ride = _make_ride(status=RideStatus.ARRIVED)
        db = _make_db_session(ride=ride)
        result = await create_fare_split(1, 1, [{"user_id": 2}], True, db)
        assert "error" not in result


# ===========================================================================
# Comprehensive Unit Tests (task-specified coverage)
# ===========================================================================

# ---------------------------------------------------------------------------
# Helper factories using the _make_db pattern from test_driver_dividends.py
# ---------------------------------------------------------------------------

def _seq_scalar_one(item) -> MagicMock:
    """Result where .scalar_one_or_none() returns item."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = item
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [item] if item is not None else []
    r.scalars.return_value = scalars_mock
    return r


def _seq_scalars_list(items: list) -> MagicMock:
    """Result where .scalars().all() returns items."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = items[0] if items else None
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = items
    r.scalars.return_value = scalars_mock
    return r


def _seq_none() -> MagicMock:
    """Result that returns nothing."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = []
    r.scalars.return_value = scalars_mock
    return r


def _seq_db(*results) -> AsyncMock:
    """AsyncSession that returns results in sequence per execute() call."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(results))
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _fs_ride(
    id: int = 1,
    rider_id: int = 10,
    status: RideStatus = RideStatus.COMPLETED,
    estimated_fare: float = 40.0,
    actual_fare: float | None = None,
) -> MagicMock:
    ride = MagicMock(spec=Ride)
    ride.id = id
    ride.rider_id = rider_id
    ride.status = status
    ride.estimated_fare = estimated_fare
    ride.actual_fare = actual_fare
    return ride


def _fs_split(
    id: int = 1,
    ride_id: int = 1,
    user_id: int | None = 10,
    is_initiator: bool = True,
    status: SplitStatus = SplitStatus.ACCEPTED,
    share_amount: float = 20.0,
    share_percentage: float = 50.0,
    invite_phone: str | None = None,
    invite_email: str | None = None,
) -> MagicMock:
    s = MagicMock(spec=FareSplit)
    s.id = id
    s.ride_id = ride_id
    s.user_id = user_id
    s.is_initiator = is_initiator
    s.status = status
    s.share_amount = share_amount
    s.share_percentage = share_percentage
    s.invite_phone = invite_phone
    s.invite_email = invite_email
    s.created_at = datetime(2026, 4, 1, tzinfo=timezone.utc)
    s.responded_at = None
    s.stripe_payment_intent_id = None
    return s


# ---------------------------------------------------------------------------
# TestFareSplitSchemas — schema validation (items 1-8)
# ---------------------------------------------------------------------------

class TestFareSplitSchemas:
    def test_rejects_empty_participants_list(self):
        """1. CreateFareSplitRequest rejects empty participants list."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CreateFareSplitRequest(participants=[])

    def test_rejects_more_than_4_participants(self):
        """2. CreateFareSplitRequest rejects > 4 participants."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CreateFareSplitRequest(
                participants=[SplitParticipant(user_id=i) for i in range(1, 6)]
            )

    def test_rejects_participant_with_no_identifier(self):
        """3. CreateFareSplitRequest rejects participant with no user_id, phone, or email."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CreateFareSplitRequest(participants=[SplitParticipant()])

    def test_split_participant_rejects_zero_share_percentage(self):
        """4. SplitParticipant rejects share_percentage of 0."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            SplitParticipant(user_id=1, share_percentage=0.0)

    def test_split_participant_rejects_over_100_share_percentage(self):
        """5. SplitParticipant rejects share_percentage > 100."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            SplitParticipant(user_id=1, share_percentage=100.1)

    def test_split_participant_accepts_50_percent(self):
        """6. SplitParticipant accepts share_percentage of 50.0."""
        p = SplitParticipant(user_id=1, share_percentage=50.0)
        assert p.share_percentage == 50.0

    def test_accepts_valid_two_participant_request(self):
        """7. CreateFareSplitRequest accepts valid 2-participant split."""
        req = CreateFareSplitRequest(
            participants=[
                SplitParticipant(user_id=2),
                SplitParticipant(email="friend@example.com"),
            ]
        )
        assert len(req.participants) == 2

    def test_split_equally_defaults_to_true(self):
        """8. Defaults: split_equally=True."""
        req = CreateFareSplitRequest(participants=[SplitParticipant(user_id=2)])
        assert req.split_equally is True


# ---------------------------------------------------------------------------
# TestCreateFareSplit2 — create_fare_split service (items 9-29)
# Uses _seq_db helper for sequenced execute() results.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCreateFareSplit2:
    async def test_error_if_ride_not_found(self):
        """9. Returns error if ride not found."""
        db = _seq_db(_seq_none())
        result = await create_fare_split(99, 10, [{"user_id": 2}], True, db)
        assert "error" in result
        assert "not found" in result["error"].lower()

    async def test_error_if_not_initiator(self):
        """10. Returns error if initiator_id != ride.rider_id."""
        ride = _fs_ride(rider_id=10)
        db = _seq_db(_seq_scalar_one(ride))
        result = await create_fare_split(1, 99, [{"user_id": 2}], True, db)
        assert "error" in result
        assert "initiator" in result["error"].lower()

    async def test_error_if_ride_status_cancelled(self):
        """11/12. Returns error if ride.status is CANCELLED."""
        ride = _fs_ride(status=RideStatus.CANCELLED)
        db = _seq_db(_seq_scalar_one(ride))
        result = await create_fare_split(1, 10, [{"user_id": 2}], True, db)
        assert "error" in result
        assert "cancelled" in result["error"].lower()

    async def test_error_if_active_split_exists(self):
        """13. Returns error if an active split already exists for the ride."""
        ride = _fs_ride()
        existing = _fs_split()
        db = _seq_db(_seq_scalar_one(ride), _seq_scalars_list([existing]))
        result = await create_fare_split(1, 10, [{"user_id": 2}], True, db)
        assert "error" in result
        assert "already exists" in result["error"].lower()

    async def test_error_if_too_many_participants(self):
        """14. Returns error if total participants (including initiator) > 5."""
        ride = _fs_ride()
        db = _seq_db(_seq_scalar_one(ride), _seq_scalars_list([]))
        participants = [{"user_id": i} for i in range(2, 7)]  # 5 + initiator = 6
        result = await create_fare_split(1, 10, participants, True, db)
        assert "error" in result
        assert "4 participants" in result["error"]

    async def test_equal_split_share_amount(self):
        """15. Equal split: share_amount = fare / n_participants (rounded to 2 dp)."""
        ride = _fs_ride(estimated_fare=60.0)
        db = _seq_db(_seq_scalar_one(ride), _seq_scalars_list([]))
        result = await create_fare_split(1, 10, [{"user_id": 2}, {"user_id": 3}], True, db)
        assert "error" not in result
        for split in result["splits"]:
            assert split["share_amount"] == pytest.approx(20.0, abs=0.01)

    async def test_equal_split_share_percentage(self):
        """16. Equal split: share_percentage = 100.0 / n_participants."""
        ride = _fs_ride(estimated_fare=40.0)
        db = _seq_db(_seq_scalar_one(ride), _seq_scalars_list([]))
        result = await create_fare_split(1, 10, [{"user_id": 2}], True, db)
        assert "error" not in result
        for split in result["splits"]:
            assert split["share_percentage"] == pytest.approx(50.0, abs=0.01)

    async def test_equal_split_initiator_accepted_others_pending(self):
        """17. Equal split: initiator gets SplitStatus.ACCEPTED, others get PENDING."""
        ride = _fs_ride(estimated_fare=40.0)
        db = _seq_db(_seq_scalar_one(ride), _seq_scalars_list([]))
        result = await create_fare_split(1, 10, [{"user_id": 2}], True, db)
        assert "error" not in result
        initiator = next(s for s in result["splits"] if s["is_initiator"])
        others = [s for s in result["splits"] if not s["is_initiator"]]
        assert initiator["status"] == SplitStatus.ACCEPTED.value
        for o in others:
            assert o["status"] == SplitStatus.PENDING.value

    async def test_equal_split_initiator_flag_set(self):
        """18. Equal split: initiator has is_initiator=True."""
        ride = _fs_ride(estimated_fare=40.0)
        db = _seq_db(_seq_scalar_one(ride), _seq_scalars_list([]))
        result = await create_fare_split(1, 10, [{"user_id": 2}], True, db)
        assert "error" not in result
        initiators = [s for s in result["splits"] if s["is_initiator"]]
        assert len(initiators) == 1

    async def test_custom_split_initiator_pct_is_remainder(self):
        """19. Custom split: initiator_pct = 100 - sum(participant_pcts)."""
        ride = _fs_ride(estimated_fare=100.0)
        db = _seq_db(_seq_scalar_one(ride), _seq_scalars_list([]))
        result = await create_fare_split(
            1, 10,
            [{"user_id": 2, "share_percentage": 30.0}],
            False, db,
        )
        assert "error" not in result
        initiator = next(s for s in result["splits"] if s["is_initiator"])
        assert initiator["share_percentage"] == pytest.approx(70.0, abs=0.01)

    async def test_custom_split_error_participant_pcts_exceed_100(self):
        """20. Custom split: returns error if participant pcts sum > 100."""
        ride = _fs_ride(estimated_fare=100.0)
        db = _seq_db(_seq_scalar_one(ride), _seq_scalars_list([]))
        result = await create_fare_split(
            1, 10,
            [
                {"user_id": 2, "share_percentage": 60.0},
                {"user_id": 3, "share_percentage": 60.0},
            ],
            False, db,
        )
        assert "error" in result
        assert "100%" in result["error"] or "exceed" in result["error"].lower()

    async def test_custom_split_error_if_initiator_pct_zero(self):
        """21. Custom split: returns error if initiator_pct == 0."""
        ride = _fs_ride(estimated_fare=100.0)
        db = _seq_db(_seq_scalar_one(ride), _seq_scalars_list([]))
        result = await create_fare_split(
            1, 10,
            [{"user_id": 2, "share_percentage": 100.0}],
            False, db,
        )
        assert "error" in result
        assert "initiator" in result["error"].lower()

    async def test_custom_split_error_if_participant_percentage_none(self):
        """22. Custom split: returns error if a participant has None/0 share_percentage."""
        ride = _fs_ride(estimated_fare=100.0)
        db = _seq_db(_seq_scalar_one(ride), _seq_scalars_list([]))
        result = await create_fare_split(
            1, 10,
            [{"user_id": 2, "share_percentage": None}],
            False, db,
        )
        assert "error" in result

    async def test_phone_lookup_resolves_user(self):
        """23. Phone lookup: if participant has phone and no user_id, db resolves user."""
        ride = _fs_ride(estimated_fare=40.0)
        found_user = MagicMock()
        found_user.id = 77
        db = _seq_db(
            _seq_scalar_one(ride),         # ride
            _seq_scalars_list([]),           # existing splits
            _seq_scalar_one(found_user),     # phone lookup
        )
        result = await create_fare_split(
            1, 10,
            [{"phone": "+15551234567"}],
            True, db,
        )
        assert "error" not in result
        participant = next(s for s in result["splits"] if not s["is_initiator"])
        assert participant["user_id"] == 77

    async def test_email_lookup_resolves_user(self):
        """24. Email lookup: if participant has email and no user_id, db resolves user."""
        ride = _fs_ride(estimated_fare=40.0)
        found_user = MagicMock()
        found_user.id = 88
        db = _seq_db(
            _seq_scalar_one(ride),         # ride
            _seq_scalars_list([]),           # existing splits
            _seq_scalar_one(found_user),     # email lookup (phone not provided so only email query fires)
        )
        result = await create_fare_split(
            1, 10,
            [{"email": "friend@example.com"}],
            True, db,
        )
        assert "error" not in result
        participant = next(s for s in result["splits"] if not s["is_initiator"])
        assert participant["user_id"] == 88

    async def test_rounding_adjustment_total_equals_fare(self):
        """25. Rounding adjustment: if total_assigned != fare, difference added to initiator."""
        ride = _fs_ride(estimated_fare=10.0)
        db = _seq_db(_seq_scalar_one(ride), _seq_scalars_list([]))
        result = await create_fare_split(
            1, 10,
            [{"user_id": 2}, {"user_id": 3}],  # 3-way split of $10
            True, db,
        )
        assert "error" not in result
        total = sum(s["share_amount"] for s in result["splits"])
        assert round(total, 2) == pytest.approx(10.0, abs=0.01)

    async def test_returns_expected_keys(self):
        """26. Returns dict with ride_id, total_fare, split_count, splits, all_accepted, all_paid."""
        ride = _fs_ride(estimated_fare=40.0)
        db = _seq_db(_seq_scalar_one(ride), _seq_scalars_list([]))
        result = await create_fare_split(1, 10, [{"user_id": 2}], True, db)
        assert "error" not in result
        for key in ("ride_id", "total_fare", "split_count", "splits", "all_accepted", "all_paid"):
            assert key in result

    async def test_all_accepted_true_only_when_all_accepted_or_paid(self):
        """27. all_accepted=True only when all non-cancelled splits are ACCEPTED or PAID."""
        ride = _fs_ride(estimated_fare=40.0)
        db = _seq_db(_seq_scalar_one(ride), _seq_scalars_list([]))
        result = await create_fare_split(1, 10, [{"user_id": 2}], True, db)
        assert "error" not in result
        # Participant is PENDING → all_accepted must be False
        assert result["all_accepted"] is False

    async def test_all_paid_true_only_when_all_splits_paid(self):
        """28. all_paid=True only when all splits are PAID."""
        ride = _fs_ride(estimated_fare=40.0)
        db = _seq_db(_seq_scalar_one(ride), _seq_scalars_list([]))
        result = await create_fare_split(1, 10, [{"user_id": 2}], True, db)
        assert "error" not in result
        assert result["all_paid"] is False

    async def test_db_commit_called_after_creating_splits(self):
        """29. db.commit() is called after creating splits."""
        ride = _fs_ride(estimated_fare=40.0)
        db = _seq_db(_seq_scalar_one(ride), _seq_scalars_list([]))
        await create_fare_split(1, 10, [{"user_id": 2}], True, db)
        db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# TestGetFareSplit2 — get_fare_split service (items 30-35)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestGetFareSplit2:
    async def test_error_if_ride_not_found(self):
        """30. Returns error if ride not found."""
        db = _seq_db(_seq_none())
        result = await get_fare_split(99, 10, db)
        assert "error" in result
        assert "not found" in result["error"].lower()

    async def test_error_if_no_active_splits(self):
        """31. Returns error if no active splits found."""
        ride = _fs_ride()
        db = _seq_db(_seq_scalar_one(ride), _seq_scalars_list([]))
        result = await get_fare_split(1, 10, db)
        assert "error" in result
        assert "no fare split" in result["error"].lower()

    async def test_error_if_user_not_authorized(self):
        """32. Returns error if user is not a participant and not the ride owner."""
        ride = _fs_ride(rider_id=10)
        split = _fs_split(user_id=10)
        db = _seq_db(_seq_scalar_one(ride), _seq_scalars_list([split]))
        result = await get_fare_split(1, 99, db)
        assert "error" in result
        assert "not authorized" in result["error"].lower()

    async def test_returns_split_for_participant(self):
        """33. Returns split details for a participant."""
        ride = _fs_ride(rider_id=10, estimated_fare=40.0)
        split = _fs_split(user_id=20, is_initiator=False)
        db = _seq_db(_seq_scalar_one(ride), _seq_scalars_list([split]))
        result = await get_fare_split(1, 20, db)
        assert "error" not in result
        assert result["ride_id"] == 1

    async def test_returns_split_for_ride_owner(self):
        """34. Returns split details for the ride owner (who is not a participant)."""
        ride = _fs_ride(rider_id=10, estimated_fare=40.0)
        split = _fs_split(user_id=20, is_initiator=False)
        db = _seq_db(_seq_scalar_one(ride), _seq_scalars_list([split]))
        result = await get_fare_split(1, 10, db)
        assert "error" not in result

    async def test_uses_actual_fare_when_set(self):
        """35a. Uses actual_fare if set."""
        ride = _fs_ride(rider_id=10, estimated_fare=40.0, actual_fare=42.50)
        split = _fs_split(user_id=10)
        db = _seq_db(_seq_scalar_one(ride), _seq_scalars_list([split]))
        result = await get_fare_split(1, 10, db)
        assert "error" not in result
        assert result["total_fare"] == pytest.approx(42.50)

    async def test_falls_back_to_estimated_fare(self):
        """35b. Falls back to estimated_fare when actual_fare is None."""
        ride = _fs_ride(rider_id=10, estimated_fare=35.0, actual_fare=None)
        split = _fs_split(user_id=10)
        db = _seq_db(_seq_scalar_one(ride), _seq_scalars_list([split]))
        result = await get_fare_split(1, 10, db)
        assert "error" not in result
        assert result["total_fare"] == pytest.approx(35.0)


# ---------------------------------------------------------------------------
# TestRespondToSplit2 — respond_to_split service (items 36-44)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRespondToSplit2:
    async def test_error_if_split_not_found(self):
        """36. Returns error if split not found."""
        db = _seq_db(_seq_none())
        result = await respond_to_split(99, 10, True, db)
        assert "error" in result
        assert "not found" in result["error"].lower()

    async def test_error_if_not_authorized(self):
        """37. Returns error if split.user_id != user_id."""
        split = _fs_split(user_id=10, is_initiator=False, status=SplitStatus.PENDING)
        db = _seq_db(_seq_scalar_one(split))
        result = await respond_to_split(1, 99, True, db)
        assert "error" in result
        assert "not authorized" in result["error"].lower()

    async def test_error_if_is_initiator(self):
        """38. Returns error if is_initiator=True."""
        split = _fs_split(user_id=10, is_initiator=True, status=SplitStatus.PENDING)
        db = _seq_db(_seq_scalar_one(split))
        result = await respond_to_split(1, 10, True, db)
        assert "error" in result
        assert "initiator" in result["error"].lower()

    async def test_error_if_not_pending(self):
        """39. Returns error if split.status != PENDING."""
        split = _fs_split(user_id=10, is_initiator=False, status=SplitStatus.ACCEPTED)
        db = _seq_db(_seq_scalar_one(split))
        result = await respond_to_split(1, 10, True, db)
        assert "error" in result
        assert "accepted" in result["error"].lower()

    async def test_accepting_sets_status_accepted(self):
        """40a. Accepting sets status=ACCEPTED."""
        split = _fs_split(
            user_id=10, is_initiator=False, status=SplitStatus.PENDING,
            share_amount=20.0, share_percentage=50.0,
        )
        split.created_at = datetime(2026, 4, 1, tzinfo=timezone.utc)
        split.responded_at = None
        split.invite_phone = None
        split.invite_email = None
        db = _seq_db(_seq_scalar_one(split))
        await respond_to_split(1, 10, True, db)
        assert split.status == SplitStatus.ACCEPTED

    async def test_accepting_sets_responded_at(self):
        """40b. Accepting sets responded_at to a datetime."""
        split = _fs_split(
            user_id=10, is_initiator=False, status=SplitStatus.PENDING,
            share_amount=20.0, share_percentage=50.0,
        )
        split.created_at = datetime(2026, 4, 1, tzinfo=timezone.utc)
        split.responded_at = None
        split.invite_phone = None
        split.invite_email = None
        db = _seq_db(_seq_scalar_one(split))
        await respond_to_split(1, 10, True, db)
        assert split.responded_at is not None
        assert isinstance(split.responded_at, datetime)

    async def test_declining_sets_status_declined(self):
        """41a. Declining sets status=DECLINED."""
        split = _fs_split(
            user_id=10, is_initiator=False, status=SplitStatus.PENDING,
            share_amount=20.0, share_percentage=50.0,
        )
        split.created_at = datetime(2026, 4, 1, tzinfo=timezone.utc)
        split.responded_at = None
        split.invite_phone = None
        split.invite_email = None
        initiator = _fs_split(
            id=2, user_id=5, is_initiator=True, status=SplitStatus.ACCEPTED,
            share_amount=20.0, share_percentage=50.0,
        )
        db = _seq_db(_seq_scalar_one(split), _seq_scalar_one(initiator))
        await respond_to_split(1, 10, False, db)
        assert split.status == SplitStatus.DECLINED

    async def test_declining_sets_responded_at(self):
        """41b. Declining sets responded_at to a datetime."""
        split = _fs_split(
            user_id=10, is_initiator=False, status=SplitStatus.PENDING,
            share_amount=20.0, share_percentage=50.0,
        )
        split.created_at = datetime(2026, 4, 1, tzinfo=timezone.utc)
        split.responded_at = None
        split.invite_phone = None
        split.invite_email = None
        initiator = _fs_split(
            id=2, user_id=5, is_initiator=True, status=SplitStatus.ACCEPTED,
            share_amount=20.0, share_percentage=50.0,
        )
        db = _seq_db(_seq_scalar_one(split), _seq_scalar_one(initiator))
        await respond_to_split(1, 10, False, db)
        assert split.responded_at is not None

    async def test_declining_redistributes_share_to_initiator(self):
        """42. Declining redistributes share_amount to initiator's split."""
        split = _fs_split(
            user_id=10, is_initiator=False, status=SplitStatus.PENDING,
            share_amount=15.0, share_percentage=37.5,
        )
        split.created_at = datetime(2026, 4, 1, tzinfo=timezone.utc)
        split.responded_at = None
        split.invite_phone = None
        split.invite_email = None
        initiator = _fs_split(
            id=2, user_id=5, is_initiator=True, status=SplitStatus.ACCEPTED,
            share_amount=25.0, share_percentage=62.5,
        )
        db = _seq_db(_seq_scalar_one(split), _seq_scalar_one(initiator))
        await respond_to_split(1, 10, False, db)
        assert initiator.share_amount == pytest.approx(40.0)

    async def test_declining_zeroes_declined_split_amounts(self):
        """43. Declining sets split.share_amount = 0.0 and share_percentage = 0.0."""
        split = _fs_split(
            user_id=10, is_initiator=False, status=SplitStatus.PENDING,
            share_amount=20.0, share_percentage=50.0,
        )
        split.created_at = datetime(2026, 4, 1, tzinfo=timezone.utc)
        split.responded_at = None
        split.invite_phone = None
        split.invite_email = None
        initiator = _fs_split(
            id=2, user_id=5, is_initiator=True, status=SplitStatus.ACCEPTED,
            share_amount=20.0, share_percentage=50.0,
        )
        db = _seq_db(_seq_scalar_one(split), _seq_scalar_one(initiator))
        await respond_to_split(1, 10, False, db)
        assert split.share_amount == 0.0
        assert split.share_percentage == 0.0

    async def test_db_commit_called_after_accept(self):
        """44. db.commit() called after response."""
        split = _fs_split(
            user_id=10, is_initiator=False, status=SplitStatus.PENDING,
        )
        split.created_at = datetime(2026, 4, 1, tzinfo=timezone.utc)
        split.responded_at = None
        split.invite_phone = None
        split.invite_email = None
        db = _seq_db(_seq_scalar_one(split))
        await respond_to_split(1, 10, True, db)
        db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# TestCancelFareSplit2 — cancel_fare_split service (items 45-51)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCancelFareSplit2:
    async def test_error_if_ride_not_found(self):
        """45. Returns error if ride not found."""
        db = _seq_db(_seq_none())
        result = await cancel_fare_split(99, 10, db)
        assert "error" in result
        assert "not found" in result["error"].lower()

    async def test_error_if_user_not_ride_rider_id(self):
        """46. Returns error if user is not ride.rider_id."""
        ride = _fs_ride(rider_id=10)
        db = _seq_db(_seq_scalar_one(ride))
        result = await cancel_fare_split(1, 99, db)
        assert "error" in result

    async def test_error_if_no_active_splits(self):
        """47. Returns error if no active splits exist."""
        ride = _fs_ride(rider_id=10)
        db = _seq_db(_seq_scalar_one(ride), _seq_scalars_list([]))
        result = await cancel_fare_split(1, 10, db)
        assert "error" in result
        assert "no active" in result["error"].lower()

    async def test_error_if_any_split_paid(self):
        """48. Returns error if any split is PAID."""
        ride = _fs_ride(rider_id=10)
        paid = _fs_split(status=SplitStatus.PAID)
        db = _seq_db(_seq_scalar_one(ride), _seq_scalars_list([paid]))
        result = await cancel_fare_split(1, 10, db)
        assert "error" in result
        assert "paid" in result["error"].lower()

    async def test_cancels_all_non_cancelled_splits(self):
        """49. Cancels all non-cancelled splits (sets status=CANCELLED)."""
        ride = _fs_ride(rider_id=10)
        s1 = _fs_split(id=1, status=SplitStatus.ACCEPTED)
        s2 = _fs_split(id=2, user_id=20, is_initiator=False, status=SplitStatus.PENDING)
        db = _seq_db(_seq_scalar_one(ride), _seq_scalars_list([s1, s2]))
        await cancel_fare_split(1, 10, db)
        assert s1.status == SplitStatus.CANCELLED
        assert s2.status == SplitStatus.CANCELLED

    async def test_returns_expected_dict(self):
        """50. Returns dict with ride_id, status='cancelled', splits_cancelled count."""
        ride = _fs_ride(rider_id=10)
        s1 = _fs_split(id=1, status=SplitStatus.ACCEPTED)
        s2 = _fs_split(id=2, user_id=20, is_initiator=False, status=SplitStatus.PENDING)
        db = _seq_db(_seq_scalar_one(ride), _seq_scalars_list([s1, s2]))
        result = await cancel_fare_split(1, 10, db)
        assert result["ride_id"] == 1
        assert result["status"] == "cancelled"
        assert result["splits_cancelled"] == 2

    async def test_db_commit_called(self):
        """51. db.commit() called."""
        ride = _fs_ride(rider_id=10)
        s1 = _fs_split(status=SplitStatus.ACCEPTED)
        db = _seq_db(_seq_scalar_one(ride), _seq_scalars_list([s1]))
        await cancel_fare_split(1, 10, db)
        db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# TestExpirePendingSplits2 — expire_pending_splits service (items 52-57)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestExpirePendingSplits2:
    async def test_returns_0_if_no_pending(self):
        """52. Returns 0 if no pending splits."""
        db = _seq_db(_seq_scalars_list([]))
        count = await expire_pending_splits(1, db)
        assert count == 0

    async def test_sets_expired_splits_to_expired_status(self):
        """53. Sets expired splits to status=EXPIRED."""
        pending = _fs_split(
            user_id=20, is_initiator=False, status=SplitStatus.PENDING,
            share_amount=20.0, share_percentage=50.0,
        )
        initiator = _fs_split(
            id=2, user_id=10, is_initiator=True, status=SplitStatus.ACCEPTED,
            share_amount=20.0, share_percentage=50.0,
        )
        db = _seq_db(_seq_scalars_list([pending]), _seq_scalar_one(initiator))
        await expire_pending_splits(1, db)
        assert pending.status == SplitStatus.EXPIRED

    async def test_redistributes_expired_amount_to_initiator(self):
        """54. Redistributes each expired split's share_amount to initiator."""
        pending = _fs_split(
            user_id=20, is_initiator=False, status=SplitStatus.PENDING,
            share_amount=15.0, share_percentage=30.0,
        )
        initiator = _fs_split(
            id=2, user_id=10, is_initiator=True, status=SplitStatus.ACCEPTED,
            share_amount=35.0, share_percentage=70.0,
        )
        db = _seq_db(_seq_scalars_list([pending]), _seq_scalar_one(initiator))
        await expire_pending_splits(1, db)
        assert initiator.share_amount == pytest.approx(50.0)
        assert initiator.share_percentage == pytest.approx(100.0)

    async def test_zeroes_expired_split_amounts(self):
        """55. Sets each expired split's share_amount and share_percentage to 0."""
        pending = _fs_split(
            user_id=20, is_initiator=False, status=SplitStatus.PENDING,
            share_amount=20.0, share_percentage=50.0,
        )
        initiator = _fs_split(
            id=2, user_id=10, is_initiator=True, status=SplitStatus.ACCEPTED,
            share_amount=20.0, share_percentage=50.0,
        )
        db = _seq_db(_seq_scalars_list([pending]), _seq_scalar_one(initiator))
        await expire_pending_splits(1, db)
        assert pending.share_amount == 0.0
        assert pending.share_percentage == 0.0

    async def test_returns_count_of_expired(self):
        """56. Returns count of expired splits."""
        p1 = _fs_split(
            id=1, user_id=20, is_initiator=False, status=SplitStatus.PENDING,
            share_amount=10.0, share_percentage=25.0,
        )
        p2 = _fs_split(
            id=2, user_id=21, is_initiator=False, status=SplitStatus.PENDING,
            share_amount=10.0, share_percentage=25.0,
        )
        initiator = _fs_split(
            id=3, user_id=10, is_initiator=True, status=SplitStatus.ACCEPTED,
            share_amount=20.0, share_percentage=50.0,
        )
        db = _seq_db(_seq_scalars_list([p1, p2]), _seq_scalar_one(initiator))
        count = await expire_pending_splits(1, db)
        assert count == 2

    async def test_db_commit_called(self):
        """57. db.commit() called."""
        pending = _fs_split(
            user_id=20, is_initiator=False, status=SplitStatus.PENDING,
            share_amount=20.0, share_percentage=50.0,
        )
        initiator = _fs_split(
            id=2, user_id=10, is_initiator=True, status=SplitStatus.ACCEPTED,
            share_amount=20.0, share_percentage=50.0,
        )
        db = _seq_db(_seq_scalars_list([pending]), _seq_scalar_one(initiator))
        await expire_pending_splits(1, db)
        db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# TestUpdateSplitAmounts2 — update_split_amounts_for_actual_fare (items 58-62)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestUpdateSplitAmounts2:
    async def test_noop_if_no_active_splits(self):
        """58. No-ops if no active splits found."""
        db = _seq_db(_seq_scalars_list([]))
        await update_split_amounts_for_actual_fare(1, 50.0, db)
        db.commit.assert_not_awaited()

    async def test_recalculates_unpaid_splits(self):
        """59. Recalculates unpaid splits based on actual_fare and share_percentage."""
        s1 = _fs_split(
            id=1, user_id=10, is_initiator=True, status=SplitStatus.ACCEPTED,
            share_amount=20.0, share_percentage=50.0,
        )
        s2 = _fs_split(
            id=2, user_id=20, is_initiator=False, status=SplitStatus.ACCEPTED,
            share_amount=20.0, share_percentage=50.0,
        )
        db = _seq_db(_seq_scalars_list([s1, s2]))
        await update_split_amounts_for_actual_fare(1, 60.0, db)
        assert s1.share_amount == pytest.approx(30.0)
        assert s2.share_amount == pytest.approx(30.0)

    async def test_does_not_change_paid_splits(self):
        """60. Does not change PAID splits."""
        paid = _fs_split(
            id=1, user_id=10, is_initiator=True, status=SplitStatus.PAID,
            share_amount=20.0, share_percentage=50.0,
        )
        unpaid = _fs_split(
            id=2, user_id=20, is_initiator=False, status=SplitStatus.ACCEPTED,
            share_amount=20.0, share_percentage=50.0,
        )
        db = _seq_db(_seq_scalars_list([paid, unpaid]))
        await update_split_amounts_for_actual_fare(1, 60.0, db)
        # Paid split stays at original $20
        assert paid.share_amount == pytest.approx(20.0)

    async def test_rounding_adjustment_applied_to_initiator(self):
        """61. Rounding adjustment applied to initiator if total doesn't sum to unpaid_fare."""
        initiator = _fs_split(
            id=1, user_id=10, is_initiator=True, status=SplitStatus.ACCEPTED,
            share_amount=0.0, share_percentage=33.33,
        )
        p2 = _fs_split(
            id=2, user_id=20, is_initiator=False, status=SplitStatus.ACCEPTED,
            share_amount=0.0, share_percentage=33.33,
        )
        p3 = _fs_split(
            id=3, user_id=21, is_initiator=False, status=SplitStatus.ACCEPTED,
            share_amount=0.0, share_percentage=33.34,
        )
        db = _seq_db(_seq_scalars_list([initiator, p2, p3]))
        actual_fare = 10.0
        await update_split_amounts_for_actual_fare(1, actual_fare, db)
        total = initiator.share_amount + p2.share_amount + p3.share_amount
        assert round(total, 2) == pytest.approx(actual_fare, abs=0.01)

    async def test_db_commit_called(self):
        """62. db.commit() called."""
        s = _fs_split(
            id=1, user_id=10, is_initiator=True, status=SplitStatus.ACCEPTED,
            share_amount=20.0, share_percentage=50.0,
        )
        db = _seq_db(_seq_scalars_list([s]))
        await update_split_amounts_for_actual_fare(1, 60.0, db)
        db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# TestHandleSplitPaymentSucceeded2 — handle_split_payment_succeeded (items 63-64)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestHandleSplitPaymentSucceeded2:
    async def test_sets_status_to_paid_if_found(self):
        """63. Sets split status to PAID if found."""
        split = _fs_split(status=SplitStatus.ACCEPTED)
        db = _seq_db(_seq_scalar_one(split))
        await handle_split_payment_succeeded(1, db)
        assert split.status == SplitStatus.PAID
        db.commit.assert_awaited_once()

    async def test_noop_if_split_not_found(self):
        """64. No-ops if split not found."""
        db = _seq_db(_seq_none())
        await handle_split_payment_succeeded(999, db)
        db.commit.assert_not_awaited()
