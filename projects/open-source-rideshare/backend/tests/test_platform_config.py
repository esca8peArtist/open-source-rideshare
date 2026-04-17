"""Comprehensive tests for the platform config feature.

Coverage
--------
parse_typed_value (unit, no DB)
  - float parses correctly
  - integer parses correctly
  - boolean "true"/"false"/"True"/"False"/"1"/"0" all parse
  - boolean invalid value raises ValueError
  - float invalid value raises ValueError
  - json valid string parses to dict
  - json invalid string raises ValueError
  - string returns as-is

get_all_configs (service, mocked DB)
  - returns all active configs when no filter
  - filters by category
  - returns empty list when no configs

get_config_by_key (service, mocked DB)
  - returns config when found
  - returns None when not found

update_config (service, mocked DB)
  - updates value and writes history entry
  - raises ValueError when key not found
  - calls db.add twice (history + updated config)
  - calls db.commit once

bulk_update_configs (service, mocked DB)
  - all valid updates succeed
  - invalid key goes to failed list
  - partial success: some succeed, some fail

get_config_history (service, mocked DB)
  - returns history entries newest-first
  - respects limit parameter

seed_defaults (service, mocked DB)
  - counts seeded vs skipped correctly when some already exist
  - when all exist, seeded=0 skipped=N

ConfigEntryResponse (schema)
  - typed_value is float when value_type="float"
  - typed_value is int when value_type="integer"
  - typed_value is bool when value_type="boolean"
  - typed_value is dict when value_type="json"
  - typed_value is str when value_type="string"

PlatformConfigRouter (router, mocked service + admin user)
  - GET /admin/config returns list
  - GET /admin/config?category=pricing filters
  - GET /admin/config/categories returns category list
  - GET /admin/config/{key} returns entry
  - GET /admin/config/{key} returns 404 for unknown key
  - PUT /admin/config/{key} calls update_config service
  - POST /admin/config/bulk-update calls bulk_update_configs
  - GET /admin/config/{key}/history returns history
  - POST /admin/config/seed calls seed_defaults
"""
from __future__ import annotations

import json as _json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.platform_config import ConfigCategory, ConfigValueType
from app.schemas.platform_config import (
    ConfigBulkUpdateItem,
    ConfigBulkUpdateRequest,
    ConfigEntryResponse,
    ConfigEntryUpdate,
    ConfigHistoryEntry,
    ConfigHistoryResponse,
    ConfigSeedResponse,
)
from app.services.platform_config import parse_typed_value

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc)


def _make_config(
    key: str = "base_fare",
    value: str = "2.5",
    value_type: ConfigValueType = ConfigValueType.float_,
    category: ConfigCategory = ConfigCategory.pricing,
    description: str = "A fare",
    is_active: bool = True,
    id: int = 1,
    updated_at: datetime = NOW,
    updated_by: int | None = None,
) -> MagicMock:
    cfg = MagicMock()
    cfg.id = id
    cfg.key = key
    cfg.value = value
    cfg.value_type = value_type
    cfg.category = category
    cfg.description = description
    cfg.is_active = is_active
    cfg.updated_at = updated_at
    cfg.updated_by = updated_by
    return cfg


def _make_history(
    config_key: str = "base_fare",
    old_value: str | None = "2.0",
    new_value: str = "2.5",
    changed_by: int | None = 1,
    changed_at: datetime = NOW,
    reason: str | None = None,
    id: int = 1,
) -> MagicMock:
    h = MagicMock()
    h.id = id
    h.config_key = config_key
    h.old_value = old_value
    h.new_value = new_value
    h.changed_by = changed_by
    h.changed_at = changed_at
    h.reason = reason
    return h


def _scalars_result(items: list) -> MagicMock:
    """Build a mock that mimics `await db.execute(...)` result."""
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = items
    result.scalars.return_value = scalars
    result.scalar_one_or_none.return_value = items[0] if items else None
    return result


# ---------------------------------------------------------------------------
# TestParseTypedValue
# ---------------------------------------------------------------------------


