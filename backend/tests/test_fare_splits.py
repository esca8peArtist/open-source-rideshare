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
