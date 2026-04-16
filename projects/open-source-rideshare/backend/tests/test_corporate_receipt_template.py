"""Tests for the Corporate Receipt Template feature.

Service layer (async, mocked DB):
  1.  get_or_create_receipt_template — creates default record when absent
  2.  get_or_create_receipt_template — returns existing template without creating
  3.  update_receipt_template — creates new template when none exists
  4.  update_receipt_template — partial update only writes supplied fields
  5.  update_receipt_template — custom_line_items serialised to dicts
  6.  update_receipt_template — sets updated_by_id on existing record
  7.  deactivate_receipt_template — 404 when no template found
  8.  deactivate_receipt_template — 409 when template already inactive
  9.  deactivate_receipt_template — success sets is_active=False
  10. delete_receipt_template — 404 when no template found
  11. delete_receipt_template — success deletes the row
  12. get_receipt_template_for_ride — returns active template
  13. get_receipt_template_for_ride — returns None when no active template
  14. list_all_receipt_templates — returns paginated list

Schema validation:
  15. ReceiptTemplateUpdate — all fields optional (empty payload valid)
  16. ReceiptTemplateUpdate — logo_url must start with http/https
  17. ReceiptTemplateUpdate — logo_url None is valid
  18. ReceiptTemplateUpdate — logo_url valid https URL accepted
  19. ReceiptTemplateUpdate — reference_prefix max 20 chars enforced
  20. ReceiptTemplateUpdate — reference_prefix exactly 20 chars accepted
  21. ReceiptTemplateUpdate — custom_line_items valid list of {label, value}
  22. ReceiptTemplateResponse — from_attributes construction
  23. ReceiptTemplateListResponse — valid construction with items

API layer (service functions patched):
  24. GET /corporate/accounts/me/receipt-template — 200 member can view
  25. GET /corporate/accounts/me/receipt-template — 404 when no corporate account
  26. PUT /corporate/accounts/me/receipt-template — 200 admin can update
  27. POST /corporate/accounts/me/receipt-template/deactivate — 200 admin can deactivate
  28. POST /corporate/accounts/me/receipt-template/deactivate — 409 already inactive
  29. DELETE /corporate/accounts/me/receipt-template — 204 admin can delete
  30. DELETE /corporate/accounts/me/receipt-template — 404 no template found
  31. GET /platform/corporate/receipt-templates — 200 platform-admin list
  32. GET /platform/corporate/accounts/{id}/receipt-template — 200 platform-admin get
  33. GET /platform/corporate/accounts/{id}/receipt-template — creates default if absent

Additional edge cases:
  34. update_receipt_template — update with all receipt fields in one call
  35. deactivate_receipt_template — updates updated_by_id on deactivation
  36. list_all_receipt_templates — respects limit and offset params
  37. get_or_create_receipt_template — default has show_driver_details=True
  38. get_or_create_receipt_template — default has show_route_map=True
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate_receipt_template import CorporateReceiptTemplate
from app.schemas.corporate_receipt_template import (
    CustomLineItem,
    ReceiptTemplateListResponse,
    ReceiptTemplateResponse,
    ReceiptTemplateUpdate,
)
from app.services.corporate_receipt_template import (
    deactivate_receipt_template,
    delete_receipt_template,
    get_or_create_receipt_template,
    get_receipt_template_for_ride,
    list_all_receipt_templates,
    update_receipt_template,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 10
ADMIN_ID = 2
USER_ID = 1

_SERVICE = "app.services.corporate_receipt_template"
_ROUTER = "app.api.v1.corporate_receipt_template"

_NOW = datetime(2026, 4, 16, 9, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_template(
    account_id: int = ACCOUNT_ID,
    company_name: str | None = "Acme Corp",
    logo_url: str | None = None,
    header_message: str | None = None,
    footer_message: str | None = None,
    reference_prefix: str | None = "ACME",
    show_driver_details: bool = True,
    show_route_map: bool = True,
    custom_line_items: list | None = None,
    is_active: bool = True,
    created_by_id: int | None = ADMIN_ID,
    updated_by_id: int | None = None,
) -> CorporateReceiptTemplate:
    """Build a minimal CorporateReceiptTemplate instance for testing."""
    t = CorporateReceiptTemplate()
    t.id = 1
    t.account_id = account_id
    t.company_name = company_name
    t.logo_url = logo_url
    t.header_message = header_message
    t.footer_message = footer_message
    t.reference_prefix = reference_prefix
    t.show_driver_details = show_driver_details
    t.show_route_map = show_route_map
    t.custom_line_items = custom_line_items
    t.is_active = is_active
    t.created_by_id = created_by_id
    t.updated_by_id = updated_by_id
    t.created_at = _NOW
    t.updated_at = _NOW
    return t


def _make_template_response(
    account_id: int = ACCOUNT_ID,
    company_name: str | None = "Acme Corp",
    is_active: bool = True,
) -> ReceiptTemplateResponse:
    return ReceiptTemplateResponse(
        id=1,
        account_id=account_id,
        company_name=company_name,
        logo_url=None,
        header_message=None,
        footer_message=None,
        reference_prefix="ACME",
        show_driver_details=True,
        show_route_map=True,
        custom_line_items=None,
        is_active=is_active,
        created_by_id=ADMIN_ID,
        updated_by_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _scalar_result(value) -> MagicMock:
    res = MagicMock()
    res.scalar_one_or_none.return_value = value
    return res


def _scalar_one_result(value) -> MagicMock:
    res = MagicMock()
    res.scalar_one.return_value = value
    return res


def _scalars_all_result(values: list) -> MagicMock:
    scalars = MagicMock()
    scalars.all.return_value = values
    res = MagicMock()
    res.scalars.return_value = scalars
    return res


def _mock_user(user_id: int = USER_ID) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    return u


# ---------------------------------------------------------------------------
# 1. get_or_create_receipt_template — creates default when absent
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_or_create_creates_default():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    added = []
    db.add = lambda x: added.append(x)

    async def _fake_refresh(obj):
        obj.id = 1
        obj.created_at = _NOW
        obj.updated_at = _NOW

    db.refresh = _fake_refresh

    result = await get_or_create_receipt_template(db, ACCOUNT_ID)

    assert len(added) == 1
    new_template = added[0]
    assert new_template.account_id == ACCOUNT_ID
    assert new_template.show_driver_details is True
    assert new_template.show_route_map is True
    assert new_template.is_active is True
    assert result.id == 1


# ---------------------------------------------------------------------------
# 2. get_or_create_receipt_template — returns existing without creating
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_or_create_returns_existing():
    db = AsyncMock()
    existing = _make_template(company_name="Globex", reference_prefix="GBX")
    db.execute.return_value = _scalar_result(existing)

    result = await get_or_create_receipt_template(db, ACCOUNT_ID)

    db.add.assert_not_called()
    assert result.company_name == "Globex"
    assert result.reference_prefix == "GBX"


# ---------------------------------------------------------------------------
# 3. update_receipt_template — creates new when none exists
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_creates_new_template():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    added = []
    db.add = lambda x: added.append(x)

    async def _fake_refresh(obj):
        obj.id = 1
        obj.created_at = _NOW
        obj.updated_at = _NOW

    db.refresh = _fake_refresh

    data = ReceiptTemplateUpdate(company_name="NewCo", reference_prefix="NCO")
    result = await update_receipt_template(db, ACCOUNT_ID, data, ADMIN_ID)

    assert len(added) == 1
    created = added[0]
    assert created.company_name == "NewCo"
    assert created.reference_prefix == "NCO"
    assert created.updated_by_id == ADMIN_ID


# ---------------------------------------------------------------------------
# 4. update_receipt_template — partial update only writes supplied fields
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_partial_fields_only():
    db = AsyncMock()
    existing = _make_template(
        company_name="OldCo",
        reference_prefix="OLD",
        show_route_map=True,
    )
    db.execute.return_value = _scalar_result(existing)
    db.refresh = AsyncMock()

    # Only update company_name; do NOT supply reference_prefix or show_route_map
    data = ReceiptTemplateUpdate(company_name="NewCo")
    await update_receipt_template(db, ACCOUNT_ID, data, ADMIN_ID)

    assert existing.company_name == "NewCo"
    assert existing.reference_prefix == "OLD"       # unchanged
    assert existing.show_route_map is True           # unchanged


# ---------------------------------------------------------------------------
# 5. update_receipt_template — custom_line_items serialised to dicts
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_custom_line_items_serialised():
    db = AsyncMock()
    existing = _make_template()
    db.execute.return_value = _scalar_result(existing)
    db.refresh = AsyncMock()

    data = ReceiptTemplateUpdate(
        custom_line_items=[CustomLineItem(label="Project", value="PROJ-007")]
    )
    await update_receipt_template(db, ACCOUNT_ID, data, ADMIN_ID)

    # Stored as plain dicts, not Pydantic objects
    assert isinstance(existing.custom_line_items[0], dict)
    assert existing.custom_line_items[0] == {"label": "Project", "value": "PROJ-007"}


# ---------------------------------------------------------------------------
# 6. update_receipt_template — sets updated_by_id on existing record
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_sets_updated_by_id():
    db = AsyncMock()
    existing = _make_template(updated_by_id=None)
    db.execute.return_value = _scalar_result(existing)
    db.refresh = AsyncMock()

    data = ReceiptTemplateUpdate(footer_message="Submit to expenses@acme.com")
    await update_receipt_template(db, ACCOUNT_ID, data, ADMIN_ID)

    assert existing.updated_by_id == ADMIN_ID
    assert existing.footer_message == "Submit to expenses@acme.com"


# ---------------------------------------------------------------------------
# 7. deactivate_receipt_template — 404 when no template found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_deactivate_404_when_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc:
        await deactivate_receipt_template(db, ACCOUNT_ID, ADMIN_ID)
    assert exc.value.status_code == 404
    assert "No receipt template found" in exc.value.detail


# ---------------------------------------------------------------------------
# 8. deactivate_receipt_template — 409 when already inactive
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_deactivate_409_when_already_inactive():
    db = AsyncMock()
    existing = _make_template(is_active=False)
    db.execute.return_value = _scalar_result(existing)

    with pytest.raises(HTTPException) as exc:
        await deactivate_receipt_template(db, ACCOUNT_ID, ADMIN_ID)
    assert exc.value.status_code == 409
    assert "already inactive" in exc.value.detail


# ---------------------------------------------------------------------------
# 9. deactivate_receipt_template — success sets is_active=False
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_deactivate_success():
    db = AsyncMock()
    existing = _make_template(is_active=True)
    db.execute.return_value = _scalar_result(existing)
    db.refresh = AsyncMock()

    result = await deactivate_receipt_template(db, ACCOUNT_ID, ADMIN_ID)

    assert existing.is_active is False
    assert existing.updated_by_id == ADMIN_ID


# ---------------------------------------------------------------------------
# 10. delete_receipt_template — 404 when no template found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delete_404_when_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc:
        await delete_receipt_template(db, ACCOUNT_ID)
    assert exc.value.status_code == 404
    assert "No receipt template found" in exc.value.detail


# ---------------------------------------------------------------------------
# 11. delete_receipt_template — success deletes the row
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delete_success():
    db = AsyncMock()
    existing = _make_template()
    db.execute.return_value = _scalar_result(existing)

    deleted = []
    db.delete = AsyncMock(side_effect=lambda x: deleted.append(x))

    await delete_receipt_template(db, ACCOUNT_ID)

    assert len(deleted) == 1
    assert deleted[0] is existing


# ---------------------------------------------------------------------------
# 12. get_receipt_template_for_ride — returns active template
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_for_ride_returns_active_template():
    db = AsyncMock()
    existing = _make_template(is_active=True)
    db.execute.return_value = _scalar_result(existing)

    result = await get_receipt_template_for_ride(db, ACCOUNT_ID)

    assert result is not None
    assert result.account_id == ACCOUNT_ID
    assert result.is_active is True


# ---------------------------------------------------------------------------
# 13. get_receipt_template_for_ride — returns None when no active template
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_for_ride_returns_none_when_no_active():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    result = await get_receipt_template_for_ride(db, ACCOUNT_ID)

    assert result is None


# ---------------------------------------------------------------------------
# 14. list_all_receipt_templates — returns paginated list
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_all_receipt_templates():
    db = AsyncMock()
    templates = [_make_template(account_id=10), _make_template(account_id=11)]
    templates[1].id = 2
    templates[1].account_id = 11

    db.execute.side_effect = [
        _scalar_one_result(2),       # COUNT query
        _scalars_all_result(templates),  # SELECT query
    ]

    result = await list_all_receipt_templates(db, limit=50, offset=0)

    assert result.total == 2
    assert result.limit == 50
    assert result.offset == 0
    assert len(result.items) == 2


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def test_receipt_template_update_all_optional():
    """15. ReceiptTemplateUpdate — all fields optional."""
    u = ReceiptTemplateUpdate()
    assert u.company_name is None
    assert u.logo_url is None
    assert u.reference_prefix is None
    assert u.show_driver_details is None
    assert u.show_route_map is None
    assert u.custom_line_items is None
    assert u.is_active is None


def test_receipt_template_update_logo_url_invalid():
    """16. logo_url must start with http:// or https://."""
    with pytest.raises(ValidationError):
        ReceiptTemplateUpdate(logo_url="ftp://images.example.com/logo.png")

    with pytest.raises(ValidationError):
        ReceiptTemplateUpdate(logo_url="not-a-url")


