"""seedgraph exceptions."""

__all__ = ["SeedgraphError"]


class SeedgraphError(Exception):
    """Base class for every error seedgraph raises.

    Constructed with one message string naming the exact shape key, column or
    model at fault.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
