"""Build the object graph declared by a shape: root count first, children level by level."""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import Column, inspect
from sqlalchemy.orm import DeclarativeBase, class_mapper
from sqlalchemy.orm.relationships import Relationship

from seedgraph.exceptions import SeedgraphError
from seedgraph.generators import (
    UNSET,
    FieldGenerator,
    GenerationState,
    GeneratorMap,
    OverrideMap,
    UnsupportedPlaceholderError,
    validate_column_declarations,
)

__all__ = [
    "AmbiguousShapeKeyError",
    "InvalidShapeCountError",
    "MissingRequiredParentError",
    "UnknownShapeKeyError",
    "UnsupportedPlaceholderError",
    "UnsupportedPrimaryKeyError",
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


class MissingRequiredParentError(SeedgraphError):
    """A required link has no matching ancestor in the branch and was not declared in the shape."""


class UnsupportedPrimaryKeyError(SeedgraphError):
    """A primary key column the database does not fill has no override to take its value from."""


def build_graph(
    model: type[DeclarativeBase],
    shape: Mapping[str, int],
    generators: GeneratorMap | None = None,
    overrides: OverrideMap | None = None,
    state: GenerationState | None = None,
) -> list[Any]:
    """Build the declared shape's objects, level by level, then link every required parent."""
    counts = dict(shape)
    root_key = model.__name__.lower()
    root_count = counts.pop(root_key, DEFAULT_COUNT)
    _check_count(root_key, root_count)
    tree = _resolve_tree(model, counts)
    validate_column_declarations(generators, overrides)
    objects = []
    generator = FieldGenerator(generators, overrides, state)
    for _ in range(root_count):
        root = _build_object(model, generator)
        _link_required_parents(root, [])
        objects.append(root)
        _attach_children(root, tree, objects, generator, [])
    return objects


def _resolve_tree(model: type[DeclarativeBase], counts: Mapping[str, int]) -> dict[str, Any]:
    """Resolve every shape key into a navigated tree — errors fire before anything is built."""
    root = {"children": {}}
    for key, count in counts.items():
        _check_count(key, count)
        node = root
        current = model
        for segment in key.split("__"):
            relationship = _resolve_segment(current, segment)
            current = relationship.mapper.class_
            node = node["children"].setdefault(
                relationship.key, {"relationship": relationship, "count": None, "children": {}}
            )
        node["count"] = count
    return root


def _resolve_segment(model: type[DeclarativeBase], segment: str) -> Relationship:
    """Resolve one shape segment: exact relationship key first, then the model it points at."""
    mapper = class_mapper(model)
    exact = [rel for rel in mapper.relationships if rel.key == segment]
    if exact:
        relationship = exact[0]
    else:
        matches = [
            rel for rel in mapper.relationships
            if rel.mapper.class_.__name__.lower() == segment
        ]
        if not matches:
            raise UnknownShapeKeyError(f"unknown shape key {segment!r} for {model.__name__}")
        if len(matches) > 1:
            names = ", ".join(sorted(rel.key for rel in matches))
            raise AmbiguousShapeKeyError(
                f"shape key {segment!r} matches several relationships of {model.__name__}"
                f" — address it by its relationship key instead: {names}"
            )
        relationship = matches[0]
    return _check_relationship(model, segment, relationship)


def _check_relationship(model: type[DeclarativeBase], segment: str, relationship: Relationship) -> Relationship:
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


def _attach_children(
    parent: Any, node: dict[str, Any], objects: list[Any], generator: FieldGenerator, ancestors: list[Any]
) -> None:
    branch = [*ancestors, parent]
    for child_node in node["children"].values():
        relationship = child_node["relationship"]
        count = DEFAULT_COUNT if child_node["count"] is None else child_node["count"]
        for _ in range(count):
            child = _build_object(relationship.mapper.class_, generator)
            getattr(parent, relationship.key).append(child)
            _link_required_parents(child, branch)
            objects.append(child)
            _attach_children(child, child_node, objects, generator, branch)


def _link_required_parents(obj: Any, ancestors: Sequence[Any]) -> None:
    """Attach each unset required link to the nearest ancestor of the target type in the branch."""
    state = inspect(obj)
    for relationship in state.mapper.relationships:
        if relationship.direction.name != "MANYTOONE" or not _is_required(relationship):
            continue
        if relationship.key not in state.unloaded and getattr(obj, relationship.key) is not None:
            continue
        target = relationship.mapper.class_
        for ancestor in reversed(ancestors):
            if type(ancestor) is target:
                setattr(obj, relationship.key, ancestor)
                break
        else:
            advice = (
                " — make the FK nullable to tie declared children, the first object of a"
                " self-referential branch cannot have a required parent"
                if target is type(obj)
                else ""
            )
            raise MissingRequiredParentError(
                f"{type(obj).__name__}.{relationship.key} requires a {target.__name__}, but no"
                f" ancestor of that type is in the branch — provide the parent in the shape{advice}"
            )


def _is_required(relationship: Relationship) -> bool:
    """A link is required when any of its local FK columns is NOT NULL."""
    return any(not local_column.nullable for local_column, _ in relationship.local_remote_pairs)


def _check_count(key: str, count: object) -> None:
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise InvalidShapeCountError(f"shape count for {key!r} must be an integer >= 0, got {count!r}")


def _build_object(model: type[DeclarativeBase], generator: FieldGenerator) -> Any:
    """Build one object of the model: generate eligible columns, apply declared overrides elsewhere."""
    obj = model()
    mapper = class_mapper(type(obj))
    for column in mapper.local_table.columns:
        if column.foreign_keys:
            continue
        key = mapper.get_property_by_column(column).key
        if column.primary_key:
            _fill_primary_key(obj, key, model, column, generator)
            continue
        if column.nullable or column.default is not None:
            override = generator.override_for(model, column)
            if override is not UNSET:
                setattr(obj, key, override)
            continue
        setattr(obj, key, generator.value_for(model, column))
    return obj


def _fill_primary_key(
    obj: Any, key: str, model: type[DeclarativeBase], column: Column[Any], generator: FieldGenerator
) -> None:
    if column is column.table.autoincrement_column or column.default is not None or column.server_default is not None:
        return
    override = generator.override_for(model, column)
    if override is not UNSET:
        setattr(obj, key, override)
        return
    raise UnsupportedPrimaryKeyError(
        f"cannot fill primary key {column.table.key}.{column.key}: the database does not generate it"
        " — give the column a default or declare its value in overrides"
    )