def test_receipt_template_update_logo_url_none_valid():
    """17. logo_url of None is valid (clears the field)."""
    u = ReceiptTemplateUpdate(logo_url=None)
    assert u.logo_url is None


def test_receipt_template_update_logo_url_valid_https():
    """18. logo_url with https:// is accepted."""
    u = ReceiptTemplateUpdate(logo_url="https://cdn.acme.com/logo.png")
    assert u.logo_url == "https://cdn.acme.com/logo.png"


def test_receipt_template_update_reference_prefix_too_long():
    """19. reference_prefix must not exceed 20 characters."""
    with pytest.raises(ValidationError):
        ReceiptTemplateUpdate(reference_prefix="A" * 21)


def test_receipt_template_update_reference_prefix_max_length():
    """20. reference_prefix of exactly 20 characters is accepted."""
    u = ReceiptTemplateUpdate(reference_prefix="A" * 20)
    assert len(u.reference_prefix) == 20


def test_receipt_template_update_custom_line_items_valid():
    """21. custom_line_items accepts a list of {label, value} objects."""
    u = ReceiptTemplateUpdate(
        custom_line_items=[
            CustomLineItem(label="Project Code", value="PROJ-001"),
            CustomLineItem(label="Cost Centre", value="CC-42"),
        ]
    )
    assert len(u.custom_line_items) == 2
    assert u.custom_line_items[0].label == "Project Code"
    assert u.custom_line_items[1].value == "CC-42"


