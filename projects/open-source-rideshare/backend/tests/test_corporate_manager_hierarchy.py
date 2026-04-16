"""Tests for the Corporate Manager Hierarchy feature.

Schema tests (sync):
  1.  RelationshipType — both values defined
  2.  ManagerRelationshipCreate — valid direct relationship
  3.  ManagerRelationshipCreate — valid dotted_line relationship
  4.  ManagerRelationshipCreate — notes max_length enforced
  5.  ManagerRelationshipUpdate — all optional fields
  6.  ManagerRelationshipResponse — from_attributes
  7.  ManagerRelationshipListResponse — wraps list and total
  8.  ReportingChainResponse — empty chain
  9.  ReportingChainResponse — chain with entries
  10. OrgSummaryResponse — all fields present

Service tests (async, mocked DB):
  11. create_relationship — direct success
  12. create_relationship — replaces existing active direct manager
  13. create_relationship — dotted_line success
  14. create_relationship — self-manager raises 400
  15. create_relationship — duplicate dotted_line raises 409
  16. create_relationship — cycle detection raises 409
  17. create_relationship — no cycle when no upstream manager
  18. get_relationship — returns row
  19. get_relationship — not found raises 404
  20. get_relationship — wrong account raises 404
  21. update_relationship — updates notes
  22. update_relationship — updates is_active
  23. update_relationship — not found raises 404
  24. remove_relationship — deletes row
  25. remove_relationship — not found raises 404
  26. list_relationships — returns all for account
  27. list_relationships — filtered by relationship_type
  28. list_relationships — filtered by is_active=False
  29. get_managers — returns managers for employee (active only)
  30. get_managers — empty list when no managers
  31. get_direct_reports — returns direct reports only
  32. get_direct_reports — empty list when no reports
  33. get_all_reports — includes dotted-line reports
  34. get_reporting_chain — returns ordered chain
  35. get_reporting_chain — empty when no direct manager
  36. get_reporting_chain — stops at max_depth
  37. get_org_summary — correct counts
  38. get_org_summary — top_level_managers excludes subordinates
  39. list_all_relationships_platform — returns all across accounts

API layer tests:
  40. POST /corporate/accounts/{id}/manager-relationships — 201 admin
  41. GET  /corporate/accounts/{id}/manager-relationships — 200 admin
  42. GET  /corporate/accounts/{id}/manager-relationships/{id} — 200 admin
  43. GET  /corporate/accounts/{id}/manager-relationships/{id} — 404 propagated
  44. PUT  /corporate/accounts/{id}/manager-relationships/{id} — 200 admin
  45. DELETE /corporate/accounts/{id}/manager-relationships/{id} — 204 admin
  46. GET  /corporate/accounts/{id}/members/{id}/managers — 200 admin
  47. GET  /corporate/accounts/{id}/members/{id}/direct-reports — 200 admin
  48. GET  /corporate/accounts/{id}/members/{id}/reporting-chain — 200 admin
  49. GET  /corporate/accounts/{id}/org-summary — 200 admin
  50. GET  /corporate/accounts/me/managers — 200 member
  51. GET  /corporate/accounts/me/managers — 404 not a member
  52. GET  /corporate/accounts/me/reporting-chain — 200 member
  53. GET  /corporate/accounts/me/direct-reports — 200 member
  54. GET  /admin/corporate/manager-relationships — 200 platform-admin
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate_manager_hierarchy import CorporateManagerRelationship
from app.schemas.corporate_manager_hierarchy import (
    ManagerRelationshipCreate,
    ManagerRelationshipListResponse,
    ManagerRelationshipResponse,
    ManagerRelationshipUpdate,
    OrgSummaryResponse,
    RelationshipType,
    ReportingChainEntry,
    ReportingChainResponse,
)
from app.services.corporate_manager_hierarchy import (
    create_relationship,
    get_all_reports,
    get_direct_reports,
    get_managers,
    get_org_summary,
    get_relationship,
    get_reporting_chain,
    list_all_relationships_platform,
    list_relationships,
    remove_relationship,
    update_relationship,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)

ACCOUNT_ID = 10
ADMIN_ID = 99
EMPLOYEE_MEMBER_ID = 20
MANAGER_MEMBER_ID = 30
ANOTHER_MEMBER_ID = 40
REL_ID = 1


def _make_rel(
    rel_id: int = REL_ID,
    account_id: int = ACCOUNT_ID,
    employee_member_id: int = EMPLOYEE_MEMBER_ID,
    manager_member_id: int = MANAGER_MEMBER_ID,
    relationship_type: str = "direct",
    notes: str | None = None,
    is_active: bool = True,
    created_by_id: int | None = ADMIN_ID,
) -> CorporateManagerRelationship:
    r = CorporateManagerRelationship()
    r.id = rel_id
    r.account_id = account_id
    r.employee_member_id = employee_member_id
    r.manager_member_id = manager_member_id
    r.relationship_type = relationship_type
    r.notes = notes
    r.is_active = is_active
    r.created_by_id = created_by_id
    r.created_at = _NOW
    r.updated_at = _NOW
    return r


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_relationship_type_values():
    assert RelationshipType.direct == "direct"
    assert RelationshipType.dotted_line == "dotted_line"


def test_manager_relationship_create_direct():
    obj = ManagerRelationshipCreate(
        employee_member_id=1,
        manager_member_id=2,
    )
    assert obj.relationship_type == RelationshipType.direct
    assert obj.notes is None


def test_manager_relationship_create_dotted_line():
    obj = ManagerRelationshipCreate(
        employee_member_id=1,
        manager_member_id=2,
        relationship_type=RelationshipType.dotted_line,
        notes="Matrix reporting",
    )
    assert obj.relationship_type == RelationshipType.dotted_line
    assert obj.notes == "Matrix reporting"


def test_manager_relationship_create_notes_max_length():
    with pytest.raises(ValidationError):
        ManagerRelationshipCreate(
            employee_member_id=1,
            manager_member_id=2,
            notes="x" * 301,
        )


def test_manager_relationship_update_all_optional():
    obj = ManagerRelationshipUpdate()
    assert obj.notes is None
    assert obj.is_active is None


def test_manager_relationship_response_from_attributes():
    row = _make_rel(notes="Test note")
    resp = ManagerRelationshipResponse.model_validate(row)
    assert resp.id == REL_ID
    assert resp.account_id == ACCOUNT_ID
    assert resp.employee_member_id == EMPLOYEE_MEMBER_ID
    assert resp.manager_member_id == MANAGER_MEMBER_ID
    assert resp.relationship_type == RelationshipType.direct
    assert resp.notes == "Test note"
    assert resp.is_active is True


def test_manager_relationship_list_response():
    row = _make_rel()
    resp = ManagerRelationshipResponse.model_validate(row)
    list_resp = ManagerRelationshipListResponse(relationships=[resp], total=1)
    assert list_resp.total == 1
    assert len(list_resp.relationships) == 1


def test_reporting_chain_response_empty():
    resp = ReportingChainResponse(employee_member_id=5, chain=[])
    assert resp.employee_member_id == 5
    assert resp.chain == []


def test_reporting_chain_response_with_entries():
    entry = ReportingChainEntry(
        member_id=MANAGER_MEMBER_ID,
        relationship_type=RelationshipType.direct,
        depth=0,
    )
    resp = ReportingChainResponse(employee_member_id=EMPLOYEE_MEMBER_ID, chain=[entry])
    assert len(resp.chain) == 1
    assert resp.chain[0].depth == 0


def test_org_summary_response_fields():
    summary = OrgSummaryResponse(
        account_id=ACCOUNT_ID,
        total_active_relationships=5,
        direct_relationships=3,
        dotted_line_relationships=2,
        members_with_direct_manager=3,
        members_who_are_managers=2,
        top_level_managers=[MANAGER_MEMBER_ID],
    )
    assert summary.total_active_relationships == 5
    assert summary.top_level_managers == [MANAGER_MEMBER_ID]


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_relationship_direct_success():
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        MagicMock(scalar_one_or_none=lambda: None),  # cycle check query
        MagicMock(scalar_one_or_none=lambda: None),  # existing direct check
    ])
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock(side_effect=lambda r: setattr(r, "id", REL_ID) or
                           setattr(r, "created_at", _NOW) or
                           setattr(r, "updated_at", _NOW))

    data = ManagerRelationshipCreate(
        employee_member_id=EMPLOYEE_MEMBER_ID,
        manager_member_id=MANAGER_MEMBER_ID,
    )
    result = await create_relationship(db, ACCOUNT_ID, data, created_by_id=ADMIN_ID)
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_relationship_replaces_existing_direct_manager():
    existing = _make_rel(rel_id=99, is_active=True)

    db = AsyncMock()
    # cycle check returns None (no cycle)
    cycle_result = MagicMock()
    cycle_result.scalar_one_or_none = MagicMock(return_value=None)
    # existing direct manager found
    existing_result = MagicMock()
    existing_result.scalar_one_or_none = MagicMock(return_value=existing)

    db.execute = AsyncMock(side_effect=[cycle_result, existing_result])
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock(side_effect=lambda r: setattr(r, "id", REL_ID) or
                           setattr(r, "created_at", _NOW) or
                           setattr(r, "updated_at", _NOW))

    data = ManagerRelationshipCreate(
        employee_member_id=EMPLOYEE_MEMBER_ID,
        manager_member_id=ANOTHER_MEMBER_ID,
    )
    await create_relationship(db, ACCOUNT_ID, data, created_by_id=ADMIN_ID)
    # existing relationship should be deactivated
    assert existing.is_active is False
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_relationship_dotted_line_success():
    db = AsyncMock()
    # cycle check: no cycle
    cycle_result = MagicMock(scalar_one_or_none=lambda: None)
    # duplicate check: no existing
    dup_result = MagicMock(scalar_one_or_none=lambda: None)
    db.execute = AsyncMock(side_effect=[cycle_result, dup_result])
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock(side_effect=lambda r: setattr(r, "id", REL_ID) or
                           setattr(r, "created_at", _NOW) or
                           setattr(r, "updated_at", _NOW))

    data = ManagerRelationshipCreate(
        employee_member_id=EMPLOYEE_MEMBER_ID,
        manager_member_id=MANAGER_MEMBER_ID,
        relationship_type=RelationshipType.dotted_line,
    )
    await create_relationship(db, ACCOUNT_ID, data, created_by_id=ADMIN_ID)
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_create_relationship_self_manager_raises_400():
    db = AsyncMock()
    data = ManagerRelationshipCreate(
        employee_member_id=EMPLOYEE_MEMBER_ID,
        manager_member_id=EMPLOYEE_MEMBER_ID,
    )
    with pytest.raises(HTTPException) as exc:
        await create_relationship(db, ACCOUNT_ID, data, created_by_id=ADMIN_ID)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_relationship_duplicate_dotted_line_raises_409():
    existing = _make_rel(relationship_type="dotted_line")
    db = AsyncMock()
    cycle_result = MagicMock(scalar_one_or_none=lambda: None)
    dup_result = MagicMock(scalar_one_or_none=lambda: existing)
    db.execute = AsyncMock(side_effect=[cycle_result, dup_result])

    data = ManagerRelationshipCreate(
        employee_member_id=EMPLOYEE_MEMBER_ID,
        manager_member_id=MANAGER_MEMBER_ID,
        relationship_type=RelationshipType.dotted_line,
    )
    with pytest.raises(HTTPException) as exc:
        await create_relationship(db, ACCOUNT_ID, data, created_by_id=ADMIN_ID)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_create_relationship_cycle_raises_409():
    """Manager's direct manager chain reaches the employee — cycle detected."""
    # Cycle: EMPLOYEE -> MANAGER, but MANAGER already has EMPLOYEE as manager
    # So when we check MANAGER's chain, it returns EMPLOYEE
    db = AsyncMock()
    cycle_result = MagicMock()
    cycle_result.scalar_one_or_none = MagicMock(return_value=EMPLOYEE_MEMBER_ID)
    db.execute = AsyncMock(return_value=cycle_result)

    data = ManagerRelationshipCreate(
        employee_member_id=EMPLOYEE_MEMBER_ID,
        manager_member_id=MANAGER_MEMBER_ID,
    )
    with pytest.raises(HTTPException) as exc:
        await create_relationship(db, ACCOUNT_ID, data, created_by_id=ADMIN_ID)
    assert exc.value.status_code == 409
    assert "cycle" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_create_relationship_no_cycle_when_no_upstream():
    """No cycle when manager has no direct manager themselves."""
    db = AsyncMock()
    # Cycle walk returns None immediately — no upstream manager
    cycle_result = MagicMock(scalar_one_or_none=lambda: None)
    existing_result = MagicMock(scalar_one_or_none=lambda: None)
    db.execute = AsyncMock(side_effect=[cycle_result, existing_result])
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock(side_effect=lambda r: setattr(r, "id", REL_ID) or
                           setattr(r, "created_at", _NOW) or
                           setattr(r, "updated_at", _NOW))

    data = ManagerRelationshipCreate(
        employee_member_id=EMPLOYEE_MEMBER_ID,
        manager_member_id=MANAGER_MEMBER_ID,
    )
    result = await create_relationship(db, ACCOUNT_ID, data, created_by_id=ADMIN_ID)
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_get_relationship_returns_row():
    row = _make_rel()
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=row)
    db.execute = AsyncMock(return_value=result)

    resp = await get_relationship(db, ACCOUNT_ID, REL_ID)
    assert resp.id == REL_ID
    assert resp.account_id == ACCOUNT_ID


