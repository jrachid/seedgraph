"""Build the object graph declared by a shape: root count first, children level by level."""

from sqlalchemy import Integer, String
from sqlalchemy.orm import class_mapper

from seedgraph.exceptions import SeedgraphError

__all__ = [
    "AmbiguousShapeKeyError",
    "InvalidShapeCountError",
    "UnknownShapeKeyError",
    "UnsupportedPlaceholderError",
    "UnsupportedShapeDirectionError",
    "build_graph",
]

DEFAULT_COUNT = 3


class UnknownShapeKeyError(SeedgraphError):
    """A shape key matches no relationship of the model at that point of the path."""


class AmbiguousShapeKeyError(SeedgraphError):
    """A shape key matches several relationships of the model at that point of the path."""


class InvalidShapeCountError(SeedgraphError):
    """A shape count is not an integer greater than or equal to zero."""


class UnsupportedShapeDirectionError(SeedgraphError):
    """A shape key walks a relationship that is not one-to-many."""


class UnsupportedPlaceholderError(SeedgraphError):
    """A NOT NULL column without default carries a type seedgraph cannot placeholder."""


def build_graph(model, shape):
    """Build the declared shape's objects — the root level and one level of children in this tranche."""
    counts = dict(shape)
    root_key = model.__name__.lower()
    root_count = counts.pop(root_key, DEFAULT_COUNT)
    _check_count(root_key, root_count)
    children = _resolve_children(model, counts)
    objects = []
    placeholders = {}
    for _ in range(root_count):
        root = _build_object(model, placeholders)
        objects.append(root)
        _attach_children(root, children, objects, placeholders)
    return objects


def _resolve_children(model, counts):
    """Resolve and validate every shape key upfront, so errors fire before anything is built."""
    children = []
    for key, count in counts.items():
        _check_count(key, count)
        segments = key.split("__")
        current = model
        relationship = None
        for segment in segments:
            relationship = _resolve_segment(current, segment)
            current = relationship.mapper.class_
        if len(segments) > 1:
            raise UnknownShapeKeyError(
                f"shape key {key!r}: nesting deeper than one level is not supported yet"
            )
        children.append((relationship, count))
    return children


def _resolve_segment(model, segment):
    matches = [
        rel for rel in class_mapper(model).relationships
        if rel.mapper.class_.__name__.lower() == segment
    ]
    if not matches:
        raise UnknownShapeKeyError(f"unknown shape key {segment!r} for {model.__name__}")
    if len(matches) > 1:
        names = ", ".join(sorted(rel.key for rel in matches))
        raise AmbiguousShapeKeyError(
            f"shape key {segment!r} matches several relationships of {model.__name__}: {names}"
        )
    relationship = matches[0]
    if relationship.direction.name == "MANYTOMANY":
        raise UnsupportedShapeDirectionError(
            f"shape key {segment!r} walks {model.__name__}.{relationship.key}, a many-to-many"
            " relationship — its foreign keys live in the secondary table, which has no objects"
        )
    if relationship.direction.name != "ONETOMANY":
        raise UnsupportedShapeDirectionError(
            f"shape key {segment!r} walks {model.__name__}.{relationship.key},"
            f" which is {relationship.direction.name.lower()} — only one-to-many paths can be built"
        )
    return relationship


def _attach_children(parent, children, objects, placeholders):
    for relationship, count in children:
        for _ in range(count):
            child = _build_object(relationship.mapper.class_, placeholders)
            getattr(parent, relationship.key).append(child)
            objects.append(child)


def _check_count(key, count):
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise InvalidShapeCountError(f"shape count for {key!r} must be an integer >= 0, got {count!r}")


def _build_object(model, placeholders):
    table_key = class_mapper(model).local_table.key
    index = placeholders.get(table_key, 0)
    placeholders[table_key] = index + 1
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
