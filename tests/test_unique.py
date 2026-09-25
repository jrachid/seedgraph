"""Core 10 — T6: unique columns stay unique across calls, sessions and rows already in the database."""

import pytest
from sqlalchemy import (
    Column,
    Index,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    event,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session, declarative_base

from seedgraph import UniqueValueExhaustedError, seed, seed_async

Base = declarative_base()


class Member(Base):
    __tablename__ = "members"
    id = Column(Integer, primary_key=True)
    email = Column(String(120), nullable=False, unique=True)


class Account(Base):
    __tablename__ = "accounts"
    id = Column(Integer, primary_key=True)
    username = Column(String(60), nullable=False)
    __table_args__ = (UniqueConstraint("username"),)


class Badge(Base):
    __tablename__ = "badges"
    id = Column(Integer, primary_key=True)
    code = Column(String(60), nullable=False)
    __table_args__ = (Index("ix_badges_code", "code", unique=True),)


@pytest.fixture()
def engine():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enforce_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine


def test_thousands_of_rows_keep_a_unique_column_unique(engine):
    with Session(engine) as session:
        graph = seed(session, Member, member=3000)
        session.commit()
        emails = {member.email for member in graph.members}

    assert len(emails) == 3000


@pytest.mark.parametrize(("model", "column"), [(Member, "email"), (Account, "username"), (Badge, "code")])
def test_a_new_session_on_a_populated_database_skips_the_values_already_taken(engine, model, column):
    with Session(engine) as session:
        seed(session, model)
        session.commit()

    with Session(engine) as session:
        seed(session, model)
        session.commit()
        values = session.scalars(select(getattr(model, column))).all()

    assert len(set(values)) == 6


def test_a_generator_that_cannot_produce_new_values_is_reported(engine):
    with Session(engine) as session, pytest.raises(UniqueValueExhaustedError, match="members.email"):
        seed(session, Member, generators={Member: {"email": lambda _: "same@example.com"}})


def test_an_overridden_unique_value_is_never_regenerated(engine):
    with Session(engine) as session, pytest.raises(IntegrityError):
        seed(session, Member, overrides={Member: {"email": "same@example.com"}})


async def test_the_async_facade_skips_the_values_already_taken(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'unique.db'}"
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    for _ in range(2):
        async with AsyncSession(engine) as session:
            await seed_async(session, Member)
            await session.commit()

    async with AsyncSession(engine) as session:
        count = await session.scalar(select(func.count(func.distinct(Member.email))))
    await engine.dispose()

    assert count == 6


@pytest.mark.postgres
def test_postgres_rows_from_an_earlier_run_do_not_block_a_new_seed(pg_session):
    engine = pg_session.get_bind()
    Base.metadata.create_all(engine)
    for _ in range(2):
        with Session(engine) as session:
            seed(session, Member, member=50)
            session.commit()

    assert pg_session.scalar(select(func.count(func.distinct(Member.email)))) == 100
