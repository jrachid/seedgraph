"""seedgraph — referentially-consistent graph seeding for SQLAlchemy models.

Declare a shape, get a coherent object graph: FK columns provably pointing at
real PKs in the same graph, before any flush happens.
"""

from sqlalchemy.orm import DeclarativeBase, Session

from seedgraph.boundary import existing_maxima
from seedgraph.generators import GeneratorMap, OverrideMap
from seedgraph.graph import Graph
from seedgraph.reconciliation import reconcile_graph
from seedgraph.shape import build_graph

__version__ = "0.1.0.dev0"
__all__ = ["__version__", "seed"]


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
    return Graph(objects)
