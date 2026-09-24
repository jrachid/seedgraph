"""Core 4 scenarios — tranche 1: the default Faker layer, realistic, distinct, deterministic."""

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import declarative_base, relationship

from seedgraph.shape import build_graph

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    email = Column(String, nullable=False)

    posts = relationship("Post", back_populates="author")
    labels = relationship("Label")


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

    post = relationship("Post", back_populates="comments")


class Item(Base):
    __tablename__ = "items"
    id = Column(Integer, primary_key=True)
    position = Column(Integer, nullable=False)


class Label(Base):
    __tablename__ = "labels"
    id = Column(Integer, primary_key=True)
    tagline = Column(Text, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"))


class Moment(Base):
    __tablename__ = "moments"
    id = Column(Integer, primary_key=True)
    scheduled_at = Column(DateTime, nullable=False)
    all_day = Column(Boolean, nullable=False)
    anniversary = Column(Date, nullable=False)


def test_generated_values_are_realistic_not_placeholders():
    [user, post, comment] = build_graph(User, {"user": 1, "post": 1, "post__comment": 1})

    assert user.name != "users-0"
    assert " " in user.name
    assert "@" in user.email
    assert post.title.endswith(".")
    assert comment.body


def test_generated_values_are_distinct_within_a_seed():
    objects = build_graph(User, {"post": 6})
    users = [obj for obj in objects if isinstance(obj, User)]
    posts = [obj for obj in objects if isinstance(obj, Post)]

    assert len({user.name for user in users}) == 3
    assert len({post.title for post in posts}) >= 2


def test_generation_is_deterministic_across_rebuilds():
    def values(objects):
        return (
            [user.name for user in objects if isinstance(user, User)],
            [post.title for post in objects if isinstance(post, Post)],
            [comment.body for comment in objects if isinstance(comment, Comment)],
        )

    first = values(build_graph(User, {"post": 2, "post__comment": 1}))
    second = values(build_graph(User, {"post": 2, "post__comment": 1}))

    assert first == second


def test_name_heuristics_pick_domain_providers():
    [user, label] = build_graph(User, {"user": 1, "label": 1})

    assert "@" in user.email
    assert " " in user.name
    assert label.tagline.endswith(".")


def test_integer_columns_get_bounded_random_values():
    items = build_graph(Item, {"item": 1})
    [item] = items

    assert isinstance(item.position, int)
    assert 0 <= item.position <= 100