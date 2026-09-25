"""The exit contract of seed(): every set link's FK columns equal the linked object's key."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Column, inspect
from sqlalchemy.orm import class_mapper

from seedgraph.exceptions import SeedgraphError

__all__ = ["IncoherentGraphError", "verify_graph"]


class IncoherentGraphError(SeedgraphError):
    """A link of the seeded graph carries FK values that differ from the linked object's key."""


def verify_graph(objects: Sequence[Any]) -> None:
    """Raise IncoherentGraphError on the first set link whose FK columns disagree with its target."""
    for obj in objects:
        state = inspect(obj)
        for relationship in state.mapper.relationships:
            if relationship.direction.name == "MANYTOMANY" or relationship.key in state.unloaded:
                continue
            value = getattr(obj, relationship.key)
            if value is None:
                continue
            linked = list(value) if relationship.direction.name == "ONETOMANY" else [value]
            for other in linked:
                for local_column, remote_column in relationship.local_remote_pairs:
                    local_value = _column_value(obj, local_column)
                    remote_value = _column_value(other, remote_column)
                    if local_value != remote_value:
                        raise IncoherentGraphError(
                            f"{type(obj).__name__}.{relationship.key}: {local_column.name}={local_value!r}"
                            f" vs {remote_column.name}={remote_value!r}"
                        )


def _column_value(obj: Any, column: Column[Any]) -> Any:
    return getattr(obj, class_mapper(type(obj)).get_property_by_column(column).key)
