"""Tests for driver payout / settlement system — bank accounts, settlement calculation, payouts."""

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.payout import (
    DriverBankAccount,
    DriverPayout,
    PayoutFrequency,
    PayoutStatus,
)
from app.models.payment import Payment, PaymentStatus, PaymentType
from app.models.ride import Ride, RideStatus
from app.models.user import User, UserRole
from app.schemas.payout import (
    AdminBulkPayoutRequest,
    AdminCreatePayoutRequest,
    AdminPayoutOverview,
    AdminProcessPayoutRequest,
    BankAccountResponse,
    ConnectAccountSetupRequest,
    ConnectAccountSetupResponse,
    PayoutDetailResponse,
    PayoutListResponse,
    PayoutSummary,
    UpdatePayoutFrequencyRequest,
)
from app.services.payouts import (
    PayoutError,
    bulk_create_payouts,
    calculate_settlement,
    create_connect_account,
    create_payout,
    deactivate_bank_account,
    get_admin_payout_overview,
    get_bank_account,
    get_driver_payouts,
    get_payout_by_id,
    get_payout_totals,
    handle_connect_account_updated,
    process_payout,
    retry_failed_payout,
    update_payout_frequency,
)


# ===========================================================================
# DriverBankAccount Model Tests
# ===========================================================================


class TestDriverBankAccountModel:
    def test_table_name(self):
        assert DriverBankAccount.__tablename__ == "driver_bank_accounts"

    def test_has_id_column(self):
        cols = {c.name for c in DriverBankAccount.__table__.columns}
        assert "id" in cols

    def test_has_driver_id_column(self):
        cols = {c.name for c in DriverBankAccount.__table__.columns}
        assert "driver_id" in cols

    def test_has_stripe_connect_account_id_column(self):
        cols = {c.name for c in DriverBankAccount.__table__.columns}
        assert "stripe_connect_account_id" in cols

    def test_has_account_status_column(self):
        cols = {c.name for c in DriverBankAccount.__table__.columns}
        assert "account_status" in cols

    def test_has_bank_last_four_column(self):
        cols = {c.name for c in DriverBankAccount.__table__.columns}
        assert "bank_last_four" in cols

    def test_has_bank_name_column(self):
        cols = {c.name for c in DriverBankAccount.__table__.columns}
        assert "bank_name" in cols

    def test_has_payout_frequency_column(self):
        cols = {c.name for c in DriverBankAccount.__table__.columns}
        assert "payout_frequency" in cols

    def test_has_is_active_column(self):
        cols = {c.name for c in DriverBankAccount.__table__.columns}
        assert "is_active" in cols

    def test_has_created_at_column(self):
        cols = {c.name for c in DriverBankAccount.__table__.columns}
        assert "created_at" in cols

    def test_has_updated_at_column(self):
        cols = {c.name for c in DriverBankAccount.__table__.columns}
        assert "updated_at" in cols

    def test_driver_id_unique(self):
        driver_id_col = DriverBankAccount.__table__.c.driver_id
        assert driver_id_col.unique is True


# ===========================================================================
# DriverPayout Model Tests
# ===========================================================================


class TestDriverPayoutModel:
    def test_table_name(self):
        assert DriverPayout.__tablename__ == "driver_payouts"

    def test_has_id_column(self):
        cols = {c.name for c in DriverPayout.__table__.columns}
        assert "id" in cols

    def test_has_driver_id_column(self):
        cols = {c.name for c in DriverPayout.__table__.columns}
        assert "driver_id" in cols

    def test_has_bank_account_id_column(self):
        cols = {c.name for c in DriverPayout.__table__.columns}
        assert "bank_account_id" in cols

    def test_has_period_start_column(self):
        cols = {c.name for c in DriverPayout.__table__.columns}
        assert "period_start" in cols

    def test_has_period_end_column(self):
        cols = {c.name for c in DriverPayout.__table__.columns}
        assert "period_end" in cols

    def test_has_ride_earnings_column(self):
        cols = {c.name for c in DriverPayout.__table__.columns}
        assert "ride_earnings" in cols

    def test_has_tip_earnings_column(self):
        cols = {c.name for c in DriverPayout.__table__.columns}
        assert "tip_earnings" in cols

    def test_has_cancellation_fee_earnings_column(self):
        cols = {c.name for c in DriverPayout.__table__.columns}
        assert "cancellation_fee_earnings" in cols

    def test_has_bonus_amount_column(self):
        cols = {c.name for c in DriverPayout.__table__.columns}
        assert "bonus_amount" in cols

    def test_has_deductions_column(self):
        cols = {c.name for c in DriverPayout.__table__.columns}
        assert "deductions" in cols

    def test_has_total_amount_column(self):
        cols = {c.name for c in DriverPayout.__table__.columns}
        assert "total_amount" in cols

    def test_has_trip_count_column(self):
        cols = {c.name for c in DriverPayout.__table__.columns}
        assert "trip_count" in cols

    def test_has_stripe_transfer_id_column(self):
        cols = {c.name for c in DriverPayout.__table__.columns}
        assert "stripe_transfer_id" in cols

    def test_has_status_column(self):
        cols = {c.name for c in DriverPayout.__table__.columns}
        assert "status" in cols

    def test_has_failure_reason_column(self):
        cols = {c.name for c in DriverPayout.__table__.columns}
        assert "failure_reason" in cols

    def test_has_notes_column(self):
        cols = {c.name for c in DriverPayout.__table__.columns}
        assert "notes" in cols

    def test_has_created_at_column(self):
        cols = {c.name for c in DriverPayout.__table__.columns}
        assert "created_at" in cols

    def test_has_processed_at_column(self):
        cols = {c.name for c in DriverPayout.__table__.columns}
        assert "processed_at" in cols

    def test_has_completed_at_column(self):
        cols = {c.name for c in DriverPayout.__table__.columns}
        assert "completed_at" in cols


