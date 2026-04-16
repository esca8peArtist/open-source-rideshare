"""Corporate Ride Satisfaction Survey models.

Enterprise admins create named surveys with configurable questions that
employees complete after corporate rides.  Admins can view aggregated
response analytics per question.

Models:
  CorporateRideSurvey
      — a named survey belonging to a corporate account
  CorporateRideSurveyResponse
      — a single employee's answers to one survey

Table names:
  corporate_ride_surveys
  corporate_ride_survey_responses
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateRideSurvey(Base):
    """A named satisfaction survey belonging to a corporate account.

    Admins define a list of questions (stored as JSON).  Each question has
    a type: ``rating``, ``text``, ``boolean``, or ``multiple_choice``.

    Attributes:
        id: UUID primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        title: Human-readable survey title, unique per account.
        description: Optional longer description.
        questions: JSON list of question objects
            ``{question_id, text, type, options}``.
        is_active: When False the survey is hidden from employees.
        valid_from: Optional start date — survey is not shown before this date.
        valid_until: Optional end date — survey is not shown after this date.
        created_by_id: FK to users (SET NULL) — admin who created the record.
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_ride_surveys"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "title",
            name="uq_corp_ride_survey_account_title",
        ),
        Index("ix_corp_ride_survey_account_id", "account_id"),
        Index("ix_corp_ride_survey_account_active", "account_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(String(150), nullable=False)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    questions: Mapped[list] = mapped_column(JSON, nullable=False)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ---- Relationships ----

    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )
    created_by = relationship("User", foreign_keys=[created_by_id], lazy="raise")
    responses = relationship(
        "CorporateRideSurveyResponse",
        back_populates="survey",
        lazy="raise",
        cascade="all, delete-orphan",
    )


class CorporateRideSurveyResponse(Base):
    """A single employee's answers to a corporate ride survey.

    ``account_id`` is denormalised for efficient platform-admin queries.
    Each ``(survey_id, member_id)`` pair is unique — members may only
    respond to a given survey once.

    Attributes:
        id: UUID primary key.
        survey_id: FK to CorporateRideSurvey (CASCADE delete).
        member_id: FK to corporate_account_members (SET NULL).
        account_id: Denormalised FK to corporate_accounts_v2 (CASCADE delete).
        ride_id: Optional FK to rides (SET NULL).
        responses: JSON list of answer objects ``{question_id, answer}``.
        submitted_at: UTC submission timestamp.
    """

    __tablename__ = "corporate_ride_survey_responses"
    __table_args__ = (
        UniqueConstraint(
            "survey_id",
            "member_id",
            name="uq_corp_ride_survey_response_survey_member",
        ),
        Index("ix_corp_ride_survey_resp_survey_id", "survey_id"),
        Index("ix_corp_ride_survey_resp_member_id", "member_id"),
        Index("ix_corp_ride_survey_resp_account_id", "account_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    survey_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("corporate_ride_surveys.id", ondelete="CASCADE"),
        nullable=False,
    )

    member_id: Mapped[int | None] = mapped_column(
        ForeignKey("corporate_account_members.id", ondelete="SET NULL"),
        nullable=True,
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    ride_id: Mapped[int | None] = mapped_column(
        ForeignKey("rides.id", ondelete="SET NULL"),
        nullable=True,
    )

    responses: Mapped[list] = mapped_column(JSON, nullable=False)

    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ---- Relationships ----

    survey = relationship(
        "CorporateRideSurvey",
        foreign_keys=[survey_id],
        back_populates="responses",
        lazy="raise",
    )
    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )
