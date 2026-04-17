"""Service layer for the persistent platform config system."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.platform_config import (
    ConfigCategory,
    ConfigValueType,
    PlatformConfig,
    PlatformConfigHistory,
)
from app.schemas.platform_config import ConfigBulkUpdateItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_typed_value(value_str: str, value_type: ConfigValueType) -> Any:
    """Parse *value_str* into the Python type indicated by *value_type*.

    Raises ``ValueError`` if the string cannot be parsed.
    """
    vt = value_type.value if hasattr(value_type, "value") else str(value_type)
    if vt == "string":
        return value_str
    if vt == "integer":
        try:
            return int(value_str)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Cannot parse {value_str!r} as integer") from exc
    if vt == "float":
        try:
            return float(value_str)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Cannot parse {value_str!r} as float") from exc
    if vt == "boolean":
        normalised = value_str.strip().lower()
        if normalised in ("true", "1", "yes"):
            return True
        if normalised in ("false", "0", "no"):
            return False
        raise ValueError(f"Cannot parse {value_str!r} as boolean")
    if vt == "json":
        try:
            return json.loads(value_str)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Cannot parse {value_str!r} as JSON") from exc
    return value_str


# ---------------------------------------------------------------------------
# Default seed data
# ---------------------------------------------------------------------------

_DEFAULT_CONFIGS: list[dict] = [
    dict(
        key="base_fare",
        category=ConfigCategory.pricing,
        value_type=ConfigValueType.float_,
        value=str(settings.base_fare),
        description="Base fare charged at ride start (USD)",
    ),
    dict(
        key="per_km_rate",
        category=ConfigCategory.pricing,
        value_type=ConfigValueType.float_,
        value=str(settings.per_km_rate),
        description="Per-kilometer rate (USD)",
    ),
    dict(
        key="per_min_rate",
        category=ConfigCategory.pricing,
        value_type=ConfigValueType.float_,
        value=str(settings.per_minute_rate),
        description="Per-minute rate (USD)",
    ),
    dict(
        key="platform_fee_pct",
        category=ConfigCategory.pricing,
        value_type=ConfigValueType.float_,
        value="0.0",
        description="Platform fee as percentage of fare (0-100)",
    ),
    dict(
        key="surge_max_multiplier",
        category=ConfigCategory.surge,
        value_type=ConfigValueType.float_,
        value="3.0",
        description="Maximum surge multiplier cap",
    ),
    dict(
        key="surge_min_demand_ratio",
        category=ConfigCategory.surge,
        value_type=ConfigValueType.float_,
        value="1.5",
        description="Demand/supply ratio that triggers surge",
    ),
    dict(
        key="max_search_radius_km",
        category=ConfigCategory.matching,
        value_type=ConfigValueType.float_,
        value=str(settings.driver_search_radius_km),
        description="Max radius to search for available drivers (km)",
    ),
    dict(
        key="driver_timeout_sec",
        category=ConfigCategory.matching,
        value_type=ConfigValueType.integer,
        value="30",
        description="Seconds before a driver match request times out",
    ),
    dict(
        key="panic_cancel_window_sec",
        category=ConfigCategory.safety,
        value_type=ConfigValueType.integer,
        value="30",
        description="Seconds after panic trigger to cancel as false alarm",
    ),
    dict(
        key="max_trusted_contacts",
        category=ConfigCategory.safety,
        value_type=ConfigValueType.integer,
        value="3",
        description="Max trusted contacts a rider can register",
    ),
    dict(
        key="pooling_enabled",
        category=ConfigCategory.features,
        value_type=ConfigValueType.boolean,
        value="true",
        description="Enable ride pooling feature",
    ),
    dict(
        key="fare_splitting_enabled",
        category=ConfigCategory.features,
        value_type=ConfigValueType.boolean,
        value="true",
        description="Enable fare splitting between riders",
    ),
    dict(
        key="chat_enabled",
        category=ConfigCategory.features,
        value_type=ConfigValueType.boolean,
        value="true",
        description="Enable in-app chat between riders and drivers",
    ),
    dict(
        key="notify_contacts_trip_start",
        category=ConfigCategory.notifications,
        value_type=ConfigValueType.boolean,
        value="true",
        description="Notify trusted contacts when a trip starts",
    ),
    dict(
        key="panic_sms_enabled",
        category=ConfigCategory.notifications,
        value_type=ConfigValueType.boolean,
        value="true",
        description="Enable SMS to trusted contacts on panic alert",
    ),
    dict(
        key="max_daily_driver_hours",
        category=ConfigCategory.compliance,
        value_type=ConfigValueType.float_,
        value="12.0",
        description="Maximum recommended daily driving hours",
    ),
    dict(
        key="max_weekly_driver_hours",
        category=ConfigCategory.compliance,
        value_type=ConfigValueType.float_,
        value="60.0",
        description="Maximum recommended weekly driving hours",
    ),
]


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------


async def get_all_configs(
    db: AsyncSession,
    category: ConfigCategory | None = None,
) -> list[PlatformConfig]:
    """Return all active config entries, optionally filtered by category."""
    stmt = select(PlatformConfig).where(PlatformConfig.is_active == True)  # noqa: E712
    if category is not None:
        stmt = stmt.where(PlatformConfig.category == category)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_config_by_key(
    db: AsyncSession,
    key: str,
) -> PlatformConfig | None:
    """Return a single config entry by key, or None if not found."""
    result = await db.execute(
        select(PlatformConfig).where(PlatformConfig.key == key)
    )
    return result.scalar_one_or_none()


async def update_config(
    db: AsyncSession,
    key: str,
    new_value_str: str,
    changed_by_id: int | None = None,
    reason: str | None = None,
) -> PlatformConfig:
    """Update a config entry and write an audit history record.

    Raises ``ValueError`` if the key does not exist or the value fails type
    validation for the entry's declared ``value_type``.
    """
    config = await get_config_by_key(db, key)
    if config is None:
        raise ValueError(f"Config key {key!r} not found")

    # Validate that the new value is parseable for the declared type
    parse_typed_value(new_value_str, config.value_type)

    history = PlatformConfigHistory(
        config_key=key,
        old_value=config.value,
        new_value=new_value_str,
        changed_by=changed_by_id,
        reason=reason,
    )
    db.add(history)

    config.value = new_value_str
    config.updated_by = changed_by_id
    db.add(config)

    await db.commit()
    await db.refresh(config)
    return config


async def bulk_update_configs(
    db: AsyncSession,
    updates: list[ConfigBulkUpdateItem],
    changed_by_id: int | None = None,
) -> tuple[list[PlatformConfig], list[dict]]:
    """Apply multiple config updates, collecting per-item errors.

    Returns ``(updated_list, failed_list)`` where each failed item is a dict
    with ``key`` and ``error`` fields.
    """
    updated: list[PlatformConfig] = []
    failed: list[dict] = []

    for item in updates:
        try:
            config = await update_config(
                db,
                key=item.key,
                new_value_str=item.value,
                changed_by_id=changed_by_id,
                reason=item.reason,
            )
            updated.append(config)
        except (ValueError, Exception) as exc:
            failed.append({"key": item.key, "error": str(exc)})

    return updated, failed


async def get_config_history(
    db: AsyncSession,
    key: str,
    limit: int = 50,
) -> list[PlatformConfigHistory]:
    """Return history entries for a key, newest first."""
    result = await db.execute(
        select(PlatformConfigHistory)
        .where(PlatformConfigHistory.config_key == key)
        .order_by(desc(PlatformConfigHistory.changed_at))
        .limit(limit)
    )
    return list(result.scalars().all())


async def seed_defaults(db: AsyncSession) -> tuple[int, int]:
    """Idempotently create default config entries.

    Returns ``(seeded_count, skipped_count)``.
    """
    seeded = 0
    skipped = 0

    for entry in _DEFAULT_CONFIGS:
        existing = await get_config_by_key(db, entry["key"])
        if existing is not None:
            skipped += 1
            continue

        config = PlatformConfig(
            key=entry["key"],
            value=entry["value"],
            value_type=entry["value_type"],
            category=entry["category"],
            description=entry["description"],
            is_active=True,
        )
        db.add(config)
        seeded += 1

    if seeded:
        await db.commit()

    return seeded, skipped
