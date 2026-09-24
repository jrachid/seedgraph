"""Core 5 scenarios — tranches 1 et 2: the overrides channel, then callables and the pins."""

import pytest
from faker import Faker
from sqlalchemy import Column, ForeignKey, Integer, String, Text, create_engine, event
from sqlalchemy.orm import Session, declarative_base, relationship

from _oracle import assert_referentially_consistent
from seedgraph import seed
from seedgraph.generators import GenerationContext, UnknownOverrideColumnError
from seedgraph.shape import build_graph

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    email = Column(String, nullable=False)

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

    post = relationship("Post", back_populates="comments")


class Nota(Base):
    __tablename__ = "notas"
    id = Column(Integer, primary_key=True)
    rating = Column(Integer, default=0)


def test_override_fixes_the_column_for_every_object_of_the_model():
    objects = build_graph(User, {"user": 3, "post": 1}, overrides={User: {"name": "alice"}})

    users = [obj for obj in objects if isinstance(obj, User)]
    posts = [obj for obj in objects if isinstance(obj, Post)]

    assert [user.name for user in users] == ["alice", "alice", "alice"]
    assert all(post.title.endswith(".") for post in posts)


def test_override_beats_generators_and_the_default():
    objects = build_graph(
        User,
        {"user": 1},
        generators={User: {"name": lambda ctx: "custom"}},
        overrides={User: {"name": "alice"}},
    )

    [user] = [obj for obj in objects if isinstance(obj, User)]

    assert user.name == "alice"
    assert "@" in user.email


def test_override_is_deterministic_across_rebuilds():
    def values(objects):
        return (
            [obj.name for obj in objects if isinstance(obj, User)],
            [obj.title for obj in objects if isinstance(obj, Post)],
        )

    first = values(build_graph(User, {"user": 2, "post": 1}, overrides={User: {"name": "alice"}}))
    second = values(build_graph(User, {"user": 2, "post": 1}, overrides={User: {"name": "alice"}}))

    assert first == second


def test_unknown_override_column_raises():
    with pytest.raises(UnknownOverrideColumnError) as excinfo:
        build_graph(User, {"user": 1}, overrides={User: {"namae": "x"}})

    assert "User" in str(excinfo.value)
    assert "namae" in str(excinfo.value)


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    @event.listens_for(engine, "connect")
    def enforce_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    with Session(engine) as session:
        yield session


def test_overrides_keyword_coexists_with_shape_and_generators(session):
    graph = seed(
        session,
        User,
        post=2,
        post__comment=1,
        generators={Comment: {"body": lambda ctx: f"commentaire-{ctx.column}"}},
        overrides={Post: {"title": "titre imposé"}},
    )

    assert len(graph.users) == 3
    assert len(graph.posts) == 6
    assert len(graph.comments) == 6
    assert all(post.title == "titre imposé" for post in graph.posts)
    assert all(comment.body == f"commentaire-{comment_body}" for comment_body in ["body"] for comment in graph.comments)
    assert_referentially_consistent(graph.users + graph.posts + graph.comments)


def test_override_callable_receives_the_context():
    contexts = []

    def override(ctx):
        contexts.append(ctx)
        return f"note pour {ctx.column}"

    first = build_graph(User, {"user": 2}, overrides={User: {"name": override}})
    second = build_graph(User, {"user": 2}, overrides={User: {"name": override}})

    assert len(contexts) == 4
    assert all(isinstance(ctx, GenerationContext) for ctx in contexts)
    assert all(isinstance(ctx.fake, Faker) for ctx in contexts)
    assert all(ctx.column == "name" for ctx in contexts)
    assert [obj.name for obj in first] == [obj.name for obj in second]


def test_override_callable_beats_the_custom_generator():
    objects = build_graph(
        User,
        {"user": 1},
        generators={User: {"name": lambda ctx: "custom"}},
        overrides={User: {"name": lambda ctx: "winner"}},
    )

    [user] = [obj for obj in objects if isinstance(obj, User)]

    assert user.name == "winner"


def test_overrides_never_touch_protected_columns(session):
    graph = seed(
        session,
        User,
        post=2,
        post__comment=1,
        overrides={
            User: {"id": "hijacked"},
            Post: {"id": "hijacked", "author_id": "hijacked"},
            Comment: {"id": "hijacked", "post_id": "hijacked"},
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


def test_override_reaches_a_non_eligible_column():
    nota = build_graph(Nota, {"nota": 1}, overrides={Nota: {"rating": 9}})[0]

    assert nota.rating == 9