@pytest.mark.asyncio
async def test_get_relationship_not_found_raises_404():
    db = AsyncMock()
    result = MagicMock(scalar_one_or_none=lambda: None)
    db.execute = AsyncMock(return_value=result)

    with pytest.raises(HTTPException) as exc:
        await get_relationship(db, ACCOUNT_ID, 9999)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_relationship_wrong_account_raises_404():
    db = AsyncMock()
    result = MagicMock(scalar_one_or_none=lambda: None)
    db.execute = AsyncMock(return_value=result)

    with pytest.raises(HTTPException) as exc:
        await get_relationship(db, account_id=999, relationship_id=REL_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_relationship_notes():
    row = _make_rel()
    db = AsyncMock()
    result = MagicMock(scalar_one_or_none=lambda: row)
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    data = ManagerRelationshipUpdate(notes="Updated note")
    resp = await update_relationship(db, ACCOUNT_ID, REL_ID, data)
    assert row.notes == "Updated note"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_relationship_is_active():
    row = _make_rel(is_active=True)
    db = AsyncMock()
    result = MagicMock(scalar_one_or_none=lambda: row)
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    data = ManagerRelationshipUpdate(is_active=False)
    await update_relationship(db, ACCOUNT_ID, REL_ID, data)
    assert row.is_active is False


@pytest.mark.asyncio
async def test_update_relationship_not_found_raises_404():
    db = AsyncMock()
    result = MagicMock(scalar_one_or_none=lambda: None)
    db.execute = AsyncMock(return_value=result)

    with pytest.raises(HTTPException) as exc:
        await update_relationship(db, ACCOUNT_ID, 9999, ManagerRelationshipUpdate())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_remove_relationship_success():
    row = _make_rel()
    db = AsyncMock()
    result = MagicMock(scalar_one_or_none=lambda: row)
    db.execute = AsyncMock(return_value=result)
    db.delete = AsyncMock()
    db.commit = AsyncMock()

    await remove_relationship(db, ACCOUNT_ID, REL_ID)
    db.delete.assert_awaited_once_with(row)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_relationship_not_found_raises_404():
    db = AsyncMock()
    result = MagicMock(scalar_one_or_none=lambda: None)
    db.execute = AsyncMock(return_value=result)

    with pytest.raises(HTTPException) as exc:
        await remove_relationship(db, ACCOUNT_ID, 9999)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_relationships_returns_all():
    rows = [_make_rel(rel_id=1), _make_rel(rel_id=2)]
    db = AsyncMock()
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=rows)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    db.execute = AsyncMock(return_value=result)

    resp = await list_relationships(db, ACCOUNT_ID)
    assert len(resp) == 2


