"""Service layer for Corporate Receipt Template.

Finance feature: corporate accounts define a custom receipt template applied
to all ride receipts for their employees.  Finance teams can brand receipts,
set reference prefixes, add footer notes, toggle driver details/route maps,
and attach custom line items such as project codes.

Public surface
--------------
get_or_create_receipt_template(db, account_id)
    -> ReceiptTemplateResponse
        Upsert-on-read: returns the existing template or creates a default.

update_receipt_template(db, account_id, data, admin_id)
    -> ReceiptTemplateResponse
        Partial update — only supplied fields are written.

deactivate_receipt_template(db, account_id, admin_id)
    -> ReceiptTemplateResponse
        Sets is_active=False; raises 409 if already inactive.

delete_receipt_template(db, account_id)
    -> None
        Hard-delete the template row.

get_receipt_template_for_ride(db, account_id)
    -> ReceiptTemplateResponse | None
        Returns the active template or None (used by receipt generation logic).

list_all_receipt_templates(db, limit, offset)
    -> ReceiptTemplateListResponse
        Platform-admin: cross-account paginated list.
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_receipt_template import CorporateReceiptTemplate
from app.schemas.corporate_receipt_template import (
    ReceiptTemplateListResponse,
    ReceiptTemplateResponse,
    ReceiptTemplateUpdate,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_response(template: CorporateReceiptTemplate) -> ReceiptTemplateResponse:
    """Convert a model instance to ReceiptTemplateResponse."""
    return ReceiptTemplateResponse(
        id=template.id,
        account_id=template.account_id,
        company_name=template.company_name,
        logo_url=template.logo_url,
        header_message=template.header_message,
        footer_message=template.footer_message,
        reference_prefix=template.reference_prefix,
        show_driver_details=template.show_driver_details,
        show_route_map=template.show_route_map,
        custom_line_items=template.custom_line_items,
        is_active=template.is_active,
        created_by_id=template.created_by_id,
        updated_by_id=template.updated_by_id,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


async def _fetch_template(
    db: AsyncSession, account_id: int
) -> Optional[CorporateReceiptTemplate]:
    """Return the receipt template row for an account, or None."""
    result = await db.execute(
        select(CorporateReceiptTemplate).where(
            CorporateReceiptTemplate.account_id == account_id
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------


async def get_or_create_receipt_template(
    db: AsyncSession,
    account_id: int,
) -> ReceiptTemplateResponse:
    """Return the receipt template for an account, creating a default if absent.

    Follows the upsert-on-read pattern used by billing settings and carbon
    budget — the first GET creates a row with sensible defaults so callers
    always receive a well-formed response.

    Args:
        db:         Async database session.
        account_id: Corporate account identifier.

    Returns:
        ReceiptTemplateResponse (existing or newly created default).
    """
    template = await _fetch_template(db, account_id)

    if template is None:
        template = CorporateReceiptTemplate(
            account_id=account_id,
            show_driver_details=True,
            show_route_map=True,
            is_active=True,
        )
        db.add(template)
        await db.commit()
        await db.refresh(template)

    return _to_response(template)


async def update_receipt_template(
    db: AsyncSession,
    account_id: int,
    data: ReceiptTemplateUpdate,
    admin_id: int,
) -> ReceiptTemplateResponse:
    """Create or update the receipt template for an account.

    Follows PUT semantics: only explicitly supplied fields are written; unset
    fields are left unchanged.  Creates the row with defaults if absent.

    Args:
        db:         Async database session.
        account_id: Corporate account identifier.
        data:       Validated update payload.
        admin_id:   ID of the admin making the change (audit trail).

    Returns:
        Updated ReceiptTemplateResponse.
    """
    template = await _fetch_template(db, account_id)

    if template is None:
        template = CorporateReceiptTemplate(
            account_id=account_id,
            show_driver_details=True,
            show_route_map=True,
            is_active=True,
            created_by_id=admin_id,
        )
        db.add(template)

    # Apply only the fields that were explicitly set in the payload.
    # For custom_line_items, serialise to plain dicts so JSONB is happy.
    payload = data.model_dump(exclude_unset=True)
    if "custom_line_items" in payload and payload["custom_line_items"] is not None:
        payload["custom_line_items"] = [
            item if isinstance(item, dict) else item.model_dump()
            for item in payload["custom_line_items"]
        ]
    for field, value in payload.items():
        setattr(template, field, value)

    template.updated_by_id = admin_id
    await db.commit()
    await db.refresh(template)
    return _to_response(template)


async def deactivate_receipt_template(
    db: AsyncSession,
    account_id: int,
    admin_id: int,
) -> ReceiptTemplateResponse:
    """Deactivate the receipt template for an account.

    Sets ``is_active=False`` so the template is no longer applied to new
    receipts.  Raises 409 when the template is already inactive, and 404 when
    no template exists.

    Args:
        db:         Async database session.
        account_id: Corporate account identifier.
        admin_id:   ID of the admin making the change (audit trail).

    Returns:
        Updated ReceiptTemplateResponse with is_active=False.

    Raises:
        HTTP 404: No receipt template found for this account.
        HTTP 409: Template is already inactive.
    """
    template = await _fetch_template(db, account_id)

    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No receipt template found for this account.",
        )

    if not template.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Receipt template is already inactive.",
        )

    template.is_active = False
    template.updated_by_id = admin_id
    await db.commit()
    await db.refresh(template)
    return _to_response(template)


async def delete_receipt_template(
    db: AsyncSession,
    account_id: int,
) -> None:
    """Hard-delete the receipt template for an account.

    This operation is irreversible.  Members may not call this — only account
    admins (enforced at the router level).

    Args:
        db:         Async database session.
        account_id: Corporate account identifier.

    Raises:
        HTTP 404: No receipt template found for this account.
    """
    template = await _fetch_template(db, account_id)

    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No receipt template found for this account.",
        )

    await db.delete(template)
    await db.commit()


async def get_receipt_template_for_ride(
    db: AsyncSession,
    account_id: int,
) -> Optional[ReceiptTemplateResponse]:
    """Return the active receipt template for an account, or None.

    Intended for use by receipt generation logic — returns None when no active
    template is configured so callers fall back to the platform default.

    Args:
        db:         Async database session.
        account_id: Corporate account identifier.

    Returns:
        ReceiptTemplateResponse if an active template exists, else None.
    """
    result = await db.execute(
        select(CorporateReceiptTemplate).where(
            CorporateReceiptTemplate.account_id == account_id,
            CorporateReceiptTemplate.is_active.is_(True),
        )
    )
    template = result.scalar_one_or_none()
    if template is None:
        return None
    return _to_response(template)


async def list_all_receipt_templates(
    db: AsyncSession,
    limit: int = 50,
    offset: int = 0,
) -> ReceiptTemplateListResponse:
    """List receipt templates across all corporate accounts.

    Platform-admin only.  Returns a paginated list ordered by account_id.

    Args:
        db:     Async database session.
        limit:  Maximum number of records to return (default 50).
        offset: Number of records to skip (default 0).

    Returns:
        ReceiptTemplateListResponse with total count and paginated items.
    """
    count_result = await db.execute(
        select(func.count()).select_from(CorporateReceiptTemplate)
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(CorporateReceiptTemplate)
        .order_by(CorporateReceiptTemplate.account_id)
        .limit(limit)
        .offset(offset)
    )
    templates = list(result.scalars().all())

    return ReceiptTemplateListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[_to_response(t) for t in templates],
    )
