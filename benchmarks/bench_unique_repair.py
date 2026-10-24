"""Compare the unique repair strategies on the same cases; run it by hand: python benchmarks/bench_unique_repair.py [case ...]."""

import statistics
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, ForeignKey, String, create_engine, event, insert, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

import _legacy_uniqueness
import seedgraph
from _legacy_uniqueness import LegacyUniqueRepair
from seedgraph import UniqueValueExhaustedError, generators, seed
from seedgraph.boundary import taken_values
from seedgraph.generators import FieldGenerator
from seedgraph.uniqueness import UniqueRepair

PASSES = 5


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    email: Mapped[str] = mapped_column(String(120), unique=True)
    posts: Mapped[list["Post"]] = relationship(back_populates="author")


class Post(Base):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    author: Mapped[User] = relationship(back_populates="posts")
    comments: Mapped[list["Comment"]] = relationship(back_populates="post")


class Comment(Base):
    __tablename__ = "comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    body: Mapped[str]
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"))
    post: Mapped[Post] = relationship(back_populates="comments")


Repair = Callable[[Session, Sequence[Any], FieldGenerator], bool]


def _rounds_of(repair_class: type) -> Repair:
    def repair(session: Session, objects: Sequence[Any], generator: FieldGenerator) -> bool:
        repair = repair_class(objects, generator)
        regenerated = False
        while queries := repair.queries():
            taken = {column: taken_values(session, column, values) for column, values in queries}
            regenerated = regenerated or any(taken.values())
            repair.reject(taken)
        return regenerated

    return repair


def _whole_column(session: Session, objects: Sequence[Any], generator: FieldGenerator) -> bool:
    """The fallback: on a column's first collision, read the whole column once and avoid it locally."""
    repair = LegacyUniqueRepair(objects, generator)
    regenerated = False
    loaded: set[Any] = set()
    skipped = 0
    while queries := repair.queries():
        taken = {}
        for column, values in queries:
            taken[column] = taken_values(session, column, values)
            if taken[column] and column not in loaded:
                with session.no_autoflush:
                    existing = set(session.scalars(select(column)))
                generator.remember(column, existing)
                skipped += len(existing)
                loaded.add(column)
        regenerated = regenerated or any(taken.values())
        # Faker repeats itself, so skipping the loaded values takes more raw draws than there are values.
        generators.MAX_UNIQUE_ATTEMPTS = ATTEMPTS + 2 * skipped
        try:
            repair.reject(taken)
        finally:
            generators.MAX_UNIQUE_ATTEMPTS = ATTEMPTS
    return regenerated


ATTEMPTS = generators.MAX_UNIQUE_ATTEMPTS


@contextmanager
def _uncapped() -> Iterator[None]:
    saved = _legacy_uniqueness.MAX_ROUNDS
    _legacy_uniqueness.MAX_ROUNDS = 10**6
    try:
        yield
    finally:
        _legacy_uniqueness.MAX_ROUNDS = saved


@contextmanager
def _nothing() -> Iterator[None]:
    yield


STRATEGIES: dict[str, tuple[Repair, Callable[[], Any]]] = {
    "0.1.6": (_rounds_of(LegacyUniqueRepair), _nothing),
    "0.1.6 uncapped": (_rounds_of(LegacyUniqueRepair), _uncapped),
    "current": (_rounds_of(UniqueRepair), _nothing),
    "whole column": (_whole_column, _nothing),
}


@contextmanager
def strategy(name: str) -> Iterator[None]:
    repair, context = STRATEGIES[name]
    original = seedgraph.repair_unique
    seedgraph.repair_unique = repair
    try:
        with context():
            yield
    finally:
        seedgraph.repair_unique = original


def _selects(engine: Engine) -> list[str]:
    seen: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def count(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            seen.append(statement)

    return seen


def _session(engine: Engine, commit: bool, **shape: int) -> float:
    start = time.perf_counter()
    with Session(engine) as session:
        seed(session, User, **shape)
        if commit:
            session.commit()
        else:
            session.rollback()
    return time.perf_counter() - start


def _median(engine: Engine, **shape: int) -> float:
    return statistics.median(_session(engine, commit=False, **shape) for _ in range(PASSES))


def sessions(engine: Engine, name: str, total: int, users: int, report: set[int]) -> None:
    """Seed `total` sessions of `users` users on one database; print the reported ones and the failures."""
    selects = _selects(engine)
    failures = 0
    start = time.perf_counter()
    with strategy(name):
        for number in range(1, total + 1):
            try:
                if number in report:
                    elapsed = _median(engine, user=users)
                    selects.clear()
                    _session(engine, commit=False, user=users)
                    print(f"  {name:>14} session {number:>3}: {elapsed * 1000:8.1f} ms, {len(selects):>3} SELECT")
                _session(engine, commit=True, user=users)
            except UniqueValueExhaustedError:
                failures += 1
                if number in report:
                    print(f"  {name:>14} session {number:>3}: failed")
    total_time = time.perf_counter() - start
    print(f"  {name:>14} all {total} sessions: {total_time:.1f} s with medians, {failures} failures")


def _sqlite(directory: Path, label: str) -> Engine:
    engine = create_engine(f"sqlite:///{directory / label}.db")
    Base.metadata.create_all(engine)
    return engine


def case_empty(directory: Path) -> None:
    print("empty database, README shape (3 users, 2 posts each, 3 comments each) and 5000 users with 2 posts each")
    for name in STRATEGIES:
        for label, shape in (("readme", {"post": 2, "post__comment": 3}), ("large", {"user": 5000, "post": 2})):
            engine = _sqlite(directory, f"empty-{label}-{name}")
            print(f"  {name:>14} {label:>6}: {_median(engine, **shape) * 1000:8.1f} ms")


def case_500x100(directory: Path) -> None:
    print("100 sessions of 500 users on one SQLite file")
    for name in STRATEGIES:
        sessions(_sqlite(directory, f"500-{name}"), name, 100, 500, {2, 10, 11, 50, 100})


def case_2000x30(directory: Path) -> None:
    print("30 sessions of 2000 users on one SQLite file")
    for name in STRATEGIES:
        sessions(_sqlite(directory, f"2000-{name}"), name, 30, 2000, {2, 10, 30})


def case_foreign(directory: Path) -> None:
    print("second session of 500 users on a table holding 100 000 rows seedgraph never generated")
    for name in STRATEGIES:
        engine = _sqlite(directory, f"foreign-{name}")
        with engine.begin() as connection:
            rows = [{"name": "x", "email": f"foreign{i}@elsewhere.invalid"} for i in range(100_000)]
            connection.execute(insert(User.__table__), rows)
        sessions(engine, name, 2, 500, {2})


def case_postgres(directory: Path) -> None:
    from testcontainers.community.postgres import PostgresContainer

    print("20 sessions of 500 users on PostgreSQL")
    with PostgresContainer("postgres:16-alpine", driver="psycopg") as container:
        engine = create_engine(container.get_connection_url())
        for name in STRATEGIES:
            Base.metadata.drop_all(engine)
            Base.metadata.create_all(engine)
            sessions(engine, name, 20, 500, {2, 10, 11, 20})


CASES = {
    "empty": case_empty,
    "500x100": case_500x100,
    "2000x30": case_2000x30,
    "foreign": case_foreign,
    "postgres": case_postgres,
}

if __name__ == "__main__":
    chosen = sys.argv[1:] or list(CASES)
    with tempfile.TemporaryDirectory() as directory:
        for case in chosen:
            CASES[case](Path(directory))
