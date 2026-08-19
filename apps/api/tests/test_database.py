"""Database integration tests.

Require the project's Docker PostgreSQL: `docker compose up -d postgres`
(see infrastructure/docker-compose.yml) and a valid DATABASE_URL in .env.
Run with: pytest -m integration
"""

import pytest
from sqlalchemy import text

from app.core.database import AsyncSessionLocal

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_database_session_created() -> None:
    async with AsyncSessionLocal() as session:
        assert session is not None


@pytest.mark.asyncio
async def test_simple_query_works() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar_one() == 1


@pytest.mark.asyncio
async def test_postgresql_reachable() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT current_database()"))
        assert result.scalar_one() == "portableai"


@pytest.mark.asyncio
async def test_pgvector_extension_exists() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        )
        assert result.scalar_one() == "vector"