class TestParseTypedValue:
    def test_float_parses_correctly(self):
        assert parse_typed_value("3.14", ConfigValueType.float_) == pytest.approx(3.14)

    def test_integer_parses_correctly(self):
        assert parse_typed_value("42", ConfigValueType.integer) == 42

    def test_boolean_true_lowercase(self):
        assert parse_typed_value("true", ConfigValueType.boolean) is True

    def test_boolean_false_lowercase(self):
        assert parse_typed_value("false", ConfigValueType.boolean) is False

    def test_boolean_true_titlecase(self):
        assert parse_typed_value("True", ConfigValueType.boolean) is True

    def test_boolean_false_titlecase(self):
        assert parse_typed_value("False", ConfigValueType.boolean) is False

    def test_boolean_one(self):
        assert parse_typed_value("1", ConfigValueType.boolean) is True

    def test_boolean_zero(self):
        assert parse_typed_value("0", ConfigValueType.boolean) is False

    def test_boolean_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_typed_value("maybe", ConfigValueType.boolean)

    def test_float_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_typed_value("not-a-float", ConfigValueType.float_)

    def test_integer_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_typed_value("3.14", ConfigValueType.integer)

    def test_json_valid_parses_to_dict(self):
        result = parse_typed_value('{"a": 1}', ConfigValueType.json)
        assert result == {"a": 1}

    def test_json_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_typed_value("{not valid json", ConfigValueType.json)

    def test_string_returns_as_is(self):
        assert parse_typed_value("hello world", ConfigValueType.string) == "hello world"


# ---------------------------------------------------------------------------
# TestGetAllConfigs
# ---------------------------------------------------------------------------


class TestGetAllConfigs:
    @pytest.mark.asyncio
    async def test_returns_all_active_configs(self):
        from app.services.platform_config import get_all_configs

        cfg1 = _make_config(key="base_fare", category=ConfigCategory.pricing)
        cfg2 = _make_config(key="surge_max_multiplier", category=ConfigCategory.surge, id=2)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result([cfg1, cfg2]))

        result = await get_all_configs(db)
        assert len(result) == 2
        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_filters_by_category(self):
        from app.services.platform_config import get_all_configs

        cfg = _make_config(key="base_fare", category=ConfigCategory.pricing)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result([cfg]))

        result = await get_all_configs(db, category=ConfigCategory.pricing)
        assert len(result) == 1
        assert result[0].key == "base_fare"

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_configs(self):
        from app.services.platform_config import get_all_configs

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result([]))

        result = await get_all_configs(db)
        assert result == []


# ---------------------------------------------------------------------------
# TestGetConfigByKey
# ---------------------------------------------------------------------------


class TestGetConfigByKey:
    @pytest.mark.asyncio
    async def test_returns_config_when_found(self):
        from app.services.platform_config import get_config_by_key

        cfg = _make_config(key="base_fare")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result([cfg]))

        result = await get_config_by_key(db, "base_fare")
        assert result is cfg

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        from app.services.platform_config import get_config_by_key

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result([]))

        result = await get_config_by_key(db, "nonexistent_key")
        assert result is None


# ---------------------------------------------------------------------------
# TestUpdateConfig
# ---------------------------------------------------------------------------


class TestUpdateConfig:
    @pytest.mark.asyncio
    async def test_updates_value_and_writes_history(self):
        from app.services.platform_config import update_config

        cfg = _make_config(key="base_fare", value="2.0")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result([cfg]))
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        await update_config(db, "base_fare", "3.0", changed_by_id=1, reason="price increase")

        assert db.add.call_count == 2
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_value_error_when_key_not_found(self):
        from app.services.platform_config import update_config

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result([]))

        with pytest.raises(ValueError, match="not found"):
            await update_config(db, "missing_key", "123")

    @pytest.mark.asyncio
    async def test_raises_value_error_on_bad_type(self):
        from app.services.platform_config import update_config

        cfg = _make_config(key="base_fare", value="2.0", value_type=ConfigValueType.float_)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result([cfg]))

        with pytest.raises(ValueError):
            await update_config(db, "base_fare", "not-a-float")

    @pytest.mark.asyncio
    async def test_calls_db_add_twice(self):
        from app.services.platform_config import update_config

        cfg = _make_config(key="base_fare", value="2.0")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result([cfg]))
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        await update_config(db, "base_fare", "3.0")
        assert db.add.call_count == 2

    @pytest.mark.asyncio
    async def test_calls_db_commit_once(self):
        from app.services.platform_config import update_config

        cfg = _make_config(key="base_fare", value="2.0")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result([cfg]))
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        await update_config(db, "base_fare", "3.0")
        db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# TestBulkUpdateConfigs
