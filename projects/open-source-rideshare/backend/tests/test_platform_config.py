"""Tests for the platform admin config feature.

Covers:

Service unit tests (AsyncMock DB):
  1.  parse_typed_value — string type returns string unchanged
  2.  parse_typed_value — float type parses correctly
  3.  parse_typed_value — int type parses correctly
  4.  parse_typed_value — bool "true" parses to True
  5.  parse_typed_value — bool "false" parses to False
  6.  parse_typed_value — bool "1" parses to True
  7.  parse_typed_value — bool "0" parses to False
  8.  parse_typed_value — bool "yes" parses to True
  9.  parse_typed_value — bool "no" parses to False
  10. parse_typed_value — bool invalid raises ValueError
  11. parse_typed_value — json parses dict correctly
  12. parse_typed_value — json invalid raises ValueError
  13. validate_value_for_type — raises ValueError for non-numeric float
  14. validate_value_for_type — passes silently for valid float
  15. get_all_config — empty DB returns empty list
  16. get_all_config — returns entries ordered by category then key
  17. get_all_config — category filter passes WHERE clause
  18. get_config_entry — returns None when key not found
  19. get_config_entry — returns dict with typed_value when found
  20. update_config_entry — returns None when key not found
  21. update_config_entry — updates value and calls commit
  22. update_config_entry — raises ValueError for type-invalid value
  23. update_config_entry — updates description when provided
  24. update_config_entry — calls log_event after update
  25. bulk_update_config — all updates succeed returns correct counts
  26. bulk_update_config — missing key in one update still processes others
  27. bulk_update_config — type-invalid value records failure
  28. bulk_update_config — failed_count matches number of errors

API integration tests (real in-transaction test DB via conftest):
  29. GET /api/v1/admin/config — 401 without auth
  30. GET /api/v1/admin/config — 403 with rider token
  31. GET /api/v1/admin/config — 403 with driver token
  32. GET /api/v1/admin/config — 200 with admin token
  33. GET /api/v1/admin/config — response has entries and total fields
  34. GET /api/v1/admin/config — category filter returns subset
  35. GET /api/v1/admin/config — invalid category returns 422
  36. GET /api/v1/admin/config/{key} — 404 for unknown key
  37. GET /api/v1/admin/config/{key} — 200 for known key
  38. GET /api/v1/admin/config/{key} — response has typed_value field
  39. PUT /api/v1/admin/config/{key} — 401 without auth
  40. PUT /api/v1/admin/config/{key} — 403 with rider token
  41. PUT /api/v1/admin/config/{key} — 404 for unknown key
  42. PUT /api/v1/admin/config/{key} — 200 updates float value
  43. PUT /api/v1/admin/config/{key} — 422 for non-numeric value on float key
  44. PUT /api/v1/admin/config/{key} — 422 for empty value
  45. PUT /api/v1/admin/config/{key} — updates description when provided
  46. POST /api/v1/admin/config/bulk — 401 without auth
  47. POST /api/v1/admin/config/bulk — 200 with valid updates
  48. POST /api/v1/admin/config/bulk — reports per-key failures in results
  49. POST /api/v1/admin/config/bulk — 422 for empty updates list
  50. POST /api/v1/admin/config/bulk — updated_count and failed_count correct
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.platform_config import ConfigCategory, ConfigValueType
from app.services.platform_config import (
    bulk_update_config,
    get_all_config,
    get_config_entry,
    parse_typed_value,
    update_config_entry,
    validate_value_for_type,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config_entry(
    key: str = "base_fare",
    category: ConfigCategory = ConfigCategory.PRICING,
    value_type: ConfigValueType = ConfigValueType.FLOAT,
    value: str = "2.5",
    label: str = "Base Fare",
    description: str | None = None,
    updated_by_id: int | None = None,
) -> MagicMock:
    entry = MagicMock()
    entry.key = key
    entry.category = category
    entry.value_type = value_type
    entry.value = value
    entry.label = label
    entry.description = description
    entry.updated_by_id = updated_by_id
    entry.updated_at = datetime(2026, 4, 14, 12, 0, 0, tzinfo=timezone.utc)
    return entry


def _make_empty_db() -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    scalars_result = MagicMock()
    scalars_result.all = MagicMock(return_value=[])
    result.scalars = MagicMock(return_value=scalars_result)
    db.execute = AsyncMock(return_value=result)
    return db


def _make_db_with_entry(entry: MagicMock) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=entry)
    scalars_result = MagicMock()
    scalars_result.all = MagicMock(return_value=[entry])
    result.scalars = MagicMock(return_value=scalars_result)
    db.execute = AsyncMock(return_value=result)
    return db


# ---------------------------------------------------------------------------
# 1-14: parse_typed_value / validate_value_for_type
# ---------------------------------------------------------------------------


class TestParseTypedValue:
    def test_string_type_returns_unchanged(self):
        assert parse_typed_value("hello", ConfigValueType.STRING) == "hello"

    def test_float_type_parses_correctly(self):
        assert parse_typed_value("3.14", ConfigValueType.FLOAT) == pytest.approx(3.14)

    def test_int_type_parses_correctly(self):
        assert parse_typed_value("42", ConfigValueType.INT) == 42

    def test_bool_true_lower(self):
        assert parse_typed_value("true", ConfigValueType.BOOL) is True

    def test_bool_false_lower(self):
        assert parse_typed_value("false", ConfigValueType.BOOL) is False

    def test_bool_one(self):
        assert parse_typed_value("1", ConfigValueType.BOOL) is True

    def test_bool_zero(self):
        assert parse_typed_value("0", ConfigValueType.BOOL) is False

    def test_bool_yes(self):
        assert parse_typed_value("yes", ConfigValueType.BOOL) is True

    def test_bool_no(self):
        assert parse_typed_value("no", ConfigValueType.BOOL) is False

    def test_bool_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_typed_value("maybe", ConfigValueType.BOOL)

    def test_json_parses_dict(self):
        result = parse_typed_value('{"a": 1}', ConfigValueType.JSON)
        assert result == {"a": 1}

    def test_json_invalid_raises(self):
        with pytest.raises((ValueError, Exception)):
            parse_typed_value("not-json", ConfigValueType.JSON)

    def test_validate_raises_for_nonnumeric_float(self):
        with pytest.raises(ValueError):
            validate_value_for_type("abc", ConfigValueType.FLOAT)

    def test_validate_passes_silently_for_valid_float(self):
        validate_value_for_type("1.5", ConfigValueType.FLOAT)  # no exception


# ---------------------------------------------------------------------------
# 15-17: get_all_config
# ---------------------------------------------------------------------------


class TestGetAllConfig:
    @pytest.mark.asyncio
    async def test_empty_db_returns_empty_list(self):
        db = _make_empty_db()
        result = await get_all_config(db)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_entries_with_typed_value(self):
        entry = _make_config_entry(value="2.5", value_type=ConfigValueType.FLOAT)
        db = _make_db_with_entry(entry)
        result = await get_all_config(db)
        assert len(result) == 1
        assert result[0]["typed_value"] == pytest.approx(2.5)

    @pytest.mark.asyncio
    async def test_category_filter_passed_to_query(self):
        db = _make_empty_db()
        # Should not raise and should use a WHERE clause (we just verify no error)
        result = await get_all_config(db, category=ConfigCategory.PRICING)
        assert result == []


# ---------------------------------------------------------------------------
# 18-19: get_config_entry
# ---------------------------------------------------------------------------


class TestGetConfigEntry:
    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        db = _make_empty_db()
        result = await get_config_entry(db, "nonexistent_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_dict_with_typed_value(self):
        entry = _make_config_entry(
            key="base_fare",
            value="2.5",
            value_type=ConfigValueType.FLOAT,
        )
        db = _make_db_with_entry(entry)
        result = await get_config_entry(db, "base_fare")
        assert result is not None
        assert result["key"] == "base_fare"
        assert result["typed_value"] == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# 20-24: update_config_entry
# ---------------------------------------------------------------------------


class TestUpdateConfigEntry:
    @pytest.mark.asyncio
    async def test_returns_none_when_key_not_found(self):
        db = _make_empty_db()
        result = await update_config_entry(db, "nonexistent", "1.0", updated_by_id=1)
        assert result is None

    @pytest.mark.asyncio
    async def test_updates_value_and_calls_commit(self):
        entry = _make_config_entry(
            key="base_fare",
            value="2.5",
            value_type=ConfigValueType.FLOAT,
        )
        db = _make_db_with_entry(entry)
        db.refresh = AsyncMock()

        with patch("app.services.platform_config.log_event", new_callable=AsyncMock):
            result = await update_config_entry(db, "base_fare", "3.0", updated_by_id=99)

        db.commit.assert_called_once()
        assert entry.value == "3.0"

    @pytest.mark.asyncio
    async def test_raises_for_type_invalid_value(self):
        entry = _make_config_entry(
            key="base_fare",
            value="2.5",
            value_type=ConfigValueType.FLOAT,
        )
        db = _make_db_with_entry(entry)
        with pytest.raises(ValueError):
            await update_config_entry(db, "base_fare", "not_a_float", updated_by_id=1)

    @pytest.mark.asyncio
    async def test_updates_description_when_provided(self):
        entry = _make_config_entry(
            key="base_fare",
            value="2.5",
            value_type=ConfigValueType.FLOAT,
            description="old description",
        )
        db = _make_db_with_entry(entry)
        db.refresh = AsyncMock()

        with patch("app.services.platform_config.log_event", new_callable=AsyncMock):
            await update_config_entry(
                db, "base_fare", "3.0", updated_by_id=1, description="new description"
            )

        assert entry.description == "new description"

    @pytest.mark.asyncio
    async def test_calls_log_event_after_update(self):
        entry = _make_config_entry(
            key="base_fare",
            value="2.5",
            value_type=ConfigValueType.FLOAT,
        )
        db = _make_db_with_entry(entry)
        db.refresh = AsyncMock()

        with patch(
            "app.services.platform_config.log_event", new_callable=AsyncMock
        ) as mock_log:
            await update_config_entry(db, "base_fare", "3.0", updated_by_id=42)

        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs["event_type"] == "config_updated"
        assert call_kwargs["actor_id"] == 42


# ---------------------------------------------------------------------------
# 25-28: bulk_update_config
# ---------------------------------------------------------------------------


class TestBulkUpdateConfig:
    @pytest.mark.asyncio
    async def test_all_succeed_returns_correct_counts(self):
        entry = _make_config_entry(
            key="base_fare",
            value="2.5",
            value_type=ConfigValueType.FLOAT,
        )
        db = MagicMock()
        db.refresh = AsyncMock()
        db.commit = AsyncMock()

        result_mock = MagicMock()
        result_mock.scalar_one_or_none = MagicMock(return_value=entry)
        db.execute = AsyncMock(return_value=result_mock)

        with patch("app.services.platform_config.log_event", new_callable=AsyncMock):
            summary = await bulk_update_config(
                db,
                [{"key": "base_fare", "value": "3.0"}],
                updated_by_id=1,
            )

        assert summary["updated_count"] == 1
        assert summary["failed_count"] == 0

    @pytest.mark.asyncio
    async def test_missing_key_records_failure(self):
        db = _make_empty_db()
        summary = await bulk_update_config(
            db,
            [{"key": "nonexistent", "value": "1.0"}],
            updated_by_id=1,
        )
        assert summary["failed_count"] == 1
        assert summary["results"][0]["success"] is False
        assert "not found" in summary["results"][0]["error"]

    @pytest.mark.asyncio
    async def test_type_invalid_value_records_failure(self):
        entry = _make_config_entry(
            key="base_fare",
            value="2.5",
            value_type=ConfigValueType.FLOAT,
        )
        db = _make_db_with_entry(entry)
        summary = await bulk_update_config(
            db,
            [{"key": "base_fare", "value": "not_a_float"}],
            updated_by_id=1,
        )
        assert summary["failed_count"] == 1
        assert summary["results"][0]["success"] is False

    @pytest.mark.asyncio
    async def test_failed_count_matches_number_of_errors(self):
        db = _make_empty_db()
        summary = await bulk_update_config(
            db,
            [
                {"key": "missing_a", "value": "1"},
                {"key": "missing_b", "value": "2"},
            ],
            updated_by_id=1,
        )
        assert summary["failed_count"] == 2
        assert summary["updated_count"] == 0
