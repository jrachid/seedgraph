---
name: seedgraph
description: Create test data for SQLAlchemy 2.x models with seedgraph — a graph of related rows (users with posts with comments) written in one call, every foreign key verified. Use when a test, fixture or seed script needs SQLAlchemy ORM objects in a database, instead of hand-building objects, chasing primary keys into foreign key columns, or using factory_boy or polyfactory.
---

# seedgraph

`seed()` builds a graph of ORM objects from a declared shape, adds it to the session, flushes so the database assigns the keys, then checks every foreign key against the row it points at. It never commits.

Install: `pip install seedgraph` (add `[async]` for `seed_async`). Requires SQLAlchemy 2.x.

## The call

```python
from sqlalchemy import ForeignKey, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

from seedgraph import seed


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    posts: Mapped[list["Post"]] = relationship(back_populates="author")


class Post(Base):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    author: Mapped[User] = relationship(back_populates="posts")


engine = create_engine("sqlite://")
Base.metadata.create_all(engine)
session = Session(engine)

graph = seed(session, User, user=2, post=3)   # 2 users, 3 posts each; the root count defaults to 3
assert len(graph.users) == 2 and len(graph.posts) == 6
assert all(post.author_id == post.author.id for post in graph.posts)
```

- Shape keys walk one-to-many or many-to-many relationships, by relationship name (`posts=3`) or target class name (`post=3`). Nest with `__`: `post__comment=2`.
- `graph.<table name>` lists the objects seeded in that table; an unseeded table gives `[]`.
- Required parents missing from the shape are generated once and shared: `seed(session, Post)` creates one `User` for all posts.

## Existing rows, pinned values, custom columns

```python
alice = graph.users[0]
more = seed(session, Post, post=2, parents=[alice])   # link to rows already in the session
assert all(post.author is alice for post in more.posts)

pinned = seed(
    session,
    User,
    user=1,
    overrides={User: {"name": "Alice"}},                            # a value, or a callable taking ctx
    generators={Post: {"title": lambda ctx: ctx.fake.sentence()}},  # ctx.fake is the seeded Faker
    post=1,
)
assert pinned.users[0].name == "Alice"
```

`generators` and `overrides` are keyed by model, then by **database column name**: for `details = mapped_column("meta", JSON)`, write `"meta"`.

## In pytest

Installing seedgraph registers fixtures; each test gets a fresh in-memory SQLite with foreign keys enforced and tables created on demand:

```python
def test_feed(seedgraph_graph):
    graph = seedgraph_graph(User, post=2)
    assert len(graph.posts) == 6
```

`seedgraph_agraph` is the async twin (`await seedgraph_agraph(...)`). For a project's own database, call `seed(session, ...)` on its session and roll back at teardown.

## Errors and their fix

| Error | Fix |
|---|---|
| `UnsupportedPlaceholderError` | a required JSON or custom-type column: add `generators={Model: {"column": lambda ctx: ...}}` |
| `UnknownShapeKeyError` | use a one-to-many or many-to-many relationship name, or its target class name |
| `UnsupportedShapeDirectionError` | the key points to a parent (many-to-one): pass the parent in `parents=[...]` instead |
| `MissingRequiredParentError` | a loop of required links, or a required link to its own table: pass one side in `parents` |
| `AmbiguousParentError` | several objects of one type in `parents` for a single link: pass only one |
| `UnattachedParentError` | a parent is not in the session: `session.add(parent)` first |
| `UniqueValueExhaustedError` | a unique column ran out of values: declare a wider generator |
| `UnknownGeneratorColumnError`, `UnknownOverrideColumnError` | the key is not a column name of that model's table |

## Do not

- Set primary or foreign key values by hand: the database assigns them and seedgraph links them.
- Expect `seed()` to commit: commit or roll back in the caller.
- Build a many-to-one side through the shape: parents come from `parents` or are generated.

Full docs and recipes: https://jrachid.github.io/seedgraph/ — for agents: https://jrachid.github.io/seedgraph/llms-full.txt
