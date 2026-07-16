from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(min_length=6, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    token: str
    user: dict


class ProfileUpdateRequest(BaseModel):
    name: Optional[str] = None
    avatar_base64: Optional[str] = None
    phone: Optional[str] = None
    notify_channel: Optional[str] = None  # "email" | "whatsapp" | "both" | "none"


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=6, max_length=100)


class PushSubscribeRequest(BaseModel):
    endpoint: str
    p256dh: str
    auth: str


class PushUnsubscribeRequest(BaseModel):
    endpoint: str


class NotificationPrefItem(BaseModel):
    line_id: str
    enabled: bool
    start_time: Optional[str] = None  # formato "HH:MM"
    end_time: Optional[str] = None


class NotificationPrefsRequest(BaseModel):
    prefs: list[NotificationPrefItem]


class StatusOverrideRequest(BaseModel):
    line_id: str
    status: str  # normal | reduzida | parcial | paralisada
    detail: Optional[str] = None
