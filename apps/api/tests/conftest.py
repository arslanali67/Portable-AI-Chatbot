"""Shared test fixtures.

The app engine pools connections per event loop; TestClient runs requests on
its own loop while async tests run on the pytest-asyncio session loop. Reusing
pooled connections across loops breaks on Windows (event loop closed). Tests
therefore use a NullPool test engine — every session gets a fresh connection on
the active loop, and the `get_db` dependency is overridden to use it.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.database import get_db
from app.main import app

test_engine = create_async_engine(settings.database_url, poolclass=NullPool)

TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)


async def override_get_db():
    async with TestSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="session")
def db_session_factory():
    return TestSessionLocal
