import asyncio
import threading
import time
import uuid

import pytest
from sqlalchemy import ForeignKey, String, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
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
    badges: Mapped[list["Badge"]] = relationship(back_populates="owner")


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


class Badge(Base):
    __tablename__ = "badges"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    owner: Mapped[User] = relationship(back_populates="badges")


LOCK_WAITERS = text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock'")
STATEMENT_TIMEOUT = text("SET statement_timeout = '15s'")


def wait_for_a_session_blocked_on_a_lock(session):
    deadline = time.monotonic() + 15
    while not session.scalar(LOCK_WAITERS):
        assert time.monotonic() < deadline, "the second session never reached the first one's pending rows"
        time.sleep(0.05)


def seed_in_a_second_session_while_the_first_is_pending(pg_session, first, seed_second):
    errors = []

    def run():
        try:
            with Session(pg_session.get_bind()) as second:
                second.execute(STATEMENT_TIMEOUT)
                seed_second(second)
                second.commit()
        except Exception as exc:  # noqa: BLE001 — le thread rapporte son échec au test
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    wait_for_a_session_blocked_on_a_lock(pg_session)
    first.commit()
    first.close()
    thread.join()
    return errors


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


def test_two_sessions_seeding_the_same_tables_at_once_do_not_collide(pg_session):
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


def test_a_unique_value_another_session_commits_mid_seed_is_regenerated(pg_session):
    engine = pg_session.get_bind()
    Base.metadata.create_all(engine)
    first = Session(engine)
    first.execute(STATEMENT_TIMEOUT)
    seed(first, Member, member=20)

    errors = seed_in_a_second_session_while_the_first_is_pending(
        pg_session, first, lambda second: seed(second, Member, member=20)
    )

    assert errors == []
    assert pg_session.scalar(select(func.count(func.distinct(Member.email)))) == 40


def test_a_regenerated_graph_keeps_its_links_to_an_existing_parent(pg_session):
    engine = pg_session.get_bind()
    Base.metadata.create_all(engine)
    pg_session.add(owner := User(name="owner"))
    pg_session.commit()
    first = Session(engine)
    first.execute(STATEMENT_TIMEOUT)
    seed(first, Badge, badge=20, parents=[first.get(User, owner.id)])

    errors = seed_in_a_second_session_while_the_first_is_pending(
        pg_session, first, lambda second: seed(second, Badge, badge=20, parents=[second.get(User, owner.id)])
    )

    assert errors == []
    assert pg_session.scalar(select(func.count(func.distinct(Badge.code)))) == 40
    assert pg_session.scalar(select(func.count()).select_from(Badge).where(Badge.owner_id == owner.id)) == 40


async def test_the_async_facade_regenerates_a_unique_value_committed_mid_seed(pg_asession):
    engine = pg_asession.bind
    await pg_asession.run_sync(lambda sync: Base.metadata.create_all(sync.get_bind()))
    await pg_asession.commit()
    first = AsyncSession(engine)
    await first.execute(STATEMENT_TIMEOUT)
    await seed_async(first, Member, member=20)

    async def seed_second():
        async with AsyncSession(engine) as second:
            await second.execute(STATEMENT_TIMEOUT)
            await seed_async(second, Member, member=20)
            await second.commit()

    second = asyncio.create_task(seed_second())
    deadline = time.monotonic() + 15
    while not await pg_asession.scalar(LOCK_WAITERS):
        assert time.monotonic() < deadline, "the second session never reached the first one's pending rows"
        await asyncio.sleep(0.05)
    await first.commit()
    await first.close()
    await second

    assert await pg_asession.scalar(select(func.count(func.distinct(Member.email)))) == 40


def test_an_overridden_duplicate_still_fails_on_postgres(pg_session):
    Base.metadata.create_all(pg_session.get_bind())

    with pytest.raises(IntegrityError):
        seed(pg_session, Member, overrides={Member: {"email": "same@example.com"}})


def test_a_rollback_still_undoes_a_seed_on_postgres(pg_session):
    Base.metadata.create_all(pg_session.get_bind())
    pg_session.commit()

    seed(pg_session, User, post=2)
    pg_session.rollback()

    assert pg_session.scalar(select(func.count()).select_from(Post)) == 0


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
