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
def test_fresh_session(seedgraph_session):
    from sqlalchemy import text

    assert seedgraph_session.connection().execute(text("PRAGMA foreign_keys")).scalar() == 1
    tables = seedgraph_session.connection().execute(text("SELECT name FROM sqlite_master")).fetchall()
    assert not [name for (name,) in tables if not name.startswith("sqlite_")]
'''
    )

    result = pytester.runpytest_subprocess()

    result.assert_outcomes(passed=1)


def test_graph_fixture_seeds_a_graph_with_the_full_api(pytester):
    pytester.makepyfile(
        f'''
{MINI_MODELS}

def test_seeded_graph(seedgraph_graph):
    graph_obj = seedgraph_graph(User, post=2, post__comment=1)

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

def test_tables_on_demand(seedgraph_graph, seedgraph_session):
    from sqlalchemy import text

    seedgraph_graph(User, post=1)
    seedgraph_graph(Label)

    names = seedgraph_session.connection().execute(text("SELECT name FROM sqlite_master")).fetchall()
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

def test_first_seeds_three(seedgraph_graph):
    graph_obj = seedgraph_graph(User)
    assert len(graph_obj.users) == 3


def test_second_finds_a_fresh_base(seedgraph_graph):
    graph_obj = seedgraph_graph(User)
    assert len(graph_obj.users) == 3
'''
    )

    result = pytester.runpytest_subprocess()

    result.assert_outcomes(passed=2)


def test_library_seed_works_on_the_plugin_session(pytester):
    pytester.makepyfile(
        f'''
{MINI_MODELS}

def test_library_seed_on_plugin_session(seedgraph_session):
    from seedgraph import seed

    User.metadata.create_all(seedgraph_session.get_bind())
    Post.metadata.create_all(seedgraph_session.get_bind())

    graph_obj = seed(seedgraph_session, User)
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

def test_all_three_channels(seedgraph_graph):
    graph_obj = seedgraph_graph(
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
def seedgraph_session():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enforce_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")
        dbapi_conn.execute("CREATE TABLE custom_flag (id INTEGER PRIMARY KEY)")

    with Session(engine) as seedgraph_session:
        yield seedgraph_session
'''
    )
    pytester.makepyfile(
        f'''
{MINI_MODELS}

def test_the_conftest_session_wins(seedgraph_session, seedgraph_graph):
    from sqlalchemy import text

    tables = seedgraph_session.connection().execute(text("SELECT name FROM sqlite_master")).fetchall()
    assert ("custom_flag",) in tables

    graph_obj = seedgraph_graph(User, post=1)
    assert len(graph_obj.users) == 3
'''
    )

    result = pytester.runpytest_subprocess()

    result.assert_outcomes(passed=1)


def test_async_fixtures_served_without_configuration(pytester):
    pytester.makepyprojecttoml('[tool.pytest.ini_options]\nasyncio_mode = "auto"\n')
    pytester.makepyfile(
        f'''
{MINI_MODELS}

async def test_async_world(seedgraph_asession, seedgraph_agraph):
    graph_obj = await seedgraph_agraph(User, post=2)

    assert len(graph_obj.users) == 3
    assert len(graph_obj.posts) == 6
    await seedgraph_asession.flush()
'''
    )

    result = pytester.runpytest_subprocess()

    result.assert_outcomes(passed=1)


def test_async_graph_accepts_channels_and_restarts_above_rows(pytester):
    pytester.makepyprojecttoml('[tool.pytest.ini_options]\nasyncio_mode = "auto"\n')
    pytester.makepyfile(
        f'''
{MINI_MODELS}

async def test_channels_and_boundary(seedgraph_agraph, seedgraph_asession):
    first = await seedgraph_agraph(User, post=1, generators={{User: {{"name": lambda ctx: "custom"}}}},
                         overrides={{Post: {{"title": "imposed"}}}})
    assert all(user.name == "custom" for user in first.users)
    assert all(post.title == "imposed" for post in first.posts)

    seedgraph_asession.add_all([User(id=50, name="legacy", email="legacy@x")])
    await seedgraph_asession.commit()

    second = await seedgraph_agraph(User, post=1)
    await seedgraph_asession.flush()
    assert [user.id for user in second.users] == [51, 52, 53]
'''
    )

    result = pytester.runpytest_subprocess()

    result.assert_outcomes(passed=1)


def test_missing_aiosqlite_leaves_sync_suites_green(pytester):
    pytester.makeconftest(
        '''
import sys

sys.modules["aiosqlite"] = None
'''
    )
    pytester.makepyfile(
        '''
def test_plain_sync_math():
    assert 1 + 1 == 2
'''
    )

    result = pytester.runpytest_subprocess()

    result.assert_outcomes(passed=1)


def test_the_prefixed_fixtures_live_beside_a_project_own_session_and_graph(pytester):
    pytester.makeconftest(
        """
import pytest


@pytest.fixture()
def session():
    return "the project's session"


@pytest.fixture()
def graph():
    return "the project's graph"
"""
    )
    pytester.makepyfile(
        f'''
{MINI_MODELS}

def test_both_worlds(session, graph, seedgraph_graph):
    assert session == "the project's session"
    assert graph == "the project's graph"
    assert len(seedgraph_graph(User).users) == 3
'''
    )

    result = pytester.runpytest_subprocess()

    result.assert_outcomes(passed=1)
