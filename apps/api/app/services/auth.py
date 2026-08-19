"""Auth service — registration, authentication, token issuance."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.repositories.user import UserRepository
from app.schemas.auth import RegisterRequest


class DuplicateEmailError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class AuthService:
    def __init__(self, db_session: AsyncSession):
        self.users = UserRepository(db_session)

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
