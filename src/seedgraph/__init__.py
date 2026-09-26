"""seedgraph — referentially-consistent graph seeding for SQLAlchemy models.

Declare a shape, get a coherent object graph: written to the session, every FK
column verified against the key of the row it points at.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

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

__version__ = "0.1.1"

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
    objects = build_graph(model, shape, generators=generators, overrides=overrides, state=state, parents=parents)
    repair = UniqueRepair(objects, FieldGenerator(generators, overrides, state))
    while queries := repair.queries():
        repair.reject({column: taken_values(session, column, values) for column, values in queries})
    session.add_all(objects)
    session.flush()
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
    objects = build_graph(model, shape, generators=generators, overrides=overrides, state=state, parents=parents)
    repair = UniqueRepair(objects, FieldGenerator(generators, overrides, state))
    while queries := repair.queries():
        repair.reject({column: await taken_values_async(session, column, values) for column, values in queries})
    session.add_all(objects)
    await session.flush()
    verify_graph(objects)
    return Graph(objects, model.metadata)