def test_receipt_template_response_from_attributes():
    """22. ReceiptTemplateResponse — constructed from keyword arguments."""
    resp = _make_template_response(company_name="Acme Corp")
    assert resp.account_id == ACCOUNT_ID
    assert resp.company_name == "Acme Corp"
    assert resp.show_driver_details is True
    assert resp.is_active is True
    assert isinstance(resp.created_at, datetime)


def test_receipt_template_list_response_valid():
    """23. ReceiptTemplateListResponse — valid with items."""
    item = _make_template_response()
    lst = ReceiptTemplateListResponse(
        total=1,
        limit=50,
        offset=0,
        items=[item],
    )
    assert lst.total == 1
    assert len(lst.items) == 1
    assert lst.items[0].account_id == ACCOUNT_ID


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_get_my_receipt_template_200():
    """24. GET /corporate/accounts/me/receipt-template — 200 member can view."""
    from app.api.v1.corporate_receipt_template import get_my_receipt_template

    user = _mock_user()
    db = AsyncMock()
    mock_resp = _make_template_response()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}.get_or_create_receipt_template",
            new=AsyncMock(return_value=mock_resp),
        ),
    ):
        result = await get_my_receipt_template(user=user, db=db)

    assert result.account_id == ACCOUNT_ID
    assert result.is_active is True


