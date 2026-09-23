"""The result of seed(): the generated objects, grouped by table name."""

from sqlalchemy.orm import class_mapper

__all__ = ["Graph"]


class Graph:
    """Expose each table's generated objects as an attribute named after the table."""

    def __init__(self, objects):
        grouped = {}
        for obj in objects:
            grouped.setdefault(class_mapper(type(obj)).local_table.name, []).append(obj)
        for table_name, group in grouped.items():
            setattr(self, table_name, group)
