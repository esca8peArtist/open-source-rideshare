"""Pydantic v2 schemas for Corporate Account Tags.

Platform admins label corporate accounts with short slugified tags for
internal classification and bulk filtering.

Public surface
--------------
TagAdd             — request body for adding a single tag.
TagBulkAdd         — request body for adding multiple tags in one call.
TagResponse        — full tag record returned by the API.
TagListResponse    — list of tags on an account.
TagSummaryResponse — platform-wide tag entry: tag name + number of accounts.
TagSummaryListResponse — list of tag summaries for the platform index.
AccountsByTagResponse  — list of account IDs that carry a given tag.
BulkAddResult      — result of a bulk-add operation.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Tag normalisation helper
# ---------------------------------------------------------------------------

_TAG_PATTERN = re.compile(r"[^a-z0-9-]")
_HYPHEN_RUN = re.compile(r"-{2,}")


def normalise_tag(raw: str) -> str:
    """Normalise a raw tag string.

    Steps:
      1. Strip leading/trailing whitespace.
      2. Lowercase.
      3. Replace spaces and underscores with hyphens.
      4. Remove any remaining non-alphanumeric non-hyphen characters.
      5. Collapse consecutive hyphens to one.
      6. Strip leading/trailing hyphens.
      7. Truncate to 50 characters.

    Raises:
        ValueError: When the result is empty.
    """
    s = raw.strip().lower()
    s = s.replace(" ", "-").replace("_", "-")
    s = _TAG_PATTERN.sub("", s)
    s = _HYPHEN_RUN.sub("-", s)
    s = s.strip("-")[:50]
    if not s:
        raise ValueError("Tag must contain at least one alphanumeric character.")
    return s


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class TagAdd(BaseModel):
    """Request body for adding a single tag to a corporate account.

    Attributes:
        tag: Raw tag string — normalised automatically (lowercase, hyphens
             only, max 50 chars).
    """

    tag: str = Field(..., min_length=1, max_length=80, description="Tag to add (normalised to slug)")

    @field_validator("tag")
    @classmethod
    def normalise(cls, v: str) -> str:
        return normalise_tag(v)


class TagBulkAdd(BaseModel):
    """Request body for adding multiple tags to a corporate account in one call.

    Attributes:
        tags: List of raw tag strings (1–20 tags per request).
    """

    tags: List[str] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Tags to add (each normalised individually; duplicates ignored)",
    )

    @field_validator("tags")
    @classmethod
    def normalise_all(cls, v: List[str]) -> List[str]:
        return [normalise_tag(t) for t in v]


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class TagResponse(BaseModel):
    """Full tag record returned by the API.

    Attributes:
        id:             Primary key.
        account_id:     Corporate account the tag belongs to.
        tag:            Normalised tag string.
        created_by_id:  User who added the tag (null if creator was deleted).
        created_at:     When the tag was added.
    """

    model_config = {"from_attributes": True}

    id: int
    account_id: int
    tag: str
    created_by_id: Optional[int]
    created_at: datetime


class TagListResponse(BaseModel):
    """List of tags on a corporate account.

    Attributes:
        tags:  Tag records, sorted alphabetically by tag string.
        total: Number of records.
    """

    tags: List[TagResponse]
    total: int


class TagSummaryResponse(BaseModel):
    """Platform-wide tag entry: tag name and the number of accounts carrying it.

    Attributes:
        tag:           Normalised tag string.
        account_count: Number of corporate accounts tagged with this value.
    """

    tag: str
    account_count: int


class TagSummaryListResponse(BaseModel):
    """Platform-wide tag index: all distinct tags with account counts.

    Attributes:
        tags:  Tag summaries, sorted by account_count descending.
        total: Number of distinct tags.
    """

    tags: List[TagSummaryResponse]
    total: int


class AccountsByTagResponse(BaseModel):
    """List of corporate account IDs that carry a specific tag.

    Attributes:
        tag:         The queried tag.
        account_ids: IDs of matching corporate accounts.
        total:       Number of matching accounts.
    """

    tag: str
    account_ids: List[int]
    total: int


class BulkAddResult(BaseModel):
    """Result of a bulk tag-add operation.

    Attributes:
        added:           Tags successfully added (were not present before).
        already_existed: Tags that were already on the account (skipped).
        tags:            Full tag records for the ``added`` tags.
    """

    added: List[str]
    already_existed: List[str]
    tags: List[TagResponse]