@pytest.mark.asyncio
async def test_list_relationships_filtered_by_type():
    rows = [_make_rel(relationship_type="dotted_line")]
    db = AsyncMock()
    scalars = MagicMock(all=MagicMock(return_value=rows))
    result = MagicMock(scalars=MagicMock(return_value=scalars))
    db.execute = AsyncMock(return_value=result)

    resp = await list_relationships(
        db, ACCOUNT_ID, relationship_type=RelationshipType.dotted_line
    )
    assert len(resp) == 1
    assert resp[0].relationship_type == RelationshipType.dotted_line


@pytest.mark.asyncio
async def test_list_relationships_filtered_by_inactive():
    rows = [_make_rel(is_active=False)]
    db = AsyncMock()
    scalars = MagicMock(all=MagicMock(return_value=rows))
    result = MagicMock(scalars=MagicMock(return_value=scalars))
    db.execute = AsyncMock(return_value=result)

    resp = await list_relationships(db, ACCOUNT_ID, is_active=False)
    assert len(resp) == 1
    assert resp[0].is_active is False


@pytest.mark.asyncio
async def test_get_managers_returns_active_managers():
    rows = [_make_rel(), _make_rel(rel_id=2, relationship_type="dotted_line")]
    db = AsyncMock()
    scalars = MagicMock(all=MagicMock(return_value=rows))
    result = MagicMock(scalars=MagicMock(return_value=scalars))
    db.execute = AsyncMock(return_value=result)

    resp = await get_managers(db, ACCOUNT_ID, EMPLOYEE_MEMBER_ID)
    assert len(resp) == 2


