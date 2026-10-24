"""Draw from the weighted tables Faker ships through cumulative weights computed once, with the exact values Faker itself draws."""

import inspect
from collections import OrderedDict
from collections.abc import Sequence
from itertools import accumulate
from types import MethodType
from typing import Any

from faker import Faker
from faker.providers import BaseProvider

__all__ = ["install_cumulative_sampling"]

FAKER_SIGNATURE = ["self", "elements", "length", "unique", "use_weighting"]

# The tables the providers carry as class attributes, by id: only these never change, so only these keep cached weights.
_shipped: dict[int, OrderedDict[Any, float]] = {}
_cumulative: dict[int, tuple[tuple[Any, ...], list[float]]] = {}


def install_cumulative_sampling(fake: Faker) -> None:
    """Give each provider of this Faker a random_elements that reuses the cumulative weights of the tables Faker ships.

    Installs nothing when one of the Faker internals it relies on is missing.
    """
    if list(inspect.signature(BaseProvider.random_elements).parameters) != FAKER_SIGNATURE:
        return
    providers = [provider for factory in getattr(fake, "factories", ()) for provider in getattr(factory, "providers", ())]
    if not all(hasattr(p, "__use_weighting__") and hasattr(getattr(p, "generator", None), "random") for p in providers):
        return
    for provider in providers:
        for cls in type(provider).__mro__:
            _shipped.update((id(table), table) for table in vars(cls).values() if isinstance(table, OrderedDict))
        provider.random_elements = MethodType(_random_elements, provider)


def _random_elements(
    provider: BaseProvider,
    elements: Any = ("a", "b", "c"),
    length: int | None = None,
    unique: bool = False,
    use_weighting: bool | None = None,
) -> Sequence[Any]:
    weighting = provider.__use_weighting__ if use_weighting is None else use_weighting
    shipped = _shipped.get(id(elements))
    if unique or not weighting or shipped is None or shipped is not elements:
        return BaseProvider.random_elements(provider, elements, length, unique, use_weighting)
    rng = provider.generator.random
    if length is None:
        length = rng.randint(1, len(shipped))
    keys, cumulative = _cumulative_table(shipped)
    # Given cum_weights, random.choices skips its accumulate pass and bisects the very totals it would have built.
    drawn: list[Any] = rng.choices(keys, cum_weights=cumulative, k=length)
    return drawn


def _cumulative_table(elements: "OrderedDict[Any, float]") -> tuple[tuple[Any, ...], list[float]]:
    table = _cumulative.get(id(elements))
    if table is None:
        table = _cumulative[id(elements)] = (tuple(elements), list(accumulate(elements.values())))
    return table
