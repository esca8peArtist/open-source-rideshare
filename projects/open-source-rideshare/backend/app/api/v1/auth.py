from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.rate_limit import RateLimit
from app.config import settings
from app.db.database import get_db
from app.models.user import User, UserRole
from app.api.deps import get_current_user
from app.schemas.auth import (
    ChangePasswordRequest,
    ChangePhoneRequest,
    DeactivateAccountRequest,
    LoginRequest,
    RegisterRequest,
    RefreshRequest,
    TokenResponse,
    UserProfileResponse,
    UserProfileUpdate,
)
from app.services.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_login_limit = RateLimit(settings.rate_limit_login, settings.rate_limit_login_window, key_prefix="login")
_register_limit = RateLimit(settings.rate_limit_register, settings.rate_limit_register_window, key_prefix="register")


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(_register_limit)])
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.phone == req.phone))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Phone number already registered")

    # Resolve referrer if a referral code was provided
    referred_by: int | None = None
    if req.referral_code:
        referrer_result = await db.execute(
            select(User).where(User.referral_code == req.referral_code.upper().strip())
        )
        referrer = referrer_result.scalar_one_or_none()
        if referrer:
            referred_by = referrer.id

    from app.models.promo import generate_referral_code

    user = User(
        phone=req.phone,
        name=req.name,
        email=req.email,
        password_hash=hash_password(req.password),
        role=UserRole(req.role),
        referral_code=generate_referral_code(),
        referred_by=referred_by,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Create the new user's own referral promo code
    from app.services.promos import create_referral_promo
    await create_referral_promo(user.id, user.referral_code, db)
    await db.commit()

    return TokenResponse(
        access_token=create_access_token(user.id, user.role.value),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(_login_limit)])
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.phone == req.phone))
    user = result.scalar_one_or_none()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return TokenResponse(
        access_token=create_access_token(user.id, user.role.value),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_token(req.refresh_token)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    user_id = int(payload["sub"])
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found")

    return TokenResponse(
        access_token=create_access_token(user.id, user.role.value),
        refresh_token=create_refresh_token(user.id),
    )


@router.get("/me", response_model=UserProfileResponse)
async def get_me(user: User = Depends(get_current_user)):
    return user


@router.put("/me", response_model=UserProfileResponse)
async def update_me(
    req: UserProfileUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if req.name is not None:
        user.name = req.name
    if req.email is not None:
        user.email = req.email
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/me/change-password", status_code=status.HTTP_200_OK)
async def change_password(
    req: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change the authenticated user's password.

    Requires the current password for verification. The new password must be
    at least 8 characters. All existing sessions remain valid (stateless JWTs).
    """
    if not verify_password(req.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    user.password_hash = hash_password(req.new_password)
    await db.commit()
    return {"status": "password updated"}


@router.post("/me/deactivate", status_code=status.HTTP_200_OK)
async def deactivate_account(
    req: DeactivateAccountRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate the authenticated user's account (soft delete).

    Requires password confirmation. Rejected if the user has any active rides.
    Account can be reactivated by an admin.
    """
    if not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect password")

    from app.models.ride import Ride, RideStatus
    _ACTIVE = (
        RideStatus.REQUESTED,
        RideStatus.MATCHED,
        RideStatus.DRIVER_EN_ROUTE,
        RideStatus.ARRIVED,
        RideStatus.IN_PROGRESS,
    )
    active_result = await db.execute(
        select(Ride).where(
            (
                (Ride.rider_id == user.id) | (Ride.driver_id == user.id)
            ),
            Ride.status.in_(_ACTIVE),
        )
    )
    if active_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail="Cannot deactivate account while an active ride is in progress",
        )

    user.is_active = False
    await db.commit()
    return {"status": "account deactivated"}


@router.post("/me/change-phone", status_code=status.HTTP_200_OK)
async def change_phone(
    req: ChangePhoneRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change the authenticated user's phone number.

    Requires password confirmation. The new number must not already be registered.
    Sets phone_verified=False — the new number must be re-verified.
    """
    if not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect password")

    if req.new_phone == user.phone:
        raise HTTPException(status_code=400, detail="New phone number is the same as current")

    existing = await db.execute(select(User).where(User.phone == req.new_phone))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Phone number already in use")

    user.phone = req.new_phone
    user.phone_verified = False
    await db.commit()
    return {"status": "phone updated"}


@router.get("/me/data-export")
async def data_export(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GDPR data export — returns all personal data stored for the authenticated user."""
    from app.services.account_data_export import export_user_data
    return await export_user_data(user.id, db)
