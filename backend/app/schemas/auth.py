from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    phone: str
    name: str
    password: str
    email: str | None = None
    role: str = "rider"
    referral_code: str | None = None  # Optional referral code from existing user


class LoginRequest(BaseModel):
    phone: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class PhoneVerifyRequest(BaseModel):
    phone: str
    code: str


class RefreshRequest(BaseModel):
    refresh_token: str


class UserProfileResponse(BaseModel):
    id: int
    phone: str
    email: str | None
    name: str
    role: str
    is_active: bool
    phone_verified: bool
    referral_code: str | None = None

    model_config = {"from_attributes": True}


class UserProfileUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
