"""seedgraph — referentially-consistent graph seeding for SQLAlchemy models.

Declare a shape, get a coherent object graph: written to the session, every FK
column verified against the key of the row it points at.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Session

from seedgraph.boundary import taken_values, taken_values_async
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
    AmbiguousShapeKeyError,
    InvalidShapeCountError,
    MissingRequiredParentError,
    UnknownShapeKeyError,
    UnsupportedPrimaryKeyError,
    UnsupportedShapeDirectionError,
    build_graph,
)
from seedgraph.uniqueness import UniqueRepair
from seedgraph.verification import IncoherentGraphError, verify_graph

__version__ = "0.1.0.dev0"

__all__ = [
    "AmbiguousShapeKeyError",
    "Graph",
    "IncoherentGraphError",
    "InvalidShapeCountError",
    "MissingRequiredParentError",
    "SeedgraphError",
    "UniqueValueExhaustedError",
    "UnknownGeneratorColumnError",
    "UnknownOverrideColumnError",
    "UnknownShapeKeyError",
    "UnsupportedPlaceholderError",
    "UnsupportedPrimaryKeyError",
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
    **shape: int,
) -> Graph:
    """Seed a coherent object graph from the declared shape and return it.

    The graph is flushed, the database assigns its keys, and every FK column is
    verified against the row it points at. ``generators`` replaces how a column
    generates, ``overrides`` pins a value; both are keyed {Model: {"column": ...}}.
    Raises a ``SeedgraphError`` subclass on any bad declaration or broken link.
    """
    state = generation_state(session.info)
    objects = build_graph(model, shape, generators=generators, overrides=overrides, state=state)
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
    **shape: int,
) -> Graph:
    """Twin of ``seed`` on an AsyncSession: same contract, the flush is awaited."""
    state = generation_state(session.sync_session.info)
    objects = build_graph(model, shape, generators=generators, overrides=overrides, state=state)
    repair = UniqueRepair(objects, FieldGenerator(generators, overrides, state))
    while queries := repair.queries():
        repair.reject({column: await taken_values_async(session, column, values) for column, values in queries})
    session.add_all(objects)
    await session.flush()
    verify_graph(objects)
    return Graph(objects, model.metadata)
