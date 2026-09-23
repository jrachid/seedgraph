"""Build the object graph declared by a shape: root count first, children level by level."""

from sqlalchemy import Integer, String
from sqlalchemy.orm import class_mapper

from seedgraph.exceptions import SeedgraphError

__all__ = [
    "InvalidShapeCountError",
    "UnknownShapeKeyError",
    "UnsupportedPlaceholderError",
    "build_graph",
]

DEFAULT_COUNT = 3


class UnknownShapeKeyError(SeedgraphError):
    """A shape key matches no relationship of the model at that point of the path."""


class InvalidShapeCountError(SeedgraphError):
    """A shape count is not an integer greater than or equal to zero."""


class UnsupportedPlaceholderError(SeedgraphError):
    """A NOT NULL column without default carries a type seedgraph cannot placeholder."""


def build_graph(model, shape):
    """Build the declared shape's objects — the root level in this tranche."""
    counts = dict(shape)
    root_key = model.__name__.lower()
    root_count = counts.pop(root_key, DEFAULT_COUNT)
    _check_count(root_key, root_count)
    for key in counts:
        raise UnknownShapeKeyError(f"unknown or unsupported shape key {key!r} for {model.__name__}")
    return [_build_object(model, index) for index in range(root_count)]


def _check_count(key, count):
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise InvalidShapeCountError(f"shape count for {key!r} must be an integer >= 0, got {count!r}")


def _build_object(model, index):
    obj = model()
    _fill_placeholders(obj, index)
    return obj


def _fill_placeholders(obj, index):
    mapper = class_mapper(type(obj))
    for column in mapper.local_table.columns:
        if column.nullable or column.default is not None or column.primary_key or column.foreign_keys:
            continue
        setattr(obj, mapper.get_property_by_column(column).key, _placeholder_value(column, index))


def _placeholder_value(column, index):
    if isinstance(column.type, Integer):
        return index
    if isinstance(column.type, String):
        return f"{column.table.key}-{index}"
    raise UnsupportedPlaceholderError(
        f"cannot placeholder NOT NULL column {column.table.key}.{column.key} of type {column.type}"
    )
