"""Replace generated unique values the database already holds, round by round, without doing any IO itself."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, NoReturn

from sqlalchemy import Column
from sqlalchemy.orm import class_mapper

from seedgraph.generators import (
    UNSET,
    FieldGenerator,
    UniqueValueExhaustedError,
    is_unique,
    mapped_table,
)

__all__ = ["UniqueRepair"]

MAX_ROUNDS = 64
MAX_RANK = 2**20
MAX_DRAWS_PER_ROUND = 300


@dataclass
class _Slot:
    obj: Any
    column: Column[Any]
    attribute: str
    origin: Any
    value: Any
    rank: int = 0
    taken_below: int = -1
    free_at: int | None = None
    best: Any = None
    gap: int = 1


class UniqueRepair:
    """Hand out the generated unique values to check, then search the first free replacement of those taken.

    Earlier sessions took ranks 0..k-1 of each value: one pilot per column finds k in O(log k) rounds, the others jump to it.
    """

    def __init__(self, objects: Sequence[Any], generator: FieldGenerator) -> None:
        self._generator = generator
        self._rounds = 0
        self._proposed: dict[Column[Any], set[Any]] = {}
        self._pilots: dict[Column[Any], _Slot] = {}
        self._settled_ranks: dict[Column[Any], int] = {}
        self._waiting: dict[Column[Any], list[_Slot]] = {}
        self._slots: list[_Slot] = []
        for obj in objects:
            mapper = class_mapper(type(obj))
            for column in mapped_table(type(obj)).columns:
                if column.foreign_keys or not is_unique(column):
                    continue
                if generator.is_overridden(type(obj), column):
                    continue
                attribute = mapper.get_property_by_column(column).key
                value = getattr(obj, attribute)
                if value is not None:
                    self._slots.append(_Slot(obj, column, attribute, value, value))

    def queries(self) -> list[tuple[Column[Any], list[Any]]]:
        """Return each column with the values still to check, empty once none is left."""
        if not self._slots:
            return []
        if self._rounds == MAX_ROUNDS:
            self._exhausted(self._slots[0].column)
        self._rounds += 1
        by_column: dict[Column[Any], list[Any]] = {}
        for slot in self._slots:
            by_column.setdefault(slot.column, []).append(slot.value)
        return list(by_column.items())

    def reject(self, taken: dict[Column[Any], set[Any]]) -> None:
        """Record which checked values are taken, settle the slots whose search is over, move the others."""
        active: list[_Slot] = []
        for slot in self._slots:
            if slot.value in taken.get(slot.column, ()):
                slot.taken_below = slot.rank
                self._generator.remember(slot.column, {slot.value})
            else:
                if slot.free_at is not None:
                    self._proposed[slot.column].discard(slot.best)
                slot.free_at, slot.best = slot.rank, slot.value
            if slot.rank == 0 and slot.free_at is None and self._pilots.setdefault(slot.column, slot) is not slot:
                if slot.column in self._settled_ranks:
                    self._jump(slot, self._settled_ranks[slot.column], active)
                else:
                    self._waiting.setdefault(slot.column, []).append(slot)
                continue
            if self._advance(slot):
                active.append(slot)
                continue
            rank = self._settle(slot)
            if self._pilots.get(slot.column) is slot:
                self._settled_ranks[slot.column] = rank
                for waiting in self._waiting.pop(slot.column, []):
                    self._jump(waiting, rank, active)
        self._slots = active

    def _jump(self, slot: _Slot, rank: int, active: list[_Slot]) -> None:
        """Check the rank the pilot settled on, taking every rank below it as taken."""
        slot.taken_below, slot.free_at, slot.gap = rank - 1, None, 1
        if self._probe(slot, rank) or self._advance(slot):
            active.append(slot)
        else:
            self._settle(slot)

    def _advance(self, slot: _Slot) -> bool:
        """Move the slot to its next rank to check; False once its first free rank is known."""
        misses = 0
        while slot.free_at is None or slot.free_at - slot.taken_below > 1:
            if slot.free_at is None:
                rank = slot.taken_below + slot.gap
                slot.gap *= 2
            else:
                rank = (slot.taken_below + slot.free_at) // 2
            if self._probe(slot, rank):
                return True
            misses += 1
            if misses == MAX_DRAWS_PER_ROUND:
                self._exhausted(slot.column)
            # A value the session already holds costs no query, so the next rank is tried before galloping on.
            slot.gap = 1
        return False

    def _probe(self, slot: _Slot, rank: int) -> bool:
        """Point the slot at its value of that rank; False when that value is known taken without asking the database."""
        if rank > MAX_RANK:
            self._exhausted(slot.column)
        value = self._generator.value_at(type(slot.obj), slot.column, slot.origin, rank)
        if value is UNSET:
            self._exhausted(slot.column)
        slot.rank = rank
        proposed = self._proposed.setdefault(slot.column, set())
        if value in proposed or self._generator.is_used(slot.column, value):
            slot.taken_below = rank
            return False
        proposed.add(value)
        slot.value = value
        return True

    def _settle(self, slot: _Slot) -> int:
        """Give the object the value of the slot's first free rank, and return that rank."""
        assert slot.free_at is not None
        setattr(slot.obj, slot.attribute, slot.best)
        self._generator.remember(slot.column, {slot.best})
        return slot.free_at

    def _exhausted(self, column: Column[Any]) -> NoReturn:
        raise UniqueValueExhaustedError(
            f"unique column {column.table.key}.{column.key} still collides with existing rows"
            f" after {self._rounds} rounds — widen its generator or declare one in generators"
        )