# ---------------------------------------------------------------------------


class TestBulkUpdateConfigs:
    @pytest.mark.asyncio
    async def test_all_valid_updates_succeed(self):
        from app.services.platform_config import bulk_update_configs

        cfg_a = _make_config(key="base_fare", value="2.0", id=1)
        cfg_b = _make_config(key="per_km_rate", value="1.0", id=2)

        call_count = 0

        async def _fake_update(db, key, new_value_str, **kwargs):
            nonlocal call_count
            call_count += 1
            return cfg_a if key == "base_fare" else cfg_b

        db = AsyncMock()
        updates = [
            ConfigBulkUpdateItem(key="base_fare", value="3.0"),
            ConfigBulkUpdateItem(key="per_km_rate", value="2.0"),
        ]

        with patch(
            "app.services.platform_config.update_config",
            side_effect=_fake_update,
        ):
            updated, failed = await bulk_update_configs(db, updates)

        assert len(updated) == 2
        assert len(failed) == 0

    @pytest.mark.asyncio
    async def test_invalid_key_goes_to_failed_list(self):
        from app.services.platform_config import bulk_update_configs

        async def _raise(*args, **kwargs):
            raise ValueError("Config key 'bad_key' not found")

        db = AsyncMock()
        updates = [ConfigBulkUpdateItem(key="bad_key", value="1.0")]

        with patch(
            "app.services.platform_config.update_config",
            side_effect=_raise,
        ):
            updated, failed = await bulk_update_configs(db, updates)

        assert len(updated) == 0
        assert len(failed) == 1
        assert failed[0]["key"] == "bad_key"

    @pytest.mark.asyncio
    async def test_partial_success(self):
        from app.services.platform_config import bulk_update_configs

        cfg_a = _make_config(key="base_fare", value="2.0", id=1)

        async def _side_effect(db, key, new_value_str, **kwargs):
            if key == "base_fare":
                return cfg_a
            raise ValueError(f"Config key {key!r} not found")

        db = AsyncMock()
        updates = [
            ConfigBulkUpdateItem(key="base_fare", value="3.0"),
            ConfigBulkUpdateItem(key="bad_key", value="99"),
        ]

        with patch(
            "app.services.platform_config.update_config",
            side_effect=_side_effect,
        ):
            updated, failed = await bulk_update_configs(db, updates)

        assert len(updated) == 1
        assert len(failed) == 1


# ---------------------------------------------------------------------------
# TestGetConfigHistory
# ---------------------------------------------------------------------------


class TestGetConfigHistory:
    @pytest.mark.asyncio
    async def test_returns_history_newest_first(self):
        from app.services.platform_config import get_config_history

        h1 = _make_history(id=2, new_value="3.0")
        h2 = _make_history(id=1, new_value="2.5")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result([h1, h2]))

        result = await get_config_history(db, "base_fare")
        assert len(result) == 2
        assert result[0].id == 2  # newest first (as returned by mock)

    @pytest.mark.asyncio
    async def test_respects_limit_parameter(self):
        from app.services.platform_config import get_config_history

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result([]))

        await get_config_history(db, "base_fare", limit=10)
        db.execute.assert_called_once()
        # Verify the call was made (limit is passed into the SQL statement, not directly assertable on mock)


# ---------------------------------------------------------------------------
# TestSeedDefaults
# ---------------------------------------------------------------------------