@pytest.mark.asyncio
async def test_api_get_my_receipt_template_404_no_account():
    """25. GET /corporate/accounts/me/receipt-template — 404 when no corporate account."""
    from app.api.v1.corporate_receipt_template import get_my_receipt_template

    user = _mock_user()
    db = AsyncMock()

    with patch(
        f"{_ROUTER}._resolve_account_id",
        new=AsyncMock(
            side_effect=HTTPException(status_code=404, detail="No account")
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await get_my_receipt_template(user=user, db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_api_update_my_receipt_template_200():
    """26. PUT /corporate/accounts/me/receipt-template — 200 admin can update."""
    from app.api.v1.corporate_receipt_template import update_my_receipt_template

    user = _mock_user(ADMIN_ID)
    db = AsyncMock()
    payload = ReceiptTemplateUpdate(
        company_name="Acme Corp",
        reference_prefix="ACME",
        footer_message="Submit within 30 days.",
    )
    mock_resp = _make_template_response(company_name="Acme Corp")

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}.update_receipt_template",
            new=AsyncMock(return_value=mock_resp),
        ),
    ):
        result = await update_my_receipt_template(
            payload=payload, user=user, db=db
        )

    assert result.company_name == "Acme Corp"
    assert result.account_id == ACCOUNT_ID


