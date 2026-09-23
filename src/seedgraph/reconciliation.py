"""Reserve deterministic primary keys for pending objects of a graph, above existing maxima."""

from sqlalchemy import Integer
from sqlalchemy.orm import class_mapper

from seedgraph.exceptions import SeedgraphError

__all__ = ["UnsupportedPrimaryKeyError", "reconcile_graph"]


class UnsupportedPrimaryKeyError(SeedgraphError):
    """A pending object carries a primary key column whose type seedgraph cannot reserve."""


def reconcile_graph(objects, existing_maxima=None):
    """Reserve a primary key for every pending object, deterministic in the given order."""
    _reserve_primary_keys(objects, existing_maxima or {})


def _reserve_primary_keys(objects, maxima):
    counters = {}
    for obj in objects:
        mapper = class_mapper(type(obj))
        pairs = _pk_pairs(mapper)
        if any(getattr(obj, attribute) is not None for _column, attribute in pairs):
            continue
        for column, attribute in pairs:
            setattr(obj, attribute, _next_pk_value(counters, maxima, mapper, column))


def _pk_pairs(mapper):
    """Return the primary key as (column, attribute name) pairs."""
    return [(column, mapper.get_property_by_column(column).key) for column in mapper.primary_key]


def _next_pk_value(counters, maxima, mapper, column):
    if not isinstance(column.type, Integer):
        raise UnsupportedPrimaryKeyError(
            f"cannot reserve non-integer primary key {mapper.local_table.key}.{column.key}"
        )
    key = (mapper.local_table.key, column.key)
    if key not in counters:
        counters[key] = maxima.get(mapper.local_table.key, {}).get(column.key, 0)
    counters[key] += 1
    return counters[key]
