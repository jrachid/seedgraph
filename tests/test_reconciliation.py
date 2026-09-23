"""Core 2 scenarios: PK reservation, FK reconciliation before any flush, the boundary bridge."""

import pytest
from sqlalchemy import Column, Integer, Text
from sqlalchemy.orm import declarative_base

from seedgraph.reconciliation import UnsupportedPrimaryKeyError, reconcile_graph

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)


class Tag(Base):
    __tablename__ = "tags"
    code = Column(Text, primary_key=True)


def _users(count=3):
    return [User(name=f"user-{index}") for index in range(count)]


def test_reserve_assigns_ids_above_existing_maxima():
    users = _users()

    reconcile_graph(users, existing_maxima={"users": {"id": 10}})

    assert [user.id for user in users] == [11, 12, 13]


def test_reserve_starts_at_one_without_maxima():
    users = _users()

    reconcile_graph(users)

    assert [user.id for user in users] == [1, 2, 3]


def test_reserve_never_overwrites_a_real_pk():
    users = _users()
    users[1].id = 999

    reconcile_graph(users, existing_maxima={"users": {"id": 10}})

    assert users[1].id == 999
    assert users[0].id == 11
    assert users[2].id == 12


def test_reserve_is_deterministic_across_rebuilds():
    first = _users()
    second = _users()

    reconcile_graph(first, existing_maxima={"users": {"id": 10}})
    reconcile_graph(second, existing_maxima={"users": {"id": 10}})

    assert [user.id for user in first] == [user.id for user in second] == [11, 12, 13]


def test_unsupported_pk_type_raises():
    tags = [Tag()]

    with pytest.raises(UnsupportedPrimaryKeyError) as excinfo:
        reconcile_graph(tags)

    assert "tags" in str(excinfo.value)
    assert "code" in str(excinfo.value)
