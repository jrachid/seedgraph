"""pytest plugin: a fresh sqlite session and a seed callable, served without configuration.

Every fixture carries the ``seedgraph_`` prefix, so it never shadows a project's own ``session``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from seedgraph import Graph, seed, seed_async
from seedgraph.generators import GeneratorMap, OverrideMap

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["seedgraph_agraph", "seedgraph_asession", "seedgraph_graph", "seedgraph_session"]


@pytest.fixture()
def seedgraph_session() -> Iterator[Session]:
    """Serve a fresh in-memory sqlite Session with foreign keys enforced."""
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enforce_fk(dbapi_conn: Any, _: Any) -> None:
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    with Session(engine) as fresh:
        yield fresh
    engine.dispose()


@pytest.fixture()
def seedgraph_graph(seedgraph_session: Session) -> Callable[..., Graph]:
    """Serve a seed callable on the fresh session; tables are created on demand."""

    def make(
        model: type[Any],
        /,
        generators: GeneratorMap | None = None,
        overrides: OverrideMap | None = None,
        parents: Sequence[Any] = (),
        **shape: int,
    ) -> Graph:
        model.metadata.create_all(seedgraph_session.get_bind(), checkfirst=True)
        return seed(seedgraph_session, model, generators=generators, overrides=overrides, parents=parents, **shape)

    return make


@pytest.fixture()
async def seedgraph_asession() -> AsyncIterator[AsyncSession]:
    """Serve a fresh in-memory aiosqlite AsyncSession with foreign keys enforced."""
    # Imported here: sqlalchemy.ext.asyncio needs greenlet, which only the async extra installs.
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    engine = create_async_engine("sqlite+aiosqlite://")

    @event.listens_for(engine.sync_engine, "connect")
    def enforce_fk(dbapi_conn: Any, _: Any) -> None:
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    async with AsyncSession(engine) as fresh:
        yield fresh
    await engine.dispose()


@pytest.fixture()
async def seedgraph_agraph(seedgraph_asession: AsyncSession) -> Callable[..., Any]:
    """Serve an awaited seed callable on the fresh async session; tables on demand."""

    async def make(
        model: type[Any],
        /,
        generators: GeneratorMap | None = None,
        overrides: OverrideMap | None = None,
        parents: Sequence[Any] = (),
        **shape: int,
    ) -> Graph:
        await seedgraph_asession.run_sync(
            lambda sync_session: model.metadata.create_all(sync_session.get_bind(), checkfirst=True)
        )
        return await seed_async(
            seedgraph_asession, model, generators=generators, overrides=overrides, parents=parents, **shape
        )

    return make
