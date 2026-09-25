from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str]:
    """Serve the psycopg URL of a disposable PostgreSQL, or skip when Docker does not answer."""
    try:
        from testcontainers.community.postgres import PostgresContainer

        container = PostgresContainer("postgres:16-alpine", driver="psycopg").start()
    except Exception as exc:  # noqa: BLE001 — sans Docker, les tests Postgres se sautent au lieu d'échouer
        pytest.skip(f"PostgreSQL container unavailable: {exc}")
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


@pytest.fixture(scope="session")
def pg_engine(pg_url: str) -> Iterator[Engine]:
    engine = create_engine(pg_url)
    yield engine
    engine.dispose()


def _reset_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))


@pytest.fixture()
def pg_session(pg_engine: Engine) -> Iterator[Session]:
    """Serve a Session on an emptied public schema; the test creates its own tables."""
    _reset_schema(pg_engine)
    with Session(pg_engine) as session:
        yield session


@pytest.fixture()
async def pg_asession(pg_url: str, pg_engine: Engine) -> AsyncIterator[AsyncSession]:
    """Twin of ``pg_session`` on asyncpg."""
    _reset_schema(pg_engine)
    engine = create_async_engine(pg_url.replace("+psycopg", "+asyncpg"))
    async with AsyncSession(engine) as session:
        yield session
    await engine.dispose()
