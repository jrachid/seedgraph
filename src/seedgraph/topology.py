"""Read the FK dependency graph between tables straight from SQLAlchemy model metadata."""

from sqlalchemy import MetaData
from sqlalchemy.exc import NoReferencedTableError

__all__ = ["dependency_graph"]


def dependency_graph(source):
    """Map every table key to the set of table keys it references through declared FK constraints."""
    metadata = _metadata_of(source)
    graph = {key: set() for key in metadata.tables}
    for child, parent, _use_alter in _declared_edges(metadata):
        graph[child].add(parent)
    return graph


def _metadata_of(source):
    """Return the MetaData behind a mapped class, or pass a MetaData through."""
    if isinstance(source, MetaData):
        return source
    metadata = getattr(source, "metadata", None)
    if isinstance(metadata, MetaData):
        return metadata
    raise TypeError("source must be a SQLAlchemy mapped class or a MetaData object")


def _declared_edges(metadata):
    """Yield (child_key, parent_key, use_alter) for each FK constraint whose target table is in the metadata."""
    for table in metadata.tables.values():
        for constraint in table.foreign_key_constraints:
            targets = set()
            for foreign_key in constraint.elements:
                try:
                    targets.add(foreign_key.column.table.key)
                except NoReferencedTableError:
                    targets.clear()
                    break
            for parent_key in targets:
                if parent_key in metadata.tables:
                    yield table.key, parent_key, constraint.use_alter