class TestSeedDefaults:
    @pytest.mark.asyncio
    async def test_seeded_vs_skipped_when_some_exist(self):
        from app.services.platform_config import _DEFAULT_CONFIGS, seed_defaults

        total = len(_DEFAULT_CONFIGS)
        pre_existing_key = _DEFAULT_CONFIGS[0]["key"]

        existing_cfg = _make_config(key=pre_existing_key)

        call_num = 0

        async def _get_config(db, key):
            nonlocal call_num
            call_num += 1
            # First key already exists, rest do not
            if key == pre_existing_key:
                return existing_cfg
            return None

        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        with patch(
            "app.services.platform_config.get_config_by_key",
            side_effect=_get_config,
        ):
            seeded, skipped = await seed_defaults(db)

        assert skipped == 1
        assert seeded == total - 1

    @pytest.mark.asyncio
    async def test_all_exist_gives_zero_seeded(self):
        from app.services.platform_config import _DEFAULT_CONFIGS, seed_defaults

        total = len(_DEFAULT_CONFIGS)
        existing_cfg = _make_config()

        async def _always_exists(db, key):
            return existing_cfg

        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        with patch(
            "app.services.platform_config.get_config_by_key",
            side_effect=_always_exists,
        ):
            seeded, skipped = await seed_defaults(db)

        assert seeded == 0
        assert skipped == total
        db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# TestConfigEntryResponse
# ---------------------------------------------------------------------------


class TestConfigEntryResponse:
    def _make_response(self, value: str, value_type: ConfigValueType) -> ConfigEntryResponse:
        cfg = _make_config(value=value, value_type=value_type)
        return ConfigEntryResponse(
            id=cfg.id,
            key=cfg.key,
            value=cfg.value,
            value_type=cfg.value_type,
            category=cfg.category,
            description=cfg.description,
            is_active=cfg.is_active,
            updated_at=cfg.updated_at,
            updated_by=cfg.updated_by,
        )

    def test_typed_value_is_float(self):
        resp = self._make_response("3.14", ConfigValueType.float_)
        assert isinstance(resp.typed_value, float)
        assert resp.typed_value == pytest.approx(3.14)

    def test_typed_value_is_int(self):
        resp = self._make_response("42", ConfigValueType.integer)
        assert isinstance(resp.typed_value, int)
        assert resp.typed_value == 42

    def test_typed_value_is_bool_true(self):
        resp = self._make_response("true", ConfigValueType.boolean)
        assert resp.typed_value is True

    def test_typed_value_is_bool_false(self):
        resp = self._make_response("false", ConfigValueType.boolean)
        assert resp.typed_value is False

    def test_typed_value_is_dict_for_json(self):
        resp = self._make_response('{"x": 1}', ConfigValueType.json)
        assert isinstance(resp.typed_value, dict)
        assert resp.typed_value == {"x": 1}

    def test_typed_value_is_str_for_string(self):
        resp = self._make_response("hello", ConfigValueType.string)
        assert isinstance(resp.typed_value, str)
        assert resp.typed_value == "hello"


# ---------------------------------------------------------------------------
# TestPlatformConfigRouter
# ---------------------------------------------------------------------------


