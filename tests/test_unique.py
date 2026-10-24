"""Core 10 — T6: unique columns stay unique across calls, sessions and rows already in the database."""

import enum
import random
import shutil

import pytest
from sqlalchemy import (
    Boolean,
    Column,
    Enum,
    ForeignKey,
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
from sqlalchemy.orm import Session, declarative_base, relationship

from seedgraph import UniqueValueExhaustedError, seed, seed_async
from seedgraph.generators import generation_state, is_unique

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


def test_a_value_the_session_holds_but_has_not_flushed_is_skipped(engine):
    with Session(engine) as session:
        upcoming = seed(session, Member).members[0].email
        session.rollback()

    with Session(engine) as session:
        session.add(Member(email=upcoming))
        graph = seed(session, Member)
        session.flush()

    assert upcoming not in {member.email for member in graph.members}


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


class Locale(enum.Enum):
    EN = "en"
    FR = "fr"


class Org(Base):
    __tablename__ = "orgs"
    id = Column(Integer, primary_key=True)
    pages = relationship("Page", back_populates="org")
    guides = relationship("Guide", back_populates="org")
    seats = relationship("Seat", back_populates="org")


class Page(Base):
    __tablename__ = "pages"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("orgs.id"), nullable=False)
    position = Column(Integer, nullable=False)
    org = relationship("Org", back_populates="pages")
    __table_args__ = (UniqueConstraint("org_id", "position"),)


class Guide(Base):
    __tablename__ = "guides"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("orgs.id"), nullable=False)
    slug = Column(String(60), nullable=False)
    locale = Column(Enum(Locale), nullable=False)
    org = relationship("Org", back_populates="guides")
    __table_args__ = (Index("ix_guides_slug_locale", "slug", "locale", unique=True),)


class Seat(Base):
    __tablename__ = "seats"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("orgs.id"), nullable=False)
    is_primary = Column(Boolean, nullable=False)
    org = relationship("Org", back_populates="seats")
    __table_args__ = (UniqueConstraint("org_id", "is_primary"),)


def test_many_rows_under_one_parent_keep_a_multi_column_constraint(engine):
    with Session(engine) as session:
        graph = seed(session, Org, org=1, pages=50)
        session.commit()

        assert len({page.position for page in graph.pages}) == 50


def test_the_generated_column_with_the_widest_values_carries_the_constraint():
    assert is_unique(Page.__table__.c.position)
    assert is_unique(Guide.__table__.c.slug)
    assert not is_unique(Guide.__table__.c.locale)


def test_a_constraint_made_only_of_booleans_and_enums_is_left_to_the_database(engine):
    assert not is_unique(Seat.__table__.c.is_primary)

    with Session(engine) as session:
        graph = seed(session, Org, org=2, seats=1)
        session.commit()

        assert len(graph.seats) == 2


def test_a_second_session_keeps_a_multi_column_constraint(engine):
    for _ in range(2):
        with Session(engine) as session:
            seed(session, Org, org=1, pages=20)
            session.commit()

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Page)) == 40


@pytest.mark.postgres
def test_a_multi_column_constraint_holds_on_postgres(pg_session):
    Base.metadata.create_all(pg_session.get_bind())

    seed(pg_session, Org, org=2, pages=50, guides=20)
    pg_session.commit()

    assert pg_session.scalar(select(func.count()).select_from(Page)) == 100


def _file_engine(path):
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    return engine


def _seed_sessions(engine, sessions, count=20, generators=None):
    for _ in range(sessions):
        with Session(engine) as session:
            seed(session, Member, member=count, generators=generators)
            session.commit()


def test_thirty_sessions_on_one_persistent_database_all_succeed(tmp_path):
    engine = _file_engine(tmp_path / "unique.db")

    _seed_sessions(engine, 30)

    with Session(engine) as session:
        assert session.scalar(select(func.count(func.distinct(Member.email)))) == 600


@pytest.mark.parametrize("earlier", [16, 64])
def test_repair_queries_grow_with_the_logarithm_of_the_earlier_sessions(tmp_path, earlier):
    engine = _file_engine(tmp_path / "unique.db")
    _seed_sessions(engine, earlier)
    selects = []

    @event.listens_for(engine, "before_cursor_execute")
    def count(conn, cursor, statement, *args):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    _seed_sessions(engine, 1)

    assert len(selects) <= 2 * earlier.bit_length() + 3


def _repaired_on_two_copies(tmp_path, generators=None):
    _seed_sessions(_file_engine(tmp_path / "a.db"), 5, generators=generators)
    shutil.copy(tmp_path / "a.db", tmp_path / "b.db")
    emails = []
    for name in ("a.db", "b.db"):
        with Session(create_engine(f"sqlite:///{tmp_path / name}")) as session:
            emails.append([member.email for member in seed(session, Member, member=20, generators=generators).members])
    return emails


def test_two_copies_of_a_database_get_the_same_repaired_values(tmp_path):
    first, second = _repaired_on_two_copies(tmp_path)

    assert first == second


def test_a_custom_generator_drawing_from_ctx_fake_gets_the_same_repaired_values(tmp_path):
    generators = {Member: {"email": lambda ctx: f"{ctx.fake.user_name()}{ctx.fake.random_int(0, 99)}@custom.invalid"}}

    first, second = _repaired_on_two_copies(tmp_path, generators)

    assert first == second


def test_a_custom_generator_drawing_its_own_randomness_still_keeps_values_unique(tmp_path):
    draw = random.Random(7)
    generators = {Member: {"email": lambda _: f"user{draw.randrange(5000)}@own.invalid"}}
    engine = _file_engine(tmp_path / "unique.db")

    _seed_sessions(engine, 12, generators=generators)

    with Session(engine) as session:
        assert session.scalar(select(func.count(func.distinct(Member.email)))) == 240


def test_a_repair_leaves_the_main_value_stream_untouched(tmp_path):
    engine = _file_engine(tmp_path / "unique.db")
    _seed_sessions(engine, 1)
    states = []
    for target in (engine, _file_engine(tmp_path / "empty.db")):
        with Session(target) as session:
            seed(session, Member, member=20)
            states.append(generation_state(session.info).fake.random.getstate())

    assert states[0] == states[1]


async def test_the_async_facade_survives_many_sessions_on_one_database(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'unique.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    for _ in range(12):
        async with AsyncSession(engine) as session:
            await seed_async(session, Member, member=20)
            await session.commit()

    async with AsyncSession(engine) as session:
        count = await session.scalar(select(func.count(func.distinct(Member.email))))
    await engine.dispose()

    assert count == 240


@pytest.mark.postgres
def test_postgres_survives_many_sessions_on_one_database(pg_session):
    engine = pg_session.get_bind()
    Base.metadata.create_all(engine)

    _seed_sessions(engine, 12)

    assert pg_session.scalar(select(func.count(func.distinct(Member.email)))) == 240