# ===========================================================================
# Enum Tests
# ===========================================================================


class TestPayoutEnums:
    def test_payout_status_values(self):
        assert PayoutStatus.PENDING.value == "pending"
        assert PayoutStatus.PROCESSING.value == "processing"
        assert PayoutStatus.COMPLETED.value == "completed"
        assert PayoutStatus.FAILED.value == "failed"

    def test_payout_status_count(self):
        assert len(PayoutStatus) == 4

    def test_payout_frequency_values(self):
        assert PayoutFrequency.WEEKLY.value == "weekly"
        assert PayoutFrequency.BIWEEKLY.value == "biweekly"
        assert PayoutFrequency.DAILY.value == "daily"

    def test_payout_frequency_count(self):
        assert len(PayoutFrequency) == 3


# ===========================================================================
# Schema Tests
# ===========================================================================


class TestConnectAccountSetupRequest:
    def test_valid_request(self):
        req = ConnectAccountSetupRequest(
            return_url="https://app.openride.coop/onboard/complete",
            refresh_url="https://app.openride.coop/onboard/refresh",
        )
        assert req.return_url == "https://app.openride.coop/onboard/complete"
        assert req.refresh_url == "https://app.openride.coop/onboard/refresh"


class TestConnectAccountSetupResponse:
    def test_valid_response(self):
        resp = ConnectAccountSetupResponse(
            account_id="acct_abc123",
            onboarding_url="https://connect.stripe.com/setup/abc",
        )
        assert resp.account_id == "acct_abc123"
        assert resp.onboarding_url == "https://connect.stripe.com/setup/abc"


class TestBankAccountResponse:
    def test_valid_response(self):
        resp = BankAccountResponse(
            id=1,
            driver_id=10,
            stripe_connect_account_id="acct_abc",
            account_status="active",
            bank_last_four="1234",
            bank_name="Chase",
            payout_frequency="weekly",
            is_active=True,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert resp.id == 1
        assert resp.bank_last_four == "1234"

    def test_nullable_fields(self):
        resp = BankAccountResponse(
            id=1,
            driver_id=10,
            stripe_connect_account_id="acct_abc",
            account_status="pending",
            payout_frequency="weekly",
            is_active=True,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert resp.bank_last_four is None
        assert resp.bank_name is None


class TestUpdatePayoutFrequencyRequest:
    def test_valid_weekly(self):
        req = UpdatePayoutFrequencyRequest(frequency="weekly")
        assert req.frequency == "weekly"

    def test_valid_biweekly(self):
        req = UpdatePayoutFrequencyRequest(frequency="biweekly")
        assert req.frequency == "biweekly"

    def test_valid_daily(self):
        req = UpdatePayoutFrequencyRequest(frequency="daily")
        assert req.frequency == "daily"

    def test_invalid_frequency(self):
        with pytest.raises(Exception):
            UpdatePayoutFrequencyRequest(frequency="monthly")


class TestPayoutSummary:
    def test_valid_summary(self):
        s = PayoutSummary(
            id=1,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 7),
            ride_earnings=150.0,
            tip_earnings=25.0,
            cancellation_fee_earnings=5.0,
            bonus_amount=10.0,
            deductions=0.0,
            total_amount=190.0,
            trip_count=12,
            status="completed",
            created_at=datetime(2026, 4, 8, tzinfo=timezone.utc),
        )
        assert s.total_amount == 190.0
        assert s.trip_count == 12

    def test_optional_dates_default_none(self):
        s = PayoutSummary(
            id=1,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 7),
            ride_earnings=0.0,
            tip_earnings=0.0,
            cancellation_fee_earnings=0.0,
            bonus_amount=0.0,
            deductions=0.0,
            total_amount=0.0,
            trip_count=0,
            status="pending",
            created_at=datetime(2026, 4, 8, tzinfo=timezone.utc),
        )
        assert s.processed_at is None
        assert s.completed_at is None


class TestPayoutDetailResponse:
    def test_valid_detail(self):
        d = PayoutDetailResponse(
            id=1,
            driver_id=10,
            bank_account_id=1,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 7),
            ride_earnings=150.0,
            tip_earnings=25.0,
            cancellation_fee_earnings=5.0,
            bonus_amount=10.0,
            deductions=2.0,
            total_amount=188.0,
            trip_count=12,
            stripe_transfer_id="tr_abc123",
            status="completed",
            failure_reason=None,
            notes="Weekly settlement",
            created_at=datetime(2026, 4, 8, tzinfo=timezone.utc),
            processed_at=datetime(2026, 4, 8, 1, 0, tzinfo=timezone.utc),
            completed_at=datetime(2026, 4, 8, 1, 5, tzinfo=timezone.utc),
        )
        assert d.stripe_transfer_id == "tr_abc123"
        assert d.notes == "Weekly settlement"


