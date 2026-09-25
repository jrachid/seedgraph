"""Core 9 scenarios — tranche 1: the async facade, fresh maxima reading, mixed suites."""

import pytest
from sqlalchemy import Column, ForeignKey, Integer, Text, event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, relationship

from _oracle import assert_referentially_consistent
from seedgraph import seed, seed_async

Base = declarative_base()


class User(Base):
    __tablename__ = "async_users"
    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    email = Column(Text, nullable=False)

    posts = relationship("Post", back_populates="author")


class Post(Base):
    __tablename__ = "async_posts"
    id = Column(Integer, primary_key=True)
    title = Column(Text, nullable=False)
    author_id = Column(Integer, ForeignKey("async_users.id"), nullable=False)

    author = relationship("User", back_populates="posts")


@pytest.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite://")

    @event.listens_for(engine.sync_engine, "connect")
    def enforce_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine) as fresh:
        yield fresh
    await engine.dispose()


async def test_seed_async_builds_a_coherent_graph(session):
    graph = await seed_async(session, User, post=2)
    await session.flush()

    assert len(graph.async_users) == 3
    assert len(graph.async_posts) == 6
    assert_referentially_consistent(graph.async_users + graph.async_posts)


async def test_seed_async_restarts_above_existing_rows(session):
    [existing_row := User(id=2, name="legacy", email="legacy@x")] and session.add(existing_row)
    await session.commit()

    graph = await seed_async(session, User)
    await session.flush()

    assert [user.id for user in graph.async_users] == [3, 4, 5]
    assert len({user.name for user in graph.async_users}) == 3


def test_seed_and_seed_async_coexist_in_one_suite():
    assert callable(seed)
    assert callable(seed_async)
    assert seed is not None and "async" not in seed.__doc__.lower()


async def test_both_channels_in_one_async_file(session):
    graph = await seed_async(session, User, post=1)
    assert callable(seed)
    assert len(graph.async_posts) == 3
    assert_referentially_consistent(graph.async_users + graph.async_posts)