@pytest.mark.asyncio
async def test_get_managers_empty_when_none():
    db = AsyncMock()
    scalars = MagicMock(all=MagicMock(return_value=[]))
    result = MagicMock(scalars=MagicMock(return_value=scalars))
    db.execute = AsyncMock(return_value=result)

    resp = await get_managers(db, ACCOUNT_ID, EMPLOYEE_MEMBER_ID)
    assert resp == []


@pytest.mark.asyncio
async def test_get_direct_reports_returns_direct_only():
    rows = [_make_rel(employee_member_id=EMPLOYEE_MEMBER_ID, manager_member_id=MANAGER_MEMBER_ID)]
    db = AsyncMock()
    scalars = MagicMock(all=MagicMock(return_value=rows))
    result = MagicMock(scalars=MagicMock(return_value=scalars))
    db.execute = AsyncMock(return_value=result)

    resp = await get_direct_reports(db, ACCOUNT_ID, MANAGER_MEMBER_ID)
    assert len(resp) == 1
    assert resp[0].manager_member_id == MANAGER_MEMBER_ID


@pytest.mark.asyncio
async def test_get_direct_reports_empty():
    db = AsyncMock()
    scalars = MagicMock(all=MagicMock(return_value=[]))
    result = MagicMock(scalars=MagicMock(return_value=scalars))
    db.execute = AsyncMock(return_value=result)

    resp = await get_direct_reports(db, ACCOUNT_ID, MANAGER_MEMBER_ID)
    assert resp == []


