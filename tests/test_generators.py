"""Core 4 scenarios — tranches 1 à 3: the Faker default layer, the custom channel, the pins."""

from datetime import date, datetime

import pytest
from faker import Faker
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    create_engine,
    event,
)
from sqlalchemy.orm import Session, declarative_base, relationship

from seedgraph import seed
from seedgraph.generators import (
    GenerationContext,
    UnknownGeneratorColumnError,
    UnsupportedPlaceholderError,
)
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


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    @event.listens_for(engine, "connect")
    def enforce_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    with Session(engine) as session:
        yield session


def test_custom_generator_overrides_the_default():
    objects = build_graph(User, {"user": 2, "post": 1}, generators={User: {"name": lambda ctx: "custom-name"}})

    users = [obj for obj in objects if isinstance(obj, User)]
    posts = [obj for obj in objects if isinstance(obj, Post)]

    assert [user.name for user in users] == ["custom-name", "custom-name"]
    assert all(post.title.endswith(".") for post in posts)


def test_custom_generator_receives_the_context():
    contexts = []

    def generator(ctx):
        contexts.append(ctx)
        return f"custom-{ctx.column}"

    first = build_graph(User, {"user": 2}, generators={User: {"name": generator}})
    second = build_graph(User, {"user": 2}, generators={User: {"name": generator}})

    assert len(contexts) == 4
    assert all(isinstance(ctx, GenerationContext) for ctx in contexts)
    assert all(isinstance(ctx.fake, Faker) for ctx in contexts)
    assert all(ctx.column == "name" for ctx in contexts)
    assert [obj.name for obj in first] == [obj.name for obj in second]


def test_unknown_generator_column_raises():
    with pytest.raises(UnknownGeneratorColumnError) as excinfo:
        build_graph(User, {"user": 1}, generators={User: {"namae": lambda ctx: "x"}})

    assert "User" in str(excinfo.value)
    assert "namae" in str(excinfo.value)


def test_generators_keyword_coexists_with_shape(session):
    graph = seed(
        session,
        User,
        post=2,
        generators={Post: {"title": lambda ctx: f"custom-{ctx.column}"}},
    )

    assert len(graph.users) == 3
    assert len(graph.posts) == 6
    assert all(post.title == f"custom-{context_column}" for context_column in ["title"] for post in graph.posts)
    for post in graph.posts:
        assert post.author_id == post.author.id

class ExoticTypeDecorator(TypeDecorator):
    impl = String

    def process_bind_param(self, value, dialect):
        return value


class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    fingerprint = Column(ExoticTypeDecorator(), nullable=False)


def test_datetime_boolean_date_columns_are_generated():
    moments = build_graph(Moment, {"moment": 2})

    assert all(isinstance(moment.scheduled_at, datetime) for moment in moments)
    assert all(isinstance(moment.all_day, bool) for moment in moments)
    assert all(isinstance(moment.anniversary, date) for moment in moments)


def test_unknown_column_type_still_raises():
    with pytest.raises(UnsupportedPlaceholderError) as excinfo:
        build_graph(Document, {"document": 1})

    assert "fingerprint" in str(excinfo.value)


def test_pk_and_fk_are_never_generated(session):
    graph = seed(
        session,
        User,
        post=2,
        post__comment=1,
        generators={
            User: {"id": lambda ctx: "pk-hijacked"},
            Post: {"id": lambda ctx: "pk-hijacked", "author_id": lambda ctx: "fk-hijacked"},
            Comment: {"id": lambda ctx: "pk-hijacked", "post_id": lambda ctx: "fk-hijacked"},
        },
    )

    assert [user.id for user in graph.users] == [1, 2, 3]
    for user in graph.users:
        for post in user.posts:
            assert isinstance(post.id, int)
            assert post.author_id == user.id
            for comment in post.comments:
                assert isinstance(comment.id, int)
                assert comment.post_id == post.id


def test_two_seeds_in_one_session_continue_the_same_faker_sequence(session):
    first = seed(session, User)
    second = seed(session, User)

    first_emails = {user.email for user in first.users}
    assert first_emails.isdisjoint(user.email for user in second.users)


def test_a_new_session_replays_the_same_values(session):
    first = [user.email for user in seed(session, User).users]
    with Session(session.get_bind()) as other:
        replayed = [user.email for user in seed(other, User).users]

    assert first == replayed
