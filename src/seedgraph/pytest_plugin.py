"""pytest plugin: a fresh sqlite session and a seed callable, served without configuration."""

try:
    from seedgraph import seed as _seed
    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001 — la garde : tout échec d'import ne doit pas casser les suites étrangères
    _seed = None
    _IMPORT_ERROR = exc

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

__all__ = ["graph", "session"]


def _fixture_error():
    return RuntimeError(
        "seedgraph failed to import; its pytest fixtures raise on first use"
        " instead of failing every foreign pytest run"
    )


@pytest.fixture()
def session():
    """Serve a fresh in-memory sqlite Session with foreign keys enforced."""
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enforce_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    with Session(engine) as fresh:
        yield fresh


@pytest.fixture()
def graph(session):
    """Serve a seed callable on the fresh session; tables are created on demand."""

    def make(model, /, generators=None, overrides=None, **shape):
        if _seed is None:
            raise _fixture_error() from _IMPORT_ERROR
        model.metadata.create_all(session.get_bind(), checkfirst=True)
        return _seed(session, model, generators=generators, overrides=overrides, **shape)

    return make
