import pytest
from sqlalchemy import ForeignKey, String, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from seedgraph import seed, seed_async

pytestmark = pytest.mark.postgres


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    posts: Mapped[list["Post"]] = relationship(back_populates="author")


class Post(Base):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    author: Mapped[User] = relationship(back_populates="posts")


def test_a_seeded_graph_flushes_on_postgres(pg_session):
    Base.metadata.create_all(pg_session.get_bind())

    graph = seed(pg_session, User, post=2)
    pg_session.flush()

    assert pg_session.scalar(select(func.count()).select_from(Post)) == 6
    assert all(post.author_id == post.author.id for post in graph.posts)


async def test_a_seeded_graph_flushes_on_async_postgres(pg_asession):
    await pg_asession.run_sync(lambda sync: Base.metadata.create_all(sync.get_bind()))

    await seed_async(pg_asession, User, post=2)
    await pg_asession.flush()

    assert await pg_asession.scalar(select(func.count()).select_from(Post)) == 6
