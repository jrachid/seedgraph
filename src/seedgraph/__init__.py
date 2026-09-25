"""seedgraph — referentially-consistent graph seeding for SQLAlchemy models.

Declare a shape, get a coherent object graph: FK columns provably pointing at
real PKs in the same graph, before any flush happens.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Session

from seedgraph.boundary import existing_maxima, existing_maxima_async
from seedgraph.exceptions import SeedgraphError
from seedgraph.generators import (
    GeneratorMap,
    OverrideMap,
    UnknownGeneratorColumnError,
    UnknownOverrideColumnError,
    UnsupportedPlaceholderError,
)
from seedgraph.graph import Graph
from seedgraph.reconciliation import PendingParentError, UnsupportedPrimaryKeyError, reconcile_graph
from seedgraph.shape import (
    AmbiguousShapeKeyError,
    InvalidShapeCountError,
    MissingRequiredParentError,
    UnknownShapeKeyError,
    UnsupportedShapeDirectionError,
    build_graph,
)
from seedgraph.topology import CyclicFKGraphError

__version__ = "0.1.0.dev0"

__all__ = [
    "AmbiguousShapeKeyError",
    "CyclicFKGraphError",
    "Graph",
    "InvalidShapeCountError",
    "MissingRequiredParentError",
    "PendingParentError",
    "SeedgraphError",
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

    Every FK column of the returned graph points at a real PK of the same graph,
    before any flush happens. ``generators`` replaces how a column generates,
    ``overrides`` pins a value; both are keyed {Model: {"column": ...}}.
    Raises a ``SeedgraphError`` subclass on any bad shape key, count, model or
    column declaration.
    """
    objects = build_graph(model, shape, generators=generators, overrides=overrides)
    reconcile_graph(objects, existing_maxima=existing_maxima(session, model))
    session.add_all(objects)
    return Graph(objects, model.metadata)


async def seed_async(
    session: AsyncSession,
    model: type[DeclarativeBase],
    /,
    generators: GeneratorMap | None = None,
    overrides: OverrideMap | None = None,
    **shape: int,
) -> Graph:
    """Twin of ``seed`` on an AsyncSession: same contract, one awaited read.

    Every FK column of the returned graph points at a real PK of the same graph,
    before any flush happens; the channels and errors match ``seed`` exactly.
    The awaited call is the PK-maxima read — the single IO of the facade.
    """
    objects = build_graph(model, shape, generators=generators, overrides=overrides)
    reconcile_graph(objects, existing_maxima=await existing_maxima_async(session, model))
    session.add_all(objects)
    return Graph(objects, model.metadata)
