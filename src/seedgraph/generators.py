"""Field generation: a seeded faker, name heuristics, custom overrides, type fallbacks.

Its world is (column, fake) -> value. No session, no shape, no graph.
"""

from collections.abc import Callable
from typing import Any, TypeAlias

from faker import Faker
from sqlalchemy import Boolean, Column, Date, DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import class_mapper

from seedgraph.exceptions import SeedgraphError

__all__ = [
    "UNSET",
    "ColumnGenerator",
    "FieldGenerator",
    "GenerationContext",
    "GenerationState",
    "UnknownGeneratorColumnError",
    "UnknownOverrideColumnError",
    "UnsupportedPlaceholderError",
    "generation_state",
    "validate_column_declarations",
]

DEFAULT_SEED = 42
DEFAULT_LOCALE = "en_US"
SESSION_INFO_KEY = "seedgraph"

UNSET: Any = object()

MAX_INTEGER = 100
MAX_NUMERIC_LEFT_DIGITS = 6
MAX_NUMERIC_RIGHT_DIGITS = 2

ColumnGenerator: TypeAlias = Callable[["GenerationContext"], Any]
ColumnOverride: TypeAlias = ColumnGenerator | Any
ColumnMap: TypeAlias = dict[str, ColumnOverride]
GeneratorMap: TypeAlias = dict[type, dict[str, ColumnGenerator]]
OverrideMap: TypeAlias = dict[type, ColumnMap]

COLUMN_HINTS = {
    "name": "name",
    "first_name": "first_name",
    "last_name": "last_name",
    "username": "user_name",
    "user_name": "user_name",
    "email": "email",
    "title": "sentence",
    "body": "paragraph",
    "description": "paragraph",
    "content": "paragraph",
    "phone": "phone_number",
    "phone_number": "phone_number",
    "url": "url",
    "company": "company",
    "city": "city",
    "country": "country",
}


class UnsupportedPlaceholderError(SeedgraphError):
    """A NOT NULL column without default carries a type no generator covers."""


class UnknownGeneratorColumnError(SeedgraphError):
    """A column declared in generators does not exist on its model."""


class UnknownOverrideColumnError(SeedgraphError):
    """A column declared in overrides does not exist on its model."""


def validate_generators(generators: GeneratorMap | None) -> None:
    """Reject any declared column that matches no column of its declared model."""
    validate_column_declarations(generators, None)


def validate_column_declarations(generators: GeneratorMap | None, overrides: OverrideMap | None) -> None:
    """Reject any declared column that matches no column of its declared model."""
    errors = (
        (generators, UnknownGeneratorColumnError, "generated"),
        (overrides, UnknownOverrideColumnError, "overridden"),
    )
    for declarations, error, verb in errors:
        for model, columns in (declarations or {}).items():
            existing = {column.key for column in class_mapper(model).local_table.columns}
            for column in columns:
                if column not in existing:
                    raise error(f"unknown {verb} column {column!r} for {model.__name__}")


class GenerationState:
    """What generation carries from one seed() to the next on the same session: the seeded faker."""

    def __init__(self) -> None:
        self.fake: Faker = Faker(locale=DEFAULT_LOCALE)
        self.fake.seed_instance(DEFAULT_SEED)


def generation_state(info: dict[Any, Any]) -> GenerationState:
    """Return the session's generation state, created on its first seed() from ``session.info``."""
    return info.setdefault(SESSION_INFO_KEY, GenerationState())


class GenerationContext:
    """The object handed to custom generators: the seeded fake and the column name."""

    def __init__(self, fake: Faker, column: str) -> None:
        self.fake: Faker = fake
        self.column: str = column


class FieldGenerator:
    """Generate values for eligible columns through one seeded Faker instance."""

    def __init__(
        self,
        generators: GeneratorMap | None = None,
        overrides: OverrideMap | None = None,
        state: GenerationState | None = None,
    ) -> None:
        self._fake = (state or GenerationState()).fake
        self._generators: dict[type, dict[str, ColumnGenerator]] = generators or {}
        self._overrides: OverrideMap = overrides or {}

    def value_for(self, model: type, column: Column[Any]) -> Any:
        override = self.override_for(model, column)
        if override is not UNSET:
            return override
        custom = self._generators.get(model)
        if custom is not None and column.key in custom:
            return custom[column.key](GenerationContext(self._fake, column.key))
        hint = COLUMN_HINTS.get(column.key.lower())
        if hint is not None:
            return getattr(self._fake, hint)()
        provider = self._type_provider(column)
        if provider is None:
            raise UnsupportedPlaceholderError(
                f"cannot generate NOT NULL column {column.table.key}.{column.key} of type {column.type}"
            )
        return provider()

    def override_for(self, model: type, column: Column[Any]) -> Any:
        """Return the declared override's resolved value for the column, or UNSET when undeclared."""
        override = self._overrides.get(model)
        if override is None or column.key not in override:
            return UNSET
        return self._resolve(override[column.key], column)

    def _resolve(self, value: ColumnOverride, column: Column[Any]) -> Any:
        if callable(value):
            return value(GenerationContext(self._fake, column.key))
        return value

    def _type_provider(self, column: Column[Any]) -> Callable[[], Any] | None:
        if isinstance(column.type, Integer):
            return lambda: self._fake.random_int(min=0, max=MAX_INTEGER)
        if isinstance(column.type, Numeric):
            return lambda: self._fake.pydecimal(
                left_digits=MAX_NUMERIC_LEFT_DIGITS, right_digits=MAX_NUMERIC_RIGHT_DIGITS, positive=True
            )
        if isinstance(column.type, DateTime):
            return self._fake.date_time
        if isinstance(column.type, Date):
            return self._fake.date_object
        if isinstance(column.type, Boolean):
            return self._fake.boolean
        if isinstance(column.type, (String, Text)):
            return self._fake.sentence
        return None