class TestPayoutListResponse:
    def test_valid_list(self):
        resp = PayoutListResponse(payouts=[], total_paid=500.0, total_pending=100.0)
        assert resp.total_paid == 500.0
        assert len(resp.payouts) == 0


class TestAdminCreatePayoutRequest:
    def test_valid_request(self):
        req = AdminCreatePayoutRequest(
            driver_id=10,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 7),
            bonus_amount=5.0,
            deductions=0.0,
            notes="Weekly auto-settlement",
        )
        assert req.driver_id == 10
        assert req.bonus_amount == 5.0

    def test_default_values(self):
        req = AdminCreatePayoutRequest(
            driver_id=10,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 7),
        )
        assert req.bonus_amount == 0.0
        assert req.deductions == 0.0
        assert req.notes is None


class TestAdminProcessPayoutRequest:
    def test_valid_request(self):
        req = AdminProcessPayoutRequest(payout_id=42)
        assert req.payout_id == 42


class TestAdminPayoutOverview:
    def test_valid_overview(self):
        o = AdminPayoutOverview(
            total_drivers_with_accounts=50,
            total_pending_payouts=12,
            total_pending_amount=3400.0,
            total_completed_payouts=200,
            total_completed_amount=85000.0,
            total_failed_payouts=3,
        )
        assert o.total_drivers_with_accounts == 50
        assert o.total_failed_payouts == 3


class TestAdminBulkPayoutRequest:
    def test_valid_request(self):
        req = AdminBulkPayoutRequest(
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 7),
        )
        assert req.bonus_amount == 0.0
        assert req.notes is None


# ===========================================================================
# Service Tests — Create Connect Account
# ===========================================================================


