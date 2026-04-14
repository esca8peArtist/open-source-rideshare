"""Platform admin config API.

Provides database-backed CRUD endpoints for runtime platform settings.
All endpoints are admin-gated.

Endpoints:
  GET  /admin/config               — list all config entries (optional ?category= filter)
  GET  /admin/config/{key}         — fetch a single entry
  PUT  /admin/config/{key}         — update a single entry
  POST /admin/config/bulk          — bulk-update multiple entries
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.models.platform_config import ConfigCategory
from app.models.user import User
from app.schemas.platform_config import (
    BulkConfigUpdateRequest,
    BulkConfigUpdateResponse,
    BulkConfigUpdateResult,
    PlatformConfigEntry,
    PlatformConfigListResponse,
    PlatformConfigUpdate,
)
from app.services.platform_config import (
    bulk_update_config,
    get_all_config,
    get_config_entry,
    update_config_entry,
)

router = APIRouter(
    prefix="/admin/config",
    tags=["admin-config"],
)


@router.get(
    "",
    response_model=PlatformConfigListResponse,
    summary="List platform config entries",
    description=(
        "Returns all runtime configuration entries. "
        "Filter by `category` to narrow results. "
        "Each entry includes a `typed_value` field already cast to the correct Python type."
    ),
)
async def list_config(
    category: ConfigCategory | None = Query(
        default=None,
        description="Filter by config category (pricing, operations, safety, features, notifications, matching).",
    ),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PlatformConfigListResponse:
    entries_raw = await get_all_config(db, category=category)
    entries = [PlatformConfigEntry(**e) for e in entries_raw]
    return PlatformConfigListResponse(entries=entries, total=len(entries))


@router.get(
    "/{key}",
    response_model=PlatformConfigEntry,
    summary="Get a single config entry",
    description="Fetch one platform config entry by its key.",
)
async def get_config(
    key: str,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PlatformConfigEntry:
    entry = await get_config_entry(db, key)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Config key '{key}' not found.",
        )
    return PlatformConfigEntry(**entry)


@router.put(
    "/{key}",
    response_model=PlatformConfigEntry,
    summary="Update a single config entry",
    description=(
        "Update the value of a platform config entry. "
        "The new value must be parseable as the entry's declared `value_type`. "
        "The change is audit-logged with the acting admin's user ID."
    ),
)
async def update_config(
    key: str,
    body: PlatformConfigUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PlatformConfigEntry:
    try:
        updated = await update_config_entry(
            db,
            key=key,
            value=body.value,
            updated_by_id=current_user.id,
            description=body.description,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Config key '{key}' not found.",
        )
    return PlatformConfigEntry(**updated)


@router.post(
    "/bulk",
    response_model=BulkConfigUpdateResponse,
    summary="Bulk-update config entries",
    description=(
        "Update multiple config entries in a single request. "
        "Per-entry errors are reported individually — the operation is best-effort, "
        "not transactional. Successfully updated entries are committed even if others fail."
    ),
)
async def bulk_update(
    body: BulkConfigUpdateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BulkConfigUpdateResponse:
    if not body.updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="updates list must not be empty.",
        )

    updates_dicts = [{"key": u.key, "value": u.value} for u in body.updates]
    summary = await bulk_update_config(db, updates_dicts, updated_by_id=current_user.id)

    results = [BulkConfigUpdateResult(**r) for r in summary["results"]]
    return BulkConfigUpdateResponse(
        results=results,
        updated_count=summary["updated_count"],
        failed_count=summary["failed_count"],
    )
