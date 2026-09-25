"""Core 3 scenarios: shape parsing, graph building, and the seed() orchestration."""

import pytest
from sqlalchemy import Column, ForeignKey, Integer, LargeBinary, Table, Text, create_engine, event
from sqlalchemy.orm import Session, declarative_base, relationship

from _oracle import assert_referentially_consistent
from seedgraph import seed
from seedgraph.shape import (
    AmbiguousShapeKeyError,
    InvalidShapeCountError,
    MissingRequiredParentError,
    UnknownShapeKeyError,
    UnsupportedPlaceholderError,
    UnsupportedShapeDirectionError,
    build_graph,
)

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


class Mailbox(Base):
    __tablename__ = "mailboxes"
    id = Column(Integer, primary_key=True)
    received = relationship("Message", foreign_keys="Message.received_in_id")
    sent = relationship("Message", foreign_keys="Message.sent_from_id")


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    received_in_id = Column(Integer, ForeignKey("mailboxes.id"))
    sent_from_id = Column(Integer, ForeignKey("mailboxes.id"))


articles_tags = Table(
    "articles_tags",
    Base.metadata,
    Column("article_id", ForeignKey("articles.id"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id"), primary_key=True),
)


class Article(Base):
    __tablename__ = "articles"
    id = Column(Integer, primary_key=True)
    tags = relationship("Tag", secondary=articles_tags)


class Tag(Base):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True)


class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True)
    payload = Column(LargeBinary, nullable=False)


def _engine():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enforce_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def session():
    with Session(_engine()) as session:
        yield session


def test_seed_builds_root_objects_with_default_count(session):
    graph = seed(session, User)

    assert len(graph.users) == 3
    assert [user.id for user in graph.users] == [1, 2, 3]
    names = [user.name for user in graph.users]
    assert all(" " in name for name in names)
    assert len(set(names)) == 3
    assert len(session.new) == 3


def test_seed_root_count_key_overrides_default(session):
    graph = seed(session, User, user=5)

    assert len(graph.users) == 5
    assert [user.id for user in graph.users] == [1, 2, 3, 4, 5]


def test_seed_root_is_deterministic():
    with Session(_engine()) as first_session:
        first_graph = seed(first_session, User)
    with Session(_engine()) as second_session:
        second_graph = seed(second_session, User)

    assert [user.id for user in first_graph.users] == [user.id for user in second_graph.users] == [1, 2, 3]
    assert [user.name for user in first_graph.users] == [user.name for user in second_graph.users]


def test_unknown_shape_key_raises():
    with pytest.raises(UnknownShapeKeyError) as excinfo:
        build_graph(User, {"blog": 2})

    assert "blog" in str(excinfo.value)


def test_invalid_shape_count_raises():
    with pytest.raises(InvalidShapeCountError) as excinfo:
        build_graph(User, {"user": "deux"})

    assert "user" in str(excinfo.value)


def test_seed_builds_one_level_shape(session):
    graph = seed(session, User, post=2)

    assert len(graph.users) == 3
    assert len(graph.posts) == 6
    titles = [post.title for post in graph.posts]
    assert all(title.endswith(".") for title in titles)
    assert len(set(titles)) >= 2
    for user in graph.users:
        assert len(user.posts) == 2
        for post in user.posts:
            assert post.author is user
            assert post.author_id == user.id
    assert_referentially_consistent(graph.users + graph.posts)


def test_seed_zero_count_yields_no_children(session):
    graph = seed(session, User, post=0)

    assert len(graph.users) == 3
    assert graph.posts == []
    assert session.query(Post).count() == 0


def test_ambiguous_shape_key_raises():
    with pytest.raises(AmbiguousShapeKeyError) as excinfo:
        build_graph(Mailbox, {"message": 2})

    assert "received" in str(excinfo.value)
    assert "sent" in str(excinfo.value)


def test_parent_direction_key_raises():
    with pytest.raises(UnsupportedShapeDirectionError) as excinfo:
        build_graph(Post, {"user": 2})

    assert "user" in str(excinfo.value)
    assert "author" in str(excinfo.value)


def test_seed_builds_nested_shape(session):
    graph = seed(session, User, post=2, post__comment=3)

    assert len(graph.users) == 3
    assert len(graph.posts) == 6
    assert len(graph.comments) == 18
    for user in graph.users:
        assert len(user.posts) == 2
        for post in user.posts:
            assert len(post.comments) == 3
            for comment in post.comments:
                assert comment.post is post
                assert comment.post_id == post.id
                assert comment.author_id == post.author_id
    assert_referentially_consistent(graph.users + graph.posts + graph.comments)


def test_fallback_without_matching_ancestor_raises(session):
    with pytest.raises(MissingRequiredParentError) as excinfo:
        seed(session, Post, comment=3)

    assert "author" in str(excinfo.value)


def test_many_to_many_key_raises():
    with pytest.raises(UnsupportedShapeDirectionError) as excinfo:
        build_graph(Article, {"tag": 2})

    assert "tag" in str(excinfo.value)
    assert "secondary" in str(excinfo.value)


def test_unsupported_placeholder_type_raises():
    with pytest.raises(UnsupportedPlaceholderError) as excinfo:
        build_graph(Event, {})

    assert "payload" in str(excinfo.value)


def test_seed_continues_above_existing_rows(session):
    session.add_all([User(name=f"legacy-{index}", id=index) for index in range(1, 5)])
    session.commit()

    graph = seed(session, User, post=1)

    assert [user.id for user in graph.users] == [5, 6, 7]
    for user in graph.users:
        assert user.posts[0].author_id == user.id