@pytest.mark.asyncio
async def test_get_all_reports_includes_dotted_line():
    rows = [
        _make_rel(relationship_type="direct"),
        _make_rel(rel_id=2, relationship_type="dotted_line"),
    ]
    db = AsyncMock()
    scalars = MagicMock(all=MagicMock(return_value=rows))
    result = MagicMock(scalars=MagicMock(return_value=scalars))
    db.execute = AsyncMock(return_value=result)

    resp = await get_all_reports(db, ACCOUNT_ID, MANAGER_MEMBER_ID)
    assert len(resp) == 2


@pytest.mark.asyncio
async def test_get_reporting_chain_returns_ordered_chain():
    """Employee has one direct manager."""
    mgr_rel = _make_rel(
        employee_member_id=EMPLOYEE_MEMBER_ID, manager_member_id=MANAGER_MEMBER_ID
    )

    call_count = 0

    async def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: return mgr_rel (employee -> manager)
            r = MagicMock(scalar_one_or_none=lambda: mgr_rel)
            return r
        else:
            # Second call: manager has no direct manager — chain ends
            r = MagicMock(scalar_one_or_none=lambda: None)
            return r

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=side_effect)

    resp = await get_reporting_chain(db, ACCOUNT_ID, EMPLOYEE_MEMBER_ID)
    assert resp.employee_member_id == EMPLOYEE_MEMBER_ID
    assert len(resp.chain) == 1
    assert resp.chain[0].member_id == MANAGER_MEMBER_ID
    assert resp.chain[0].depth == 0


@pytest.mark.asyncio
async def test_get_reporting_chain_empty_when_no_manager():
    db = AsyncMock()
    result = MagicMock(scalar_one_or_none=lambda: None)
    db.execute = AsyncMock(return_value=result)

    resp = await get_reporting_chain(db, ACCOUNT_ID, EMPLOYEE_MEMBER_ID)
    assert resp.chain == []


@pytest.mark.asyncio
async def test_get_reporting_chain_respects_max_depth():
    """Chain is artificially long; max_depth=2 truncates at 2 entries."""
    # Build an infinite chain: A -> B -> C -> ... (all return the same mgr_rel)
    # The chain will stop at max_depth=2
    call_count = 0
    members = [10, 20, 30, 40]  # A, B, C, D

    async def side_effect(*args, **kwargs):
        nonlocal call_count
        idx = call_count
        call_count += 1
        if idx < len(members) - 1:
            row = MagicMock()
            row.manager_member_id = members[idx + 1]
            row.relationship_type = "direct"
            r = MagicMock(scalar_one_or_none=lambda row=row: row)
            return r
        r = MagicMock(scalar_one_or_none=lambda: None)
        return r

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=side_effect)

    resp = await get_reporting_chain(db, ACCOUNT_ID, members[0], max_depth=2)
    assert len(resp.chain) == 2  # truncated at max_depth=2