@pytest.mark.asyncio
async def test_api_deactivate_my_receipt_template_200():
    """27. POST /corporate/accounts/me/receipt-template/deactivate — 200."""
    from app.api.v1.corporate_receipt_template import deactivate_my_receipt_template

    user = _mock_user(ADMIN_ID)
    db = AsyncMock()
    mock_resp = _make_template_response(is_active=False)

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}.deactivate_receipt_template",
            new=AsyncMock(return_value=mock_resp),
        ),
    ):
        result = await deactivate_my_receipt_template(user=user, db=db)

    assert result.is_active is False


@pytest.mark.asyncio
async def test_api_deactivate_409_already_inactive():
    """28. POST /corporate/accounts/me/receipt-template/deactivate — 409."""
    from app.api.v1.corporate_receipt_template import deactivate_my_receipt_template

    user = _mock_user(ADMIN_ID)
    db = AsyncMock()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}.deactivate_receipt_template",
            new=AsyncMock(
                side_effect=HTTPException(
                    status_code=409, detail="Receipt template is already inactive."
                )
            ),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await deactivate_my_receipt_template(user=user, db=db)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_api_delete_my_receipt_template_204():
    """29. DELETE /corporate/accounts/me/receipt-template — 204 success."""
    from app.api.v1.corporate_receipt_template import delete_my_receipt_template

    user = _mock_user(ADMIN_ID)
    db = AsyncMock()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}.delete_receipt_template",
            new=AsyncMock(return_value=None),
        ),
    ):
        result = await delete_my_receipt_template(user=user, db=db)

    # 204 No Content — function returns None
    assert result is None


