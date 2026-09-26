# Columns seedgraph cannot fill on its own

seedgraph generates strings, numbers, dates, booleans, enums, UUIDs, binary and arrays of those, fitted to each column's type. Two kinds of column have no defensible default: **JSON**, whose expected shape only your application knows, and **custom types** built on `TypeDecorator`. A nullable one is left empty; a required one stops the seed with `UnsupportedPlaceholderError` until you say how to fill it.

These tests use the `seedgraph_graph` fixture, which the plugin registers when seedgraph is installed.

## The models

```python
from decimal import Decimal

import pytest
from sqlalchemy import JSON, Integer, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from seedgraph import UnsupportedPlaceholderError


class Cents(TypeDecorator):
    """Store a Decimal amount as an integer number of cents."""

    impl = Integer
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else int(value * 100)

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value) / 100


class Base(DeclarativeBase):
    pass


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str]
    total = mapped_column(Cents(), nullable=False)
    details: Mapped[dict] = mapped_column(JSON)
```

## The error names the column

```python
def test_a_required_custom_column_stops_the_seed(seedgraph_graph):
    with pytest.raises(UnsupportedPlaceholderError, match="orders.total"):
        seedgraph_graph(Order)
```

## Declaring a generator

A generator receives a context: `ctx.fake` is the session's seeded [Faker](https://faker.readthedocs.io/), so values stay reproducible, and `ctx.column` is the column name.

```python
def amount(ctx):
    return Decimal(ctx.fake.pyint(min_value=100, max_value=99_999)) / 100


def test_generators_fill_the_custom_and_json_columns(seedgraph_graph):
    graph = seedgraph_graph(
        Order,
        order=5,
        generators={
            Order: {
                "total": amount,
                "details": lambda ctx: {"channel": ctx.fake.random_element(["web", "store"])},
            }
        },
    )

    assert all(Decimal("1.00") <= order.total <= Decimal("999.99") for order in graph.orders)
    assert {order.details["channel"] for order in graph.orders} <= {"web", "store"}
```

## Pinning one value instead

When every object needs the same value, an override is shorter than a generator. A plain value pins it; a callable taking the same context computes it:

```python
def test_an_override_pins_the_value(seedgraph_graph):
    graph = seedgraph_graph(
        Order,
        order=2,
        generators={Order: {"total": amount}},
        overrides={Order: {"details": {"channel": "web"}, "reference": lambda ctx: ctx.fake.bothify("ORD-####")}},
    )

    assert [order.details for order in graph.orders] == [{"channel": "web"}, {"channel": "web"}]
    assert all(order.reference.startswith("ORD-") for order in graph.orders)
```
