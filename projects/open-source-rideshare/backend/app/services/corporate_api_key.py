"""Service layer for Corporate API Keys.

Enterprise admins generate named API keys with configurable permission scopes.
External systems use these keys to pull data from the corporate account.
Only the SHA-256 hash is stored; the plaintext is returned once at creation
or rotation.

Public surface
--------------
create_api_key(db, account_id, name, scopes, expires_at, created_by_id)
    → (CorporateApiKey, plain_key)
get_api_key(db, account_id, key_id)
    → CorporateApiKey
list_api_keys(db, account_id, active_only)
    → list[CorporateApiKey]
update_api_key(db, account_id, key_id, **fields)
    → CorporateApiKey
revoke_api_key(db, account_id, key_id)
    → CorporateApiKey
delete_api_key(db, account_id, key_id)
    → None
rotate_api_key(db, account_id, key_id)
    → (CorporateApiKey, plain_key)
verify_api_key(db, raw_key)
    → CorporateApiKey | None
"""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_api_key import CorporateApiKey

# ---------------------------------------------------------------------------
# Known permission scopes
# ---------------------------------------------------------------------------

KNOWN_SCOPES: frozenset[str] = frozenset(
    [
        "rides:read",
        "invoices:read",
        "analytics:read",
        "employees:read",
        "exports:read",
        "reports:read",
    ]
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_KEY_PREFIX_MARKER = "rsk_"


def _generate_api_key() -> str:
    """Generate a cryptographically random API key.

    Format: ``rsk_<64 lowercase hex chars>`` (32 bytes of randomness).
    """
    return f"{_KEY_PREFIX_MARKER}{os.urandom(32).hex()}"


def _hash_key(raw_key: str) -> str:
    """Return the SHA-256 hex digest of *raw_key*."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _validate_scopes(scopes: list[str]) -> None:
    """Raise HTTP 422 if any scope is not in the known set."""
    unknown = set(scopes) - KNOWN_SCOPES
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Unknown scope(s): {sorted(unknown)}. "
                f"Valid scopes are: {sorted(KNOWN_SCOPES)}"
            ),
        )


async def _get_key_by_id(
    db: AsyncSession,
    account_id: int,
    key_id: uuid.UUID,
) -> CorporateApiKey:
    """Return the key or raise HTTP 404 if not found in this account."""
    result = await db.execute(
        select(CorporateApiKey).where(
            CorporateApiKey.id == key_id,
            CorporateApiKey.account_id == account_id,
        )
    )
    key = result.scalar_one_or_none()
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found in this account.",
        )
    return key


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------


async def create_api_key(
    db: AsyncSession,
    account_id: int,
    name: str,
    scopes: Optional[list[str]] = None,
    expires_at: Optional[datetime] = None,
    created_by_id: Optional[int] = None,
) -> tuple[CorporateApiKey, str]:
    """Create a new API key for a corporate account.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        name: Human-readable label for the key.
        scopes: Optional list of permission scope strings.
        expires_at: Optional expiry datetime.
        created_by_id: ID of the admin creating this key.

    Returns:
        A tuple of ``(CorporateApiKey, plain_key)`` where ``plain_key`` is
        the full API key string (shown only once).

    Raises:
        HTTP 422: When any scope is not in the known set.
    """
    if scopes is None:
        scopes = []
    _validate_scopes(scopes)

    plain_key = _generate_api_key()
    key_obj = CorporateApiKey(
        account_id=account_id,
        name=name,
        key_prefix=plain_key[:8],
        key_hash=_hash_key(plain_key),
        scopes=scopes,
        is_active=True,
        expires_at=expires_at,
        created_by_id=created_by_id,
    )
    db.add(key_obj)
    await db.flush()
    return key_obj, plain_key


async def get_api_key(
    db: AsyncSession,
    account_id: int,
    key_id: uuid.UUID,
) -> CorporateApiKey:
    """Return a single API key by ID.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        key_id: API key UUID.

    Raises:
        HTTP 404: When the key is not found in this account.
    """
    return await _get_key_by_id(db, account_id, key_id)


async def list_api_keys(
    db: AsyncSession,
    account_id: int,
    active_only: bool = True,
) -> list[CorporateApiKey]:
    """Return API keys for a corporate account.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        active_only: When True, only return active (non-revoked) keys.

    Returns:
        List of CorporateApiKey instances.
    """
    q = select(CorporateApiKey).where(CorporateApiKey.account_id == account_id)
    if active_only:
        q = q.where(CorporateApiKey.is_active.is_(True))
    result = await db.execute(q)
    return list(result.scalars().all())


async def update_api_key(
    db: AsyncSession,
    account_id: int,
    key_id: uuid.UUID,
    name: Optional[str] = None,
    scopes: Optional[list[str]] = None,
    expires_at: Optional[datetime] = None,
) -> CorporateApiKey:
    """Update an existing API key's metadata.

    Updatable fields: name, scopes, expires_at.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        key_id: API key UUID.
        name: New label, if changing.
        scopes: New scope list, if changing.
        expires_at: New expiry datetime, if changing.

    Returns:
        The updated CorporateApiKey instance.

    Raises:
        HTTP 404: When the key is not found in this account.
        HTTP 422: When any supplied scope is unknown.
    """
    key_obj = await _get_key_by_id(db, account_id, key_id)

    if name is not None:
        key_obj.name = name
    if scopes is not None:
        _validate_scopes(scopes)
        key_obj.scopes = scopes
    if expires_at is not None:
        key_obj.expires_at = expires_at

    await db.flush()
    return key_obj


async def revoke_api_key(
    db: AsyncSession,
    account_id: int,
    key_id: uuid.UUID,
) -> CorporateApiKey:
    """Soft-delete an API key by setting is_active=False.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        key_id: API key UUID.

    Returns:
        The updated CorporateApiKey instance.

    Raises:
        HTTP 404: When the key is not found in this account.
        HTTP 409: When the key is already revoked.
    """
    key_obj = await _get_key_by_id(db, account_id, key_id)
    if not key_obj.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="API key is already revoked.",
        )
    key_obj.is_active = False
    await db.flush()
    return key_obj


async def delete_api_key(
    db: AsyncSession,
    account_id: int,
    key_id: uuid.UUID,
) -> None:
    """Hard-delete an API key record.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        key_id: API key UUID.

    Raises:
        HTTP 404: When the key is not found in this account.
    """
    key_obj = await _get_key_by_id(db, account_id, key_id)
    await db.delete(key_obj)
    await db.flush()


async def rotate_api_key(
    db: AsyncSession,
    account_id: int,
    key_id: uuid.UUID,
) -> tuple[CorporateApiKey, str]:
    """Invalidate the current secret and generate a new one.

    The key record is updated in-place: ``key_hash`` and ``key_prefix`` change,
    ``is_active`` is set to True (re-activates a previously revoked key).
    Scopes and expiry are preserved.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        key_id: API key UUID.

    Returns:
        A tuple of ``(CorporateApiKey, plain_key)`` with the new plaintext key.

    Raises:
        HTTP 404: When the key is not found in this account.
    """
    key_obj = await _get_key_by_id(db, account_id, key_id)

    plain_key = _generate_api_key()
    key_obj.key_hash = _hash_key(plain_key)
    key_obj.key_prefix = plain_key[:8]
    key_obj.is_active = True

    await db.flush()
    return key_obj, plain_key


async def verify_api_key(
    db: AsyncSession,
    raw_key: str,
) -> Optional[CorporateApiKey]:
    """Look up and verify an API key by its raw value.

    Checks that the key exists, is active, and has not expired.  If valid,
    updates ``last_used_at`` on the key record.

    Args:
        db: Database session.
        raw_key: The full API key string as supplied by the caller.

    Returns:
        The CorporateApiKey if valid, or ``None`` if the key is not found,
        revoked, or expired.
    """
    key_hash = _hash_key(raw_key)
    result = await db.execute(
        select(CorporateApiKey).where(CorporateApiKey.key_hash == key_hash)
    )
    key_obj = result.scalar_one_or_none()

    if key_obj is None:
        return None
    if not key_obj.is_active:
        return None
    if key_obj.expires_at is not None:
        now = datetime.now(timezone.utc)
        # Normalise to UTC-aware for comparison
        exp = key_obj.expires_at
        if exp.tzinfo is None:
            from datetime import timezone as tz
            exp = exp.replace(tzinfo=tz.utc)
        if now > exp:
            return None

    key_obj.last_used_at = datetime.now(timezone.utc)
    await db.flush()
    return key_obj
