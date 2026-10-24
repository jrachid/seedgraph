"""The unique repair against the one frozen at 0.1.6: same output without collision, same guarantees with collisions."""

from contextlib import contextmanager

from hypothesis import example, given
from hypothesis import strategies as st
from sqlalchemy import Column, Integer, String, create_engine, insert, select
from sqlalchemy.orm import Session, declarative_base

import seedgraph
from _legacy_uniqueness import LegacyUniqueRepair
from seedgraph import UniqueValueExhaustedError, seed
from seedgraph.boundary import taken_values
from seedgraph.generators import FieldGenerator, GenerationState, generation_state

Base = declarative_base()


class Member(Base):
    __tablename__ = "members"
    id = Column(Integer, primary_key=True)
    email = Column(String(120), nullable=False, unique=True)


class Account(Base):
    __tablename__ = "accounts"
    id = Column(Integer, primary_key=True)
    username = Column(String(60), nullable=False, unique=True)
    email = Column(String(120), nullable=False, unique=True)


def _legacy_repair(session, objects, generator):
    repair = LegacyUniqueRepair(objects, generator)
    while queries := repair.queries():
        repair.reject({column: taken_values(session, column, values) for column, values in queries})


@contextmanager
def _repaired_by(legacy):
    original = seedgraph.repair_unique
    if legacy:
        seedgraph.repair_unique = _legacy_repair
    try:
        yield
    finally:
        seedgraph.repair_unique = original


def _database(model, rows):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    if rows:
        with engine.begin() as connection:
            connection.execute(insert(model.__table__), rows)
    return engine


def _stream(model, column, count):
    """The first values a new session generates for a unique column: what earlier sessions leave in the database."""
    generator = FieldGenerator(state=GenerationState())
    return [generator.value_for(model, model.__table__.c[column]) for _ in range(count)]


def _seed(legacy, engine, model, columns, generators=None, **shape):
    """Seed once; return the generated values and the next draw of the stream, or None when the column ran out."""
    with _repaired_by(legacy), Session(engine) as session:
        try:
            graph = seed(session, model, generators=generators, **shape)
        except UniqueValueExhaustedError:
            return None
        rows = [tuple(getattr(obj, column) for column in columns) for obj in getattr(graph, model.__tablename__)]
        return rows, generation_state(session.info).fake.random_int(0, 10**9)


def _existing(engine, column):
    with Session(engine) as session:
        return set(session.scalars(select(column)))


def _foreign(count):
    return [{"email": f"foreign{i}@elsewhere.invalid"} for i in range(count)]


@given(count=st.integers(1, 60), foreign=st.integers(0, 50))
def test_without_collision_the_values_and_the_stream_match_the_frozen_repair(count, foreign):
    outcomes = [_seed(legacy, _database(Member, _foreign(foreign)), Member, ["email"], member=count) for legacy in (True, False)]

    assert outcomes[0] == outcomes[1]


@given(previous=st.integers(1, 9), per_session=st.integers(1, 40), count=st.integers(1, 60), foreign=st.integers(0, 30))
def test_with_collisions_values_stay_unique_new_and_never_fail_where_the_frozen_repair_succeeds(previous, per_session, count, foreign):
    rows = [{"email": email} for email in _stream(Member, "email", previous * per_session)] + _foreign(foreign)
    legacy = _seed(True, _database(Member, rows), Member, ["email"], member=count)
    engine = _database(Member, rows)
    existing = _existing(engine, Member.email)

    outcome = _seed(False, engine, Member, ["email"], member=count)

    assert legacy is None or outcome is not None
    emails = {email for (email,) in outcome[0]}
    assert len(emails) == count
    assert not emails & existing


@given(previous=st.integers(0, 6), count=st.integers(1, 40))
def test_two_unique_columns_of_one_table_are_repaired_together(previous, count):
    usernames = _stream(Account, "username", previous * count)
    rows = [{"username": username, "email": f"{i}@seeded.invalid"} for i, username in enumerate(usernames)]
    legacy = _seed(True, _database(Account, rows), Account, ["username", "email"], account=count)
    engine = _database(Account, rows)
    existing = _existing(engine, Account.username)

    outcome = _seed(False, engine, Account, ["username", "email"], account=count)

    assert legacy is None or outcome is not None
    assert len({username for username, _ in outcome[0]}) == count == len({email for _, email in outcome[0]})
    assert not {username for username, _ in outcome[0]} & existing


@given(space=st.integers(5, 120), taken=st.integers(0, 60), count=st.integers(1, 60))
@example(space=63, taken=15, count=44)
@example(space=87, taken=59, count=57)
def test_a_small_custom_value_space_fails_no_more_often_than_with_the_frozen_repair(space, taken, count):
    generators = {Member: {"email": lambda ctx: f"u{ctx.fake.random_int(0, space - 1)}@small.invalid"}}
    rows = [{"email": f"u{i}@small.invalid"} for i in range(0, min(taken, space), 2)]
    legacy = _seed(True, _database(Member, rows), Member, ["email"], generators=generators, member=count)
    engine = _database(Member, rows)
    existing = _existing(engine, Member.email)

    outcome = _seed(False, engine, Member, ["email"], generators=generators, member=count)

    assert legacy is None or outcome is not None
    if outcome is not None:
        emails = {email for (email,) in outcome[0]}
        assert len(emails) == count
        assert not emails & existing
