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
    "AmbiguousParentError",
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
    """A shape key walks a relationship that cannot build children: towards a parent, or view-only."""


class MissingRequiredParentError(SeedgraphError):
    """A required link has no matching ancestor in the branch and was not declared in the shape."""


class AmbiguousParentError(SeedgraphError):
    """A link towards a single parent finds several objects of its type among the provided parents."""


class UnsupportedPrimaryKeyError(SeedgraphError):
    """A primary key column the database does not fill has no override to take its value from."""


def build_graph(
    model: type[DeclarativeBase],
    shape: Mapping[str, int],
    generators: GeneratorMap | None = None,
    overrides: OverrideMap | None = None,
    state: GenerationState | None = None,
    parents: Sequence[Any] = (),
) -> list[Any]:
    """Build the declared shape's objects, level by level, and link their parents.

    A link takes the nearest ancestor of its type in the branch, then the provided parent of that type;
    a required link still unset gets a parent generated once per type and shared, added to the result.
    """
    counts = dict(shape)
    root_key = model.__name__.lower()
    root_count = counts.pop(root_key, DEFAULT_COUNT)
    _check_count(root_key, root_count)
    tree = _resolve_tree(model, counts)
    validate_column_declarations(generators, overrides)
    objects: list[Any] = []
    generator = FieldGenerator(generators, overrides, state)
    linker = _ParentLinker(generator, objects, parents)
    for _ in range(root_count):
        root = _build_object(model, generator)
        linker.link(root, [])
        objects.append(root)
        _attach_children(root, tree, objects, generator, linker, [])
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
            if rel.mapper.class_.__name__.lower() == segment and not rel.viewonly
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
    walked = f"shape key {segment!r} walks {model.__name__}.{relationship.key}"
    if relationship.viewonly:
        raise UnsupportedShapeDirectionError(f"{walked}, a viewonly relationship — nothing would be written")
    if relationship.direction.name == "MANYTOONE":
        raise UnsupportedShapeDirectionError(
            f"{walked}, which points at a parent — parents are linked or generated on their own,"
            " pass existing ones in parents"
        )
    return relationship


def _attach_children(
    parent: Any,
    node: dict[str, Any],
    objects: list[Any],
    generator: FieldGenerator,
    linker: "_ParentLinker",
    ancestors: list[Any],
) -> None:
    branch = [*ancestors, parent]
    for child_node in node["children"].values():
        relationship = child_node["relationship"]
        count = DEFAULT_COUNT if child_node["count"] is None else child_node["count"]
        for _ in range(count):
            child = _build_object(relationship.mapper.class_, generator)
            getattr(parent, relationship.key).append(child)
            linker.link(child, branch)
            objects.append(child)
            _attach_children(child, child_node, objects, generator, linker, branch)


class _ParentLinker:
    def __init__(self, generator: FieldGenerator, objects: list[Any], parents: Sequence[Any]) -> None:
        self._generator = generator
        self._objects = objects
        self._provided = _index_parents(parents)
        self._generated: dict[type, Any] = {}
        self._in_progress: list[type] = []

    def link(self, obj: Any, ancestors: Sequence[Any]) -> None:
        state = inspect(obj)
        for relationship in state.mapper.relationships:
            if relationship.viewonly:
                continue
            if relationship.direction.name == "MANYTOMANY":
                self._share(obj, relationship)
                continue
            if relationship.direction.name != "MANYTOONE":
                continue
            if relationship.key not in state.unloaded and getattr(obj, relationship.key) is not None:
                continue
            parent = self._parent_for(obj, relationship, ancestors)
            if parent is not None:
                setattr(obj, relationship.key, parent)

    def _parent_for(self, obj: Any, relationship: Relationship, ancestors: Sequence[Any]) -> Any:
        target = relationship.mapper.class_
        required = _is_required(relationship)
        if required:
            for ancestor in reversed(ancestors):
                if type(ancestor) is target:
                    return ancestor
        candidates = self._provided.get(target, [])
        if len(candidates) > 1:
            raise AmbiguousParentError(
                f"{type(obj).__name__}.{relationship.key} links one {target.__name__}, but {len(candidates)}"
                " were passed in parents — pass one"
            )
        if candidates:
            return candidates[0]
        if not required:
            return None
        if target in self._generated:
            return self._generated[target]
        if target is type(obj) or target in self._in_progress:
            raise MissingRequiredParentError(self._unreachable(obj, relationship, target))
        return self._generate(target)

    def _share(self, obj: Any, relationship: Relationship) -> None:
        collection = getattr(obj, relationship.key)
        for shared in self._provided.get(relationship.mapper.class_, []):
            if shared not in collection:
                collection.append(shared)

    def _generate(self, target: type[DeclarativeBase]) -> Any:
        self._in_progress.append(target)
        parent = _build_object(target, self._generator)
        self.link(parent, [])
        self._in_progress.pop()
        self._generated[target] = parent
        self._objects.append(parent)
        return parent

    def _unreachable(self, obj: Any, relationship: Relationship, target: type) -> str:
        where = f"{type(obj).__name__}.{relationship.key} requires a {target.__name__}"
        if target is type(obj):
            return (
                f"{where}: the first object of a self-referential branch cannot have a required parent"
                " — make the FK nullable, or pass an existing one in parents"
            )
        loop = " -> ".join(model.__name__ for model in [*self._in_progress, target])
        return f"{where}, but required links form a loop ({loop}) — pass one of them in parents"


def _index_parents(parents: Sequence[Any]) -> dict[type, list[Any]]:
    provided: dict[type, list[Any]] = {}
    for parent in parents:
        provided.setdefault(type(parent), []).append(parent)
    return provided


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
        if column.default is not None or column.server_default is not None:
            override = generator.override_for(model, column)
            if override is not UNSET:
                setattr(obj, key, override)
            continue
        value = generator.value_for(model, column)
        if value is not UNSET:
            setattr(obj, key, value)
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
