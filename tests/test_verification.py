"""Core 10 — T3: the database assigns the keys at flush, seedgraph verifies the graph afterwards."""

import itertools
import uuid

import pytest
from sqlalchemy import (
    JSON,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Text,
    Uuid,
    create_engine,
    event,
    func,
    select,
)
from sqlalchemy.orm import Session, declarative_base, relationship

from _oracle import assert_referentially_consistent
from seedgraph import IncoherentGraphError, UnsupportedPlaceholderError, seed
from seedgraph.verification import verify_graph

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


class Department(Base):
    __tablename__ = "departments"
    id = Column(Integer, primary_key=True)
    head_id = Column(Integer, ForeignKey("employees.id"))
    head = relationship("Employee", foreign_keys=[head_id])
    employees = relationship("Employee", foreign_keys="Employee.dept_id", back_populates="dept")


class Employee(Base):
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True)
    dept_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    dept = relationship("Department", foreign_keys=[dept_id], back_populates="employees")


class Tag(Base):
    __tablename__ = "tags"
    code = Column(Text, primary_key=True)


class Snapshot(Base):
    __tablename__ = "snapshots"
    payload = Column(JSON, primary_key=True)


class Token(Base):
    __tablename__ = "tokens"
    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    label = Column(Text, nullable=False)


class Order(Base):
    __tablename__ = "orders"
    k1 = Column(Integer, primary_key=True)
    k2 = Column(Integer, primary_key=True)
    items = relationship("OrderItem", back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True)
    k1 = Column(Integer, nullable=False)
    k2 = Column(Integer, nullable=False)
    __table_args__ = (ForeignKeyConstraint(["k1", "k2"], ["orders.k1", "orders.k2"]),)
    order = relationship("Order", back_populates="items")


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enforce_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_seed_returns_a_graph_already_written_with_real_keys(session):
    graph = seed(session, User, post=2)

    assert not session.new
    assert all(user.id is not None for user in graph.users)
    assert_referentially_consistent(graph.users + graph.posts)


def test_two_seeds_in_a_row_without_a_manual_flush_do_not_collide(session):
    first = seed(session, User, post=1)
    second = seed(session, User, post=1)

    ids = [user.id for user in first.users + second.users]
    assert len(set(ids)) == 6
    assert session.scalar(select(func.count()).select_from(Post)) == 6


def test_seed_continues_after_rows_the_application_wrote(session):
    session.add(User(name="already there"))
    session.commit()

    graph = seed(session, User)

    assert sorted(user.id for user in graph.users) == [2, 3, 4]


def test_a_uuid_primary_key_with_a_default_is_filled_by_its_default(session):
    graph = seed(session, Token)

    assert all(isinstance(token.id, uuid.UUID) for token in graph.tokens)


def test_a_natural_text_key_is_generated(session):
    graph = seed(session, Tag)

    assert len({tag.code for tag in graph.tags}) == 3


def test_natural_keys_skip_the_ones_already_in_the_database(session):
    seed(session, Tag)
    session.commit()
    with Session(session.get_bind()) as other:
        seed(other, Tag)
        other.commit()

    assert session.scalar(select(func.count(func.distinct(Tag.code)))) == 6


def test_a_composite_integer_key_and_its_composite_foreign_key_are_generated(session):
    graph = seed(session, Order, order=2, items=2)

    assert_referentially_consistent(graph.orders + graph.order_items)
    assert len({(order.k1, order.k2) for order in graph.orders}) == 2


def test_hundreds_of_rows_with_a_composite_key_do_not_run_out_of_values(session):
    graph = seed(session, Order, order=500)

    assert len(graph.orders) == 500


def test_a_primary_key_of_an_uncovered_type_is_refused(session):
    with pytest.raises(UnsupportedPlaceholderError, match="snapshots.payload"):
        seed(session, Snapshot)


def test_an_overridden_natural_primary_key_is_used(session):
    codes = iter(["red", "green", "blue"])

    graph = seed(session, Tag, overrides={Tag: {"code": lambda _: next(codes)}})

    assert [tag.code for tag in graph.tags] == ["red", "green", "blue"]


def test_a_composite_foreign_key_follows_its_overridden_composite_parent(session):
    counter = itertools.count(1)

    graph = seed(session, Order, order=2, items=2, overrides={Order: {"k1": lambda _: next(counter), "k2": 7}})

    assert_referentially_consistent(graph.orders + graph.order_items)
    assert {(item.k1, item.k2) for item in graph.order_items} == {(1, 7), (2, 7)}


def test_tables_referencing_each_other_seed_and_flush(session):
    graph = seed(session, Department, department=2, employees=2)

    assert_referentially_consistent(graph.departments + graph.employees)
    assert all(employee.dept_id is not None for employee in graph.employees)


def test_verify_graph_names_the_link_whose_foreign_key_disagrees():
    author = User(id=1, name="a")
    post = Post(id=1, title="t", author=author)
    post.author_id = 99

    with pytest.raises(IncoherentGraphError, match="Post.author: author_id=99 vs id=1"):
        verify_graph([post, author])
