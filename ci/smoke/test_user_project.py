"""A user's project on an installed seedgraph, under pytest's and pytest-asyncio's default settings."""

import pytest
from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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


def test_sync_fixture(seedgraph_graph):
    graph = seedgraph_graph(User, post=2)

    assert len(graph.posts) == 6


@pytest.mark.asyncio
async def test_async_fixture(seedgraph_agraph):
    graph = await seedgraph_agraph(User, post=2)

    assert len(graph.posts) == 6
