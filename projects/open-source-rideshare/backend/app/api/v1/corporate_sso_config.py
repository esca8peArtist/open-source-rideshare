"""Corporate SSO Configuration endpoints.

Enterprise accounts configure their identity provider so employees log in
via SSO.  Admins set provider credentials, test the connection, activate,
and optionally enforce SSO for all members.

Admin endpoints (require corporate account membership):
  GET    /corporate/{account_id}/sso              — get SSO config
  POST   /corporate/{account_id}/sso              — create SSO config (201)
  PATCH  /corporate/{account_id}/sso              — update SSO config
  DELETE /corporate/{account_id}/sso              — delete SSO config (204)
  POST   /corporate/{account_id}/sso/enforce      — toggle enforcement
  POST   /corporate/{account_id}/sso/activate     — mark config as active
  POST   /corporate/{account_id}/sso/disable      — disable config
  POST   /corporate/{account_id}/sso/test         — record successful test

Platform-admin endpoints:
  GET /platform-admin/corporate/sso/configs                   — list all
  GET /platform-admin/corporate/sso/accounts/{account_id}     — get for account
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_sso_config import SSOProvider, SSOStatus
from app.models.user import User
from app.schemas.corporate_sso_config import (
    CorporateSSOConfigCreate,
    CorporateSSOConfigResponse,
    CorporateSSOConfigUpdate,
    SSOEnforcementUpdate,
)
from app.services.corporate_sso_config import (
    activate_sso_config,
    create_sso_config,
    delete_sso_config,
    disable_sso_config,
    get_sso_config,
    list_sso_configs,
    record_sso_test,
    set_sso_enforcement,
    update_sso_config,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-sso-config"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_response(cfg: object) -> CorporateSSOConfigResponse:
    return CorporateSSOConfigResponse.model_validate(cfg)


# ---------------------------------------------------------------------------
# Admin: get SSO config
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/sso",
    response_model=CorporateSSOConfigResponse,
    summary="Admin: get SSO configuration for a corporate account",
)
async def get_sso_config_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the SSO configuration for *account_id*.

    Returns 404 if no SSO configuration has been created for this account.
    """
    cfg = await get_sso_config(db, account_id=account_id)
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SSO configuration not found for this account.",
        )
    return _to_response(cfg)


# ---------------------------------------------------------------------------
# Admin: create SSO config
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/sso",
    response_model=CorporateSSOConfigResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: create SSO configuration for a corporate account",
)
async def create_sso_config_endpoint(
    account_id: int,
    data: CorporateSSOConfigCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new SSO configuration for *account_id*.

    Returns 409 if a configuration already exists — delete it first before
    creating a replacement.
    """
    kwargs = data.model_dump(exclude={"provider"}, exclude_none=True)
    cfg = await create_sso_config(
        db,
        account_id=account_id,
        provider=data.provider,
        created_by_id=user.id,
        **kwargs,
    )
    await db.commit()
    return _to_response(cfg)


# ---------------------------------------------------------------------------
# Admin: update SSO config
# ---------------------------------------------------------------------------


@router.patch(
    "/corporate/{account_id}/sso",
    response_model=CorporateSSOConfigResponse,
    summary="Admin: update SSO configuration for a corporate account",
)
async def update_sso_config_endpoint(
    account_id: int,
    data: CorporateSSOConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update the SSO configuration for *account_id*.

    Only supplied fields are changed.  Returns 404 if not found.
    """
    updates = data.model_dump(exclude_none=True)
    cfg = await update_sso_config(db, account_id=account_id, **updates)
    await db.commit()
    return _to_response(cfg)


# ---------------------------------------------------------------------------
# Admin: delete SSO config
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/{account_id}/sso",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Admin: delete SSO configuration for a corporate account",
)
async def delete_sso_config_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Hard-delete the SSO configuration for *account_id*.

    Returns 404 if not found.
    """
    await delete_sso_config(db, account_id=account_id)
    await db.commit()


# ---------------------------------------------------------------------------
# Admin: toggle SSO enforcement
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/sso/enforce",
    response_model=CorporateSSOConfigResponse,
    summary="Admin: enable or disable SSO enforcement for a corporate account",
)
async def set_sso_enforcement_endpoint(
    account_id: int,
    data: SSOEnforcementUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Enable or disable SSO enforcement for *account_id*.

    When ``enforce`` is ``true``, all members must authenticate via SSO and
    password login is blocked.  Returns 422 if attempting to enable enforcement
    when the configuration status is not ``active``.
    """
    cfg = await set_sso_enforcement(db, account_id=account_id, enforce=data.enforce)
    await db.commit()
    return _to_response(cfg)


# ---------------------------------------------------------------------------
# Admin: activate SSO config
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/sso/activate",
    response_model=CorporateSSOConfigResponse,
    summary="Admin: mark SSO configuration as active",
)
async def activate_sso_config_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark the SSO configuration for *account_id* as active.

    Call this after verifying that the SSO connection works correctly.
    Returns 404 if not found.
    """
    cfg = await activate_sso_config(db, account_id=account_id)
    await db.commit()
    return _to_response(cfg)


# ---------------------------------------------------------------------------
# Admin: disable SSO config
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/sso/disable",
    response_model=CorporateSSOConfigResponse,
    summary="Admin: disable SSO configuration",
)
async def disable_sso_config_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Disable the SSO configuration for *account_id*.

    Also clears ``enforce_sso`` so members can log in with a password again.
    Returns 404 if not found.
    """
    cfg = await disable_sso_config(db, account_id=account_id)
    await db.commit()
    return _to_response(cfg)


# ---------------------------------------------------------------------------
# Admin: record successful SSO test
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/sso/test",
    response_model=CorporateSSOConfigResponse,
    summary="Admin: record a successful SSO connection test",
)
async def record_sso_test_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record that the SSO connection was successfully tested.

    Updates ``last_tested_at`` and ``last_tested_by_id``.  This simulates the
    "Test Connection" button in the UI.  Returns 404 if not found.
    """
    cfg = await record_sso_test(db, account_id=account_id, tested_by_id=user.id)
    await db.commit()
    return _to_response(cfg)


# ---------------------------------------------------------------------------
# Platform-admin: list all SSO configs
# ---------------------------------------------------------------------------


@router.get(
    "/platform-admin/corporate/sso/configs",
    response_model=list[CorporateSSOConfigResponse],
    summary="Platform admin: list all corporate SSO configurations",
)
async def platform_admin_list_sso_configs(
    status_filter: Optional[SSOStatus] = Query(
        None, alias="status", description="Filter by SSO status."
    ),
    provider_filter: Optional[SSOProvider] = Query(
        None, alias="provider", description="Filter by SSO provider."
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all corporate SSO configurations.

    Optionally filter by ``status`` and/or ``provider``.
    """
    configs = await list_sso_configs(
        db,
        status_filter=status_filter,
        provider_filter=provider_filter,
        skip=skip,
        limit=limit,
    )
    return [_to_response(c) for c in configs]


# ---------------------------------------------------------------------------
# Platform-admin: get SSO config for a specific account
# ---------------------------------------------------------------------------


@router.get(
    "/platform-admin/corporate/sso/accounts/{account_id}",
    response_model=CorporateSSOConfigResponse,
    summary="Platform admin: get SSO configuration for a specific corporate account",
)
async def platform_admin_get_sso_config(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the SSO configuration for any corporate account.

    Returns 404 if no SSO configuration has been created for this account.
    """
    cfg = await get_sso_config(db, account_id=account_id)
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SSO configuration not found for this account.",
        )
    return _to_response(cfg)
