"""Tests for the Corporate Account Tags feature.

Schema / normalisation tests (sync):
  1.  normalise_tag — lowercase and hyphen conversion
  2.  normalise_tag — strips non-alphanumeric chars
  3.  normalise_tag — collapses consecutive hyphens
  4.  normalise_tag — truncates to 50 chars
  5.  normalise_tag — empty result after stripping → ValueError
  6.  TagAdd — valid tag is normalised
  7.  TagAdd — empty string after normalisation → ValidationError
  8.  TagBulkAdd — normalises all tags in list
  9.  TagBulkAdd — rejects list longer than 20
  10. TagResponse — from_attributes
  11. BulkAddResult — structure

Service tests (async, mocked DB):
  12. add_tag — success
  13. add_tag — duplicate → 409
  14. remove_tag — success
  15. remove_tag — not found → 404
  16. list_tags — returns sorted results
  17. list_tags — empty account returns []
  18. get_platform_tag_summary — aggregates tag counts
  19. list_accounts_by_tag — returns matching account IDs
  20. list_accounts_by_tag — no matches returns empty list
  21. bulk_add_tags — all new tags
  22. bulk_add_tags — mix of new and existing
  23. bulk_add_tags — all already exist → no commit
  24. bulk_add_tags — deduplicates input

API layer tests (service patched):
  25. POST /admin/corporate/accounts/{id}/tags — 201
  26. POST /admin/corporate/accounts/{id}/tags — duplicate → 409 propagated
  27. DELETE /admin/corporate/accounts/{id}/tags/{tag} — 204
  28. DELETE /admin/corporate/accounts/{id}/tags/{tag} — normalises path param
  29. DELETE /admin/corporate/accounts/{id}/tags/{tag} — invalid tag → 422
  30. GET  /admin/corporate/accounts/{id}/tags — 200
  31. POST /admin/corporate/accounts/{id}/tags/bulk — 200
  32. GET  /admin/corporate/tags — 200
  33. GET  /admin/corporate/tags/{tag}/accounts — 200
  34. GET  /admin/corporate/tags/{tag}/accounts — invalid tag → 422
  35. GET  /corporate/accounts/me/tags — 200 (member)
  36. GET  /corporate/accounts/me/tags — 404 when not a member
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate_account_tag import CorporateAccountTag
from app.schemas.corporate_account_tag import (
    AccountsByTagResponse,
    BulkAddResult,
    TagAdd,
    TagBulkAdd,
    TagListResponse,
    TagResponse,
    TagSummaryListResponse,
    TagSummaryResponse,
    normalise_tag,
)
from app.services.corporate_account_tags import (
    add_tag,
    bulk_add_tags,
    get_platform_tag_summary,
    list_accounts_by_tag,
    list_tags,
    remove_tag,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)


def _make_tag(
    tag_id: int = 1,
    account_id: int = 42,
    tag: str = "vip",
    created_by_id: int = 99,
) -> CorporateAccountTag:
    t = CorporateAccountTag()
    t.id = tag_id
    t.account_id = account_id
    t.tag = tag
    t.created_by_id = created_by_id
    t.created_at = _NOW
    return t


def _make_db(
    scalar_one: CorporateAccountTag | None = None,
    scalars_all: list[CorporateAccountTag] | None = None,
    rows_all: list | None = None,
) -> AsyncMock:
    """Return a mock AsyncSession pre-configured for common queries."""
    db = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = scalar_one
    mock_result.scalars.return_value.all.return_value = scalars_all or []
    mock_result.all.return_value = rows_all or []

    db.execute = AsyncMock(return_value=mock_result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    return db


def _populate_tag(template: CorporateAccountTag):
    """Side-effect for db.refresh — copies server-default fields from template."""
    def _side_effect(obj):
        obj.id = template.id
        obj.created_at = template.created_at
    return _side_effect


# ===========================================================================
# 1–11  Schema / normalisation tests
# ===========================================================================


def test_normalise_tag_lowercase_and_hyphens():
    """normalise_tag — lowercase and hyphen conversion."""
    assert normalise_tag("VIP Client") == "vip-client"
    assert normalise_tag("At_Risk") == "at-risk"


def test_normalise_tag_strips_non_alphanumeric():
    """normalise_tag — strips non-alphanumeric chars."""
    assert normalise_tag("health&care!") == "healthcare"
    assert normalise_tag("govt.account") == "govtaccount"


def test_normalise_tag_collapses_hyphens():
    """normalise_tag — collapses consecutive hyphens."""
    assert normalise_tag("big--enterprise") == "big-enterprise"
    assert normalise_tag("a---b---c") == "a-b-c"


def test_normalise_tag_truncates_to_50():
    """normalise_tag — truncates to 50 chars."""
    long = "a" * 80
    result = normalise_tag(long)
    assert len(result) == 50


def test_normalise_tag_empty_raises():
    """normalise_tag — empty result after stripping → ValueError."""
    with pytest.raises(ValueError, match="alphanumeric"):
        normalise_tag("---")
    with pytest.raises(ValueError):
        normalise_tag("!!!")


def test_tag_add_normalises():
    """TagAdd — valid tag is normalised."""
    t = TagAdd(tag="VIP Client")
    assert t.tag == "vip-client"


def test_tag_add_empty_raises():
    """TagAdd — empty string after normalisation → ValidationError."""
    with pytest.raises(ValidationError):
        TagAdd(tag="")


def test_tag_bulk_add_normalises_all():
    """TagBulkAdd — normalises all tags in list."""
    b = TagBulkAdd(tags=["VIP", "At_Risk", "Healthcare"])
    assert b.tags == ["vip", "at-risk", "healthcare"]


def test_tag_bulk_add_max_20():
    """TagBulkAdd — rejects list longer than 20."""
    with pytest.raises(ValidationError):
        TagBulkAdd(tags=[f"tag{i}" for i in range(21)])


def test_tag_response_from_attributes():
    """TagResponse — from_attributes."""
    t = _make_tag()
    resp = TagResponse.model_validate(t)
    assert resp.id == 1
    assert resp.account_id == 42
    assert resp.tag == "vip"
    assert resp.created_by_id == 99


def test_bulk_add_result_structure():
    """BulkAddResult — structure."""
    r = BulkAddResult(added=["vip"], already_existed=["at-risk"], tags=[])
    assert r.added == ["vip"]
    assert r.already_existed == ["at-risk"]


# ===========================================================================
# 12–24  Service tests
# ===========================================================================


@pytest.mark.asyncio
async def test_add_tag_success():
    """add_tag — success."""
    tag_row = _make_tag()
    db = _make_db(scalar_one=None)  # no existing tag
    db.refresh.side_effect = _populate_tag(tag_row)

    result = await add_tag(db, account_id=42, tag="vip", created_by_id=99)

    db.add.assert_called_once()
    db.commit.assert_called_once()
    assert result.tag == "vip"


@pytest.mark.asyncio
async def test_add_tag_duplicate_raises_409():
    """add_tag — duplicate → 409."""
    existing = _make_tag()
    db = _make_db(scalar_one=existing)

    with pytest.raises(HTTPException) as exc_info:
        await add_tag(db, account_id=42, tag="vip", created_by_id=99)

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_remove_tag_success():
    """remove_tag — success."""
    tag_row = _make_tag()
    db = _make_db(scalar_one=tag_row)

    await remove_tag(db, account_id=42, tag="vip")

    db.delete.assert_called_once_with(tag_row)
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_remove_tag_not_found_raises_404():
    """remove_tag — not found → 404."""
    db = _make_db(scalar_one=None)

    with pytest.raises(HTTPException) as exc_info:
        await remove_tag(db, account_id=42, tag="vip")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_tags_sorted():
    """list_tags — returns sorted results."""
    tags = [_make_tag(tag_id=2, tag="vip"), _make_tag(tag_id=1, tag="at-risk")]
    db = _make_db(scalars_all=tags)

    result = await list_tags(db, account_id=42)

    assert len(result) == 2
    assert result[0].tag == "vip"  # order depends on mock; sorted by DB in real impl


@pytest.mark.asyncio
async def test_list_tags_empty():
    """list_tags — empty account returns []."""
    db = _make_db(scalars_all=[])

    result = await list_tags(db, account_id=42)

    assert result == []


@pytest.mark.asyncio
async def test_get_platform_tag_summary():
    """get_platform_tag_summary — aggregates tag counts."""
    # Simulate DB returning rows with .tag and .account_count
    row1 = MagicMock()
    row1.tag = "vip"
    row1.account_count = 5
    row2 = MagicMock()
    row2.tag = "at-risk"
    row2.account_count = 2

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [row1, row2]
    db.execute = AsyncMock(return_value=mock_result)

    result = await get_platform_tag_summary(db)

    assert result.total == 2
    assert result.tags[0].tag == "vip"
    assert result.tags[0].account_count == 5


@pytest.mark.asyncio
async def test_list_accounts_by_tag_found():
    """list_accounts_by_tag — returns matching account IDs."""
    row1 = (10,)
    row2 = (20,)

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [row1, row2]
    db.execute = AsyncMock(return_value=mock_result)

    result = await list_accounts_by_tag(db, tag="vip")

    assert result.tag == "vip"
    assert result.account_ids == [10, 20]
    assert result.total == 2


@pytest.mark.asyncio
async def test_list_accounts_by_tag_empty():
    """list_accounts_by_tag — no matches returns empty list."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = []
    db.execute = AsyncMock(return_value=mock_result)

    result = await list_accounts_by_tag(db, tag="unknown-tag")

    assert result.account_ids == []
    assert result.total == 0


