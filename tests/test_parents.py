"""Core 10 — T7: existing parents are linked, missing required parents are generated once and shared."""

import pytest
from sqlalchemy import Column, ForeignKey, Integer, Text, create_engine, event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session, declarative_base, relationship

from _oracle import assert_referentially_consistent
from seedgraph import (
    AmbiguousParentError,
    MissingRequiredParentError,
    UnattachedParentError,
    seed,
    seed_async,
)
from seedgraph.shape import build_graph

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    posts = relationship("Post", back_populates="author")


class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True)
    title = Column(Text, nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    author = relationship("User", back_populates="posts")
    comments = relationship("Comment", back_populates="post")


class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True)
    body = Column(Text, nullable=False)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    post = relationship("Post", back_populates="comments")
    author = relationship("User")


class Review(Base):
    __tablename__ = "reviews"
    id = Column(Integer, primary_key=True)
    body = Column(Text, nullable=False)
    reviewer_id = Column(Integer, ForeignKey("users.id"))
    reviewer = relationship("User")


class Hen(Base):
    __tablename__ = "hens"
    id = Column(Integer, primary_key=True)
    egg_id = Column(Integer, ForeignKey("eggs.id", use_alter=True), nullable=False)
    egg = relationship("Egg", foreign_keys=[egg_id])


class Egg(Base):
    __tablename__ = "eggs"
    id = Column(Integer, primary_key=True)
    hen_id = Column(Integer, ForeignKey("hens.id"), nullable=False)
    hen = relationship("Hen", foreign_keys=[hen_id])


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enforce_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine, tables=[User.__table__, Post.__table__, Comment.__table__, Review.__table__])
    with Session(engine) as session:
        yield session


def test_a_child_seeded_alone_gets_one_generated_parent_shared_by_all(session):
    graph = seed(session, Post)

    assert len(graph.posts) == 3
    assert len(graph.users) == 1
    assert all(post.author is graph.users[0] for post in graph.posts)


def test_generated_parents_are_shared_across_the_links_that_need_them(session):
    graph = seed(session, Comment)

    [post] = graph.posts
    [user] = graph.users
    assert post.author is user
    assert all(comment.post is post and comment.author is user for comment in graph.comments)
    assert_referentially_consistent(graph.comments + graph.posts)


def test_a_parent_already_in_the_database_is_linked_and_left_out_of_the_graph(session):
    alice = User(name="alice")
    session.add(alice)
    session.commit()

    graph = seed(session, Post, parents=[alice])

    assert all(post.author is alice for post in graph.posts)
    assert graph.users == []
    assert session.scalar(select(func.count()).select_from(User)) == 1


def test_a_parent_only_added_to_the_session_is_linked_too(session):
    alice = User(name="alice")
    session.add(alice)

    graph = seed(session, Post, parents=[alice])

    assert all(post.author_id == alice.id for post in graph.posts)


def test_a_provided_parent_fills_an_optional_link(session):
    alice = User(name="alice")
    session.add(alice)

    with_parent = seed(session, Review, parents=[alice])
    without_parent = seed(session, Review)

    assert all(review.reviewer is alice for review in with_parent.reviews)
    assert all(review.reviewer is None for review in without_parent.reviews)


def test_a_parent_outside_the_session_is_refused(session):
    with pytest.raises(UnattachedParentError, match="User"):
        seed(session, Post, parents=[User(name="stranger")])


def test_two_parents_of_the_same_type_are_refused(session):
    session.add_all([alice := User(name="alice"), bob := User(name="bob")])

    with pytest.raises(AmbiguousParentError, match="User"):
        seed(session, Post, parents=[alice, bob])


def test_a_loop_of_required_links_names_both_tables():
    with pytest.raises(MissingRequiredParentError, match="Egg.*Hen|Hen.*Egg"):
        build_graph(Egg, {})


async def test_the_async_facade_links_an_existing_parent():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all, tables=[User.__table__, Post.__table__])
    async with AsyncSession(engine) as session:
        alice = User(name="alice")
        session.add(alice)
        await session.commit()

        graph = await seed_async(session, Post, parents=[alice])

        assert all(post.author_id == alice.id for post in graph.posts)
    await engine.dispose()


@pytest.mark.postgres
def test_a_parent_from_postgres_is_linked(pg_session):
    Base.metadata.create_all(pg_session.get_bind(), tables=[User.__table__, Post.__table__])
    alice = User(name="alice")
    pg_session.add(alice)
    pg_session.commit()

    seed(pg_session, Post, parents=[alice])
    pg_session.commit()

    assert pg_session.scalar(select(func.count()).select_from(User)) == 1
    assert pg_session.scalar(select(func.count()).select_from(Post).where(Post.author_id == alice.id)) == 3
