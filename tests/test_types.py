"""Core 10 — T5: every generated value is one its column type accepts, or the column is refused."""

import enum
import uuid
from datetime import time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import (
    JSON,
    Column,
    Enum,
    Float,
    Integer,
    Interval,
    LargeBinary,
    Numeric,
    String,
    Text,
    Time,
    Uuid,
    create_engine,
    text,
)
from sqlalchemy.orm import Session, declarative_base

from seedgraph import UnsupportedPlaceholderError, seed
from seedgraph.shape import build_graph

Base = declarative_base()


class Status(enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"


class Profile(Base):
    __tablename__ = "profiles"
    id = Column(Integer, primary_key=True)
    status = Column(Enum(Status), nullable=False)
    kind = Column(Enum("admin", "member", name="kind"), nullable=False)
    name = Column(String(10), nullable=False)
    headline = Column(String(12), nullable=False)
    balance = Column(Numeric(5, 2), nullable=False)
    score = Column(Float, nullable=False)
    token = Column(Uuid, nullable=False)
    opens_at = Column(Time, nullable=False)
    lasts = Column(Interval, nullable=False)
    avatar = Column(LargeBinary, nullable=False)
    bio = Column(Text)
    settings = Column(JSON)
    created_by = Column(Text, server_default=text("'system'"))


class Blob(Base):
    __tablename__ = "blobs"
    id = Column(Integer, primary_key=True)
    payload = Column(JSON, nullable=False)


@pytest.fixture(scope="module")
def profiles():
    return build_graph(Profile, {"profile": 20})


def test_an_enum_column_gets_a_member_of_its_enum_class(profiles):
    assert all(isinstance(profile.status, Status) for profile in profiles)


def test_a_string_enum_column_gets_one_of_its_declared_values(profiles):
    assert {profile.kind for profile in profiles} <= {"admin", "member"}


def test_a_generated_string_fits_the_declared_length(profiles):
    assert all(len(profile.name) <= 10 for profile in profiles)
    assert all(len(profile.headline) <= 12 for profile in profiles)


def test_a_numeric_value_fits_its_precision_and_scale(profiles):
    for profile in profiles:
        assert isinstance(profile.balance, Decimal)
        assert abs(profile.balance) < 1000
        assert profile.balance.as_tuple().exponent >= -2


def test_float_uuid_time_interval_and_binary_columns_are_generated(profiles):
    for profile in profiles:
        assert isinstance(profile.score, float)
        assert isinstance(profile.token, uuid.UUID)
        assert isinstance(profile.opens_at, time)
        assert isinstance(profile.lasts, timedelta)
        assert isinstance(profile.avatar, bytes)


def test_a_nullable_column_is_filled_too(profiles):
    assert all(profile.bio for profile in profiles)


def test_a_nullable_column_of_an_uncovered_type_stays_empty(profiles):
    assert all(profile.settings is None for profile in profiles)


def test_a_server_default_column_is_left_to_the_database(profiles):
    assert all(profile.created_by is None for profile in profiles)


def test_a_required_column_of_an_uncovered_type_is_refused():
    with pytest.raises(UnsupportedPlaceholderError, match="blobs.payload"):
        build_graph(Blob, {"blob": 1})


def test_the_generated_profiles_are_written_on_sqlite():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Profile.__table__])
    with Session(engine) as session:
        graph = seed(session, Profile, profile=5)
        session.commit()

        assert len(graph.profiles) == 5


@pytest.mark.postgres
def test_the_generated_profiles_are_written_on_postgres(pg_session):
    Base.metadata.create_all(pg_session.get_bind(), tables=[Profile.__table__])

    graph = seed(pg_session, Profile, profile=20)
    pg_session.commit()

    assert len(graph.profiles) == 20
