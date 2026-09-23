"""Reserve primary keys for pending objects, then reconcile FK columns from their linked parents."""

from sqlalchemy import Integer, inspect
from sqlalchemy.orm import class_mapper

from seedgraph.exceptions import SeedgraphError

__all__ = ["PendingParentError", "UnsupportedPrimaryKeyError", "reconcile_graph"]


class PendingParentError(SeedgraphError):
    """A linked parent has no primary key and was not part of the objects given to reconcile_graph."""


class UnsupportedPrimaryKeyError(SeedgraphError):
    """A pending object carries a primary key column whose type seedgraph cannot reserve."""


def reconcile_graph(objects, existing_maxima=None):
    """Reserve a primary key for every pending object, then copy each linked parent's PK into the child's FK columns."""
    _reserve_primary_keys(objects, existing_maxima or {})
    _reconcile_foreign_keys(objects)


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


def _reconcile_foreign_keys(objects):
    for obj in objects:
        state = inspect(obj)
        for relationship in state.mapper.relationships:
            _reconcile_relationship(obj, state, relationship)


def _reconcile_relationship(obj, state, relationship):
    if relationship.direction.name == "MANYTOMANY" or relationship.key in state.unloaded:
        return
    value = getattr(obj, relationship.key)
    if value is None:
        return
    linked = list(value) if relationship.direction.name == "ONETOMANY" else [value]
    for related in linked:
        for local_column, remote_column in relationship.local_remote_pairs:
            _reconcile_pair(obj, related, relationship, local_column, remote_column)


def _reconcile_pair(obj, related, relationship, local_column, remote_column):
    flow = _pk_flow(obj, related, local_column, remote_column)
    if flow is None:
        return
    source, source_column, target, target_column = flow
    value = _column_value(source, source_column)
    if value is None:
        raise PendingParentError(
            f"{type(source).__name__} linked by {type(obj).__name__}.{relationship.key} has no"
            " primary key — include it in the objects passed to reconcile_graph"
        )
    setattr(target, _column_attribute(target, target_column), value)


def _pk_flow(obj, related, local_column, remote_column):
    """Return (source, source column, target, target column) so the value flows PK side to FK side."""
    if local_column.primary_key and remote_column.primary_key:
        if local_column.foreign_keys:
            return related, remote_column, obj, local_column
        if remote_column.foreign_keys:
            return obj, local_column, related, remote_column
        return None
    if remote_column.primary_key:
        return related, remote_column, obj, local_column
    if local_column.primary_key:
        return obj, local_column, related, remote_column
    return None


def _column_value(obj, column):
    return getattr(obj, _column_attribute(obj, column))


def _column_attribute(obj, column):
    return class_mapper(type(obj)).get_property_by_column(column).key
