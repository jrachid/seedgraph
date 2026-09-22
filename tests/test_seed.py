"""The first red test.

Fails until seed() produces a graph where every FK column points at a real PK
in the same graph. This is the invariant the whole library exists for.
"""

import pytest
from sqlalchemy import Column, ForeignKey, Integer, Text, create_engine, event
from sqlalchemy.orm import Session, declarative_base, relationship

from seedgraph import seed

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


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    @event.listens_for(engine, "connect")
    def enforce_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    with Session(engine) as session:
        yield session


def test_seed_returns_consistent_graph(session):
    graph = seed(session, User, post=2, post__comment=3)

    assert len(graph.users) == 3
    for user in graph.users:
        assert len(user.posts) == 2
        for post in user.posts:
            # THE invariant: no phantom FK, ever.
            assert post.author_id == user.id
            assert post in user.posts
            assert len(post.comments) == 3
            for comment in post.comments:
                assert comment.post_id == post.id
                assert comment.author_id in {u.id for u in graph.users}


def test_seed_persists_without_fk_violation(session):
    graph = seed(session, User, post=2, post__comment=3)
    session.flush()

    user_count = session.query(User).count()
    post_count = session.query(Post).count()
    comment_count = session.query(Comment).count()

    assert (user_count, post_count, comment_count) == (3, 6, 18)