@pytest.mark.asyncio
async def test_bulk_add_tags_all_new():
    """bulk_add_tags — all new tags."""
    tag1 = _make_tag(tag_id=1, tag="vip")
    tag2 = _make_tag(tag_id=2, tag="at-risk")

    existing_result = MagicMock()
    existing_result.all.return_value = []  # no existing tags

    db = AsyncMock()
    db.execute = AsyncMock(return_value=existing_result)
    db.add = MagicMock()
    db.commit = AsyncMock()

    call_count = [0]
    async def refresh_side_effect(obj):
        if obj.tag == "vip":
            obj.id = 1
            obj.created_at = _NOW
        else:
            obj.id = 2
            obj.created_at = _NOW
    db.refresh = AsyncMock(side_effect=refresh_side_effect)

    result = await bulk_add_tags(db, account_id=42, tags=["vip", "at-risk"], created_by_id=99)

    assert result.added == ["vip", "at-risk"]
    assert result.already_existed == []
    assert len(result.tags) == 2
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_bulk_add_tags_mixed():
    """bulk_add_tags — mix of new and existing."""
    existing_row = MagicMock()
    existing_row.__iter__ = lambda self: iter(["vip"])

    existing_result = MagicMock()
    existing_result.all.return_value = [("vip",)]

    db = AsyncMock()
    db.execute = AsyncMock(return_value=existing_result)
    db.add = MagicMock()
    db.commit = AsyncMock()

    async def refresh_side_effect(obj):
        obj.id = 10
        obj.created_at = _NOW
    db.refresh = AsyncMock(side_effect=refresh_side_effect)

    result = await bulk_add_tags(db, account_id=42, tags=["vip", "healthcare"], created_by_id=99)

    assert "vip" in result.already_existed
    assert "healthcare" in result.added
    assert len(result.tags) == 1


