"""Core 11 — T1: a shape walks many-to-many relationships, each count building new objects per parent."""

import pytest
from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    create_engine,
    event,
    func,
    select,
)
from sqlalchemy.orm import Session, declarative_base, relationship

from seedgraph import UnsupportedShapeDirectionError, seed
from seedgraph.shape import build_graph

Base = declarative_base()

articles_tags = Table(
    "articles_tags",
    Base.metadata,
    Column("article_id", ForeignKey("articles.id"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id"), primary_key=True),
)


class Article(Base):
    __tablename__ = "articles"
    id = Column(Integer, primary_key=True)
    title = Column(Text, nullable=False)
    tags = relationship("Tag", secondary=articles_tags, back_populates="articles")
    tag_names = relationship("Tag", secondary=articles_tags, viewonly=True)


class Tag(Base):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True)
    name = Column(String(40), nullable=False, unique=True)
    articles = relationship("Article", secondary=articles_tags, back_populates="tags")
    notes = relationship("TagNote", back_populates="tag")


class TagNote(Base):
    __tablename__ = "tag_notes"
    id = Column(Integer, primary_key=True)
    body = Column(Text, nullable=False)
    tag_id = Column(Integer, ForeignKey("tags.id"), nullable=False)
    tag = relationship("Tag", back_populates="notes")


class Book(Base):
    __tablename__ = "books"
    id = Column(Integer, primary_key=True)
    title = Column(Text, nullable=False)
    credits = relationship("Credit", back_populates="book")


class Writer(Base):
    __tablename__ = "writers"
    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)


class Credit(Base):
    __tablename__ = "credits"
    book_id = Column(Integer, ForeignKey("books.id"), primary_key=True)
    writer_id = Column(Integer, ForeignKey("writers.id"), primary_key=True)
    book = relationship("Book", back_populates="credits")
    writer = relationship("Writer")


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enforce_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _links(session):
    return session.scalar(select(func.count()).select_from(articles_tags))


def test_a_many_to_many_count_builds_new_objects_for_each_parent(session):
    graph = seed(session, Article, article=5, tags=3)

    assert len(graph.articles) == 5
    assert len(graph.tags) == 15
    assert all(len(article.tags) == 3 for article in graph.articles)
    assert _links(session) == 15


def test_a_many_to_many_key_matches_the_target_class_name_too(session):
    graph = seed(session, Article, article=2, tag=1)

    assert len(graph.tags) == 2
    assert _links(session) == 2


def test_objects_nest_under_a_many_to_many_level(session):
    graph = seed(session, Article, article=2, tags=2, tags__notes=2)

    assert len(graph.tag_notes) == 8
    assert all(note.tag_id == note.tag.id for note in graph.tag_notes)


def test_the_other_side_of_the_relationship_walks_too(session):
    graph = seed(session, Tag, tag=2, articles=3)

    assert len(graph.articles) == 6
    assert all(tag in article.tags for tag in graph.tags for article in tag.articles)
    assert _links(session) == 6


def test_a_view_only_relationship_is_refused():
    with pytest.raises(UnsupportedShapeDirectionError, match="tag_names.*viewonly"):
        build_graph(Article, {"tag_names": 2})


def test_a_parent_key_is_refused_and_points_to_parents():
    with pytest.raises(UnsupportedShapeDirectionError, match="parents"):
        build_graph(TagNote, {"tag": 1})


def test_an_association_class_goes_through_one_to_many_then_its_parent(session):
    graph = seed(session, Book, book=2, credits=1)

    [writer] = graph.writers
    assert len(graph.credits) == 2
    assert all(credit.writer is writer for credit in graph.credits)


@pytest.mark.postgres
def test_many_to_many_rows_are_written_on_postgres(pg_session):
    Base.metadata.create_all(pg_session.get_bind())

    seed(pg_session, Article, article=5, tags=3)
    pg_session.commit()

    assert _links(pg_session) == 15


def test_existing_objects_passed_as_parents_are_shared_by_every_generated_object(session):
    python, sql = Tag(name="python"), Tag(name="sql")
    session.add_all([python, sql])
    session.commit()

    graph = seed(session, Article, article=4, parents=[python, sql])

    assert all(set(article.tags) == {python, sql} for article in graph.articles)
    assert graph.tags == []
    assert _links(session) == 8


def test_shared_parents_add_to_the_objects_the_shape_builds(session):
    python = Tag(name="python")
    session.add(python)

    graph = seed(session, Article, article=2, tags=2, parents=[python])

    assert all(len(article.tags) == 3 and python in article.tags for article in graph.articles)
    assert len(graph.tags) == 4


async def test_the_async_facade_shares_an_existing_object():
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from seedgraph import seed_async

    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine) as session:
        python = Tag(name="python")
        session.add(python)
        await session.commit()

        await seed_async(session, Article, article=3, parents=[python])
        await session.commit()

        assert await session.scalar(select(func.count()).select_from(articles_tags)) == 3
    await engine.dispose()


@pytest.mark.postgres
def test_existing_objects_are_shared_on_postgres(pg_session):
    Base.metadata.create_all(pg_session.get_bind())
    python, sql = Tag(name="python"), Tag(name="sql")
    pg_session.add_all([python, sql])
    pg_session.commit()

    seed(pg_session, Article, article=5, parents=[python, sql])
    pg_session.commit()

    assert _links(pg_session) == 10
