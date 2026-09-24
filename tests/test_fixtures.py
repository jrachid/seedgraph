"""Core 6 scenarios — tranche 1: the pytest plugin, a fresh session and a seed callable.

Each scenario plays a real mini test-suite via pytester: it consumes the plugin
fixtures the way a user's project would, then asserts on the outcome.
"""


MINI_MODELS = '''
from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    email = Column(String, nullable=False)

    posts = relationship("Post", back_populates="author")


class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True)
    title = Column(Text, nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    author = relationship("User", back_populates="posts")
    comments = relationship("Comment", back_populates="post")


class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True)
    body = Column(Text, nullable=False)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False)

    post = relationship("Post", back_populates="comments")


class Label(Base):
    __tablename__ = "labels"
    id = Column(Integer, primary_key=True)
    tagline = Column(Text, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"))
'''


def test_plugin_serves_session_without_configuration(pytester):
    pytester.makepyfile(
        '''
def test_fresh_session(session):
    from sqlalchemy import text

    assert session.connection().execute(text("PRAGMA foreign_keys")).scalar() == 1
    tables = session.connection().execute(text("SELECT name FROM sqlite_master")).fetchall()
    assert not [name for (name,) in tables if not name.startswith("sqlite_")]
'''
    )

    result = pytester.runpytest_subprocess()

    result.assert_outcomes(passed=1)


def test_graph_fixture_seeds_a_graph_with_the_full_api(pytester):
    pytester.makepyfile(
        f'''
{MINI_MODELS}

def test_seeded_graph(graph):
    graph_obj = graph(User, post=2, post__comment=1)

    assert len(graph_obj.users) == 3
    assert len(graph_obj.posts) == 6
    assert len(graph_obj.comments) == 6
'''
    )

    result = pytester.runpytest_subprocess()

    result.assert_outcomes(passed=1)


def test_tables_are_created_on_demand_from_the_seeded_model(pytester):
    pytester.makepyfile(
        MINI_MODELS
        + '''

def test_tables_on_demand(graph, session):
    from sqlalchemy import text

    graph(User, post=1)
    graph(Label)

    names = session.connection().execute(text("SELECT name FROM sqlite_master")).fetchall()
    names = {name for (name,) in names if not name.startswith("sqlite_")}
    assert {"users", "posts", "comments", "labels"} <= names
'''
    )

    result = pytester.runpytest_subprocess()

    result.assert_outcomes(passed=1)


def test_each_test_starts_on_a_fresh_database(pytester):
    pytester.makepyfile(
        f'''
{MINI_MODELS}

def test_first_seeds_three(graph):
    graph_obj = graph(User)
    assert len(graph_obj.users) == 3


def test_second_finds_a_fresh_base(graph):
    graph_obj = graph(User)
    assert len(graph_obj.users) == 3
'''
    )

    result = pytester.runpytest_subprocess()

    result.assert_outcomes(passed=2)


def test_library_seed_works_on_the_plugin_session(pytester):
    pytester.makepyfile(
        f'''
{MINI_MODELS}

def test_library_seed_on_plugin_session(session):
    from seedgraph import seed

    User.metadata.create_all(session.get_bind())
    Post.metadata.create_all(session.get_bind())

    graph_obj = seed(session, User)
    assert len(graph_obj.users) == 3
'''
    )

    result = pytester.runpytest_subprocess()

    result.assert_outcomes(passed=1)


def test_plugin_active_but_unused_leaves_the_run_green(pytester):
    pytester.makepyfile(
        '''
def test_plain_math():
    assert 1 + 1 == 2
'''
    )

    result = pytester.runpytest_subprocess()

    result.assert_outcomes(passed=1)


def test_graph_fixture_accepts_generators_and_overrides(pytester):
    pytester.makepyfile(
        f'''
{MINI_MODELS}

def test_all_three_channels(graph):
    graph_obj = graph(
        User,
        post=2,
        post__comment=1,
        generators={{User: {{"name": lambda ctx: "custom-from-generators"}}}},
        overrides={{User: {{"name": "winner"}}}},
    )

    assert all(user.name == "winner" for user in graph_obj.users)
    assert all(post.title.endswith(".") for post in graph_obj.posts)
    assert graph_obj.users[0].email and "@" in graph_obj.users[0].email
'''
    )

    result = pytester.runpytest_subprocess()

    result.assert_outcomes(passed=1)


def test_user_conftest_overrides_plugin_fixtures(pytester):
    pytester.makeconftest(
        '''
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enforce_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")
        dbapi_conn.execute("CREATE TABLE custom_flag (id INTEGER PRIMARY KEY)")

    with Session(engine) as session:
        yield session
'''
    )
    pytester.makepyfile(
        f'''
{MINI_MODELS}

def test_the_conftest_session_wins(session, graph):
    from sqlalchemy import text

    tables = session.connection().execute(text("SELECT name FROM sqlite_master")).fetchall()
    assert ("custom_flag",) in tables

    graph_obj = graph(User, post=1)
    assert len(graph_obj.users) == 3
'''
    )

    result = pytester.runpytest_subprocess()

    result.assert_outcomes(passed=1)
