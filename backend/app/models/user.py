import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class UserRole(str, enum.Enum):
    RIDER = "rider"
    DRIVER = "driver"
    ADMIN = "admin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.RIDER)
    is_active: Mapped[bool] = mapped_column(default=True)
    phone_verified: Mapped[bool] = mapped_column(default=False)
    referral_code: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True, index=True)
    referred_by: Mapped[int | None] = mapped_column(nullable=True)  # user_id of referrer
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