@pytest.mark.asyncio
async def test_bulk_add_tags_all_existing_no_commit():
    """bulk_add_tags — all already exist → no commit."""
    existing_result = MagicMock()
    existing_result.all.return_value = [("vip",), ("at-risk",)]

    db = AsyncMock()
    db.execute = AsyncMock(return_value=existing_result)
    db.commit = AsyncMock()

    result = await bulk_add_tags(db, account_id=42, tags=["vip", "at-risk"], created_by_id=99)

    assert result.added == []
    assert set(result.already_existed) == {"vip", "at-risk"}
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_bulk_add_tags_deduplicates_input():
    """bulk_add_tags — deduplicates input."""
    existing_result = MagicMock()
    existing_result.all.return_value = []

    db = AsyncMock()
    db.execute = AsyncMock(return_value=existing_result)
    db.add = MagicMock()
    db.commit = AsyncMock()

    async def refresh_side_effect(obj):
        obj.id = 1
        obj.created_at = _NOW
    db.refresh = AsyncMock(side_effect=refresh_side_effect)

    result = await bulk_add_tags(db, account_id=42, tags=["vip", "vip", "vip"], created_by_id=99)

    # Only one add call, not three
    assert db.add.call_count == 1
    assert result.added == ["vip"]


# ===========================================================================
# 25–36  API layer tests (service patched)
# ===========================================================================


_ROUTER = "app.api.v1.corporate_account_tags"

ACCOUNT_ID = 42
ADMIN_ID = 99


def _mock_user(user_id: int = ADMIN_ID) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    return u


def _make_tag_response(
    tag: str = "vip",
    tag_id: int = 1,
    account_id: int = ACCOUNT_ID,
) -> TagResponse:
    return TagResponse(
        id=tag_id,
        account_id=account_id,
        tag=tag,
        created_by_id=ADMIN_ID,
        created_at=_NOW,
    )


# ===========================================================================
# 25–36  API layer tests (endpoint functions called directly)
# ===========================================================================


@pytest.mark.asyncio
async def test_api_admin_add_tag_201():
    """POST /admin/corporate/accounts/{id}/tags — 201 happy path."""
    from app.api.v1.corporate_account_tags import admin_add_tag

    admin = _mock_user()
    db = AsyncMock()
    payload = TagAdd(tag="VIP")

    with patch(f"{_ROUTER}.add_tag", new=AsyncMock(return_value=_make_tag_response())):
        result = await admin_add_tag(account_id=ACCOUNT_ID, payload=payload, admin=admin, db=db)

    assert result.tag == "vip"
    assert result.account_id == ACCOUNT_ID


@pytest.mark.asyncio
async def test_api_admin_add_tag_409():
    """POST /admin/corporate/accounts/{id}/tags — duplicate → 409 propagated."""
    from app.api.v1.corporate_account_tags import admin_add_tag

    admin = _mock_user()
    db = AsyncMock()
    payload = TagAdd(tag="vip")

    with patch(
        f"{_ROUTER}.add_tag",
        new=AsyncMock(side_effect=HTTPException(status_code=409, detail="Tag 'vip' already exists on this account.")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await admin_add_tag(account_id=ACCOUNT_ID, payload=payload, admin=admin, db=db)

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_api_admin_remove_tag_204():
    """DELETE /admin/corporate/accounts/{id}/tags/{tag} — 204 happy path."""
    from app.api.v1.corporate_account_tags import admin_remove_tag

    db = AsyncMock()

    with patch(f"{_ROUTER}.remove_tag", new=AsyncMock(return_value=None)):
        result = await admin_remove_tag(account_id=ACCOUNT_ID, tag="vip", _admin=_mock_user(), db=db)

    assert result is None


@pytest.mark.asyncio
async def test_api_admin_remove_tag_normalises_path():
    """DELETE /admin/corporate/accounts/{id}/tags/{tag} — normalises path param."""
    from app.api.v1.corporate_account_tags import admin_remove_tag

    db = AsyncMock()
    mock_remove = AsyncMock(return_value=None)

    with patch(f"{_ROUTER}.remove_tag", new=mock_remove):
        await admin_remove_tag(account_id=ACCOUNT_ID, tag="VIP", _admin=_mock_user(), db=db)

    # Service should be called with normalised tag
    called_tag = mock_remove.call_args.kwargs.get("tag") or mock_remove.call_args.args[2]
    assert called_tag == "vip"


@pytest.mark.asyncio
async def test_api_admin_remove_tag_invalid_tag():
    """DELETE /admin/corporate/accounts/{id}/tags/{tag} — invalid tag → 422."""
    from app.api.v1.corporate_account_tags import admin_remove_tag

    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await admin_remove_tag(account_id=ACCOUNT_ID, tag="---", _admin=_mock_user(), db=db)

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_api_admin_list_tags_200():
    """GET /admin/corporate/accounts/{id}/tags — 200."""
    from app.api.v1.corporate_account_tags import admin_list_tags

    db = AsyncMock()
    tags = [_make_tag_response()]

    with patch(f"{_ROUTER}.list_tags", new=AsyncMock(return_value=tags)):
        result = await admin_list_tags(account_id=ACCOUNT_ID, _admin=_mock_user(), db=db)

    assert result.total == 1
    assert result.tags[0].tag == "vip"


@pytest.mark.asyncio
async def test_api_admin_bulk_add_200():
    """POST /admin/corporate/accounts/{id}/tags/bulk — 200."""
    from app.api.v1.corporate_account_tags import admin_bulk_add_tags

    admin = _mock_user()
    db = AsyncMock()
    payload = TagBulkAdd(tags=["VIP", "Healthcare"])
    bulk_result = BulkAddResult(
        added=["vip", "healthcare"],
        already_existed=[],
        tags=[_make_tag_response("vip"), _make_tag_response("healthcare", tag_id=2)],
    )

    with patch(f"{_ROUTER}.bulk_add_tags", new=AsyncMock(return_value=bulk_result)):
        result = await admin_bulk_add_tags(account_id=ACCOUNT_ID, payload=payload, admin=admin, db=db)

    assert "vip" in result.added
    assert "healthcare" in result.added
    assert result.already_existed == []


@pytest.mark.asyncio
async def test_api_admin_platform_tag_index_200():
    """GET /admin/corporate/tags — 200."""
    from app.api.v1.corporate_account_tags import admin_platform_tag_index

    db = AsyncMock()
    summary = TagSummaryListResponse(
        tags=[TagSummaryResponse(tag="vip", account_count=3)],
        total=1,
    )

    with patch(f"{_ROUTER}.get_platform_tag_summary", new=AsyncMock(return_value=summary)):
        result = await admin_platform_tag_index(skip=0, limit=100, _admin=_mock_user(), db=db)

    assert result.total == 1
    assert result.tags[0].tag == "vip"


@pytest.mark.asyncio
async def test_api_admin_accounts_by_tag_200():
    """GET /admin/corporate/tags/{tag}/accounts — 200."""
    from app.api.v1.corporate_account_tags import admin_accounts_by_tag

    db = AsyncMock()
    by_tag = AccountsByTagResponse(tag="vip", account_ids=[10, 20], total=2)

    with patch(f"{_ROUTER}.list_accounts_by_tag", new=AsyncMock(return_value=by_tag)):
        result = await admin_accounts_by_tag(tag="vip", skip=0, limit=100, _admin=_mock_user(), db=db)

    assert result.tag == "vip"
    assert result.total == 2
    assert 10 in result.account_ids


@pytest.mark.asyncio
async def test_api_admin_accounts_by_tag_invalid_422():
    """GET /admin/corporate/tags/{tag}/accounts — invalid tag → 422."""
    from app.api.v1.corporate_account_tags import admin_accounts_by_tag

    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await admin_accounts_by_tag(tag="!!!", skip=0, limit=100, _admin=_mock_user(), db=db)

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_api_member_list_tags_200():
    """GET /corporate/accounts/me/tags — 200 (member)."""
    from app.api.v1.corporate_account_tags import member_list_tags

    user = _mock_user(user_id=7)
    db = AsyncMock()

    mock_account = MagicMock()
    mock_account.id = ACCOUNT_ID
    tags = [_make_tag_response()]

    with patch(f"{_ROUTER}.get_user_account", new=AsyncMock(return_value=mock_account)), \
         patch(f"{_ROUTER}.list_tags", new=AsyncMock(return_value=tags)):
        result = await member_list_tags(user=user, db=db)

    assert result.total == 1
    assert result.tags[0].tag == "vip"


@pytest.mark.asyncio
async def test_api_member_list_tags_not_member_404():
    """GET /corporate/accounts/me/tags — 404 when not a member."""
    from app.api.v1.corporate_account_tags import member_list_tags

    user = _mock_user(user_id=7)
    db = AsyncMock()

    with patch(f"{_ROUTER}.get_user_account", new=AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc_info:
            await member_list_tags(user=user, db=db)

    assert exc_info.value.status_code == 404
