"""seedgraph — referentially-consistent graph seeding for SQLAlchemy models.

Declare a shape, get a coherent object graph: FK columns provably pointing at
real PKs in the same graph, before any flush happens.
"""

from seedgraph.boundary import existing_maxima
from seedgraph.graph import Graph
from seedgraph.reconciliation import reconcile_graph
from seedgraph.shape import build_graph

__version__ = "0.1.0.dev0"

__all__ = ["__version__", "seed"]


def seed(session, model, /, generators=None, **shape):
    """Seed a referentially-consistent object graph from the declared shape."""
    objects = build_graph(model, shape, generators=generators)
    reconcile_graph(objects, existing_maxima=existing_maxima(session, model))
    session.add_all(objects)
    return Graph(objects)
