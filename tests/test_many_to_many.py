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