@pytest.mark.asyncio
async def test_get_org_summary_correct_counts():
    rows = [
        _make_rel(
            rel_id=1,
            employee_member_id=EMPLOYEE_MEMBER_ID,
            manager_member_id=MANAGER_MEMBER_ID,
            relationship_type="direct",
        ),
        _make_rel(
            rel_id=2,
            employee_member_id=ANOTHER_MEMBER_ID,
            manager_member_id=MANAGER_MEMBER_ID,
            relationship_type="direct",
        ),
        _make_rel(
            rel_id=3,
            employee_member_id=EMPLOYEE_MEMBER_ID,
            manager_member_id=ANOTHER_MEMBER_ID,
            relationship_type="dotted_line",
        ),
    ]
    db = AsyncMock()
    scalars = MagicMock(all=MagicMock(return_value=rows))
    result = MagicMock(scalars=MagicMock(return_value=scalars))
    db.execute = AsyncMock(return_value=result)

    summary = await get_org_summary(db, ACCOUNT_ID)
    assert summary.total_active_relationships == 3
    assert summary.direct_relationships == 2
    assert summary.dotted_line_relationships == 1
    # EMPLOYEE_MEMBER_ID and ANOTHER_MEMBER_ID have direct managers
    assert summary.members_with_direct_manager == 2
    # Managers: MANAGER_MEMBER_ID and ANOTHER_MEMBER_ID
    assert summary.members_who_are_managers == 2


@pytest.mark.asyncio
async def test_get_org_summary_top_level_excludes_subordinates():
    """Top-level managers are managers who don't appear as employees in direct links."""
    rows = [
        _make_rel(
            rel_id=1,
            employee_member_id=EMPLOYEE_MEMBER_ID,
            manager_member_id=MANAGER_MEMBER_ID,
            relationship_type="direct",
        ),
    ]
    db = AsyncMock()
    scalars = MagicMock(all=MagicMock(return_value=rows))
    result = MagicMock(scalars=MagicMock(return_value=scalars))
    db.execute = AsyncMock(return_value=result)

    summary = await get_org_summary(db, ACCOUNT_ID)
    # MANAGER_MEMBER_ID manages others and is not subordinate in any direct link
    assert MANAGER_MEMBER_ID in summary.top_level_managers
    # EMPLOYEE_MEMBER_ID is subordinate, not a top-level manager
    assert EMPLOYEE_MEMBER_ID not in summary.top_level_managers


@pytest.mark.asyncio
async def test_list_all_relationships_platform():
    rows = [_make_rel(rel_id=i, account_id=i * 10) for i in range(1, 4)]
    db = AsyncMock()
    scalars = MagicMock(all=MagicMock(return_value=rows))
    result = MagicMock(scalars=MagicMock(return_value=scalars))
    db.execute = AsyncMock(return_value=result)

    resp = await list_all_relationships_platform(db)
    assert len(resp) == 3


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------

MEMBER_USER_ID = 55
MEMBER_DB_ID = 20  # corporate_account_members.id


def _make_admin():
    u = MagicMock()
    u.id = ADMIN_ID
    u.role = "admin"
    return u


def _make_member_user():
    u = MagicMock()
    u.id = MEMBER_USER_ID
    u.role = "rider"
    return u


def _make_account():
    a = MagicMock()
    a.id = ACCOUNT_ID
    return a


@pytest.mark.asyncio
async def test_api_admin_create_relationship_201():
    from app.api.v1.corporate_manager_hierarchy import admin_create_relationship

    row = _make_rel()
    resp = ManagerRelationshipResponse.model_validate(row)

    with patch(
        "app.api.v1.corporate_manager_hierarchy.create_relationship",
        new=AsyncMock(return_value=resp),
    ):
        result = await admin_create_relationship(
            account_id=ACCOUNT_ID,
            payload=ManagerRelationshipCreate(
                employee_member_id=EMPLOYEE_MEMBER_ID,
                manager_member_id=MANAGER_MEMBER_ID,
            ),
            admin=_make_admin(),
            db=AsyncMock(),
        )
    assert result.id == REL_ID


@pytest.mark.asyncio
async def test_api_admin_list_relationships_200():
    from app.api.v1.corporate_manager_hierarchy import admin_list_relationships

    rows = [ManagerRelationshipResponse.model_validate(_make_rel())]

    with patch(
        "app.api.v1.corporate_manager_hierarchy.list_relationships",
        new=AsyncMock(return_value=rows),
    ):
        result = await admin_list_relationships(
            account_id=ACCOUNT_ID,
            relationship_type=None,
            is_active=None,
            skip=0,
            limit=100,
            _admin=_make_admin(),
            db=AsyncMock(),
        )
    assert result.total == 1


