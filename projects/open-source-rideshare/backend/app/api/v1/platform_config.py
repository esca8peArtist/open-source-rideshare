"""Admin API for persistent platform configuration.

All endpoints are scoped under /admin/config and require admin role.

Route ordering note: POST /admin/config/seed and POST /admin/config/bulk-update
are registered *before* the parameterised /{key} routes to prevent FastAPI
treating the literal path segments as key values.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.database import get_db
from app.models.platform_config import ConfigCategory, PlatformConfig
from app.models.user import User
from app.schemas.platform_config import (
    ConfigBulkUpdateRequest,
    ConfigBulkUpdateResponse,
    ConfigEntryResponse,
    ConfigEntryUpdate,
    ConfigHistoryResponse,
    ConfigSeedResponse,
)
from app.services.platform_config import (
    bulk_update_configs,
    get_all_configs,
    get_config_by_key,
    get_config_history,
    seed_defaults,
    update_config,
)

router = APIRouter(prefix="/admin/config", tags=["admin-config"])


# ---------------------------------------------------------------------------
# Non-parameterised routes (must come first)
# ---------------------------------------------------------------------------


@router.get("", response_model=list[ConfigEntryResponse])
async def list_configs(
    category: str | None = Query(default=None, description="Filter by category"),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[ConfigEntryResponse]:
    """List all active platform config entries, with optional category filter."""
    cat = None
    if category is not None:
        try:
            cat = ConfigCategory(category)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown category: {category!r}",
            )
    configs = await get_all_configs(db, category=cat)
    return [ConfigEntryResponse.model_validate(c) for c in configs]


@router.get("/categories", response_model=list[str])
async def list_categories(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[str]:
    """Return the distinct categories that have at least one active config entry."""
    result = await db.execute(
        select(PlatformConfig.category)
        .where(PlatformConfig.is_active == True)  # noqa: E712
        .distinct()
    )
    return [row[0].value for row in result.all()]


@router.post("/seed", response_model=ConfigSeedResponse)
async def seed_config_defaults(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> ConfigSeedResponse:
    """Idempotently seed default config entries.  Safe to call multiple times."""
    seeded, skipped = await seed_defaults(db)
    return ConfigSeedResponse(seeded=seeded, skipped=skipped)


@router.post("/bulk-update", response_model=ConfigBulkUpdateResponse)
async def bulk_update(
    body: ConfigBulkUpdateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ConfigBulkUpdateResponse:
    """Apply multiple config updates in a single request."""
    updated, failed = await bulk_update_configs(
        db, updates=body.updates, changed_by_id=admin.id
    )
    return ConfigBulkUpdateResponse(
        updated=[ConfigEntryResponse.model_validate(c) for c in updated],
        failed=failed,
    )


# ---------------------------------------------------------------------------
# Parameterised routes (must come after fixed-path routes)
# ---------------------------------------------------------------------------


@router.get("/{key}", response_model=ConfigEntryResponse)
async def get_config(
    key: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> ConfigEntryResponse:
    """Retrieve a single config entry by key."""
    config = await get_config_by_key(db, key)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Config key {key!r} not found",
        )
    return ConfigEntryResponse.model_validate(config)


@router.put("/{key}", response_model=ConfigEntryResponse)
async def update_config_entry(
    key: str,
    body: ConfigEntryUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ConfigEntryResponse:
    """Update a single config entry value."""
    try:
        config = await update_config(
            db,
            key=key,
            new_value_str=body.value,
            changed_by_id=admin.id,
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    return ConfigEntryResponse.model_validate(config)


@router.get("/{key}/history", response_model=ConfigHistoryResponse)
async def get_history(
    key: str,
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> ConfigHistoryResponse:
    """Retrieve the change history for a config key."""
    history = await get_config_history(db, key=key, limit=limit)
    from app.schemas.platform_config import ConfigHistoryEntry  # local to avoid circular

    return ConfigHistoryResponse(
        key=key,
        history=[ConfigHistoryEntry.model_validate(h) for h in history],
    )
