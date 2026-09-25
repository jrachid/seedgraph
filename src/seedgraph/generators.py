"""Field generation: a seeded faker, name heuristics, custom overrides, type fallbacks.

Its world is (column, fake) -> value. No session, no shape, no graph.
"""

from collections.abc import Callable
from typing import Any, TypeAlias

from faker import Faker
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    Integer,
    Interval,
    LargeBinary,
    Numeric,
    String,
    Time,
    Uuid,
)
from sqlalchemy.orm import class_mapper
from sqlalchemy.types import TypeEngine

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
MAX_FLOAT_LEFT_DIGITS = 4
BINARY_LENGTH = 16

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
        """Return the column's value, or UNSET for a nullable column of a type no provider covers."""
        override = self.override_for(model, column)
        if override is not UNSET:
            return override
        custom = self._generators.get(model)
        if custom is not None and column.key in custom:
            return custom[column.key](GenerationContext(self._fake, column.key))
        provider = self._provider(column)
        if provider is None:
            if column.nullable:
                return UNSET
            raise UnsupportedPlaceholderError(
                f"cannot generate NOT NULL column {column.table.key}.{column.key} of type {column.type}"
            )
        return _fit(provider(), column.type)

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

    def _provider(self, column: Column[Any]) -> Callable[[], Any] | None:
        if _is_text(column.type):
            hint = COLUMN_HINTS.get(column.key.lower())
            if hint is not None:
                return getattr(self._fake, hint)
        return self._type_provider(column.type)

    def _type_provider(self, type_: TypeEngine[Any]) -> Callable[[], Any] | None:
        fake = self._fake
        if isinstance(type_, Enum):
            choices = list(type_.enum_class) if type_.enum_class is not None else list(type_.enums)
            return lambda: fake.random_element(choices)
        if isinstance(type_, Boolean):
            return fake.boolean
        if isinstance(type_, Integer):
            return lambda: fake.random_int(min=0, max=MAX_INTEGER)
        if isinstance(type_, Float):
            return lambda: fake.pyfloat(left_digits=MAX_FLOAT_LEFT_DIGITS, right_digits=MAX_NUMERIC_RIGHT_DIGITS)
        if isinstance(type_, Numeric):
            return self._numeric_provider(type_)
        if isinstance(type_, DateTime):
            return fake.date_time
        if isinstance(type_, Date):
            return fake.date_object
        if isinstance(type_, Time):
            return fake.time_object
        if isinstance(type_, Interval):
            return fake.time_delta
        if isinstance(type_, Uuid):
            return (lambda: fake.uuid4(cast_to=None)) if type_.as_uuid else fake.uuid4
        if isinstance(type_, LargeBinary):
            return lambda: fake.binary(length=BINARY_LENGTH)
        if isinstance(type_, String):
            return fake.sentence
        return None

    def _numeric_provider(self, type_: Numeric[Any]) -> Callable[[], Any]:
        right = MAX_NUMERIC_RIGHT_DIGITS if type_.scale is None else type_.scale
        left = MAX_NUMERIC_LEFT_DIGITS if type_.precision is None else type_.precision - right
        return lambda: self._fake.pydecimal(left_digits=left, right_digits=right, positive=True)


def _is_text(type_: TypeEngine[Any]) -> bool:
    return isinstance(type_, String) and not isinstance(type_, Enum)


def _fit(value: Any, type_: TypeEngine[Any]) -> Any:
    """Cut a generated string to the column's declared length."""
    if isinstance(value, str) and _is_text(type_) and type_.length:
        return value[: type_.length].rstrip()
    return value
