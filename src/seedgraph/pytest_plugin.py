"""pytest plugin: a fresh sqlite session and a seed callable, served without configuration.

The package import is guarded: a failing import surfaces only on first fixture
use, never as a broken foreign pytest run.
"""

try:
    from seedgraph import seed as _seed
    from seedgraph import seed_async as _seed_async
    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001 — la garde : tout échec d'import ne doit pas casser les suites étrangères
    _seed = None
    _seed_async = None
    _IMPORT_ERROR = exc

from collections.abc import Callable, Iterator, Sequence
from typing import Any

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session

from seedgraph.generators import GeneratorMap, OverrideMap

__all__ = ["agraph", "asession", "graph", "session"]


def _fixture_error() -> RuntimeError:
    return RuntimeError(
        "seedgraph failed to import; its pytest fixtures raise on first use"
        " instead of failing every foreign pytest run"
    )


@pytest.fixture()
def session() -> Iterator[Session]:
    """Serve a fresh in-memory sqlite Session with foreign keys enforced."""
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enforce_fk(dbapi_conn: Any, _: Any) -> None:
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    with Session(engine) as fresh:
        yield fresh


@pytest.fixture()
def graph(session: Session) -> Callable[..., Any]:
    """Serve a seed callable on the fresh session; tables are created on demand."""

    def make(
        model: type[Any],
        /,
        generators: GeneratorMap | None = None,
        overrides: OverrideMap | None = None,
        parents: Sequence[Any] = (),
        **shape: int,
    ) -> Any:
        if _seed is None:
            raise _fixture_error() from _IMPORT_ERROR
        model.metadata.create_all(session.get_bind(), checkfirst=True)
        return _seed(session, model, generators=generators, overrides=overrides, parents=parents, **shape)

    return make


@pytest.fixture()
async def asession() -> Iterator[AsyncSession]:
    """Serve a fresh in-memory aiosqlite AsyncSession with foreign keys enforced."""
    engine = create_async_engine("sqlite+aiosqlite://")

    @event.listens_for(engine.sync_engine, "connect")
    def enforce_fk(dbapi_conn: Any, _: Any) -> None:
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    async with AsyncSession(engine) as fresh:
        yield fresh
    await engine.dispose()


@pytest.fixture()
async def agraph(asession: AsyncSession) -> Callable[..., Any]:
    """Serve an awaited seed callable on the fresh async session; tables on demand."""

    async def make(
        model: type[Any],
        /,
        generators: GeneratorMap | None = None,
        overrides: OverrideMap | None = None,
        parents: Sequence[Any] = (),
        **shape: int,
    ) -> Any:
        if _seed_async is None:
            raise _fixture_error() from _IMPORT_ERROR
        await asession.run_sync(
            lambda sync_session: model.metadata.create_all(sync_session.get_bind(), checkfirst=True)
        )
        return await _seed_async(asession, model, generators=generators, overrides=overrides, parents=parents, **shape)

    return make
