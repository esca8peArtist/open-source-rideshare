"""Corporate API Key endpoints.

Enterprise admins generate named API keys with configurable permission scopes.
External systems use these keys to pull data from the corporate account via
the REST API (pull-based complement to webhooks).

Admin endpoints (require account membership):
  GET    /corporate/accounts/me/api-keys                          — list keys
  POST   /corporate/accounts/me/api-keys                         — create key (returns plaintext once)
  GET    /corporate/accounts/me/api-keys/{key_id}                — get key
  PUT    /corporate/accounts/me/api-keys/{key_id}                — update name/scopes/expiry
  DELETE /corporate/accounts/me/api-keys/{key_id}/revoke         — soft-delete
  DELETE /corporate/accounts/me/api-keys/{key_id}                — hard-delete
  POST   /corporate/accounts/me/api-keys/{key_id}/rotate         — rotate secret (returns new plaintext)

Platform-admin endpoints:
  GET  /admin/corporate/accounts/{account_id}/api-keys           — list all for account
  POST /admin/corporate/api-keys/verify                          — verify a raw key
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Query, status
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_api_key import (
    ApiKeyCreate,
    ApiKeyCreateResponse,
    ApiKeyListResponse,
    ApiKeyResponse,
    ApiKeyUpdate,
    ApiKeyVerifyRequest,
    ApiKeyVerifyResponse,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_api_key import (
    KNOWN_SCOPES,
    create_api_key,
    delete_api_key,
    get_api_key,
    list_api_keys,
    revoke_api_key,
    rotate_api_key,
    update_api_key,
    verify_api_key,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-api-keys"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _resolve_account_id(db: AsyncSession, user_id: int) -> int:
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


def _key_to_response(key_obj) -> ApiKeyResponse:
    return ApiKeyResponse.model_validate(key_obj)


def _key_to_create_response(key_obj, plain_key: str) -> ApiKeyCreateResponse:
    data = ApiKeyResponse.model_validate(key_obj).model_dump()
    data["plain_key"] = plain_key
    return ApiKeyCreateResponse(**data)


# ---------------------------------------------------------------------------
# Admin: list keys
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/api-keys",
    response_model=ApiKeyListResponse,
    summary="Admin: list API keys for my corporate account",
)
async def list_account_api_keys(
    active_only: bool = Query(True, description="When True, only return active keys."),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all API keys configured for the caller's corporate account.

    Requires account membership.
    """
    account_id = await _resolve_account_id(db, user.id)
    keys = await list_api_keys(db, account_id, active_only=active_only)
    return ApiKeyListResponse(
        account_id=account_id,
        total=len(keys),
        keys=[_key_to_response(k) for k in keys],
    )


# ---------------------------------------------------------------------------
# Admin: create key
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/api-keys",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: create an API key for my corporate account",
)
async def create_account_api_key(
    data: ApiKeyCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new API key for the caller's corporate account.

    The ``plain_key`` field in the response contains the full key value.
    **Store it securely — it will not be shown again.**

    Requires ADMIN role within the account (enforced by the service layer).
    """
    account_id = await _resolve_account_id(db, user.id)
    key_obj, plain_key = await create_api_key(
        db,
        account_id=account_id,
        name=data.name,
        scopes=data.scopes,
        expires_at=data.expires_at,
        created_by_id=user.id,
    )
    await db.commit()
    return _key_to_create_response(key_obj, plain_key)


# ---------------------------------------------------------------------------
# Admin: get key
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/api-keys/{key_id}",
    response_model=ApiKeyResponse,
    summary="Admin: get an API key by ID",
)
async def get_account_api_key(
    key_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return metadata for a specific API key.

    The plaintext key is not returned.  Requires account membership.
    """
    account_id = await _resolve_account_id(db, user.id)
    key_obj = await get_api_key(db, account_id, key_id)
    return _key_to_response(key_obj)


# ---------------------------------------------------------------------------
# Admin: update key
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/accounts/me/api-keys/{key_id}",
    response_model=ApiKeyResponse,
    summary="Admin: update an API key",
)
async def update_account_api_key(
    key_id: uuid.UUID,
    data: ApiKeyUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an API key's name, scopes, or expiry datetime.

    All fields are optional.  Requires account membership.
    """
    account_id = await _resolve_account_id(db, user.id)
    key_obj = await update_api_key(
        db,
        account_id=account_id,
        key_id=key_id,
        name=data.name,
        scopes=data.scopes,
        expires_at=data.expires_at,
    )
    await db.commit()
    return _key_to_response(key_obj)


# ---------------------------------------------------------------------------
# Admin: revoke (soft-delete)
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/api-keys/{key_id}/revoke",
    response_model=ApiKeyResponse,
    summary="Admin: revoke an API key (soft-delete)",
)
async def revoke_account_api_key(
    key_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke an API key by setting is_active=False.

    The key record is preserved for audit purposes.
    Requires account membership.
    """
    account_id = await _resolve_account_id(db, user.id)
    key_obj = await revoke_api_key(db, account_id, key_id)
    await db.commit()
    return _key_to_response(key_obj)


# ---------------------------------------------------------------------------
# Admin: hard-delete
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Admin: hard-delete an API key",
)
async def delete_account_api_key(
    key_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete an API key record.

    Requires account membership.
    """
    account_id = await _resolve_account_id(db, user.id)
    await delete_api_key(db, account_id, key_id)
    await db.commit()


# ---------------------------------------------------------------------------
# Admin: rotate key
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/api-keys/{key_id}/rotate",
    response_model=ApiKeyCreateResponse,
    summary="Admin: rotate an API key (generate new secret)",
)
async def rotate_account_api_key(
    key_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Invalidate the current key secret and generate a new one.

    The ``plain_key`` field contains the new full key value.
    **Store it securely — it will not be shown again.**
    Scopes and expiry are preserved.  Requires account membership.
    """
    account_id = await _resolve_account_id(db, user.id)
    key_obj, plain_key = await rotate_api_key(db, account_id, key_id)
    await db.commit()
    return _key_to_create_response(key_obj, plain_key)


# ---------------------------------------------------------------------------
# Platform-admin: list all keys for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/api-keys",
    response_model=ApiKeyListResponse,
    summary="Platform admin: list all API keys for a corporate account",
)
async def platform_admin_list_api_keys(
    account_id: int,
    active_only: bool = Query(False),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all API keys for any corporate account.

    Requires platform-level admin role.
    """
    keys = await list_api_keys(db, account_id, active_only=active_only)
    return ApiKeyListResponse(
        account_id=account_id,
        total=len(keys),
        keys=[_key_to_response(k) for k in keys],
    )


# ---------------------------------------------------------------------------
# Platform-admin: verify a raw key
# ---------------------------------------------------------------------------


@router.post(
    "/admin/corporate/api-keys/verify",
    response_model=ApiKeyVerifyResponse,
    summary="Platform admin: verify a raw API key",
)
async def platform_admin_verify_api_key(
    data: ApiKeyVerifyRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Verify whether a raw API key is valid and return its metadata.

    Returns ``{"valid": false}`` when the key is not found, revoked, or expired.
    Requires platform-level admin role.
    """
    key_obj = await verify_api_key(db, data.raw_key)
    await db.commit()
    if key_obj is None:
        return ApiKeyVerifyResponse(valid=False)
    return ApiKeyVerifyResponse(
        valid=True,
        account_id=key_obj.account_id,
        key_id=key_obj.id,
        scopes=key_obj.scopes,
    )
