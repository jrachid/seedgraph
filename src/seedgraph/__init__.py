"""seedgraph — referentially-consistent graph seeding for SQLAlchemy models.

Declare a shape, get a coherent object graph: written to the session, every FK
column verified against the key of the row it points at.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Session

from seedgraph.boundary import (
    UnattachedParentError,
    check_parents_attached,
    taken_values,
    taken_values_async,
)
from seedgraph.exceptions import SeedgraphError
from seedgraph.generators import (
    FieldGenerator,
    GeneratorMap,
    OverrideMap,
    UniqueValueExhaustedError,
    UnknownGeneratorColumnError,
    UnknownOverrideColumnError,
    UnsupportedPlaceholderError,
    generation_state,
)
from seedgraph.graph import Graph
from seedgraph.shape import (
    AmbiguousParentError,
    AmbiguousShapeKeyError,
    InvalidShapeCountError,
    MissingRequiredParentError,
    UnknownShapeKeyError,
    UnsupportedShapeDirectionError,
    build_graph,
)
from seedgraph.uniqueness import UniqueRepair
from seedgraph.verification import IncoherentGraphError, verify_graph

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__version__ = "0.1.2"

__all__ = [
    "AmbiguousParentError",
    "AmbiguousShapeKeyError",
    "Graph",
    "IncoherentGraphError",
    "InvalidShapeCountError",
    "MissingRequiredParentError",
    "SeedgraphError",
    "UnattachedParentError",
    "UniqueValueExhaustedError",
    "UnknownGeneratorColumnError",
    "UnknownOverrideColumnError",
    "UnknownShapeKeyError",
    "UnsupportedPlaceholderError",
    "UnsupportedShapeDirectionError",
    "__version__",
    "seed",
    "seed_async",
]


MAX_WRITE_ATTEMPTS = 5


def savepoints_commit(session: Session, model: type[DeclarativeBase]) -> bool:
    """Tell whether releasing a SAVEPOINT on this session's database commits everything written so far."""
    # pysqlite and aiosqlite open no transaction before a SAVEPOINT, so releasing it commits the session's work.
    return session.get_bind(model).dialect.name == "sqlite"


def repair_unique(session: Session, objects: Sequence[Any], generator: FieldGenerator) -> bool:
    """Regenerate the generated unique values the database already holds; tell whether any was taken."""
    repair = UniqueRepair(objects, generator)
    regenerated = False
    while queries := repair.queries():
        taken = {column: taken_values(session, column, values) for column, values in queries}
        regenerated = regenerated or any(taken.values())
        repair.reject(taken)
    return regenerated


async def repair_unique_async(session: AsyncSession, objects: Sequence[Any], generator: FieldGenerator) -> bool:
    """Twin of ``repair_unique`` on an AsyncSession."""
    repair = UniqueRepair(objects, generator)
    regenerated = False
    while queries := repair.queries():
        taken = {column: await taken_values_async(session, column, values) for column, values in queries}
        regenerated = regenerated or any(taken.values())
        repair.reject(taken)
    return regenerated


def write_through_savepoints(session: Session, build: Callable[[], list[Any]], generator: FieldGenerator) -> list[Any]:
    """Build and flush the graph in a SAVEPOINT, regenerating the unique values another session committed meanwhile."""
    objects: list[Any] | None = None
    for attempt in range(1, MAX_WRITE_ATTEMPTS + 1):
        try:
            # Opened before build() links the graph to its parents: opening a SAVEPOINT flushes the session.
            with session.begin_nested():
                if objects is None:
                    objects = build()
                session.add_all(objects)
                session.flush()
            return objects
        except IntegrityError:
            if objects is None or attempt == MAX_WRITE_ATTEMPTS or not repair_unique(session, objects, generator):
                raise
    raise AssertionError("unreachable")


async def write_through_savepoints_async(
    session: AsyncSession, build: Callable[[], Awaitable[list[Any]]], generator: FieldGenerator
) -> list[Any]:
    """Twin of ``write_through_savepoints`` on an AsyncSession."""
    objects: list[Any] | None = None
    for attempt in range(1, MAX_WRITE_ATTEMPTS + 1):
        try:
            async with session.begin_nested():
                if objects is None:
                    objects = await build()
                session.add_all(objects)
                await session.flush()
            return objects
        except IntegrityError:
            if (
                objects is None
                or attempt == MAX_WRITE_ATTEMPTS
                or not await repair_unique_async(session, objects, generator)
            ):
                raise
    raise AssertionError("unreachable")


def seed(
    session: Session,
    model: type[DeclarativeBase],
    /,
    generators: GeneratorMap | None = None,
    overrides: OverrideMap | None = None,
    parents: Sequence[Any] = (),
    **shape: int,
) -> Graph:
    """Seed a coherent object graph from the declared shape and return it.

    The graph is flushed, the database assigns its keys, and every FK column is
    verified against the row it points at. ``generators`` replaces how a column
    generates, ``overrides`` pins a value; both are keyed {Model: {"column": ...}}.
    ``parents`` are objects of the session that links of their type point at.
    Raises a ``SeedgraphError`` subclass on any bad declaration or broken link.
    """
    check_parents_attached(session, parents)
    # Flushed before the graph links to pending objects, so the unique checks see their rows.
    session.flush()
    state = generation_state(session.info)
    generator = FieldGenerator(generators, overrides, state)

    def build() -> list[Any]:
        objects = build_graph(model, shape, generators=generators, overrides=overrides, state=state, parents=parents)
        repair_unique(session, objects, generator)
        return objects

    if savepoints_commit(session, model):
        objects = build()
        session.add_all(objects)
        session.flush()
    else:
        objects = write_through_savepoints(session, build, generator)
    verify_graph(objects)
    return Graph(objects, model.metadata)


async def seed_async(
    session: AsyncSession,
    model: type[DeclarativeBase],
    /,
    generators: GeneratorMap | None = None,
    overrides: OverrideMap | None = None,
    parents: Sequence[Any] = (),
    **shape: int,
) -> Graph:
    """Twin of ``seed`` on an AsyncSession: same contract, the flush is awaited."""
    check_parents_attached(session.sync_session, parents)
    await session.flush()
    state = generation_state(session.sync_session.info)
    generator = FieldGenerator(generators, overrides, state)

    async def build() -> list[Any]:
        objects = build_graph(model, shape, generators=generators, overrides=overrides, state=state, parents=parents)
        await repair_unique_async(session, objects, generator)
        return objects

    if savepoints_commit(session.sync_session, model):
        objects = await build()
        session.add_all(objects)
        await session.flush()
    else:
        objects = await write_through_savepoints_async(session, build, generator)
    verify_graph(objects)
    return Graph(objects, model.metadata)