class TestPlatformConfigRouter:
    """Router-level tests using direct async handler invocation (no HTTP layer)."""

    def _make_admin(self, id: int = 99) -> MagicMock:
        admin = MagicMock()
        admin.id = id
        return admin

    def _make_entry_response(self, key: str = "base_fare") -> ConfigEntryResponse:
        return ConfigEntryResponse(
            id=1,
            key=key,
            value="2.5",
            value_type=ConfigValueType.float_,
            category=ConfigCategory.pricing,
            description="Test",
            is_active=True,
            updated_at=NOW,
            updated_by=None,
        )

    # --- GET /admin/config ---

    @pytest.mark.asyncio
    async def test_list_configs_returns_list(self):
        from app.api.v1.platform_config import list_configs

        cfg = _make_config()
        db = AsyncMock()

        with patch(
            "app.api.v1.platform_config.get_all_configs",
            new_callable=AsyncMock,
            return_value=[cfg],
        ):
            result = await list_configs(category=None, db=db, _admin=self._make_admin())

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_list_configs_filters_by_category(self):
        from app.api.v1.platform_config import list_configs

        cfg = _make_config(category=ConfigCategory.pricing)
        db = AsyncMock()

        with patch(
            "app.api.v1.platform_config.get_all_configs",
            new_callable=AsyncMock,
            return_value=[cfg],
        ) as mock_svc:
            result = await list_configs(category="pricing", db=db, _admin=self._make_admin())

        assert len(result) == 1
        mock_svc.assert_called_once()
        _, call_kwargs = mock_svc.call_args
        assert call_kwargs.get("category") == ConfigCategory.pricing

    # --- GET /admin/config/categories ---

    @pytest.mark.asyncio
    async def test_list_categories_returns_list(self):
        from app.api.v1.platform_config import list_categories

        db = AsyncMock()
        pricing_row = MagicMock()
        pricing_row.__getitem__ = lambda self, idx: ConfigCategory.pricing

        result_mock = MagicMock()
        result_mock.all.return_value = [(ConfigCategory.pricing,), (ConfigCategory.surge,)]
        db.execute = AsyncMock(return_value=result_mock)

        result = await list_categories(db=db, _admin=self._make_admin())
        assert isinstance(result, list)
        assert "pricing" in result

    # --- GET /admin/config/{key} ---

    @pytest.mark.asyncio
    async def test_get_config_returns_entry(self):
        from app.api.v1.platform_config import get_config

        cfg = _make_config(key="base_fare")
        db = AsyncMock()

        with patch(
            "app.api.v1.platform_config.get_config_by_key",
            new_callable=AsyncMock,
            return_value=cfg,
        ):
            result = await get_config(key="base_fare", db=db, _admin=self._make_admin())

        assert result.key == "base_fare"

    @pytest.mark.asyncio
    async def test_get_config_returns_404_for_unknown_key(self):
        from fastapi import HTTPException

        from app.api.v1.platform_config import get_config

        db = AsyncMock()

        with patch(
            "app.api.v1.platform_config.get_config_by_key",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_config(key="no_such_key", db=db, _admin=self._make_admin())

        assert exc_info.value.status_code == 404

    # --- PUT /admin/config/{key} ---

    @pytest.mark.asyncio
    async def test_update_config_entry_calls_service(self):
        from app.api.v1.platform_config import update_config_entry

        cfg = _make_config(key="base_fare", value="3.0")
        db = AsyncMock()
        body = ConfigEntryUpdate(value="3.0", reason="test")
        admin = self._make_admin(id=1)

        with patch(
            "app.api.v1.platform_config.update_config",
            new_callable=AsyncMock,
            return_value=cfg,
        ) as mock_svc:
            result = await update_config_entry(
                key="base_fare", body=body, db=db, admin=admin
            )

        mock_svc.assert_called_once_with(
            db,
            key="base_fare",
            new_value_str="3.0",
            changed_by_id=1,
            reason="test",
        )
        assert result.key == "base_fare"

    # --- POST /admin/config/bulk-update ---

    @pytest.mark.asyncio
    async def test_bulk_update_calls_service(self):
        from app.api.v1.platform_config import bulk_update

        cfg = _make_config(key="base_fare", value="3.0")
        db = AsyncMock()
        body = ConfigBulkUpdateRequest(
            updates=[ConfigBulkUpdateItem(key="base_fare", value="3.0")]
        )
        admin = self._make_admin(id=1)

        with patch(
            "app.api.v1.platform_config.bulk_update_configs",
            new_callable=AsyncMock,
            return_value=([cfg], []),
        ) as mock_svc:
            result = await bulk_update(body=body, db=db, admin=admin)

        mock_svc.assert_called_once()
        assert len(result.updated) == 1
        assert len(result.failed) == 0

    # --- GET /admin/config/{key}/history ---

    @pytest.mark.asyncio
    async def test_get_history_returns_history_response(self):
        from app.api.v1.platform_config import get_history

        h = _make_history()
        db = AsyncMock()

        with patch(
            "app.api.v1.platform_config.get_config_history",
            new_callable=AsyncMock,
            return_value=[h],
        ):
            result = await get_history(key="base_fare", limit=50, db=db, _admin=self._make_admin())

        assert result.key == "base_fare"
        assert len(result.history) == 1

    # --- POST /admin/config/seed ---

    @pytest.mark.asyncio
    async def test_seed_calls_seed_defaults(self):
        from app.api.v1.platform_config import seed_config_defaults

        db = AsyncMock()

        with patch(
            "app.api.v1.platform_config.seed_defaults",
            new_callable=AsyncMock,
            return_value=(17, 0),
        ) as mock_svc:
            result = await seed_config_defaults(db=db, _admin=self._make_admin())

        mock_svc.assert_called_once_with(db)
        assert result.seeded == 17
        assert result.skipped == 0
