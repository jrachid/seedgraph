"""Replace generated unique values the database already holds, round by round, without doing any IO itself."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Column
from sqlalchemy.orm import class_mapper

from seedgraph.generators import FieldGenerator, UniqueValueExhaustedError, is_unique

__all__ = ["UniqueRepair"]

MAX_ROUNDS = 10


class UniqueRepair:
    """Hand out the generated unique values to check, then regenerate those the database reports as taken."""

    def __init__(self, objects: Sequence[Any], generator: FieldGenerator) -> None:
        self._generator = generator
        self._rounds = 0
        self._slots: list[tuple[Any, Column[Any], str]] = []
        for obj in objects:
            mapper = class_mapper(type(obj))
            for column in mapper.local_table.columns:
                if column.foreign_keys or not is_unique(column):
                    continue
                if generator.is_overridden(type(obj), column):
                    continue
                attribute = mapper.get_property_by_column(column).key
                if getattr(obj, attribute) is not None:
                    self._slots.append((obj, column, attribute))

    def queries(self) -> list[tuple[Column[Any], list[Any]]]:
        """Return each column with the values still to check, empty once none is left."""
        if not self._slots:
            return []
        if self._rounds == MAX_ROUNDS:
            _, column, _ = self._slots[0]
            raise UniqueValueExhaustedError(
                f"unique column {column.table.key}.{column.key} still collides with existing rows"
                f" after {MAX_ROUNDS} rounds — widen its generator or declare one in generators"
            )
        self._rounds += 1
        by_column: dict[Column[Any], list[Any]] = {}
        for obj, column, attribute in self._slots:
            by_column.setdefault(column, []).append(getattr(obj, attribute))
        return list(by_column.items())

    def reject(self, taken: dict[Column[Any], set[Any]]) -> None:
        """Regenerate every slot whose value is taken; only those are checked again."""
        still = []
        for obj, column, attribute in self._slots:
            value = getattr(obj, attribute)
            if value in taken.get(column, ()):
                self._generator.remember(column, taken[column])
                setattr(obj, attribute, self._generator.value_for(type(obj), column))
                still.append((obj, column, attribute))
        self._slots = still