@pytest.mark.asyncio
async def test_api_delete_my_receipt_template_404():
    """30. DELETE /corporate/accounts/me/receipt-template — 404 no template."""
    from app.api.v1.corporate_receipt_template import delete_my_receipt_template

    user = _mock_user(ADMIN_ID)
    db = AsyncMock()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}.delete_receipt_template",
            new=AsyncMock(
                side_effect=HTTPException(
                    status_code=404, detail="No receipt template found for this account."
                )
            ),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await delete_my_receipt_template(user=user, db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_api_admin_list_receipt_templates_200():
    """31. GET /platform/corporate/receipt-templates — 200 platform-admin list."""
    from app.api.v1.corporate_receipt_template import admin_list_receipt_templates

    admin = _mock_user(ADMIN_ID)
    db = AsyncMock()
    mock_resp = ReceiptTemplateListResponse(
        total=1,
        limit=50,
        offset=0,
        items=[_make_template_response()],
    )

    with patch(
        f"{_ROUTER}.list_all_receipt_templates",
        new=AsyncMock(return_value=mock_resp),
    ):
        result = await admin_list_receipt_templates(
            limit=50, offset=0, _admin=admin, db=db
        )

    assert result.total == 1
    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_api_admin_get_receipt_template_200():
    """32. GET /platform/corporate/accounts/{id}/receipt-template — 200."""
    from app.api.v1.corporate_receipt_template import admin_get_receipt_template

    admin = _mock_user(ADMIN_ID)
    db = AsyncMock()
    mock_resp = _make_template_response(account_id=ACCOUNT_ID)

    with patch(
        f"{_ROUTER}.get_or_create_receipt_template",
        new=AsyncMock(return_value=mock_resp),
    ):
        result = await admin_get_receipt_template(
            account_id=ACCOUNT_ID, _admin=admin, db=db
        )

    assert result.account_id == ACCOUNT_ID


@pytest.mark.asyncio
async def test_api_admin_get_receipt_template_creates_default():
    """33. GET /platform/corporate/accounts/{id}/receipt-template — creates default."""
    from app.api.v1.corporate_receipt_template import admin_get_receipt_template

    admin = _mock_user(ADMIN_ID)
    db = AsyncMock()
    # Simulate a newly created default (no company_name)
    mock_resp = ReceiptTemplateResponse(
        id=99,
        account_id=ACCOUNT_ID,
        company_name=None,
        logo_url=None,
        header_message=None,
        footer_message=None,
        reference_prefix=None,
        show_driver_details=True,
        show_route_map=True,
        custom_line_items=None,
        is_active=True,
        created_by_id=None,
        updated_by_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )

    with patch(
        f"{_ROUTER}.get_or_create_receipt_template",
        new=AsyncMock(return_value=mock_resp),
    ):
        result = await admin_get_receipt_template(
            account_id=ACCOUNT_ID, _admin=admin, db=db
        )

    assert result.company_name is None
    assert result.show_driver_details is True
    assert result.is_active is True


# ---------------------------------------------------------------------------
# Additional edge case tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_all_fields_at_once():
    """34. update_receipt_template — update with all receipt fields."""
    db = AsyncMock()
    existing = _make_template()
    db.execute.return_value = _scalar_result(existing)
    db.refresh = AsyncMock()

    data = ReceiptTemplateUpdate(
        company_name="FullCo",
        logo_url="https://cdn.fullco.com/logo.png",
        header_message="Thank you for riding with FullCo",
        footer_message="Submit to finance@fullco.com",
        reference_prefix="FC",
        show_driver_details=False,
        show_route_map=False,
        custom_line_items=[CustomLineItem(label="Division", value="West")],
        is_active=True,
    )
    await update_receipt_template(db, ACCOUNT_ID, data, ADMIN_ID)

    assert existing.company_name == "FullCo"
    assert existing.logo_url == "https://cdn.fullco.com/logo.png"
    assert existing.header_message == "Thank you for riding with FullCo"
    assert existing.footer_message == "Submit to finance@fullco.com"
    assert existing.reference_prefix == "FC"
    assert existing.show_driver_details is False
    assert existing.show_route_map is False


@pytest.mark.anyio
async def test_deactivate_sets_updated_by_id():
    """35. deactivate_receipt_template — updates updated_by_id."""
    db = AsyncMock()
    existing = _make_template(is_active=True, updated_by_id=None)
    db.execute.return_value = _scalar_result(existing)
    db.refresh = AsyncMock()

    await deactivate_receipt_template(db, ACCOUNT_ID, ADMIN_ID)

    assert existing.updated_by_id == ADMIN_ID


@pytest.mark.anyio
async def test_list_all_respects_limit_and_offset():
    """36. list_all_receipt_templates — respects limit and offset params."""
    db = AsyncMock()
    db.execute.side_effect = [
        _scalar_one_result(100),
        _scalars_all_result([]),
    ]

    result = await list_all_receipt_templates(db, limit=10, offset=20)

    assert result.total == 100
    assert result.limit == 10
    assert result.offset == 20
    assert result.items == []


@pytest.mark.anyio
async def test_get_or_create_default_show_driver_details():
    """37. get_or_create_receipt_template — default has show_driver_details=True."""
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)
    added = []
    db.add = lambda x: added.append(x)

    async def _fake_refresh(obj):
        obj.id = 1
        obj.created_at = _NOW
        obj.updated_at = _NOW

    db.refresh = _fake_refresh

    await get_or_create_receipt_template(db, ACCOUNT_ID)

    assert len(added) == 1
    assert added[0].show_driver_details is True


@pytest.mark.anyio
async def test_get_or_create_default_show_route_map():
    """38. get_or_create_receipt_template — default has show_route_map=True."""
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)
    added = []
    db.add = lambda x: added.append(x)

    async def _fake_refresh(obj):
        obj.id = 1
        obj.created_at = _NOW
        obj.updated_at = _NOW

    db.refresh = _fake_refresh

    await get_or_create_receipt_template(db, ACCOUNT_ID)

    assert len(added) == 1
    assert added[0].show_route_map is True
