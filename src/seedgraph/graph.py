"""The result of seed(): the generated objects, grouped by table name."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy.orm import class_mapper

__all__ = ["Graph"]


class Graph:
    """Group the seeded objects by table name, exposed as attributes.

    Each table name is an attribute holding the list of generated objects of
    that table, shaped by ``seed``'s declared shape: ``graph.users``,
    ``graph.posts``, ...
    """

    def __init__(self, objects: Sequence[Any]) -> None:
        grouped: dict[str, list[Any]] = {}
        for obj in objects:
            grouped.setdefault(class_mapper(type(obj)).local_table.name, []).append(obj)
        for table_name, group in grouped.items():
            setattr(self, table_name, group)