@pytest.mark.asyncio
async def test_api_admin_get_relationship_200():
    from app.api.v1.corporate_manager_hierarchy import admin_get_relationship

    resp = ManagerRelationshipResponse.model_validate(_make_rel())

    with patch(
        "app.api.v1.corporate_manager_hierarchy.get_relationship",
        new=AsyncMock(return_value=resp),
    ):
        result = await admin_get_relationship(
            account_id=ACCOUNT_ID,
            rel_id=REL_ID,
            _admin=_make_admin(),
            db=AsyncMock(),
        )
    assert result.id == REL_ID


@pytest.mark.asyncio
async def test_api_admin_get_relationship_404_propagated():
    from app.api.v1.corporate_manager_hierarchy import admin_get_relationship

    with patch(
        "app.api.v1.corporate_manager_hierarchy.get_relationship",
        new=AsyncMock(
            side_effect=HTTPException(status_code=404, detail="Not found")
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await admin_get_relationship(
                account_id=ACCOUNT_ID,
                rel_id=9999,
                _admin=_make_admin(),
                db=AsyncMock(),
            )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_api_admin_update_relationship_200():
    from app.api.v1.corporate_manager_hierarchy import admin_update_relationship

    row = _make_rel(notes="Updated")
    resp = ManagerRelationshipResponse.model_validate(row)

    with patch(
        "app.api.v1.corporate_manager_hierarchy.update_relationship",
        new=AsyncMock(return_value=resp),
    ):
        result = await admin_update_relationship(
            account_id=ACCOUNT_ID,
            rel_id=REL_ID,
            payload=ManagerRelationshipUpdate(notes="Updated"),
            _admin=_make_admin(),
            db=AsyncMock(),
        )
    assert result.notes == "Updated"


@pytest.mark.asyncio
async def test_api_admin_delete_relationship_204():
    from app.api.v1.corporate_manager_hierarchy import admin_delete_relationship

    with patch(
        "app.api.v1.corporate_manager_hierarchy.remove_relationship",
        new=AsyncMock(return_value=None),
    ):
        await admin_delete_relationship(
            account_id=ACCOUNT_ID,
            rel_id=REL_ID,
            _admin=_make_admin(),
            db=AsyncMock(),
        )


@pytest.mark.asyncio
async def test_api_admin_get_member_managers_200():
    from app.api.v1.corporate_manager_hierarchy import admin_get_member_managers

    rows = [ManagerRelationshipResponse.model_validate(_make_rel())]

    with patch(
        "app.api.v1.corporate_manager_hierarchy.get_managers",
        new=AsyncMock(return_value=rows),
    ):
        result = await admin_get_member_managers(
            account_id=ACCOUNT_ID,
            member_id=EMPLOYEE_MEMBER_ID,
            is_active=True,
            _admin=_make_admin(),
            db=AsyncMock(),
        )
    assert result.total == 1


@pytest.mark.asyncio
async def test_api_admin_get_member_direct_reports_200():
    from app.api.v1.corporate_manager_hierarchy import admin_get_member_direct_reports

    rows = [ManagerRelationshipResponse.model_validate(_make_rel())]

    with patch(
        "app.api.v1.corporate_manager_hierarchy.get_direct_reports",
        new=AsyncMock(return_value=rows),
    ):
        result = await admin_get_member_direct_reports(
            account_id=ACCOUNT_ID,
            member_id=MANAGER_MEMBER_ID,
            include_dotted_line=False,
            _admin=_make_admin(),
            db=AsyncMock(),
        )
    assert result.total == 1


@pytest.mark.asyncio
async def test_api_admin_get_reporting_chain_200():
    from app.api.v1.corporate_manager_hierarchy import admin_get_reporting_chain

    chain_resp = ReportingChainResponse(
        employee_member_id=EMPLOYEE_MEMBER_ID,
        chain=[
            ReportingChainEntry(
                member_id=MANAGER_MEMBER_ID,
                relationship_type=RelationshipType.direct,
                depth=0,
            )
        ],
    )

    with patch(
        "app.api.v1.corporate_manager_hierarchy.get_reporting_chain",
        new=AsyncMock(return_value=chain_resp),
    ):
        result = await admin_get_reporting_chain(
            account_id=ACCOUNT_ID,
            member_id=EMPLOYEE_MEMBER_ID,
            _admin=_make_admin(),
            db=AsyncMock(),
        )
    assert len(result.chain) == 1


@pytest.mark.asyncio
async def test_api_admin_get_org_summary_200():
    from app.api.v1.corporate_manager_hierarchy import admin_get_org_summary

    summary = OrgSummaryResponse(
        account_id=ACCOUNT_ID,
        total_active_relationships=2,
        direct_relationships=1,
        dotted_line_relationships=1,
        members_with_direct_manager=1,
        members_who_are_managers=1,
        top_level_managers=[MANAGER_MEMBER_ID],
    )

    with patch(
        "app.api.v1.corporate_manager_hierarchy.get_org_summary",
        new=AsyncMock(return_value=summary),
    ):
        result = await admin_get_org_summary(
            account_id=ACCOUNT_ID,
            _admin=_make_admin(),
            db=AsyncMock(),
        )
    assert result.total_active_relationships == 2


@pytest.mark.asyncio
async def test_api_member_get_own_managers_200():
    from app.api.v1.corporate_manager_hierarchy import member_get_own_managers

    rows = [ManagerRelationshipResponse.model_validate(_make_rel())]

    with patch(
        "app.api.v1.corporate_manager_hierarchy._resolve_member_account",
        new=AsyncMock(return_value=ACCOUNT_ID),
    ), patch(
        "app.api.v1.corporate_manager_hierarchy._get_member_id_for_user",
        new=AsyncMock(return_value=MEMBER_DB_ID),
    ), patch(
        "app.api.v1.corporate_manager_hierarchy.get_managers",
        new=AsyncMock(return_value=rows),
    ):
        result = await member_get_own_managers(
            user=_make_member_user(),
            db=AsyncMock(),
        )
    assert result.total == 1


@pytest.mark.asyncio
async def test_api_member_get_own_managers_404_not_a_member():
    from app.api.v1.corporate_manager_hierarchy import member_get_own_managers

    with patch(
        "app.api.v1.corporate_manager_hierarchy._resolve_member_account",
        new=AsyncMock(
            side_effect=HTTPException(status_code=404, detail="Not a member")
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await member_get_own_managers(
                user=_make_member_user(),
                db=AsyncMock(),
            )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_api_member_get_reporting_chain_200():
    from app.api.v1.corporate_manager_hierarchy import member_get_own_reporting_chain

    chain_resp = ReportingChainResponse(
        employee_member_id=MEMBER_DB_ID,
        chain=[],
    )

    with patch(
        "app.api.v1.corporate_manager_hierarchy._resolve_member_account",
        new=AsyncMock(return_value=ACCOUNT_ID),
    ), patch(
        "app.api.v1.corporate_manager_hierarchy._get_member_id_for_user",
        new=AsyncMock(return_value=MEMBER_DB_ID),
    ), patch(
        "app.api.v1.corporate_manager_hierarchy.get_reporting_chain",
        new=AsyncMock(return_value=chain_resp),
    ):
        result = await member_get_own_reporting_chain(
            user=_make_member_user(),
            db=AsyncMock(),
        )
    assert result.employee_member_id == MEMBER_DB_ID


@pytest.mark.asyncio
async def test_api_member_get_direct_reports_200():
    from app.api.v1.corporate_manager_hierarchy import member_get_own_direct_reports

    rows = [ManagerRelationshipResponse.model_validate(_make_rel())]

    with patch(
        "app.api.v1.corporate_manager_hierarchy._resolve_member_account",
        new=AsyncMock(return_value=ACCOUNT_ID),
    ), patch(
        "app.api.v1.corporate_manager_hierarchy._get_member_id_for_user",
        new=AsyncMock(return_value=MEMBER_DB_ID),
    ), patch(
        "app.api.v1.corporate_manager_hierarchy.get_direct_reports",
        new=AsyncMock(return_value=rows),
    ):
        result = await member_get_own_direct_reports(
            user=_make_member_user(),
            db=AsyncMock(),
        )
    assert result.total == 1


@pytest.mark.asyncio
async def test_api_platform_admin_list_all_200():
    from app.api.v1.corporate_manager_hierarchy import platform_admin_list_all

    rows = [ManagerRelationshipResponse.model_validate(_make_rel())]

    with patch(
        "app.api.v1.corporate_manager_hierarchy.list_all_relationships_platform",
        new=AsyncMock(return_value=rows),
    ):
        result = await platform_admin_list_all(
            skip=0,
            limit=100,
            _admin=_make_admin(),
            db=AsyncMock(),
        )
    assert result.total == 1
