"""pytest plugin: a fresh sqlite session and a seed callable, served without configuration.

The package import is guarded: a failing import surfaces only on first fixture
use, never as a broken foreign pytest run.
"""

try:
    from seedgraph import seed as _seed
    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001 — la garde : tout échec d'import ne doit pas casser les suites étrangères
    _seed = None
    _IMPORT_ERROR = exc

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from seedgraph.generators import GeneratorMap, OverrideMap

__all__ = ["graph", "session"]


def _fixture_error() -> RuntimeError:
    return RuntimeError(
        "seedgraph failed to import; its pytest fixtures raise on first use"
        " instead of failing every foreign pytest run"
    )


@pytest.fixture()
def session() -> Iterator[Session]:
    """Serve a fresh in-memory sqlite Session with foreign keys enforced."""
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enforce_fk(dbapi_conn: Any, _: Any) -> None:
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    with Session(engine) as fresh:
        yield fresh


@pytest.fixture()
def graph(session: Session) -> Callable[..., Any]:
    """Serve a seed callable on the fresh session; tables are created on demand."""

    def make(
        model: type[Any],
        /,
        generators: GeneratorMap | None = None,
        overrides: OverrideMap | None = None,
        **shape: int,
    ) -> Any:
        if _seed is None:
            raise _fixture_error() from _IMPORT_ERROR
        model.metadata.create_all(session.get_bind(), checkfirst=True)
        return _seed(session, model, generators=generators, overrides=overrides, **shape)

    return make
