"""Core 7 scenarios — tranches 1 et 2: relationship-key segments, self-references, the pins."""

import pytest
from sqlalchemy import Column, ForeignKey, Integer, create_engine, event
from sqlalchemy.orm import Session, declarative_base, relationship

from _oracle import assert_referentially_consistent
from seedgraph import seed
from seedgraph.shape import MissingRequiredParentError, build_graph

Base = declarative_base()


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True)
    parent_id = Column(Integer, ForeignKey("categories.id"))
    children = relationship("Category", back_populates="parent")
    parent = relationship("Category", back_populates="children", remote_side=[id])


class StrictNode(Base):
    __tablename__ = "strict_nodes"
    id = Column(Integer, primary_key=True)
    parent_id = Column(Integer, ForeignKey("strict_nodes.id"), nullable=False)
    children = relationship("StrictNode", back_populates="parent")
    parent = relationship("StrictNode", back_populates="children", remote_side=[id])


class LoopA(Base):
    __tablename__ = "loop_as"
    id = Column(Integer, primary_key=True)
    bs = relationship("LoopB", back_populates="a")


class LoopB(Base):
    __tablename__ = "loop_bs"
    id = Column(Integer, primary_key=True)
    a_id = Column(Integer, ForeignKey("loop_as.id"), nullable=False)
    a = relationship("LoopA", back_populates="bs")


def test_shape_segment_matches_the_relationship_key_by_name():
    objects = build_graph(Category, {"category": 1, "children": 2})

    assert len(objects) == 3
    roots = [obj for obj in objects if obj.parent is None]
    assert len(roots) == 1
    children = [obj for obj in objects if obj.parent is not None]
    assert len(children) == 2


def test_children_under_a_nullable_self_fk_attach_their_branch_parent():
    [root, first, second] = build_graph(Category, {"category": 1, "children": 2})

    assert first.parent is root
    assert second.parent is root
    assert root.parent_id is None


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    @event.listens_for(engine, "connect")
    def enforce_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    with Session(engine) as session:
        yield session


def test_self_reference_flushes_under_fk_enforcement(session):
    graph = seed(session, Category, category=1, children=2)
    session.flush()

    assert_referentially_consistent(graph.categories)
    memberships = [(child.parent_id) for child in graph.categories if child.parent_id is not None]
    assert len(memberships) == 2
    assert set(memberships) == {root.id for root in graph.categories if root.parent_id is None}


def test_not_null_self_fk_refuses_the_root_with_a_clear_message():
    with pytest.raises(MissingRequiredParentError) as excinfo:
        build_graph(StrictNode, {"strictnode": 1})

    message = str(excinfo.value)
    assert "parent" in message
    assert "nullable" in message


def test_cyclic_fk_across_models_keeps_branch_parents():
    [root, first, second] = build_graph(LoopA, {"loopa": 1, "bs": 2})

    assert first.a is root
    assert second.a is root


def test_cycle_flushes_under_fk_enforcement(session):
    graph = seed(session, LoopA, loopa=1, bs=2)
    session.flush()

    assert_referentially_consistent(graph.loop_bs)
    assert all(b.a_id == graph.loop_as[0].id for b in graph.loop_bs)
