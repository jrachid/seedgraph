"""seedgraph — referentially-consistent graph seeding for SQLAlchemy models.

Declare a shape, get a coherent object graph: FK columns provably pointing at
real PKs in the same graph, before any flush happens.
"""

__version__ = "0.1.0.dev0"

__all__ = ["__version__", "seed"]


def seed(session, model, /, **shape):
    """Seed a referentially-consistent object graph.

    Target API:

        graph = seed(session, User, post=2, post__comment=3)
        graph.users[0].posts[0].author_id == graph.users[0].id  # True

    """
    raise NotImplementedError(
        "seedgraph is under active development — see the README roadmap."
    )
