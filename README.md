# seedgraph

> Seed your SQLAlchemy models as a referentially-consistent graph — one call, shared parents, real PKs.

**Status: work in progress.** The API below is the target design. Everything marked 🎯 is planned, not shipped yet.

---

## Why

Every Python team that seeds a relational test database eventually hand-rolls the same
plumbing: generate rows, stage commits so primary keys exist, chase those PKs into FK
columns, repeat for every relationship, pray the graph stays consistent.

You shouldn't have to. But after empirically testing the landscape (SQLAlchemy 2.x era,
August 2026), none of the existing options actually does it:

| Tool | What you get on a `User ← Post ← Comment` schema |
|------|---------------------------------------------------|
| `polyfactory` | Builds related objects, **but every FK column is a random int pointing at nothing**: `post.author_id != post.author.id`. Silent data corruption — tests pass on garbage unless you enable FK enforcement (most don't). |
| `faker-sqlalchemy` (unmaintained since 2022, pinned to SQLAlchemy 1.x) | `RecursionError` on standard `backref` relationships, on self-referential FKs, and its `overrides` API silently drops FK values. |
| `sqlalchemyseed` | Seeds data *you already have* (JSON/YAML), doesn't generate. |
| `sqlseed`, `sowdb` | Solid fillers, but schema-level and flat: "N rows per table". They work from raw SQL schemas, not your models, and can't express a graph shape like *"3 users → 2 posts each → 5 comments per post"*. |

The one-line failure we're fixing:

```python
p = PostFactory.build()
p.author_id == p.author.id   # False. Every FK in the graph is disconnected.
```

`seedgraph` exists so this is always `True`.

## The pitch 🎯

Declare a **shape**, get a **coherent object graph** in one call — FK columns provably
pointing at real PKs in the same graph, before any flush happens.

```python
from seedgraph import seed

graph = seed(
    session,
    User,
    post=2,            # 2 posts per user — shared parent
    post__comment=5,   # 5 comments per post
)
assert len(graph.users) == 3
assert graph.users[0].posts[0].author_id == graph.users[0].id  # real PK, real FK
```

## Design principles

1. **Model-first, not schema-first.** Works from your SQLAlchemy ORM models and relationships — introspection only as a fallback.
2. **Referential consistency is an invariant, not a hope.** FK reconciliation happens in the object graph, before the unit of work flushes.
3. **Shared parents are the point.** Realistic data shares parents (one author, many posts). One object per FK is not a graph.
4. **Deterministic.** A seed produces the same graph twice.
5. **Cycles and self-references are normal.** `Category.parent`, circular FKs — supported by construction.
6. **Stop generating at the boundary.** Existing rows with real PKs are usable as parents; only missing parents get generated.

## Roadmap 🎯

- [ ] Core: FK-graph topology from metadata (topological order, cycle detection)
- [ ] PK reservation/reconciliation across the graph
- [ ] Shape API (`relation=n`, nesting, shared parents)
- [ ] Custom field generators (Faker under the hood)
- [ ] Overriding specific attributes on generated objects
- [ ] pytest fixture helpers
- [ ] Self-referential and cyclic FKs
- [ ] Async sessions support

## Installation 🎯

```bash
pip install seedgraph
```

Requires Python 3.11+ and SQLAlchemy 2.x.

## License

MIT
