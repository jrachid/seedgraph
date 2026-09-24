"""Read what already exists at the boundary: per-table, per-column primary key maxima."""

from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session

from seedgraph.topology import MetaDataOrModel, metadata_of

__all__ = ["existing_maxima"]


def existing_maxima(session: Session, source: MetaDataOrModel) -> dict[str, dict[str, int]]:
    """Read the current maximum of every integer primary key column of the source's tables."""
    metadata = metadata_of(source)
    maxima = {}
    for table in metadata.tables.values():
        columns = {
            column.key: session.scalar(select(func.max(column))) or 0
            for column in table.primary_key.columns
            if isinstance(column.type, Integer)
        }
        if columns:
            maxima[table.key] = columns
    return maxima
