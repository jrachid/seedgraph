"""The result of seed(): the generated objects, grouped by table name."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import MetaData

from seedgraph.generators import mapped_table

__all__ = ["Graph"]


class Graph:
    """Group the seeded objects by table name, exposed as attributes.

    Each table of the seeded model's metadata is an attribute holding the list of
    generated objects of that table, empty when the shape built none: ``graph.users``.
    """

    def __init__(self, objects: Sequence[Any], metadata: MetaData) -> None:
        self._table_names = sorted(table.name for table in metadata.tables.values())
        grouped: dict[str, list[Any]] = {}
        for obj in objects:
            grouped.setdefault(mapped_table(type(obj)).name, []).append(obj)
        for table_name, group in grouped.items():
            setattr(self, table_name, group)

    def __getattr__(self, name: str) -> list[Any]:
        if not name.startswith("_") and name in self._table_names:
            return []
        known = ", ".join(self._table_names)
        raise AttributeError(f"the graph has no table {name!r} — known tables: {known}")
