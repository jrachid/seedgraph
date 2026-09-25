"""Read what already exists at the boundary: which candidate values a unique column already holds."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Column, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

__all__ = ["taken_values", "taken_values_async"]

CHUNK = 500


def taken_values(session: Session, column: Column[Any], candidates: Sequence[Any]) -> set[Any]:
    """Return the candidates the column already holds in the database."""
    taken = set()
    for start in range(0, len(candidates), CHUNK):
        taken.update(session.scalars(select(column).where(column.in_(candidates[start : start + CHUNK]))))
    return taken


async def taken_values_async(session: AsyncSession, column: Column[Any], candidates: Sequence[Any]) -> set[Any]:
    """Twin of ``taken_values`` on an AsyncSession."""
    taken = set()
    for start in range(0, len(candidates), CHUNK):
        taken.update(await session.scalars(select(column).where(column.in_(candidates[start : start + CHUNK]))))
    return taken
