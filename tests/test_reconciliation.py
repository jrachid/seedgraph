"""Core 2 scenarios: PK reservation, FK reconciliation before any flush, the boundary bridge."""

import pytest
from sqlalchemy import Column, ForeignKey, Integer, Text, create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, class_mapper, declarative_base, relationship

from seedgraph.boundary import existing_maxima
from seedgraph.reconciliation import PendingParentError, UnsupportedPrimaryKeyError, reconcile_graph

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    posts = relationship("Post", overlaps="author")


class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True)
    title = Column(Text, nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    author = relationship("User", overlaps="posts")


class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True)
    body = Column(Text, nullable=False)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    post = relationship("Post")
    author = relationship("User")


class Employee(Base):
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True)
    dept_id = Column(Integer, ForeignKey("departments.id"))
    dept = relationship("Department", foreign_keys=[dept_id])


class Department(Base):
    __tablename__ = "departments"
    id = Column(Integer, primary_key=True)
    head_id = Column(Integer, ForeignKey("employees.id"))
    head = relationship("Employee", foreign_keys=[head_id])


class Tag(Base):
    __tablename__ = "tags"
    code = Column(Text, primary_key=True)


def _users(count=3):
    return [User(name=f"user-{index}") for index in range(count)]


def _column_value(obj, column):
    return getattr(obj, class_mapper(type(obj)).get_property_by_column(column).key)


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enforce_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def assert_referentially_consistent(objects):
    """Test oracle: for every set relationship, the child FK columns equal the linked parent's PK."""
    for obj in objects:
        state = inspect(obj)
        for rel in state.mapper.relationships:
            if rel.direction.name == "MANYTOMANY" or rel.key in state.unloaded:
                continue
            value = getattr(obj, rel.key)
            if value is None:
                continue
            linked = list(value) if rel.direction.name == "ONETOMANY" else [value]
            for other in linked:
                for local_column, remote_column in rel.local_remote_pairs:
                    owner_value = _column_value(obj, local_column)
                    other_value = _column_value(other, remote_column)
                    assert owner_value == other_value, (
                        f"{type(obj).__name__}.{rel.key}: {local_column.name}={owner_value}"
                        f" vs {remote_column.name}={other_value}"
                    )


def test_reserve_assigns_ids_above_existing_maxima():
    users = _users()

    reconcile_graph(users, existing_maxima={"users": {"id": 10}})

    assert [user.id for user in users] == [11, 12, 13]


def test_reserve_starts_at_one_without_maxima():
    users = _users()

    reconcile_graph(users)

    assert [user.id for user in users] == [1, 2, 3]


def test_reserve_never_overwrites_a_real_pk():
    users = _users()
    users[1].id = 999

    reconcile_graph(users, existing_maxima={"users": {"id": 10}})

    assert users[1].id == 999
    assert users[0].id == 11
    assert users[2].id == 12


def test_reserve_is_deterministic_across_rebuilds():
    first = _users()
    second = _users()

    reconcile_graph(first, existing_maxima={"users": {"id": 10}})
    reconcile_graph(second, existing_maxima={"users": {"id": 10}})

    assert [user.id for user in first] == [user.id for user in second] == [11, 12, 13]


def test_unsupported_pk_type_raises():
    tags = [Tag()]

    with pytest.raises(UnsupportedPrimaryKeyError) as excinfo:
        reconcile_graph(tags)

    assert "tags" in str(excinfo.value)
    assert "code" in str(excinfo.value)


def test_reconcile_copies_parent_pk_into_fk_columns():
    alice = User(name="alice")
    post = Post(title="p1", author=alice)

    reconcile_graph([alice, post])

    assert post.author_id == alice.id == 1
    assert_referentially_consistent([alice, post])


def test_reconcile_supports_shared_parents():
    users = _users()
    posts = [Post(title=f"p{index}", author=users[0]) for index in range(3)]
    comments = [
        Comment(body=f"c{index}", post=posts[index], author=users[index % 3]) for index in range(3)
    ]
    graph = users + posts + comments

    reconcile_graph(graph)

    assert_referentially_consistent(graph)
    for post in posts:
        assert post.author_id == users[0].id
    assert {comment.author_id for comment in comments} == {user.id for user in users}
    for index, comment in enumerate(comments):
        assert comment.post_id == posts[index].id


def test_reconcile_from_the_collection_side():
    alice = User(name="alice")
    posts = [Post(title=f"p{index}") for index in range(2)]
    alice.posts = posts

    reconcile_graph([alice, *posts])

    assert_referentially_consistent([alice, *posts])
    for post in posts:
        assert post.author is None
        assert post.author_id == alice.id


def test_reconcile_reuses_a_persistent_parent_real_pk():
    existing = User(name="legacy")
    existing.id = 17
    post = Post(title="p1", author=existing)

    reconcile_graph([post])

    assert post.author_id == 17
    assert existing.id == 17
    assert existing.name == "legacy"
    assert_referentially_consistent([post])


def test_pending_parent_outside_graph_raises():
    orphan_author = User(name="never-reserved")
    post = Post(title="p1", author=orphan_author)

    with pytest.raises(PendingParentError) as excinfo:
        reconcile_graph([post])

    assert "author" in str(excinfo.value)


def test_reconcile_mutual_references_without_flush():
    employee = Employee()
    department = Department()
    employee.dept = department
    department.head = employee

    reconcile_graph([employee, department])

    assert employee.dept_id == department.id
    assert department.head_id == employee.id
    assert_referentially_consistent([employee, department])


def test_existing_maxima_reads_real_maxima(session):
    session.add_all([User(name="legacy-1", id=1), User(name="legacy-2", id=12)])
    session.commit()

    maxima = existing_maxima(session, User)

    assert maxima["users"] == {"id": 12}
    assert maxima["posts"] == {"id": 0}
    assert "tags" not in maxima


def test_full_flow_flushes_without_fk_violation(session):
    session.add_all([User(name="legacy-1", id=11), User(name="legacy-2", id=12)])
    session.commit()

    alice = User(name="alice")
    bob = User(name="bob")
    posts = [Post(title=f"p{index}", author=alice) for index in range(2)]
    comments = [
        Comment(body=f"c{index}", post=posts[index % 2], author=bob) for index in range(3)
    ]
    graph = [alice, bob, *posts, *comments]

    reconcile_graph(graph, existing_maxima=existing_maxima(session, User))
    assert_referentially_consistent(graph)

    assert [alice.id, bob.id] == [13, 14]
    assert [post.id for post in posts] == [1, 2]
    for post in posts:
        assert post.author_id == alice.id
    assert {comment.author_id for comment in comments} == {bob.id}

    session.add_all(graph)
    session.flush()

    assert (
        session.query(User).count(),
        session.query(Post).count(),
        session.query(Comment).count(),
    ) == (4, 2, 3)


def test_seeding_without_maxima_collides_at_flush(session):
    session.add_all([User(name="legacy-1", id=1), User(name="legacy-2", id=2)])
    session.commit()

    alice = User(name="alice")
    post = Post(title="p1", author=alice)

    reconcile_graph([alice, post])
    assert alice.id == 1

    session.add_all([alice, post])
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
