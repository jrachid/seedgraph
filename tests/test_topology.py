"""Core 1 scenarios: the FK dependency graph, the strict order, the refusal of undeclared cycles."""

import pytest
from sqlalchemy import Column, ForeignKey, ForeignKeyConstraint, Integer, MetaData, Table, Text
from sqlalchemy.orm import declarative_base, relationship

from seedgraph.topology import CyclicFKGraphError, dependency_graph, topological_order

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


def test_topological_order_puts_parents_first():
    order = topological_order(User)

    assert [table.name for table in order] == ["users", "posts", "comments"]


def test_order_is_deterministic_regardless_of_definition_order():
    first = MetaData()
    Table("users", first, Column("id", Integer, primary_key=True))
    Table("posts", first, Column("id", Integer, primary_key=True), Column("author_id", Integer, ForeignKey("users.id")))
    Table("apple", first, Column("id", Integer, primary_key=True))
    Table("zebra", first, Column("id", Integer, primary_key=True))

    second = MetaData()
    Table("zebra", second, Column("id", Integer, primary_key=True))
    Table("apple", second, Column("id", Integer, primary_key=True))
    Table("posts", second, Column("id", Integer, primary_key=True), Column("author_id", Integer, ForeignKey("users.id")))
    Table("users", second, Column("id", Integer, primary_key=True))

    first_order = [table.name for table in topological_order(first)]
    second_order = [table.name for table in topological_order(second)]

    assert first_order == second_order == ["apple", "users", "posts", "zebra"]


def _rich_schema():
    metadata = MetaData()
    Table("users", metadata, Column("id", Integer, primary_key=True))
    Table("posts", metadata, Column("id", Integer, primary_key=True), Column("author_id", Integer, ForeignKey("users.id")))
    Table(
        "comments",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("post_id", Integer, ForeignKey("posts.id")),
        Column("author_id", Integer, ForeignKey("users.id")),
    )
    Table("orders", metadata, Column("k1", Integer, primary_key=True), Column("k2", Integer, primary_key=True))
    Table(
        "order_items",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("k1", Integer),
        Column("k2", Integer),
        ForeignKeyConstraint(["k1", "k2"], ["orders.k1", "orders.k2"]),
    )
    Table("shared", metadata, Column("id", Integer, primary_key=True))
    Table(
        "shared",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("shared_id", Integer, ForeignKey("shared.id")),
        schema="app",
    )
    return metadata


def assert_respects_every_fk_edge(metadata):
    """Test oracle: every declared FK edge (minus self-reference and use_alter) is respected by the order."""
    order = [table.key for table in topological_order(metadata)]
    for table in metadata.tables.values():
        for constraint in table.foreign_key_constraints:
            if constraint.use_alter:
                continue
            parent_key = constraint.elements[0].column.table.key
            if parent_key == table.key:
                continue
            assert order.index(parent_key) < order.index(table.key), f"{table.key} precedes its parent {parent_key}"


def test_order_respects_every_fk_edge():
    metadata = _rich_schema()
    order = [table.key for table in topological_order(metadata)]

    assert_respects_every_fk_edge(metadata)
    assert order == ["orders", "order_items", "shared", "app.shared", "users", "posts", "comments"]


def test_empty_metadata_yields_empty_order():
    assert topological_order(MetaData()) == []


def test_fk_free_metadata_sorts_by_name():
    metadata = MetaData()
    Table("zebra", metadata, Column("id", Integer, primary_key=True))
    Table("mike", metadata, Column("id", Integer, primary_key=True))
    Table("alpha", metadata, Column("id", Integer, primary_key=True))

    assert [table.name for table in topological_order(metadata)] == ["alpha", "mike", "zebra"]


def test_self_reference_does_not_block_order():
    metadata = MetaData()
    Table(
        "categories",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("parent_id", Integer, ForeignKey("categories.id")),
    )

    assert [table.name for table in topological_order(metadata)] == ["categories"]


def _mutual_cycle(use_alter):
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
        Column("head_id", Integer, ForeignKey("employees.id", use_alter=use_alter)),
    )
    return metadata


def test_use_alter_does_not_block_order():
    order = [table.name for table in topological_order(_mutual_cycle(use_alter=True))]

    assert order == ["departments", "employees"]


def test_undeclared_mutual_cycle_raises_cyclic_fk_graph_error():
    with pytest.raises(CyclicFKGraphError) as excinfo:
        topological_order(_mutual_cycle(use_alter=False))

    assert excinfo.value.groups == (("departments", "employees"),)
    assert "departments" in str(excinfo.value)
    assert "employees" in str(excinfo.value)


def test_cycle_error_lists_only_cyclic_tables():
    metadata = _mutual_cycle(use_alter=False)
    Table("users", metadata, Column("id", Integer, primary_key=True))
    Table("posts", metadata, Column("id", Integer, primary_key=True), Column("author_id", Integer, ForeignKey("users.id")))

    with pytest.raises(CyclicFKGraphError) as excinfo:
        topological_order(metadata)

    assert excinfo.value.groups == (("departments", "employees"),)


def test_deep_3000_table_chain_never_recurses():
    metadata = MetaData()
    previous = None
    for index in range(3000):
        columns = [Column("id", Integer, primary_key=True)]
        if previous is not None:
            columns.append(Column("parent_id", Integer, ForeignKey(f"{previous}.id")))
        previous = Table(f"t{index:04d}", metadata, *columns).key

    order = [table.name for table in topological_order(metadata)]

    assert order == [f"t{index:04d}" for index in range(3000)]


def test_3000_table_ring_reports_cycle_without_recursion():
    metadata = MetaData()
    tables = [
        Table(f"r{index:04d}", metadata, Column("id", Integer, primary_key=True), Column("prev_id", Integer))
        for index in range(3000)
    ]
    for index, table in enumerate(tables):
        table.append_constraint(ForeignKeyConstraint(["prev_id"], [f"r{(index - 1) % 3000:04d}.id"]))

    with pytest.raises(CyclicFKGraphError) as excinfo:
        topological_order(metadata)

    assert len(excinfo.value.groups) == 1
    assert len(excinfo.value.groups[0]) == 3000
