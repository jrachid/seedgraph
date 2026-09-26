import threading
import time
import uuid

import pytest
from sqlalchemy import ForeignKey, String, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

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


class Member(Base):
    __tablename__ = "members"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(120), unique=True)


class Token(Base):
    __tablename__ = "tokens"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    label: Mapped[str] = mapped_column(String(80))


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


def test_the_application_still_inserts_after_a_seed_on_top_of_its_rows(pg_session):
    Base.metadata.create_all(pg_session.get_bind())
    pg_session.add_all([User(name="legacy-1"), User(name="legacy-2")])
    pg_session.commit()

    graph = seed(pg_session, User, post=1)
    pg_session.commit()
    pg_session.add(User(name="written by the application after the seed"))
    pg_session.commit()

    assert [user.id for user in graph.users] == [3, 4, 5]
    assert pg_session.scalar(select(func.max(User.id))) == 6


def test_two_sessions_seeding_the_same_tables_at_once_do_not_collide_on_keys(pg_session):
    engine = pg_session.get_bind()
    Base.metadata.create_all(engine)
    errors = []

    def seed_and_commit():
        try:
            with Session(engine) as session:
                seed(session, User, user=20, post=2)
                session.commit()
        except Exception as exc:  # noqa: BLE001 — le thread rapporte son échec au test
            errors.append(exc)

    threads = [threading.Thread(target=seed_and_commit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert pg_session.scalar(select(func.count()).select_from(Post)) == 80


def test_two_sessions_seeding_a_generated_unique_column_at_once_are_stopped_by_the_database(pg_session):
    engine = pg_session.get_bind()
    Base.metadata.create_all(engine)
    errors = []
    first = Session(engine)
    first.execute(text("SET statement_timeout = '15s'"))
    seed(first, Member, member=20)

    def seed_second_while_the_first_is_pending():
        try:
            with Session(engine) as second:
                second.execute(text("SET statement_timeout = '15s'"))
                seed(second, Member, member=20)
                second.commit()
        except IntegrityError as exc:
            errors.append(exc)

    thread = threading.Thread(target=seed_second_while_the_first_is_pending)
    thread.start()
    deadline = time.monotonic() + 15
    while not pg_session.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock'")):
        assert time.monotonic() < deadline, "the second session never reached the first one's pending rows"
        time.sleep(0.05)
    first.commit()
    first.close()
    thread.join()

    assert len(errors) == 1
    assert pg_session.scalar(select(func.count()).select_from(Member)) == 20


def test_two_seeds_in_a_row_on_postgres(pg_session):
    Base.metadata.create_all(pg_session.get_bind())

    seed(pg_session, User, post=1)
    seed(pg_session, User, post=1)
    pg_session.commit()

    assert pg_session.scalar(select(func.count()).select_from(User)) == 6


def test_a_uuid_primary_key_on_postgres(pg_session):
    Base.metadata.create_all(pg_session.get_bind())

    graph = seed(pg_session, Token)
    pg_session.commit()

    assert all(isinstance(token.id, uuid.UUID) for token in graph.tokens)
