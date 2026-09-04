"""Auth schemas."""

import re

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.user import UserResponse

_UPPERCASE_PATTERN = re.compile(r"[A-Z]")
_SPECIAL_CHAR_PATTERN = re.compile(r"[^a-zA-Z0-9]")

_PASSWORD_COMPLEXITY_MESSAGE = (
    "Password must contain at least one uppercase letter and one special character"
)


def _validate_password_complexity(value: str) -> str:
    """Shared by every schema field that sets a NEW password (register,
    password-reset confirm) — never applied to LoginRequest.password,
    which only ever checks an existing password against its hash."""
    if not _UPPERCASE_PATTERN.search(value) or not _SPECIAL_CHAR_PATTERN.search(value):
        raise ValueError(_PASSWORD_COMPLEXITY_MESSAGE)
    return value


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)

    @field_validator("password")
    @classmethod
    def password_complexity(cls, value: str) -> str:
        return _validate_password_complexity(value)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RegisterResponse(UserResponse):
    """Register returns safe user data only — never password or hash."""


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_complexity(cls, value: str) -> str:
        return _validate_password_complexity(value)
