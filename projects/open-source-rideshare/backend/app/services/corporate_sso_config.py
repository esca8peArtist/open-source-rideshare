"""Service functions for corporate SSO configuration.

Enterprise accounts configure their identity provider (IdP) here so employees
can authenticate via SSO instead of username/password.

Public API
----------
create_sso_config      — create config; 409 if one already exists
get_sso_config         — return config or None
update_sso_config      — partial update; 404 if not found
delete_sso_config      — hard delete; 404 if not found
set_sso_enforcement    — enable/disable enforce_sso flag; 422 if enabling when not active
activate_sso_config    — mark config as active; 404 if not found
disable_sso_config     — mark config as disabled; also clears enforce_sso
record_sso_test        — record a successful connection test; 404 if not found
list_sso_configs       — platform-admin: list all configs with optional filters
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_sso_config import CorporateSSOConfig, SSOStatus


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _get_config_or_404(
    db: AsyncSession, account_id: int
) -> CorporateSSOConfig:
    """Return the SSO config for *account_id*; raise 404 if not found."""
    result = await db.execute(
        select(CorporateSSOConfig).where(
            CorporateSSOConfig.account_id == account_id
        )
    )
    cfg = result.scalar_one_or_none()
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SSO configuration not found for this account.",
        )
    return cfg


# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------


async def create_sso_config(
    db: AsyncSession,
    account_id: int,
    provider: str,
    created_by_id: int,
    **kwargs: Any,
) -> CorporateSSOConfig:
    """Create an SSO configuration for *account_id*.

    Raises 409 if a configuration already exists — callers must delete the
    existing config before creating a new one.
    """
    existing = await db.execute(
        select(CorporateSSOConfig).where(
            CorporateSSOConfig.account_id == account_id
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "An SSO configuration already exists for this account. "
                "Delete it before creating a new one."
            ),
        )

    cfg = CorporateSSOConfig(
        account_id=account_id,
        provider=provider,
        status=SSOStatus.pending,
        enforce_sso=False,
        created_by_id=created_by_id,
        **kwargs,
    )
    db.add(cfg)
    await db.flush()
    return cfg


async def get_sso_config(
    db: AsyncSession, account_id: int
) -> Optional[CorporateSSOConfig]:
    """Return the SSO config for *account_id*, or None if not configured."""
    result = await db.execute(
        select(CorporateSSOConfig).where(
            CorporateSSOConfig.account_id == account_id
        )
    )
    return result.scalar_one_or_none()


async def update_sso_config(
    db: AsyncSession, account_id: int, **kwargs: Any
) -> CorporateSSOConfig:
    """Partially update the SSO config for *account_id*.

    Only keys present in *kwargs* are applied.  Raises 404 if not found.
    """
    cfg = await _get_config_or_404(db, account_id)
    for field, value in kwargs.items():
        setattr(cfg, field, value)
    await db.flush()
    return cfg


async def delete_sso_config(db: AsyncSession, account_id: int) -> None:
    """Hard-delete the SSO config for *account_id*.

    Raises 404 if not found.
    """
    cfg = await _get_config_or_404(db, account_id)
    await db.delete(cfg)
    await db.flush()


async def set_sso_enforcement(
    db: AsyncSession, account_id: int, enforce: bool
) -> CorporateSSOConfig:
    """Enable or disable SSO enforcement for *account_id*.

    Raises 404 if the config does not exist.
    Raises 422 if attempting to enable enforcement when ``status != active``.
    """
    cfg = await _get_config_or_404(db, account_id)
    if enforce and cfg.status != SSOStatus.active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "SSO enforcement can only be enabled when the configuration "
                "status is 'active'.  Activate the configuration first."
            ),
        )
    cfg.enforce_sso = enforce
    await db.flush()
    return cfg


async def activate_sso_config(
    db: AsyncSession, account_id: int
) -> CorporateSSOConfig:
    """Mark the SSO config as active.

    Called by an admin after they have verified the SSO connection works.
    Raises 404 if the config does not exist.
    """
    cfg = await _get_config_or_404(db, account_id)
    cfg.status = SSOStatus.active
    await db.flush()
    return cfg


async def disable_sso_config(
    db: AsyncSession, account_id: int
) -> CorporateSSOConfig:
    """Disable the SSO config and clear enforcement.

    Sets ``status = disabled`` and ``enforce_sso = False``.
    Raises 404 if the config does not exist.
    """
    cfg = await _get_config_or_404(db, account_id)
    cfg.status = SSOStatus.disabled
    cfg.enforce_sso = False
    await db.flush()
    return cfg


async def record_sso_test(
    db: AsyncSession, account_id: int, tested_by_id: int
) -> CorporateSSOConfig:
    """Record that an SSO connection test succeeded.

    Updates ``last_tested_at`` to the current UTC timestamp and sets
    ``last_tested_by_id`` to the requesting user.
    Raises 404 if the config does not exist.
    """
    cfg = await _get_config_or_404(db, account_id)
    cfg.last_tested_at = datetime.now(tz=timezone.utc)
    cfg.last_tested_by_id = tested_by_id
    await db.flush()
    return cfg


async def list_sso_configs(
    db: AsyncSession,
    status_filter: Optional[SSOStatus] = None,
    provider_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
) -> list[CorporateSSOConfig]:
    """Return all SSO configs for platform-admin use.

    Optionally filter by *status_filter* and/or *provider_filter*.
    """
    query = (
        select(CorporateSSOConfig)
        .order_by(CorporateSSOConfig.id)
        .offset(skip)
        .limit(limit)
    )
    if status_filter is not None:
        query = query.where(CorporateSSOConfig.status == status_filter)
    if provider_filter is not None:
        query = query.where(CorporateSSOConfig.provider == provider_filter)

    result = await db.execute(query)
    return list(result.scalars().all())
