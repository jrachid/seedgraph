"""Read what already exists at the boundary: provided parents, and the values unique columns already hold."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from sqlalchemy import Column, select
from sqlalchemy.orm import Session

from seedgraph.exceptions import SeedgraphError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["UnattachedParentError", "check_parents_attached", "taken_values", "taken_values_async"]

CHUNK = 500


class UnattachedParentError(SeedgraphError):
    """A provided parent is neither pending nor persistent in the session seeding the graph."""


def check_parents_attached(session: Session, parents: Sequence[Any]) -> None:
    """Refuse any provided parent that the session does not hold, since flushing would insert it silently."""
    for parent in parents:
        if parent not in session:
            raise UnattachedParentError(
                f"parent {type(parent).__name__} is not in the session — add it, or load it, before seeding"
            )


def taken_values(session: Session, column: Column[Any], candidates: Sequence[Any]) -> set[Any]:
    """Return the candidates the column already holds in the database, without flushing the session."""
    taken: set[Any] = set()
    with session.no_autoflush:
        for start in range(0, len(candidates), CHUNK):
            taken.update(session.scalars(select(column).where(column.in_(candidates[start : start + CHUNK]))))
    return taken


async def taken_values_async(session: AsyncSession, column: Column[Any], candidates: Sequence[Any]) -> set[Any]:
    """Twin of ``taken_values`` on an AsyncSession."""
    taken: set[Any] = set()
    with session.sync_session.no_autoflush:
        for start in range(0, len(candidates), CHUNK):
            taken.update(await session.scalars(select(column).where(column.in_(candidates[start : start + CHUNK]))))
    return taken
