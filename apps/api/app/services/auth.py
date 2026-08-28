"""Auth service — registration, authentication, token issuance, refresh-token
rotation, logout, and password reset."""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    create_access_token,
    generate_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.models import User
from app.repositories.auth_token import PasswordResetTokenRepository, RefreshTokenRepository
from app.repositories.user import UserRepository
from app.schemas.auth import RegisterRequest

logger = logging.getLogger("portableai.auth")


class DuplicateEmailError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class RefreshTokenInvalidError(Exception):
    pass


class RefreshTokenReuseDetectedError(Exception):
    pass


class PasswordResetTokenInvalidError(Exception):
    pass


class AuthService:
    def __init__(self, db_session: AsyncSession):
        self.users = UserRepository(db_session)
        self.refresh_tokens = RefreshTokenRepository(db_session)
        self.reset_tokens = PasswordResetTokenRepository(db_session)

    async def register(self, payload: RegisterRequest) -> User:
        email = payload.email.lower()
        existing = await self.users.get_by_email(email)
        if existing is not None:
            raise DuplicateEmailError()

        user = await self.users.create(
            email=email,
            password_hash=hash_password(payload.password),
            full_name=payload.full_name,
        )
        try:
            await self.users.db.commit()
        except IntegrityError:
            await self.users.db.rollback()
            raise DuplicateEmailError()
        await self.users.db.refresh(user)
        return user

    async def authenticate(self, email: str, password: str) -> User:
        user = await self.users.get_by_email(email.lower())
        if (
            user is None
            or not user.is_active
            or not verify_password(password, user.password_hash)
        ):
            # Generic failure — inactive users are indistinguishable from bad
            # credentials, so the endpoint semantics stay enumeration-free.
            raise InvalidCredentialsError()
        return user

    def issue_token(self, user: User) -> str:
        return create_access_token(user.id)

    async def issue_refresh_token(self, user_id: int, family_id: str | None = None) -> str:
        """Create a new refresh token row and return the raw (unhashed)
        token. A fresh family_id is minted unless one is passed in (used
        by rotation, so every token descended from one login shares it)."""
        raw = generate_token()
        family = family_id or uuid.uuid4().hex
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=settings.refresh_token_expire_days
        )
        await self.refresh_tokens.create(
            user_id=user_id, family_id=family, token_hash=hash_token(raw), expires_at=expires_at
        )
        await self.refresh_tokens.db.commit()
        return raw

    async def rotate_refresh_token(self, raw_token: str) -> tuple[str, str]:
        """Validate + rotate a refresh token. Returns (new_access_token,
        new_raw_refresh_token). Raises RefreshTokenInvalidError for an
        unknown/expired/inactive-user token, or
        RefreshTokenReuseDetectedError (after revoking the whole family)
        if the presented token was already rotated out."""
        row = await self.refresh_tokens.get_by_hash(hash_token(raw_token))
        if row is None:
            raise RefreshTokenInvalidError()

        if row.revoked_at is not None:
            # Reuse of an already-rotated-out token is a theft signal —
            # kill every token descended from this login, not just this row.
            await self.refresh_tokens.revoke_family(row.family_id)
            await self.refresh_tokens.db.commit()
            raise RefreshTokenReuseDetectedError()

        if row.expires_at <= datetime.now(timezone.utc):
            raise RefreshTokenInvalidError()

        user = await self.users.get(row.user_id)
        if user is None or not user.is_active:
            raise RefreshTokenInvalidError()

        row.revoked_at = datetime.now(timezone.utc)
        new_raw = await self.issue_refresh_token(user.id, family_id=row.family_id)
        new_access = create_access_token(user.id)
        return new_access, new_raw

    async def logout(self, raw_token: str) -> None:
        """Best-effort: revoke the presented token if it's still valid.
        A missing/unknown/already-revoked token is not an error — the
        caller's goal (be logged out) is already satisfied either way."""
        row = await self.refresh_tokens.get_by_hash(hash_token(raw_token))
        if row is not None and row.revoked_at is None:
            row.revoked_at = datetime.now(timezone.utc)
            await self.refresh_tokens.db.commit()

    async def request_password_reset(self, email: str) -> None:
        """Enumeration-safe: does real work only if the account exists and
        is active, but the caller (router) always returns the same generic
        response either way."""
        user = await self.users.get_by_email(email.lower())
        if user is None or not user.is_active:
            return

        raw = generate_token()
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.password_reset_token_expire_minutes
        )
        await self.reset_tokens.create(
            user_id=user.id, token_hash=hash_token(raw), expires_at=expires_at
        )
        await self.reset_tokens.db.commit()

        reset_url = f"{settings.frontend_base_url}/reset-password?token={raw}"
        # DEV-STUB ONLY — no transactional email provider is configured yet
        # (see architecture.md "Refresh Token Rotation & Password Reset").
        # Logging a raw bearer token is a deliberate, temporary exception to
        # the "never log bearer credentials" policy and must not ship as-is
        # to a real production deployment with real user emails.
        logger.info("Password reset requested for user_id=%s: %s", user.id, reset_url)

    async def confirm_password_reset(self, raw_token: str, new_password: str) -> None:
        row = await self.reset_tokens.get_by_hash(hash_token(raw_token))
        if row is None or row.used_at is not None or row.expires_at <= datetime.now(timezone.utc):
            raise PasswordResetTokenInvalidError()

        user = await self.users.get(row.user_id)
        if user is None:
            raise PasswordResetTokenInvalidError()

        user.password_hash = hash_password(new_password)
        row.used_at = datetime.now(timezone.utc)
        # A reset invalidates any possibly-stolen sessions too.
        await self.refresh_tokens.revoke_all_for_user(user.id)
        await self.reset_tokens.db.commit()
