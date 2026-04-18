import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CardBrand(str, enum.Enum):
    VISA = "visa"
    MASTERCARD = "mastercard"
    AMEX = "amex"
    DISCOVER = "discover"
    DINERS = "diners"
    JCB = "jcb"
    UNIONPAY = "unionpay"
    UNKNOWN = "unknown"


class RiderPaymentMethod(Base):
    __tablename__ = "rider_payment_methods"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    stripe_payment_method_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    card_brand: Mapped[str] = mapped_column(String(50), nullable=False)
    card_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    card_exp_month: Mapped[int] = mapped_column(Integer(), nullable=False)
    card_exp_year: Mapped[int] = mapped_column(Integer(), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean(), default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user = relationship("User", backref="payment_methods")
