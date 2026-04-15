"""Unit tests for the driver tax reporting / 1099-NEC feature.

All tests are pure unit tests — no database or HTTP client required.
Every external dependency (DB session) is mocked with AsyncMock / MagicMock.

Covers:
- DriverTaxProfile model fields and enum values
- DriverTaxDocument model fields, enums, and unique constraint definition
- Schemas: TaxProfileResponse, TaxDocumentResponse, W9SubmitRequest,
           BatchGenerateResponse, AdminSubmitRequest
- get_or_create_tax_profile: existing found, not found → creates new
- update_w9: success, invalid tin_last4 raises 422
- calculate_annual_earnings: earnings present, no payouts, no driver profile
- generate_tax_document: below $600 → earnings_summary, at/above $600 → 1099_nec,
  update existing document
- get_driver_tax_documents: returns list, empty list
- get_driver_tax_documents_for_year: filters by year
- admin_get_tax_documents: no filter, status filter
- admin_batch_generate: success with multiple drivers, empty set, error handling
- mark_submitted: success, not found raises 404
- Router endpoints: all 8 routes — success, auth mocking, response shape
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.driver_tax_document import (
    DriverTaxDocument,
    DriverTaxProfile,
    TaxDocumentStatus,
    TaxDocumentType,
    TinType,
)
from app.schemas.driver_tax import (
    AdminSubmitRequest,
    BatchGenerateResponse,
    TaxDocumentResponse,
    TaxProfileResponse,
    W9SubmitRequest,
)
from app.services.driver_tax import (
    NEC_THRESHOLD_CENTS,
    admin_batch_generate,
    admin_get_tax_documents,
    calculate_annual_earnings,
    generate_tax_document,
    get_driver_tax_documents,
    get_driver_tax_documents_for_year,
    get_or_create_tax_profile,
    mark_submitted,
    update_w9,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _make_tax_profile(
    id: int = 1,
    driver_profile_id: int = 10,
    tin_type: TinType | None = TinType.ssn,
    tin_last4: str | None = "1234",
    business_name: str | None = None,
    has_w9: bool = True,
    is_backup_withholding_exempt: bool = True,
) -> DriverTaxProfile:
    p = DriverTaxProfile()
    p.id = id
    p.driver_profile_id = driver_profile_id
    p.tin_type = tin_type
    p.tin_last4 = tin_last4
    p.business_name = business_name
    p.has_w9 = has_w9
    p.w9_received_at = _now() if has_w9 else None
    p.is_backup_withholding_exempt = is_backup_withholding_exempt
    p.created_at = _now()
    p.updated_at = _now()
    return p


def _make_tax_document(
    id: int = 1,
    driver_profile_id: int = 10,
    tax_year: int = 2025,
    document_type: TaxDocumentType = TaxDocumentType.nec_1099,
    status: TaxDocumentStatus = TaxDocumentStatus.ready,
    gross_earnings_cents: int = 120_000,
    nonemployee_compensation_cents: int = 120_000,
    rides_count: int = 50,
    admin_notes: str | None = None,
    generated_at: datetime | None = None,
    submitted_at: datetime | None = None,
) -> DriverTaxDocument:
    d = DriverTaxDocument()
    d.id = id
    d.driver_profile_id = driver_profile_id
    d.tax_year = tax_year
    d.document_type = document_type
    d.status = status
    d.gross_earnings_cents = gross_earnings_cents
    d.nonemployee_compensation_cents = nonemployee_compensation_cents
    d.rides_count = rides_count
    d.admin_notes = admin_notes
    d.generated_at = generated_at or _now()
    d.submitted_at = submitted_at
    d.created_at = _now()
    d.updated_at = _now()
    return d


def _db_result(value):
    """Return a mock db.execute() result with scalar_one_or_none and scalars."""
    m = MagicMock()
    m.scalar_one_or_none.return_value = value
    m.scalar_one.return_value = value if not isinstance(value, list) else None
    m.scalar.return_value = value if not isinstance(value, list) else (len(value) if value else 0)
    scalars_m = MagicMock()
    scalars_m.all.return_value = value if isinstance(value, list) else ([value] if value else [])
    m.scalars.return_value = scalars_m
    row = MagicMock()
    row.gross_cents = 0
    row.rides_count = 0
    m.one.return_value = row
    return m


def _make_db(execute_results=None) -> AsyncMock:
    db = AsyncMock()
    if execute_results is not None:
        db.execute.side_effect = execute_results
    return db


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestDriverTaxProfileModel:
    def test_tablename(self):
        assert DriverTaxProfile.__tablename__ == "driver_tax_profiles"

    def test_tin_type_enum_values(self):
        assert TinType.ssn.value == "ssn"
        assert TinType.ein.value == "ein"

    def test_tin_type_is_str_enum(self):
        assert isinstance(TinType.ssn, str)

    def test_make_profile_fields(self):
        p = _make_tax_profile()
        assert p.id == 1
        assert p.driver_profile_id == 10
        assert p.tin_type == TinType.ssn
        assert p.tin_last4 == "1234"
        assert p.has_w9 is True
        assert p.is_backup_withholding_exempt is True

    def test_profile_nullable_fields(self):
        p = _make_tax_profile(tin_type=None, tin_last4=None, has_w9=False)
        assert p.tin_type is None
        assert p.tin_last4 is None
        assert p.w9_received_at is None


class TestDriverTaxDocumentModel:
    def test_tablename(self):
        assert DriverTaxDocument.__tablename__ == "driver_tax_documents"

    def test_document_type_enum_values(self):
        assert TaxDocumentType.nec_1099.value == "1099_nec"
        assert TaxDocumentType.earnings_summary.value == "earnings_summary"

    def test_status_enum_values(self):
        assert TaxDocumentStatus.pending.value == "pending"
        assert TaxDocumentStatus.ready.value == "ready"
        assert TaxDocumentStatus.submitted_to_irs.value == "submitted_to_irs"
        assert TaxDocumentStatus.corrected.value == "corrected"

    def test_document_type_is_str_enum(self):
        assert isinstance(TaxDocumentType.nec_1099, str)

    def test_status_is_str_enum(self):
        assert isinstance(TaxDocumentStatus.pending, str)

    def test_make_document_fields(self):
        d = _make_tax_document()
        assert d.id == 1
        assert d.driver_profile_id == 10
        assert d.tax_year == 2025
        assert d.document_type == TaxDocumentType.nec_1099
        assert d.status == TaxDocumentStatus.ready
        assert d.gross_earnings_cents == 120_000
        assert d.nonemployee_compensation_cents == 120_000
        assert d.rides_count == 50
        assert d.submitted_at is None

    def test_table_args_unique_constraint_defined(self):
        # The model must declare a UniqueConstraint
        args = DriverTaxDocument.__table_args__
        assert len(args) >= 1

    def test_nec_threshold_cents(self):
        assert NEC_THRESHOLD_CENTS == 60_000


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestW9SubmitRequest:
    def test_valid_ssn(self):
        req = W9SubmitRequest(tin_type=TinType.ssn, tin_last4="1234")
        assert req.tin_type == TinType.ssn
        assert req.tin_last4 == "1234"
        assert req.business_name is None

    def test_valid_ein_with_business_name(self):
        req = W9SubmitRequest(
            tin_type=TinType.ein, tin_last4="5678", business_name="ACME LLC"
        )
        assert req.business_name == "ACME LLC"

    def test_invalid_tin_last4_too_short_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            W9SubmitRequest(tin_type=TinType.ssn, tin_last4="12")

    def test_invalid_tin_last4_non_digit_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            W9SubmitRequest(tin_type=TinType.ssn, tin_last4="12ab")


class TestTaxProfileResponse:
    def test_from_attributes(self):
        p = _make_tax_profile()
        resp = TaxProfileResponse.model_validate(p)
        assert resp.id == 1
        assert resp.driver_profile_id == 10
        assert resp.tin_last4 == "1234"
        assert resp.has_w9 is True

    def test_nullable_tin_fields(self):
        p = _make_tax_profile(tin_type=None, tin_last4=None, has_w9=False)
        resp = TaxProfileResponse.model_validate(p)
        assert resp.tin_type is None
        assert resp.tin_last4 is None


class TestTaxDocumentResponse:
    def test_from_attributes(self):
        d = _make_tax_document()
        resp = TaxDocumentResponse.model_validate(d)
        assert resp.id == 1
        assert resp.tax_year == 2025
        assert resp.document_type == TaxDocumentType.nec_1099
        assert resp.status == TaxDocumentStatus.ready
        assert resp.gross_earnings_cents == 120_000

    def test_nullable_fields(self):
        d = _make_tax_document(admin_notes=None, submitted_at=None)
        resp = TaxDocumentResponse.model_validate(d)
        assert resp.admin_notes is None
        assert resp.submitted_at is None


class TestBatchGenerateResponse:
    def test_fields(self):
        resp = BatchGenerateResponse(tax_year=2025, generated=10, skipped=2, errors=1)
        assert resp.tax_year == 2025
        assert resp.generated == 10
        assert resp.skipped == 2
        assert resp.errors == 1


class TestAdminSubmitRequest:
    def test_defaults(self):
        req = AdminSubmitRequest()
        assert req.admin_notes is None

    def test_with_notes(self):
        req = AdminSubmitRequest(admin_notes="Submitted batch Jan 31")
        assert req.admin_notes == "Submitted batch Jan 31"


# ---------------------------------------------------------------------------
# Service: get_or_create_tax_profile
# ---------------------------------------------------------------------------


class TestGetOrCreateTaxProfile:
    @pytest.mark.asyncio
    async def test_existing_profile_returned(self):
        profile = _make_tax_profile()
        db = _make_db()
        db.execute.return_value = _db_result(profile)

        result = await get_or_create_tax_profile(db, driver_profile_id=10)
        assert result is profile

    @pytest.mark.asyncio
    async def test_creates_new_profile_when_not_found(self):
        db = AsyncMock()
        # execute returns None → not found
        not_found = MagicMock()
        not_found.scalar_one_or_none.return_value = None
        db.execute.return_value = not_found
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        result = await get_or_create_tax_profile(db, driver_profile_id=10)

        db.add.assert_called_once()
        db.flush.assert_called_once()
        # The result should be a DriverTaxProfile with the correct driver_profile_id
        assert isinstance(result, DriverTaxProfile)
        assert result.driver_profile_id == 10


# ---------------------------------------------------------------------------
# Service: update_w9
# ---------------------------------------------------------------------------


class TestUpdateW9:
    @pytest.mark.asyncio
    async def test_success(self):
        profile = _make_tax_profile(has_w9=False, tin_type=None, tin_last4=None)
        db = _make_db()
        db.execute.return_value = _db_result(profile)
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        result = await update_w9(db, driver_profile_id=10, tin_type=TinType.ssn, tin_last4="4321")

        assert profile.has_w9 is True
        assert profile.tin_type == TinType.ssn
        assert profile.tin_last4 == "4321"
        assert profile.w9_received_at is not None

    @pytest.mark.asyncio
    async def test_business_name_saved_for_ein(self):
        profile = _make_tax_profile(has_w9=False, tin_type=None, tin_last4=None)
        db = _make_db()
        db.execute.return_value = _db_result(profile)
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        await update_w9(
            db,
            driver_profile_id=10,
            tin_type=TinType.ein,
            tin_last4="7890",
            business_name="Driver LLC",
        )

        assert profile.business_name == "Driver LLC"
        assert profile.tin_type == TinType.ein

    @pytest.mark.asyncio
    async def test_invalid_tin_last4_raises_422(self):
        from fastapi import HTTPException

        db = _make_db()
        with pytest.raises(HTTPException) as exc_info:
            await update_w9(db, driver_profile_id=10, tin_type=TinType.ssn, tin_last4="AB12")

        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_tin_last4_too_short_raises_422(self):
        from fastapi import HTTPException

        db = _make_db()
        with pytest.raises(HTTPException) as exc_info:
            await update_w9(db, driver_profile_id=10, tin_type=TinType.ssn, tin_last4="12")

        assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# Service: calculate_annual_earnings
# ---------------------------------------------------------------------------


class TestCalculateAnnualEarnings:
    @pytest.mark.asyncio
    async def test_driver_profile_not_found_returns_zeros(self):
        db = _make_db()
        db.execute.return_value = _db_result(None)

        result = await calculate_annual_earnings(db, driver_profile_id=999, tax_year=2025)

        assert result["gross_earnings_cents"] == 0
        assert result["rides_count"] == 0

    @pytest.mark.asyncio
    async def test_earnings_summed_correctly(self):
        db = AsyncMock()

        # First call: resolve user_id from driver_profile_id
        profile_result = MagicMock()
        profile_result.scalar_one_or_none.return_value = 42  # user_id

        # Second call: aggregate payouts
        earnings_row = MagicMock()
        earnings_row.gross_cents = 150_000
        earnings_row.rides_count = 60
        earnings_result = MagicMock()
        earnings_result.one.return_value = earnings_row

        db.execute.side_effect = [profile_result, earnings_result]

        result = await calculate_annual_earnings(db, driver_profile_id=10, tax_year=2025)

        assert result["gross_earnings_cents"] == 150_000
        assert result["rides_count"] == 60

    @pytest.mark.asyncio
    async def test_no_completed_payouts_returns_zeros(self):
        db = AsyncMock()

        profile_result = MagicMock()
        profile_result.scalar_one_or_none.return_value = 42

        earnings_row = MagicMock()
        earnings_row.gross_cents = 0
        earnings_row.rides_count = 0
        earnings_result = MagicMock()
        earnings_result.one.return_value = earnings_row

        db.execute.side_effect = [profile_result, earnings_result]

        result = await calculate_annual_earnings(db, driver_profile_id=10, tax_year=2025)

        assert result["gross_earnings_cents"] == 0
        assert result["rides_count"] == 0


# ---------------------------------------------------------------------------
# Service: generate_tax_document
# ---------------------------------------------------------------------------


class TestGenerateTaxDocument:
    @pytest.mark.asyncio
    async def test_below_600_generates_earnings_summary(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        # No existing doc found
        not_found = MagicMock()
        not_found.scalar_one_or_none.return_value = None
        db.execute.return_value = not_found

        with patch(
            "app.services.driver_tax.calculate_annual_earnings",
            new=AsyncMock(return_value={"gross_earnings_cents": 30_000, "rides_count": 10}),
        ):
            result = await generate_tax_document(db, driver_profile_id=10, tax_year=2025)

        assert result.document_type == TaxDocumentType.earnings_summary
        assert result.nonemployee_compensation_cents == 0
        assert result.gross_earnings_cents == 30_000
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_at_600_generates_1099_nec(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        not_found = MagicMock()
        not_found.scalar_one_or_none.return_value = None
        db.execute.return_value = not_found

        with patch(
            "app.services.driver_tax.calculate_annual_earnings",
            new=AsyncMock(return_value={"gross_earnings_cents": 60_000, "rides_count": 30}),
        ):
            result = await generate_tax_document(db, driver_profile_id=10, tax_year=2025)

        assert result.document_type == TaxDocumentType.nec_1099
        assert result.nonemployee_compensation_cents == 60_000
        assert result.rides_count == 30

    @pytest.mark.asyncio
    async def test_above_600_generates_1099_nec(self):
        db = AsyncMock()

        with patch(
            "app.services.driver_tax.calculate_annual_earnings",
            new=AsyncMock(return_value={"gross_earnings_cents": 120_000, "rides_count": 50}),
        ):
            existing_doc = _make_tax_document(
                document_type=TaxDocumentType.nec_1099,
                status=TaxDocumentStatus.pending,
            )
            db.execute.return_value = _db_result(existing_doc)
            db.flush = AsyncMock()
            db.refresh = AsyncMock()

            result = await generate_tax_document(db, driver_profile_id=10, tax_year=2025)

        assert result.document_type == TaxDocumentType.nec_1099
        assert result.gross_earnings_cents == 120_000
        assert result.status == TaxDocumentStatus.ready

    @pytest.mark.asyncio
    async def test_updates_existing_document(self):
        """Re-running generate_tax_document updates the existing doc."""
        db = AsyncMock()

        with patch(
            "app.services.driver_tax.calculate_annual_earnings",
            new=AsyncMock(return_value={"gross_earnings_cents": 80_000, "rides_count": 35}),
        ):
            existing_doc = _make_tax_document(
                gross_earnings_cents=70_000,
                nonemployee_compensation_cents=70_000,
                status=TaxDocumentStatus.pending,
            )
            db.execute.return_value = _db_result(existing_doc)
            db.flush = AsyncMock()
            db.refresh = AsyncMock()

            result = await generate_tax_document(db, driver_profile_id=10, tax_year=2025)

        assert result.gross_earnings_cents == 80_000
        assert result.rides_count == 35
        assert result.generated_at is not None


# ---------------------------------------------------------------------------
# Service: get_driver_tax_documents
# ---------------------------------------------------------------------------


class TestGetDriverTaxDocuments:
    @pytest.mark.asyncio
    async def test_returns_list(self):
        docs = [_make_tax_document(id=i) for i in range(3)]
        db = _make_db()
        db.execute.return_value = _db_result(docs)

        result = await get_driver_tax_documents(db, driver_profile_id=10)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_empty_list(self):
        db = _make_db()
        db.execute.return_value = _db_result([])

        result = await get_driver_tax_documents(db, driver_profile_id=99)
        assert result == []


# ---------------------------------------------------------------------------
# Service: get_driver_tax_documents_for_year
# ---------------------------------------------------------------------------


class TestGetDriverTaxDocumentsForYear:
    @pytest.mark.asyncio
    async def test_filters_by_year(self):
        doc = _make_tax_document(tax_year=2024)
        db = _make_db()
        db.execute.return_value = _db_result([doc])

        result = await get_driver_tax_documents_for_year(db, driver_profile_id=10, tax_year=2024)
        assert len(result) == 1
        assert result[0].tax_year == 2024

    @pytest.mark.asyncio
    async def test_empty_for_year(self):
        db = _make_db()
        db.execute.return_value = _db_result([])

        result = await get_driver_tax_documents_for_year(db, driver_profile_id=10, tax_year=2020)
        assert result == []


# ---------------------------------------------------------------------------
# Service: admin_get_tax_documents
# ---------------------------------------------------------------------------


class TestAdminGetTaxDocuments:
    @pytest.mark.asyncio
    async def test_no_status_filter(self):
        docs = [_make_tax_document(id=i, driver_profile_id=i + 1) for i in range(5)]
        db = _make_db()
        db.execute.return_value = _db_result(docs)

        result = await admin_get_tax_documents(db, tax_year=2025)
        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_with_status_filter(self):
        db = _make_db()
        db.execute.return_value = _db_result([])

        result = await admin_get_tax_documents(
            db, tax_year=2025, status=TaxDocumentStatus.ready
        )
        assert result == []
        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_pagination_params(self):
        db = _make_db()
        db.execute.return_value = _db_result([])

        await admin_get_tax_documents(db, tax_year=2025, limit=10, offset=20)
        db.execute.assert_called_once()


# ---------------------------------------------------------------------------
# Service: admin_batch_generate
# ---------------------------------------------------------------------------


class TestAdminBatchGenerate:
    @pytest.mark.asyncio
    async def test_generates_for_all_drivers(self):
        db = AsyncMock()

        # First execute: distinct driver user_ids
        user_ids_result = MagicMock()
        user_ids_result.all.return_value = [(1,), (2,), (3,)]

        # Second execute: resolve to driver_profile_ids
        profile_ids_result = MagicMock()
        profile_ids_result.all.return_value = [(10,), (20,), (30,)]

        db.execute.side_effect = [user_ids_result, profile_ids_result]

        with patch(
            "app.services.driver_tax.generate_tax_document",
            new=AsyncMock(return_value=_make_tax_document()),
        ) as mock_gen:
            result = await admin_batch_generate(db, tax_year=2025)

        assert result["generated"] == 3
        assert result["errors"] == 0
        assert mock_gen.call_count == 3

    @pytest.mark.asyncio
    async def test_no_drivers_returns_zeros(self):
        db = AsyncMock()

        user_ids_result = MagicMock()
        user_ids_result.all.return_value = []

        profile_ids_result = MagicMock()
        profile_ids_result.all.return_value = []

        db.execute.side_effect = [user_ids_result, profile_ids_result]

        result = await admin_batch_generate(db, tax_year=2025)

        assert result["generated"] == 0
        assert result["errors"] == 0
        assert result["skipped"] == 0

    @pytest.mark.asyncio
    async def test_errors_counted_on_failure(self):
        db = AsyncMock()

        user_ids_result = MagicMock()
        user_ids_result.all.return_value = [(1,)]

        profile_ids_result = MagicMock()
        profile_ids_result.all.return_value = [(10,)]

        db.execute.side_effect = [user_ids_result, profile_ids_result]

        with patch(
            "app.services.driver_tax.generate_tax_document",
            new=AsyncMock(side_effect=Exception("DB error")),
        ):
            result = await admin_batch_generate(db, tax_year=2025)

        assert result["errors"] == 1
        assert result["generated"] == 0


# ---------------------------------------------------------------------------
# Service: mark_submitted
# ---------------------------------------------------------------------------


class TestMarkSubmitted:
    @pytest.mark.asyncio
    async def test_success(self):
        doc = _make_tax_document(status=TaxDocumentStatus.ready)
        db = _make_db()
        db.execute.return_value = _db_result(doc)
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        result = await mark_submitted(db, document_id=1)

        assert doc.status == TaxDocumentStatus.submitted_to_irs
        assert doc.submitted_at is not None

    @pytest.mark.asyncio
    async def test_admin_notes_saved(self):
        doc = _make_tax_document(status=TaxDocumentStatus.ready)
        db = _make_db()
        db.execute.return_value = _db_result(doc)
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        await mark_submitted(db, document_id=1, admin_notes="IRS batch January 2026")

        assert doc.admin_notes == "IRS batch January 2026"

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        from fastapi import HTTPException

        db = _make_db()
        db.execute.return_value = _db_result(None)

        with pytest.raises(HTTPException) as exc_info:
            await mark_submitted(db, document_id=999)

        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Router / endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_driver():
    from app.models.user import User, UserRole
    user = MagicMock(spec=User)
    user.id = 42
    user.role = UserRole.DRIVER
    return user


@pytest.fixture
def mock_admin():
    from app.models.user import User, UserRole
    user = MagicMock(spec=User)
    user.id = 1
    user.role = UserRole.ADMIN
    return user


@pytest.fixture
def mock_db():
    return AsyncMock()


class TestGetMyTaxProfileEndpoint:
    @pytest.mark.asyncio
    async def test_returns_profile(self, mock_driver, mock_db):
        from app.api.v1.driver_tax import get_my_tax_profile

        profile = _make_tax_profile()

        with patch(
            "app.api.v1.driver_tax._get_driver_profile_id",
            new=AsyncMock(return_value=10),
        ), patch(
            "app.api.v1.driver_tax.get_or_create_tax_profile",
            new=AsyncMock(return_value=profile),
        ):
            result = await get_my_tax_profile(user=mock_driver, db=mock_db)

        assert result.driver_profile_id == 10
        assert result.tin_last4 == "1234"

    @pytest.mark.asyncio
    async def test_no_profile_creates_blank(self, mock_driver, mock_db):
        from app.api.v1.driver_tax import get_my_tax_profile

        blank_profile = _make_tax_profile(tin_type=None, tin_last4=None, has_w9=False)

        with patch(
            "app.api.v1.driver_tax._get_driver_profile_id",
            new=AsyncMock(return_value=10),
        ), patch(
            "app.api.v1.driver_tax.get_or_create_tax_profile",
            new=AsyncMock(return_value=blank_profile),
        ):
            result = await get_my_tax_profile(user=mock_driver, db=mock_db)

        assert result.has_w9 is False
        assert result.tin_last4 is None


class TestSubmitW9Endpoint:
    @pytest.mark.asyncio
    async def test_success(self, mock_driver, mock_db):
        from app.api.v1.driver_tax import submit_w9

        profile = _make_tax_profile()
        req = W9SubmitRequest(tin_type=TinType.ssn, tin_last4="1234")

        with patch(
            "app.api.v1.driver_tax._get_driver_profile_id",
            new=AsyncMock(return_value=10),
        ), patch(
            "app.api.v1.driver_tax.update_w9",
            new=AsyncMock(return_value=profile),
        ):
            result = await submit_w9(req=req, user=mock_driver, db=mock_db)

        assert result.has_w9 is True
        assert result.tin_last4 == "1234"

    @pytest.mark.asyncio
    async def test_ein_with_business_name(self, mock_driver, mock_db):
        from app.api.v1.driver_tax import submit_w9

        profile = _make_tax_profile(tin_type=TinType.ein, business_name="LLC Co")
        req = W9SubmitRequest(
            tin_type=TinType.ein, tin_last4="5678", business_name="LLC Co"
        )

        with patch(
            "app.api.v1.driver_tax._get_driver_profile_id",
            new=AsyncMock(return_value=10),
        ), patch(
            "app.api.v1.driver_tax.update_w9",
            new=AsyncMock(return_value=profile),
        ):
            result = await submit_w9(req=req, user=mock_driver, db=mock_db)

        assert result.business_name == "LLC Co"


class TestListMyTaxDocumentsEndpoint:
    @pytest.mark.asyncio
    async def test_returns_list(self, mock_driver, mock_db):
        from app.api.v1.driver_tax import list_my_tax_documents

        docs = [_make_tax_document(id=i) for i in range(3)]

        with patch(
            "app.api.v1.driver_tax._get_driver_profile_id",
            new=AsyncMock(return_value=10),
        ), patch(
            "app.api.v1.driver_tax.get_driver_tax_documents",
            new=AsyncMock(return_value=docs),
        ):
            result = await list_my_tax_documents(user=mock_driver, db=mock_db)

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_empty_list(self, mock_driver, mock_db):
        from app.api.v1.driver_tax import list_my_tax_documents

        with patch(
            "app.api.v1.driver_tax._get_driver_profile_id",
            new=AsyncMock(return_value=10),
        ), patch(
            "app.api.v1.driver_tax.get_driver_tax_documents",
            new=AsyncMock(return_value=[]),
        ):
            result = await list_my_tax_documents(user=mock_driver, db=mock_db)

        assert result == []


class TestGetMyTaxDocumentsForYearEndpoint:
    @pytest.mark.asyncio
    async def test_returns_documents_for_year(self, mock_driver, mock_db):
        from app.api.v1.driver_tax import get_my_tax_documents_for_year

        docs = [_make_tax_document(tax_year=2025)]

        with patch(
            "app.api.v1.driver_tax._get_driver_profile_id",
            new=AsyncMock(return_value=10),
        ), patch(
            "app.api.v1.driver_tax.get_driver_tax_documents_for_year",
            new=AsyncMock(return_value=docs),
        ):
            result = await get_my_tax_documents_for_year(
                year=2025, user=mock_driver, db=mock_db
            )

        assert len(result) == 1
        assert result[0].tax_year == 2025

    @pytest.mark.asyncio
    async def test_no_documents_for_year(self, mock_driver, mock_db):
        from app.api.v1.driver_tax import get_my_tax_documents_for_year

        with patch(
            "app.api.v1.driver_tax._get_driver_profile_id",
            new=AsyncMock(return_value=10),
        ), patch(
            "app.api.v1.driver_tax.get_driver_tax_documents_for_year",
            new=AsyncMock(return_value=[]),
        ):
            result = await get_my_tax_documents_for_year(
                year=2020, user=mock_driver, db=mock_db
            )

        assert result == []


class TestAdminListTaxDocumentsEndpoint:
    @pytest.mark.asyncio
    async def test_returns_all_documents(self, mock_admin, mock_db):
        from app.api.v1.driver_tax import admin_list_tax_documents

        docs = [_make_tax_document(id=i, driver_profile_id=i + 1) for i in range(5)]

        with patch(
            "app.api.v1.driver_tax.admin_get_tax_documents",
            new=AsyncMock(return_value=docs),
        ):
            result = await admin_list_tax_documents(
                year=2025, status=None, limit=50, offset=0,
                _admin=mock_admin, db=mock_db,
            )

        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_with_status_filter(self, mock_admin, mock_db):
        from app.api.v1.driver_tax import admin_list_tax_documents

        with patch(
            "app.api.v1.driver_tax.admin_get_tax_documents",
            new=AsyncMock(return_value=[]),
        ) as mock_fn:
            result = await admin_list_tax_documents(
                year=2025,
                status=TaxDocumentStatus.ready,
                limit=50,
                offset=0,
                _admin=mock_admin,
                db=mock_db,
            )

        assert result == []
        mock_fn.assert_called_once_with(
            mock_db, 2025, status=TaxDocumentStatus.ready, limit=50, offset=0
        )


class TestAdminBatchGenerateEndpoint:
    @pytest.mark.asyncio
    async def test_returns_batch_response(self, mock_admin, mock_db):
        from app.api.v1.driver_tax import admin_batch_generate_documents

        with patch(
            "app.api.v1.driver_tax.admin_batch_generate",
            new=AsyncMock(return_value={"generated": 5, "skipped": 0, "errors": 1}),
        ):
            result = await admin_batch_generate_documents(
                year=2025, _admin=mock_admin, db=mock_db
            )

        assert result.tax_year == 2025
        assert result.generated == 5
        assert result.errors == 1

    @pytest.mark.asyncio
    async def test_zero_drivers(self, mock_admin, mock_db):
        from app.api.v1.driver_tax import admin_batch_generate_documents

        with patch(
            "app.api.v1.driver_tax.admin_batch_generate",
            new=AsyncMock(return_value={"generated": 0, "skipped": 0, "errors": 0}),
        ):
            result = await admin_batch_generate_documents(
                year=2025, _admin=mock_admin, db=mock_db
            )

        assert result.generated == 0


class TestAdminMarkSubmittedEndpoint:
    @pytest.mark.asyncio
    async def test_success(self, mock_admin, mock_db):
        from app.api.v1.driver_tax import admin_mark_submitted

        doc = _make_tax_document(status=TaxDocumentStatus.submitted_to_irs)

        with patch(
            "app.api.v1.driver_tax.mark_submitted",
            new=AsyncMock(return_value=doc),
        ):
            result = await admin_mark_submitted(
                document_id=1, req=None, _admin=mock_admin, db=mock_db
            )

        assert result.status == TaxDocumentStatus.submitted_to_irs

    @pytest.mark.asyncio
    async def test_with_admin_notes(self, mock_admin, mock_db):
        from app.api.v1.driver_tax import admin_mark_submitted

        doc = _make_tax_document(
            status=TaxDocumentStatus.submitted_to_irs, admin_notes="Batch run"
        )
        req = AdminSubmitRequest(admin_notes="Batch run")

        with patch(
            "app.api.v1.driver_tax.mark_submitted",
            new=AsyncMock(return_value=doc),
        ) as mock_fn:
            result = await admin_mark_submitted(
                document_id=1, req=req, _admin=mock_admin, db=mock_db
            )

        mock_fn.assert_called_once_with(mock_db, 1, admin_notes="Batch run")
        assert result.admin_notes == "Batch run"


class TestAdminGetDriverTaxProfileEndpoint:
    @pytest.mark.asyncio
    async def test_returns_profile(self, mock_admin, mock_db):
        from app.api.v1.driver_tax import admin_get_driver_tax_profile

        profile = _make_tax_profile(driver_profile_id=99)

        with patch(
            "app.api.v1.driver_tax.get_or_create_tax_profile",
            new=AsyncMock(return_value=profile),
        ):
            result = await admin_get_driver_tax_profile(
                driver_profile_id=99, _admin=mock_admin, db=mock_db
            )

        assert result.driver_profile_id == 99

    @pytest.mark.asyncio
    async def test_creates_blank_if_not_found(self, mock_admin, mock_db):
        from app.api.v1.driver_tax import admin_get_driver_tax_profile

        blank = _make_tax_profile(driver_profile_id=50, tin_type=None, tin_last4=None, has_w9=False)

        with patch(
            "app.api.v1.driver_tax.get_or_create_tax_profile",
            new=AsyncMock(return_value=blank),
        ):
            result = await admin_get_driver_tax_profile(
                driver_profile_id=50, _admin=mock_admin, db=mock_db
            )

        assert result.has_w9 is False
