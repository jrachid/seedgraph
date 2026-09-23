"""Core 1 scenarios: the FK dependency graph, the strict order, the refusal of undeclared cycles."""

from sqlalchemy import Column, ForeignKey, ForeignKeyConstraint, Integer, MetaData, Table, Text
from sqlalchemy.orm import declarative_base, relationship

from seedgraph.topology import dependency_graph

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


class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True)
    body = Column(Text, nullable=False)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    post = relationship("Post")
    author = relationship("User")


def test_dependency_graph_builds_edges_from_model_metadata():
    graph = dependency_graph(User)

    assert graph == {"users": set(), "posts": {"users"}, "comments": {"users", "posts"}}


def test_dependency_graph_accepts_metadata_object():
    graph = dependency_graph(Base.metadata)

    assert graph == {"users": set(), "posts": {"users"}, "comments": {"users", "posts"}}


def test_composite_fk_counts_as_one_edge():
    metadata = MetaData()
    Table("orders", metadata, Column("k1", Integer, primary_key=True), Column("k2", Integer, primary_key=True))
    Table(
        "order_items",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("k1", Integer),
        Column("k2", Integer),
        ForeignKeyConstraint(["k1", "k2"], ["orders.k1", "orders.k2"]),
    )

    assert dependency_graph(metadata) == {"orders": set(), "order_items": {"orders"}}


def test_fk_to_missing_target_table_is_ignored():
    metadata = MetaData()
    Table(
        "externals",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("ghost_id", Integer, ForeignKey("ghosts.id")),
    )

    assert dependency_graph(metadata) == {"externals": set()}


def test_self_referential_fk_is_visible_in_graph():
    metadata = MetaData()
    Table(
        "categories",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("parent_id", Integer, ForeignKey("categories.id")),
    )

    assert dependency_graph(metadata) == {"categories": {"categories"}}


def test_use_alter_edge_is_visible_in_graph():
    metadata = MetaData()
    Table(
        "employees",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("dept_id", Integer, ForeignKey("departments.id")),
    )
    Table(
        "departments",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("head_id", Integer, ForeignKey("employees.id", use_alter=True)),
    )

    assert dependency_graph(metadata) == {"employees": {"departments"}, "departments": {"employees"}}


def test_same_name_in_two_schemas_is_two_nodes():
    metadata = MetaData()
    Table("shared", metadata, Column("id", Integer, primary_key=True))
    Table(
        "shared",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("shared_id", Integer, ForeignKey("shared.id")),
        schema="app",
    )

    assert dependency_graph(metadata) == {"shared": set(), "app.shared": {"shared"}}


def test_two_fks_to_same_table_yield_one_edge():
    metadata = MetaData()
    Table("users", metadata, Column("id", Integer, primary_key=True))
    Table(
        "messages",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("from_id", Integer, ForeignKey("users.id")),
        Column("to_id", Integer, ForeignKey("users.id")),
    )

    assert dependency_graph(metadata) == {"users": set(), "messages": {"users"}}


def test_empty_metadata_yields_empty_graph():
    assert dependency_graph(MetaData()) == {}
