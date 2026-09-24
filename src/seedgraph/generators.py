"""Field generation: a seeded faker, name heuristics, and type-based fallbacks.

Its world is (column, fake) -> value. No session, no shape, no graph.
"""

from faker import Faker
from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text

from seedgraph.exceptions import SeedgraphError

__all__ = ["FieldGenerator", "GenerationContext", "UnsupportedPlaceholderError"]

DEFAULT_SEED = 42
DEFAULT_LOCALE = "en_US"

MAX_INTEGER = 100
MAX_NUMERIC_LEFT_DIGITS = 6
MAX_NUMERIC_RIGHT_DIGITS = 2

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


class GenerationContext:
    """The object handed to custom generators: the seeded fake and the column name."""

    def __init__(self, fake, column):
        self.fake = fake
        self.column = column


class FieldGenerator:
    """Generate values for eligible columns through one seeded Faker instance."""

    def __init__(self):
        self._fake = Faker(locale=DEFAULT_LOCALE)
        self._fake.seed_instance(DEFAULT_SEED)

    def value_for(self, column):
        hint = COLUMN_HINTS.get(column.key.lower())
        if hint is not None:
            return getattr(self._fake, hint)()
        provider = self._type_provider(column)
        if provider is None:
            raise UnsupportedPlaceholderError(
                f"cannot generate NOT NULL column {column.table.key}.{column.key} of type {column.type}"
            )
        return provider()

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