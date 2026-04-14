"""Platform configuration service.

Provides database-backed CRUD for runtime platform settings.
Seed defaults are drawn from app.config.settings so a fresh deployment
works out of the box without any manual DB inserts.

Value coercion:
  - "string" → str (stored as-is)
  - "float"  → float
  - "int"    → int
  - "bool"   → bool (accepts "true"/"false", "1"/"0", "yes"/"no")
  - "json"   → any JSON-parseable structure

Audit logs are written for every mutating operation.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.platform_config import ConfigCategory, ConfigValueType, PlatformConfig
from app.services.audit import log_event

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default seed data — every entry the platform ships with
# ---------------------------------------------------------------------------

_DEFAULTS: list[dict[str, Any]] = [
    # ---- Pricing ----
    {
        "key": "base_fare",
        "category": ConfigCategory.PRICING,
        "value_type": ConfigValueType.FLOAT,
        "value": str(settings.base_fare),
        "label": "Base Fare",
        "description": "Fixed charge applied to every ride before distance/time rates.",
    },
    {
        "key": "per_km_rate",
        "category": ConfigCategory.PRICING,
        "value_type": ConfigValueType.FLOAT,
        "value": str(settings.per_km_rate),
        "label": "Per-Km Rate",
        "description": "Fare charged per kilometre of trip distance.",
    },
    {
        "key": "per_minute_rate",
        "category": ConfigCategory.PRICING,
        "value_type": ConfigValueType.FLOAT,
        "value": str(settings.per_minute_rate),
        "label": "Per-Minute Rate",
        "description": "Fare charged per minute of trip duration.",
    },
    {
        "key": "minimum_fare",
        "category": ConfigCategory.PRICING,
        "value_type": ConfigValueType.FLOAT,
        "value": str(settings.minimum_fare),
        "label": "Minimum Fare",
        "description": "Floor price — no ride costs less than this amount.",
    },
    {
        "key": "platform_fee_percent",
        "category": ConfigCategory.PRICING,
        "value_type": ConfigValueType.FLOAT,
        "value": "0.0",
        "label": "Platform Fee (%)",
        "description": "Percentage of each fare retained by the platform (0 = cooperative model with zero extraction).",
    },
    {
        "key": "demand_pricing_enabled",
        "category": ConfigCategory.PRICING,
        "value_type": ConfigValueType.BOOL,
        "value": str(settings.demand_pricing_enabled).lower(),
        "label": "Demand Pricing Enabled",
        "description": "Whether transparent supply/demand fare adjustments are active.",
    },
    {
        "key": "demand_pricing_max_multiplier",
        "category": ConfigCategory.PRICING,
        "value_type": ConfigValueType.FLOAT,
        "value": str(settings.demand_pricing_max_multiplier),
        "label": "Demand Pricing Max Multiplier",
        "description": "Hard cap on fare multiplier — cooperative policy. 1.5 = max 50% increase.",
    },
    # ---- Operations ----
    {
        "key": "driver_search_radius_km",
        "category": ConfigCategory.OPERATIONS,
        "value_type": ConfigValueType.FLOAT,
        "value": str(settings.driver_search_radius_km),
        "label": "Driver Search Radius (km)",
        "description": "Maximum radius to search for available drivers when a ride is requested.",
    },
    {
        "key": "driver_search_initial_radius_km",
        "category": ConfigCategory.OPERATIONS,
        "value_type": ConfigValueType.FLOAT,
        "value": str(settings.driver_search_initial_radius_km),
        "label": "Driver Search Initial Radius (km)",
        "description": "First-pass radius; expands if no drivers are found within this distance.",
    },
    {
        "key": "ride_offer_timeout_seconds",
        "category": ConfigCategory.OPERATIONS,
        "value_type": ConfigValueType.INT,
        "value": str(settings.ride_offer_timeout_seconds),
        "label": "Ride Offer Timeout (s)",
        "description": "Seconds a driver has to accept or decline a ride offer before it moves on.",
    },
    {
        "key": "max_ride_offers",
        "category": ConfigCategory.OPERATIONS,
        "value_type": ConfigValueType.INT,
        "value": str(settings.max_ride_offers),
        "label": "Max Ride Offers",
        "description": "Maximum number of drivers to offer a single ride request before failing.",
    },
    {
        "key": "schedule_min_advance_minutes",
        "category": ConfigCategory.OPERATIONS,
        "value_type": ConfigValueType.INT,
        "value": str(settings.schedule_min_advance_minutes),
        "label": "Scheduled Ride Min Advance (min)",
        "description": "Minimum minutes in advance a rider must schedule a future ride.",
    },
    {
        "key": "schedule_max_advance_hours",
        "category": ConfigCategory.OPERATIONS,
        "value_type": ConfigValueType.INT,
        "value": str(settings.schedule_max_advance_hours),
        "label": "Scheduled Ride Max Advance (h)",
        "description": "Maximum hours in advance a rider can schedule a future ride.",
    },
    # ---- Matching ----
    {
        "key": "driver_location_ttl_seconds",
        "category": ConfigCategory.MATCHING,
        "value_type": ConfigValueType.INT,
        "value": str(settings.driver_location_ttl_seconds),
        "label": "Driver Location TTL (s)",
        "description": "Seconds before a driver's last-known location is considered stale for matching.",
    },
    # ---- Safety ----
    {
        "key": "ws_heartbeat_interval_seconds",
        "category": ConfigCategory.SAFETY,
        "value_type": ConfigValueType.INT,
        "value": str(settings.ws_heartbeat_interval_seconds),
        "label": "WebSocket Heartbeat Interval (s)",
        "description": "Seconds between server-sent pings on open WebSocket connections.",
    },
    {
        "key": "ws_heartbeat_timeout_seconds",
        "category": ConfigCategory.SAFETY,
        "value_type": ConfigValueType.INT,
        "value": str(settings.ws_heartbeat_timeout_seconds),
        "label": "WebSocket Heartbeat Timeout (s)",
        "description": "Seconds the client has to respond to a heartbeat ping before disconnection.",
    },
    # ---- Notifications ----
    {
        "key": "notifications_sms_enabled",
        "category": ConfigCategory.NOTIFICATIONS,
        "value_type": ConfigValueType.BOOL,
        "value": str(settings.notifications_sms_enabled).lower(),
        "label": "SMS Notifications Enabled",
        "description": "Enable Twilio SMS dispatch for ride and safety events.",
    },
    {
        "key": "notifications_email_enabled",
        "category": ConfigCategory.NOTIFICATIONS,
        "value_type": ConfigValueType.BOOL,
        "value": str(settings.notifications_email_enabled).lower(),
        "label": "Email Notifications Enabled",
        "description": "Enable SendGrid email dispatch for receipts and account events.",
    },
    {
        "key": "notifications_push_enabled",
        "category": ConfigCategory.NOTIFICATIONS,
        "value_type": ConfigValueType.BOOL,
        "value": str(settings.notifications_push_enabled).lower(),
        "label": "Push Notifications Enabled",
        "description": "Enable Firebase Cloud Messaging push notifications for mobile apps.",
    },
    # ---- Features ----
    {
        "key": "pooling_enabled",
        "category": ConfigCategory.FEATURES,
        "value_type": ConfigValueType.BOOL,
        "value": "true",
        "label": "Ride Pooling Enabled",
        "description": "Allow riders to share rides with other passengers on similar routes.",
    },
    {
        "key": "fare_split_enabled",
        "category": ConfigCategory.FEATURES,
        "value_type": ConfigValueType.BOOL,
        "value": "true",
        "label": "Fare Split Enabled",
        "description": "Allow riders to split fares with friends inside the app.",
    },
    {
        "key": "in_app_chat_enabled",
        "category": ConfigCategory.FEATURES,
        "value_type": ConfigValueType.BOOL,
        "value": "true",
        "label": "In-App Chat Enabled",
        "description": "Allow drivers and riders to exchange text messages during a ride.",
    },
]


# ---------------------------------------------------------------------------
# Value parsing
# ---------------------------------------------------------------------------


def parse_typed_value(value: str, value_type: ConfigValueType) -> Any:
    """Convert the stored string to its native Python type.

    Raises ValueError if parsing fails (e.g., non-numeric string for float).
    """
    if value_type == ConfigValueType.STRING:
        return value
    if value_type == ConfigValueType.FLOAT:
        return float(value)
    if value_type == ConfigValueType.INT:
        return int(value)
    if value_type == ConfigValueType.BOOL:
        lower = value.strip().lower()
        if lower in ("true", "1", "yes"):
            return True
        if lower in ("false", "0", "no"):
            return False
        raise ValueError(f"Cannot parse {value!r} as bool")
    if value_type == ConfigValueType.JSON:
        return json.loads(value)
    raise ValueError(f"Unknown value_type {value_type!r}")


def validate_value_for_type(value: str, value_type: ConfigValueType) -> None:
    """Raise ValueError if `value` cannot be parsed as `value_type`."""
    parse_typed_value(value, value_type)


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------


async def seed_default_config(db: AsyncSession) -> int:
    """Insert missing default config entries (idempotent — skips existing keys).

    Returns the number of new rows inserted.
    """
    inserted = 0
    for entry in _DEFAULTS:
        existing = await db.execute(
            select(PlatformConfig).where(PlatformConfig.key == entry["key"])
        )
        if existing.scalar_one_or_none() is None:
            db.add(PlatformConfig(**entry))
            inserted += 1
    if inserted:
        await db.commit()
    return inserted


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


async def get_all_config(
    db: AsyncSession,
    category: ConfigCategory | None = None,
) -> list[dict[str, Any]]:
    """Return all config entries, optionally filtered by category.

    Each dict includes a `typed_value` field for convenience.
    """
    stmt = select(PlatformConfig).order_by(PlatformConfig.category, PlatformConfig.key)
    if category is not None:
        stmt = stmt.where(PlatformConfig.category == category)
    result = await db.execute(stmt)
    entries = result.scalars().all()
    return [_entry_to_dict(e) for e in entries]


async def get_config_entry(db: AsyncSession, key: str) -> dict[str, Any] | None:
    """Return a single config entry by key, or None if not found."""
    result = await db.execute(
        select(PlatformConfig).where(PlatformConfig.key == key)
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        return None
    return _entry_to_dict(entry)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


async def update_config_entry(
    db: AsyncSession,
    key: str,
    value: str,
    updated_by_id: int,
    description: str | None = None,
) -> dict[str, Any] | None:
    """Update a single config entry.

    Returns the updated entry dict, or None if the key does not exist.
    Raises ValueError if the new value cannot be parsed as the entry's type.
    """
    result = await db.execute(
        select(PlatformConfig).where(PlatformConfig.key == key)
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        return None

    validate_value_for_type(value, entry.value_type)

    old_value = entry.value
    entry.value = value
    if description is not None:
        entry.description = description
    entry.updated_by_id = updated_by_id

    await db.commit()
    await db.refresh(entry)

    await log_event(
        db,
        category="admin",
        event_type="config_updated",
        description=f"Config key '{key}' changed from '{old_value}' to '{value}'",
        actor_id=updated_by_id,
        actor_role="admin",
        target_type="platform_config",
        metadata={"key": key, "old_value": old_value, "new_value": value},
    )

    return _entry_to_dict(entry)


async def bulk_update_config(
    db: AsyncSession,
    updates: list[dict[str, str]],
    updated_by_id: int,
) -> dict[str, Any]:
    """Update multiple config entries in one operation.

    Args:
        updates: list of {"key": ..., "value": ...} dicts
        updated_by_id: admin user id performing the update

    Returns a summary dict with `results`, `updated_count`, and `failed_count`.
    """
    results = []
    updated_count = 0
    failed_count = 0

    for item in updates:
        key = item["key"]
        value = item["value"]
        try:
            updated = await update_config_entry(db, key, value, updated_by_id)
            if updated is None:
                results.append({"key": key, "success": False, "error": "key not found"})
                failed_count += 1
            else:
                results.append({"key": key, "success": True, "error": None})
                updated_count += 1
        except ValueError as exc:
            results.append({"key": key, "success": False, "error": str(exc)})
            failed_count += 1

    return {
        "results": results,
        "updated_count": updated_count,
        "failed_count": failed_count,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _entry_to_dict(entry: PlatformConfig) -> dict[str, Any]:
    try:
        typed_value = parse_typed_value(entry.value, entry.value_type)
    except (ValueError, Exception):
        typed_value = entry.value  # fallback: return raw string

    return {
        "key": entry.key,
        "category": entry.category,
        "value_type": entry.value_type,
        "value": entry.value,
        "typed_value": typed_value,
        "label": entry.label,
        "description": entry.description,
        "updated_at": entry.updated_at,
        "updated_by_id": entry.updated_by_id,
    }
