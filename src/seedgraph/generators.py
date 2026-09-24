"""Field generation: a seeded faker, name heuristics, custom overrides, type fallbacks.

Its world is (column, fake) -> value. No session, no shape, no graph.
"""

from collections.abc import Callable
from typing import Any, TypeAlias

from faker import Faker
from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import class_mapper

from seedgraph.exceptions import SeedgraphError

__all__ = [
    "ColumnGenerator",
    "FieldGenerator",
    "GenerationContext",
    "UnknownGeneratorColumnError",
    "UnknownOverrideColumnError",
    "UnsupportedPlaceholderError",
    "validate_column_declarations",
]

DEFAULT_SEED = 42
DEFAULT_LOCALE = "en_US"

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


def validate_generators(generators):
    """Reject any declared column that matches no column of its declared model."""
    validate_column_declarations(generators, None)


def validate_column_declarations(generators, overrides):
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


class GenerationContext:
    """The object handed to custom generators: the seeded fake and the column name."""

    def __init__(self, fake, column):
        self.fake = fake
        self.column = column


class FieldGenerator:
    """Generate values for eligible columns through one seeded Faker instance."""

    def __init__(self, generators=None, overrides=None):
        self._fake = Faker(locale=DEFAULT_LOCALE)
        self._fake.seed_instance(DEFAULT_SEED)
        self._generators = generators or {}
        self._overrides = overrides or {}

    def value_for(self, model, column):
        override = self.override_for(model, column)
        if override is not None:
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

    def override_for(self, model, column):
        """Return the declared override's resolved value for the column, or None when undeclared."""
        override = self._overrides.get(model)
        if override is None or column.key not in override:
            return None
        return self._resolve(override[column.key], column)

    def _resolve(self, value, column):
        if callable(value):
            return value(GenerationContext(self._fake, column.key))
        return value

    def _type_provider(self, column):
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