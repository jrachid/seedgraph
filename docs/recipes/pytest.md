# Seeding your own database in pytest

The four built-in fixtures (`seedgraph_graph`, `seedgraph_agraph` and their sessions) give each test a fresh in-memory SQLite. This recipe is for the other case: your tests run against your own engine — PostgreSQL in CI, SQLite locally — and each test must leave the database as it found it.

## One engine, one rolled-back session per test

`seed()` flushes but never commits. A session that rolls back at the end of each test therefore undoes everything the test seeded, with no cleanup code:

```python
import os

import pytest
from sqlalchemy import ForeignKey, create_engine, event, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

from seedgraph import seed


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    posts: Mapped[list["Post"]] = relationship(back_populates="author")


class Post(Base):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    author: Mapped[User] = relationship(back_populates="posts")


@pytest.fixture(scope="session")
def engine():
    engine = create_engine(os.environ.get("TEST_DATABASE_URL", "sqlite://"))
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def enforce_foreign_keys(dbapi_connection, _):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def session(engine):
    with Session(engine) as session:
        yield session
        session.rollback()
```

SQLite ignores foreign keys unless each connection turns them on. Without the `PRAGMA`, a broken link goes unnoticed — which is exactly the bug seedgraph exists to prevent.

## Writing the tests

```python
def test_each_post_belongs_to_the_user_it_was_seeded_under(session):
    graph = seed(session, User, post=2)

    for user in graph.users:
        assert [post.author_id for post in user.posts] == [user.id, user.id]


def test_a_test_starts_on_an_empty_database(session):
    seed(session, User, post=2)

    assert session.scalar(select(func.count()).select_from(Post)) == 6


def test_the_rows_of_the_previous_test_are_gone(session):
    assert session.scalar(select(func.count()).select_from(Post)) == 0
```

## When the code under test commits

A `commit()` inside the code under test ends the transaction the fixture meant to roll back. Bind the session to a connection whose outer transaction the fixture owns, as described in SQLAlchemy's [joining a session into an external transaction](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#joining-a-session-into-an-external-transaction-such-as-for-test-suites); `seed()` works unchanged on that session.

## Same values on every run

A new session replays the same generated values from the same seed, so a failing test fails the same way on the next run. Two calls to `seed()` in one session continue the sequence instead of repeating it, which keeps unique columns unique.
