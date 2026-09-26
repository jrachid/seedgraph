# Testing a FastAPI endpoint

Seed the graph in the test, hand the same session to the application through `dependency_overrides`, and call the endpoint: the application reads rows that were never committed, and the test rolls them back at the end.

## The application

```python
from typing import Annotated

from fastapi import Depends, FastAPI
from sqlalchemy import ForeignKey, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    posts: Mapped[list["Post"]] = relationship(back_populates="author")


class Post(Base):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    author: Mapped[User] = relationship(back_populates="posts")


production_engine = create_engine("sqlite:///app.db")


def get_session():
    with Session(production_engine) as session:
        yield session


app = FastAPI()


@app.get("/users/{user_id}/posts")
def list_posts(user_id: int, session: Annotated[Session, Depends(get_session)]) -> list[dict]:
    posts = session.scalars(select(Post).where(Post.author_id == user_id).order_by(Post.id))
    return [{"id": post.id, "title": post.title} for post in posts]
```

## The tests

`TestClient` runs synchronous endpoints in a worker thread. An in-memory SQLite gives each thread its own empty database unless the engine keeps a single connection, hence `StaticPool`:

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool

from seedgraph import seed


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
        session.rollback()
    engine.dispose()


@pytest.fixture()
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_a_user_sees_only_their_own_posts(session, client):
    graph = seed(session, User, user=2, post=3)
    alice, bob = graph.users

    response = client.get(f"/users/{alice.id}/posts")

    assert response.status_code == 200
    assert [post["id"] for post in response.json()] == [post.id for post in alice.posts]
    assert not {post.id for post in bob.posts} & {post["id"] for post in response.json()}


def test_a_user_without_posts_gets_an_empty_list(session, client):
    graph = seed(session, User)

    assert client.get(f"/users/{graph.users[0].id}/posts").json() == []
```

Against PostgreSQL, drop `StaticPool` and `check_same_thread`: every thread goes through the same session object, so it sees the same transaction.