class TestCreateConnectAccount:
    @pytest.mark.asyncio
    async def test_creates_account_and_returns_link(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with patch("app.services.payouts.stripe") as mock_stripe:
            mock_stripe.Account.create.return_value = MagicMock(id="acct_new123")
            mock_stripe.AccountLink.create.return_value = MagicMock(
                url="https://connect.stripe.com/setup/link"
            )

            result = await create_connect_account(
                driver_id=10,
                return_url="https://app.openride.coop/complete",
                refresh_url="https://app.openride.coop/refresh",
                db=mock_db,
            )

        assert result["account_id"] == "acct_new123"
        assert result["onboarding_url"] == "https://connect.stripe.com/setup/link"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_if_already_has_active_account(self):
        mock_db = AsyncMock()
        existing = MagicMock(is_active=True)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        with pytest.raises(PayoutError, match="already has an active bank account"):
            await create_connect_account(10, "url", "url", mock_db)

    @pytest.mark.asyncio
    async def test_reactivates_existing_inactive_account(self):
        mock_db = AsyncMock()
        existing = MagicMock(is_active=False)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        with patch("app.services.payouts.stripe") as mock_stripe:
            mock_stripe.Account.create.return_value = MagicMock(id="acct_reactivated")
            mock_stripe.AccountLink.create.return_value = MagicMock(url="https://link")

            result = await create_connect_account(10, "url", "url", mock_db)

        assert result["account_id"] == "acct_reactivated"
        assert existing.stripe_connect_account_id == "acct_reactivated"
        assert existing.is_active is True


# ===========================================================================
# Service Tests — Handle Connect Account Updated
# ===========================================================================


class TestHandleConnectAccountUpdated:
    @pytest.mark.asyncio
    async def test_sets_active_when_enabled(self):
        mock_db = AsyncMock()
        bank_account = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = bank_account
        mock_db.execute.return_value = mock_result

        account_data = {
            "id": "acct_abc",
            "charges_enabled": True,
            "payouts_enabled": True,
            "external_accounts": {
                "data": [{"last4": "9876", "bank_name": "Wells Fargo"}]
            },
        }

        await handle_connect_account_updated(account_data, mock_db)

        assert bank_account.account_status == "active"
        assert bank_account.bank_last_four == "9876"
        assert bank_account.bank_name == "Wells Fargo"

    @pytest.mark.asyncio
    async def test_sets_requires_info_when_due(self):
        mock_db = AsyncMock()
        bank_account = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = bank_account
        mock_db.execute.return_value = mock_result

        account_data = {
            "id": "acct_abc",
            "charges_enabled": False,
            "payouts_enabled": False,
            "requirements": {"currently_due": ["individual.dob.day"]},
            "external_accounts": {"data": []},
        }

        await handle_connect_account_updated(account_data, mock_db)

        assert bank_account.account_status == "requires_info"

    @pytest.mark.asyncio
    async def test_sets_pending_when_not_enabled_no_due(self):
        mock_db = AsyncMock()
        bank_account = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = bank_account
        mock_db.execute.return_value = mock_result

        account_data = {
            "id": "acct_abc",
            "charges_enabled": False,
            "payouts_enabled": False,
            "requirements": {"currently_due": []},
            "external_accounts": {"data": []},
        }

        await handle_connect_account_updated(account_data, mock_db)

        assert bank_account.account_status == "pending"

    @pytest.mark.asyncio
    async def test_no_account_found_does_not_crash(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        await handle_connect_account_updated({"id": "acct_ghost"}, mock_db)
        mock_db.commit.assert_not_awaited()


# ===========================================================================
# Service Tests — Get Bank Account
# ===========================================================================


class TestGetBankAccount:
    @pytest.mark.asyncio
    async def test_returns_active_account(self):
        mock_db = AsyncMock()
        account = MagicMock(is_active=True)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = account
        mock_db.execute.return_value = mock_result

        result = await get_bank_account(10, mock_db)
        assert result == account

    @pytest.mark.asyncio
    async def test_returns_none_if_no_account(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await get_bank_account(10, mock_db)
        assert result is None


# ===========================================================================
# Service Tests — Update Payout Frequency
# ===========================================================================


class TestUpdatePayoutFrequency:
    @pytest.mark.asyncio
    async def test_updates_frequency(self):
        mock_db = AsyncMock()
        account = MagicMock(is_active=True)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = account
        mock_db.execute.return_value = mock_result

        result = await update_payout_frequency(10, "daily", mock_db)
        assert result.payout_frequency == PayoutFrequency.DAILY

    @pytest.mark.asyncio
    async def test_raises_if_no_account(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(PayoutError, match="No active bank account"):
            await update_payout_frequency(10, "weekly", mock_db)


# ===========================================================================
# Service Tests — Deactivate Bank Account
# ===========================================================================


class TestDeactivateBankAccount:
    @pytest.mark.asyncio
    async def test_deactivates(self):
        mock_db = AsyncMock()
        account = MagicMock(is_active=True)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = account
        mock_db.execute.return_value = mock_result

        await deactivate_bank_account(10, mock_db)
        assert account.is_active is False

    @pytest.mark.asyncio
    async def test_raises_if_no_account(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(PayoutError, match="No active bank account"):
            await deactivate_bank_account(10, mock_db)


# ===========================================================================
# Service Tests — Calculate Settlement
# ===========================================================================


class TestCalculateSettlement:
    @pytest.mark.asyncio
    async def test_returns_zeroes_for_no_rides(self):
        mock_db = AsyncMock()
        ride_row = MagicMock(ride_earnings=0.0, tip_earnings=0.0, trip_count=0)
        ride_result = MagicMock()
        ride_result.one.return_value = ride_row

        cancel_result = MagicMock()
        cancel_result.scalar.return_value = 0.0

        mock_db.execute = AsyncMock(side_effect=[ride_result, cancel_result])

        result = await calculate_settlement(10, date(2026, 4, 1), date(2026, 4, 7), mock_db)

        assert result["ride_earnings"] == 0.0
        assert result["tip_earnings"] == 0.0
        assert result["cancellation_fee_earnings"] == 0.0
        assert result["trip_count"] == 0

    @pytest.mark.asyncio
    async def test_calculates_earnings(self):
        mock_db = AsyncMock()
        ride_row = MagicMock(ride_earnings=250.50, tip_earnings=45.00, trip_count=15)
        ride_result = MagicMock()
        ride_result.one.return_value = ride_row

        cancel_result = MagicMock()
        cancel_result.scalar.return_value = 12.50

        mock_db.execute = AsyncMock(side_effect=[ride_result, cancel_result])

        result = await calculate_settlement(10, date(2026, 4, 1), date(2026, 4, 7), mock_db)

        assert result["ride_earnings"] == 250.50
        assert result["tip_earnings"] == 45.00
        assert result["cancellation_fee_earnings"] == 12.50
        assert result["trip_count"] == 15


# ===========================================================================
# Service Tests — Create Payout
# ===========================================================================


class TestCreatePayout:
    @pytest.mark.asyncio
    async def test_creates_payout_for_driver(self):
        mock_db = AsyncMock()

        bank_account = MagicMock(
            id=1, is_active=True, account_status="active", driver_id=10
        )

        # Call sequence: get_bank_account, overlap check, ride query, cancel query
        bank_result = MagicMock()
        bank_result.scalar_one_or_none.return_value = bank_account

        overlap_result = MagicMock()
        overlap_result.scalar_one_or_none.return_value = None

        ride_row = MagicMock(ride_earnings=100.0, tip_earnings=20.0, trip_count=8)
        ride_result = MagicMock()
        ride_result.one.return_value = ride_row

        cancel_result = MagicMock()
        cancel_result.scalar.return_value = 5.0

        mock_db.execute = AsyncMock(
            side_effect=[bank_result, overlap_result, ride_result, cancel_result]
        )

        payout = await create_payout(
            driver_id=10,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 7),
            db=mock_db,
            bonus_amount=10.0,
        )

        mock_db.add.assert_called_once()
        added = mock_db.add.call_args[0][0]
        assert isinstance(added, DriverPayout)
        assert added.total_amount == 135.0  # 100 + 20 + 5 + 10
        assert added.trip_count == 8

    @pytest.mark.asyncio
    async def test_raises_if_no_bank_account(self):
        mock_db = AsyncMock()
        bank_result = MagicMock()
        bank_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = bank_result

        with pytest.raises(PayoutError, match="no active bank account"):
            await create_payout(10, date(2026, 4, 1), date(2026, 4, 7), mock_db)

    @pytest.mark.asyncio
    async def test_raises_if_bank_not_active_status(self):
        mock_db = AsyncMock()
        bank_account = MagicMock(is_active=True, account_status="pending")
        bank_result = MagicMock()
        bank_result.scalar_one_or_none.return_value = bank_account
        mock_db.execute.return_value = bank_result

        with pytest.raises(PayoutError, match="not active"):
            await create_payout(10, date(2026, 4, 1), date(2026, 4, 7), mock_db)

    @pytest.mark.asyncio
    async def test_raises_if_overlapping_payout(self):
        mock_db = AsyncMock()
        bank_account = MagicMock(is_active=True, account_status="active")
        bank_result = MagicMock()
        bank_result.scalar_one_or_none.return_value = bank_account

        overlap_result = MagicMock()
        overlap_result.scalar_one_or_none.return_value = MagicMock()  # existing payout

        mock_db.execute = AsyncMock(side_effect=[bank_result, overlap_result])

        with pytest.raises(PayoutError, match="Overlapping payout"):
            await create_payout(10, date(2026, 4, 1), date(2026, 4, 7), mock_db)

    @pytest.mark.asyncio
    async def test_raises_if_total_not_positive(self):
        mock_db = AsyncMock()
        bank_account = MagicMock(id=1, is_active=True, account_status="active")
        bank_result = MagicMock()
        bank_result.scalar_one_or_none.return_value = bank_account

        overlap_result = MagicMock()
        overlap_result.scalar_one_or_none.return_value = None

        ride_row = MagicMock(ride_earnings=0.0, tip_earnings=0.0, trip_count=0)
        ride_result = MagicMock()
        ride_result.one.return_value = ride_row

        cancel_result = MagicMock()
        cancel_result.scalar.return_value = 0.0

        mock_db.execute = AsyncMock(
            side_effect=[bank_result, overlap_result, ride_result, cancel_result]
        )

        with pytest.raises(PayoutError, match="must be positive"):
            await create_payout(10, date(2026, 4, 1), date(2026, 4, 7), mock_db)

    @pytest.mark.asyncio
    async def test_applies_deductions(self):
        mock_db = AsyncMock()
        bank_account = MagicMock(id=1, is_active=True, account_status="active")
        bank_result = MagicMock()
        bank_result.scalar_one_or_none.return_value = bank_account

        overlap_result = MagicMock()
        overlap_result.scalar_one_or_none.return_value = None

        ride_row = MagicMock(ride_earnings=100.0, tip_earnings=10.0, trip_count=5)
        ride_result = MagicMock()
        ride_result.one.return_value = ride_row

        cancel_result = MagicMock()
        cancel_result.scalar.return_value = 0.0

        mock_db.execute = AsyncMock(
            side_effect=[bank_result, overlap_result, ride_result, cancel_result]
        )

        payout = await create_payout(
            10, date(2026, 4, 1), date(2026, 4, 7), mock_db,
            deductions=20.0,
        )

        added = mock_db.add.call_args[0][0]
        assert added.total_amount == 90.0  # 100 + 10 + 0 - 20


# ===========================================================================
# Service Tests — Process Payout
# ===========================================================================


class TestProcessPayout:
    @pytest.mark.asyncio
    async def test_processes_pending_payout(self):
        mock_db = AsyncMock()
        payout = MagicMock(
            id=1, status=PayoutStatus.PENDING, total_amount=150.0,
            bank_account_id=1, driver_id=10,
            period_start=date(2026, 4, 1), period_end=date(2026, 4, 7),
        )
        payout_result = MagicMock()
        payout_result.scalar_one_or_none.return_value = payout

        bank_account = MagicMock(
            id=1, is_active=True, stripe_connect_account_id="acct_dest"
        )
        bank_result = MagicMock()
        bank_result.scalar_one_or_none.return_value = bank_account

        mock_db.execute = AsyncMock(side_effect=[payout_result, bank_result])

        with patch("app.services.payouts.stripe") as mock_stripe:
            mock_stripe.Transfer.create.return_value = MagicMock(id="tr_done123")
            mock_stripe.error.StripeError = Exception

            result = await process_payout(1, mock_db)

        assert payout.stripe_transfer_id == "tr_done123"
        assert payout.status == PayoutStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_raises_if_not_found(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(PayoutError, match="not found"):
            await process_payout(999, mock_db)

    @pytest.mark.asyncio
    async def test_raises_if_not_pending(self):
        mock_db = AsyncMock()
        payout = MagicMock(id=1, status=PayoutStatus.COMPLETED)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = payout
        mock_db.execute.return_value = mock_result

        with pytest.raises(PayoutError, match="not pending"):
            await process_payout(1, mock_db)

    @pytest.mark.asyncio
    async def test_fails_if_bank_inactive(self):
        mock_db = AsyncMock()
        payout = MagicMock(
            id=1, status=PayoutStatus.PENDING, bank_account_id=1,
        )
        payout_result = MagicMock()
        payout_result.scalar_one_or_none.return_value = payout

        bank_result = MagicMock()
        bank_result.scalar_one_or_none.return_value = None

        mock_db.execute = AsyncMock(side_effect=[payout_result, bank_result])

        with pytest.raises(PayoutError, match="not found or inactive"):
            await process_payout(1, mock_db)
        assert payout.status == PayoutStatus.FAILED

    @pytest.mark.asyncio
    async def test_handles_stripe_error(self):
        mock_db = AsyncMock()
        payout = MagicMock(
            id=1, status=PayoutStatus.PENDING, total_amount=50.0,
            bank_account_id=1, driver_id=10,
            period_start=date(2026, 4, 1), period_end=date(2026, 4, 7),
        )
        payout_result = MagicMock()
        payout_result.scalar_one_or_none.return_value = payout

        bank_account = MagicMock(
            id=1, is_active=True, stripe_connect_account_id="acct_dest"
        )
        bank_result = MagicMock()
        bank_result.scalar_one_or_none.return_value = bank_account

        mock_db.execute = AsyncMock(side_effect=[payout_result, bank_result])

        with patch("app.services.payouts.stripe") as mock_stripe:
            mock_stripe.error.StripeError = Exception
            mock_stripe.Transfer.create.side_effect = Exception("Insufficient funds")

            with pytest.raises(PayoutError, match="Stripe transfer failed"):
                await process_payout(1, mock_db)

        assert payout.status == PayoutStatus.FAILED
        assert "Insufficient funds" in payout.failure_reason


# ===========================================================================
# Service Tests — Retry Failed Payout
# ===========================================================================


class TestRetryFailedPayout:
    @pytest.mark.asyncio
    async def test_retries_failed_payout(self):
        mock_db = AsyncMock()
        payout = MagicMock(
            id=1, status=PayoutStatus.FAILED, failure_reason="network error",
            processed_at=datetime(2026, 4, 8),
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = payout
        mock_db.execute.return_value = mock_result

        result = await retry_failed_payout(1, mock_db)

        assert payout.status == PayoutStatus.PENDING
        assert payout.failure_reason is None
        assert payout.processed_at is None

    @pytest.mark.asyncio
    async def test_raises_if_not_failed(self):
        mock_db = AsyncMock()
        payout = MagicMock(id=1, status=PayoutStatus.COMPLETED)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = payout
        mock_db.execute.return_value = mock_result

        with pytest.raises(PayoutError, match="Only failed payouts"):
            await retry_failed_payout(1, mock_db)

    @pytest.mark.asyncio
    async def test_raises_if_not_found(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(PayoutError, match="not found"):
            await retry_failed_payout(999, mock_db)


# ===========================================================================
# Service Tests — Get Driver Payouts
# ===========================================================================


class TestGetDriverPayouts:
    @pytest.mark.asyncio
    async def test_returns_payouts_list(self):
        mock_db = AsyncMock()
        payouts = [MagicMock(), MagicMock()]
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = payouts
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result

        result = await get_driver_payouts(10, mock_db)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_payouts(self):
        mock_db = AsyncMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result

        result = await get_driver_payouts(10, mock_db)
        assert result == []


# ===========================================================================
# Service Tests — Get Payout Totals
# ===========================================================================


class TestGetPayoutTotals:
    @pytest.mark.asyncio
    async def test_returns_totals(self):
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[
            MagicMock(scalar=MagicMock(return_value=500.0)),
            MagicMock(scalar=MagicMock(return_value=100.0)),
        ])

        result = await get_payout_totals(10, mock_db)
        assert result["total_paid"] == 500.0
        assert result["total_pending"] == 100.0

    @pytest.mark.asyncio
    async def test_returns_zeroes_if_no_payouts(self):
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[
            MagicMock(scalar=MagicMock(return_value=None)),
            MagicMock(scalar=MagicMock(return_value=None)),
        ])

        result = await get_payout_totals(10, mock_db)
        assert result["total_paid"] == 0.0
        assert result["total_pending"] == 0.0


# ===========================================================================
# Service Tests — Get Payout By ID
# ===========================================================================


class TestGetPayoutById:
    @pytest.mark.asyncio
    async def test_returns_payout(self):
        mock_db = AsyncMock()
        payout = MagicMock(id=1)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = payout
        mock_db.execute.return_value = mock_result

        result = await get_payout_by_id(1, mock_db)
        assert result == payout

    @pytest.mark.asyncio
    async def test_returns_none_if_not_found(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await get_payout_by_id(999, mock_db)
        assert result is None


# ===========================================================================
# Service Tests — Admin Payout Overview
# ===========================================================================


class TestGetAdminPayoutOverview:
    @pytest.mark.asyncio
    async def test_returns_overview(self):
        mock_db = AsyncMock()

        drivers_result = MagicMock(scalar=MagicMock(return_value=50))
        pending_row = MagicMock(count=12, amount=3400.0)
        pending_result = MagicMock()
        pending_result.one.return_value = pending_row
        completed_row = MagicMock(count=200, amount=85000.0)
        completed_result = MagicMock()
        completed_result.one.return_value = completed_row
        failed_result = MagicMock(scalar=MagicMock(return_value=3))

        mock_db.execute = AsyncMock(
            side_effect=[drivers_result, pending_result, completed_result, failed_result]
        )

        result = await get_admin_payout_overview(mock_db)

        assert result["total_drivers_with_accounts"] == 50
        assert result["total_pending_payouts"] == 12
        assert result["total_pending_amount"] == 3400.0
        assert result["total_completed_payouts"] == 200
        assert result["total_completed_amount"] == 85000.0
        assert result["total_failed_payouts"] == 3


# ===========================================================================
# Service Tests — Bulk Create Payouts
# ===========================================================================


class TestBulkCreatePayouts:
    @pytest.mark.asyncio
    async def test_creates_payouts_for_all_eligible(self):
        mock_db = AsyncMock()
        ba1 = MagicMock(driver_id=10, is_active=True, account_status="active", id=1)
        ba2 = MagicMock(driver_id=20, is_active=True, account_status="active", id=2)

        accounts_result = MagicMock()
        accounts_scalars = MagicMock()
        accounts_scalars.all.return_value = [ba1, ba2]
        accounts_result.scalars.return_value = accounts_scalars

        # For each driver: get_bank_account, overlap, ride query, cancel query
        def make_sequence(ba, earnings, tips, trips, cancel):
            bank_r = MagicMock()
            bank_r.scalar_one_or_none.return_value = ba
            overlap_r = MagicMock()
            overlap_r.scalar_one_or_none.return_value = None
            ride_r = MagicMock()
            ride_r.one.return_value = MagicMock(
                ride_earnings=earnings, tip_earnings=tips, trip_count=trips
            )
            cancel_r = MagicMock()
            cancel_r.scalar.return_value = cancel
            return [bank_r, overlap_r, ride_r, cancel_r]

        call_sequence = [accounts_result]
        call_sequence.extend(make_sequence(ba1, 100.0, 20.0, 5, 5.0))
        call_sequence.extend(make_sequence(ba2, 200.0, 30.0, 10, 0.0))

        mock_db.execute = AsyncMock(side_effect=call_sequence)

        result = await bulk_create_payouts(
            date(2026, 4, 1), date(2026, 4, 7), mock_db
        )

        assert mock_db.add.call_count == 2

    @pytest.mark.asyncio
    async def test_skips_drivers_with_no_earnings(self):
        mock_db = AsyncMock()
        ba1 = MagicMock(driver_id=10, is_active=True, account_status="active", id=1)

        accounts_result = MagicMock()
        accounts_scalars = MagicMock()
        accounts_scalars.all.return_value = [ba1]
        accounts_result.scalars.return_value = accounts_scalars

        bank_r = MagicMock()
        bank_r.scalar_one_or_none.return_value = ba1
        overlap_r = MagicMock()
        overlap_r.scalar_one_or_none.return_value = None
        ride_r = MagicMock()
        ride_r.one.return_value = MagicMock(ride_earnings=0.0, tip_earnings=0.0, trip_count=0)
        cancel_r = MagicMock()
        cancel_r.scalar.return_value = 0.0

        mock_db.execute = AsyncMock(
            side_effect=[accounts_result, bank_r, overlap_r, ride_r, cancel_r]
        )

        result = await bulk_create_payouts(
            date(2026, 4, 1), date(2026, 4, 7), mock_db
        )

        assert len(result) == 0
        mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_empty_if_no_accounts(self):
        mock_db = AsyncMock()
        accounts_result = MagicMock()
        accounts_scalars = MagicMock()
        accounts_scalars.all.return_value = []
        accounts_result.scalars.return_value = accounts_scalars
        mock_db.execute.return_value = accounts_result

        result = await bulk_create_payouts(
            date(2026, 4, 1), date(2026, 4, 7), mock_db
        )
        assert result == []


# ===========================================================================
# API Router Tests
# ===========================================================================


class TestPayoutAPIRegistration:
    def test_payouts_router_imported(self):
        from app.api.v1 import payouts as payouts_module
        assert hasattr(payouts_module, "router")

    def test_payouts_router_prefix(self):
        from app.api.v1.payouts import router
        assert router.prefix == "/payouts"

    def test_payouts_router_tags(self):
        from app.api.v1.payouts import router
        assert "payouts" in router.tags

    def test_payouts_router_registered_in_app(self):
        from app.main import app
        routes = [r.path for r in app.routes]
        assert any("/api/v1/payouts" in r for r in routes)


class TestPayoutRouteCount:
    def test_has_bank_account_setup_route(self):
        from app.api.v1.payouts import router
        paths = [r.path for r in router.routes]
        assert "/payouts/bank-account/setup" in paths

    def test_has_bank_account_get_route(self):
        from app.api.v1.payouts import router
        paths = [r.path for r in router.routes]
        assert "/payouts/bank-account" in paths

    def test_has_frequency_update_route(self):
        from app.api.v1.payouts import router
        paths = [r.path for r in router.routes]
        assert "/payouts/bank-account/frequency" in paths

    def test_has_my_payouts_route(self):
        from app.api.v1.payouts import router
        paths = [r.path for r in router.routes]
        assert "/payouts/my-payouts" in paths

    def test_has_payout_detail_route(self):
        from app.api.v1.payouts import router
        paths = [r.path for r in router.routes]
        assert "/payouts/my-payouts/{payout_id}" in paths

    def test_has_admin_overview_route(self):
        from app.api.v1.payouts import router
        paths = [r.path for r in router.routes]
        assert "/payouts/admin/overview" in paths

    def test_has_admin_create_route(self):
        from app.api.v1.payouts import router
        paths = [r.path for r in router.routes]
        assert "/payouts/admin/create" in paths

    def test_has_admin_process_route(self):
        from app.api.v1.payouts import router
        paths = [r.path for r in router.routes]
        assert "/payouts/admin/process" in paths

    def test_has_admin_retry_route(self):
        from app.api.v1.payouts import router
        paths = [r.path for r in router.routes]
        assert "/payouts/admin/retry/{payout_id}" in paths

    def test_has_admin_bulk_route(self):
        from app.api.v1.payouts import router
        paths = [r.path for r in router.routes]
        assert "/payouts/admin/bulk" in paths

    def test_has_admin_driver_payouts_route(self):
        from app.api.v1.payouts import router
        paths = [r.path for r in router.routes]
        assert "/payouts/admin/driver/{driver_id}" in paths


# ===========================================================================
# Model Registration Tests
# ===========================================================================


class TestModelRegistration:
    def test_driver_bank_account_registered(self):
        from app.models import DriverBankAccount as DBA
        assert DBA.__tablename__ == "driver_bank_accounts"

    def test_driver_payout_registered(self):
        from app.models import DriverPayout as DP
        assert DP.__tablename__ == "driver_payouts"


# ===========================================================================
# Edge Case Tests
# ===========================================================================


class TestPayoutEdgeCases:
    def test_payout_status_is_string_enum(self):
        assert isinstance(PayoutStatus.PENDING, str)
        assert PayoutStatus.PENDING == "pending"

    def test_payout_frequency_is_string_enum(self):
        assert isinstance(PayoutFrequency.WEEKLY, str)
        assert PayoutFrequency.WEEKLY == "weekly"

    def test_payout_detail_with_all_nulls(self):
        d = PayoutDetailResponse(
            id=1,
            driver_id=1,
            bank_account_id=1,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 7),
            ride_earnings=0.0,
            tip_earnings=0.0,
            cancellation_fee_earnings=0.0,
            bonus_amount=0.0,
            deductions=0.0,
            total_amount=0.0,
            trip_count=0,
            status="pending",
            created_at=datetime(2026, 1, 8, tzinfo=timezone.utc),
        )
        assert d.stripe_transfer_id is None
        assert d.failure_reason is None
        assert d.notes is None
        assert d.processed_at is None
        assert d.completed_at is None

    def test_bank_account_response_from_attributes(self):
        assert BankAccountResponse.model_config.get("from_attributes") is True

    def test_payout_summary_from_attributes(self):
        assert PayoutSummary.model_config.get("from_attributes") is True

    def test_payout_detail_from_attributes(self):
        assert PayoutDetailResponse.model_config.get("from_attributes") is True

    @pytest.mark.asyncio
    async def test_create_connect_account_stripe_called_with_correct_params(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with patch("app.services.payouts.stripe") as mock_stripe:
            mock_stripe.Account.create.return_value = MagicMock(id="acct_test")
            mock_stripe.AccountLink.create.return_value = MagicMock(url="https://link")

            await create_connect_account(42, "https://return", "https://refresh", mock_db)

            mock_stripe.Account.create.assert_called_once_with(
                type="express",
                country="US",
                capabilities={"transfers": {"requested": True}},
                metadata={"driver_id": "42"},
            )
            mock_stripe.AccountLink.create.assert_called_once_with(
                account="acct_test",
                refresh_url="https://refresh",
                return_url="https://return",
                type="account_onboarding",
            )

    @pytest.mark.asyncio
    async def test_process_payout_stripe_transfer_params(self):
        mock_db = AsyncMock()
        payout = MagicMock(
            id=5, status=PayoutStatus.PENDING, total_amount=99.99,
            bank_account_id=1, driver_id=7,
            period_start=date(2026, 4, 1), period_end=date(2026, 4, 7),
        )
        payout_result = MagicMock()
        payout_result.scalar_one_or_none.return_value = payout

        bank_account = MagicMock(
            id=1, is_active=True, stripe_connect_account_id="acct_driver7"
        )
        bank_result = MagicMock()
        bank_result.scalar_one_or_none.return_value = bank_account

        mock_db.execute = AsyncMock(side_effect=[payout_result, bank_result])

        with patch("app.services.payouts.stripe") as mock_stripe:
            mock_stripe.Transfer.create.return_value = MagicMock(id="tr_x")
            mock_stripe.error.StripeError = Exception

            await process_payout(5, mock_db)

            mock_stripe.Transfer.create.assert_called_once_with(
                amount=9999,
                currency="usd",
                destination="acct_driver7",
                metadata={
                    "payout_id": "5",
                    "driver_id": "7",
                    "period": "2026-04-01 to 2026-04-07",
                },
            )
