"""Draw from Faker's weighted tables through cumulative weights computed once, with the exact values Faker itself draws."""

import inspect
from collections import OrderedDict
from collections.abc import Sequence
from itertools import accumulate
from types import MethodType
from typing import Any

from faker import Faker
from faker.providers import BaseProvider

__all__ = ["install_cumulative_sampling"]

CACHE_ATTRIBUTE = "_seedgraph_cumulative"
FAKER_SIGNATURE = ["self", "elements", "length", "unique", "use_weighting"]


def install_cumulative_sampling(fake: Faker) -> None:
    """Give each provider of this Faker a random_elements that reuses each weighted table's cumulative weights.

    Installs nothing when one of the Faker internals it relies on is missing.
    """
    if list(inspect.signature(BaseProvider.random_elements).parameters) != FAKER_SIGNATURE:
        return
    providers = [provider for factory in getattr(fake, "factories", ()) for provider in getattr(factory, "providers", ())]
    if not all(hasattr(p, "__use_weighting__") and hasattr(getattr(p, "generator", None), "random") for p in providers):
        return
    for provider in providers:
        provider.random_elements = MethodType(_random_elements, provider)


def _random_elements(
    provider: BaseProvider,
    elements: Any = ("a", "b", "c"),
    length: int | None = None,
    unique: bool = False,
    use_weighting: bool | None = None,
) -> Sequence[Any]:
    weighting = provider.__use_weighting__ if use_weighting is None else use_weighting
    if unique or not weighting or not isinstance(elements, OrderedDict):
        return BaseProvider.random_elements(provider, elements, length, unique, use_weighting)
    rng = provider.generator.random
    if length is None:
        length = rng.randint(1, len(elements))
    keys, cumulative = _cumulative_table(elements)
    # Given cum_weights, random.choices skips its accumulate pass and bisects the very totals it would have built.
    drawn: list[Any] = rng.choices(keys, cum_weights=cumulative, k=length)
    return drawn


def _cumulative_table(elements: "OrderedDict[Any, float]") -> tuple[tuple[Any, ...], list[float]]:
    table: tuple[tuple[Any, ...], list[float]] | None = getattr(elements, CACHE_ATTRIBUTE, None)
    if table is None or len(table[0]) != len(elements):
        table = (tuple(elements), list(accumulate(elements.values())))
        setattr(elements, CACHE_ATTRIBUTE, table)
    return table
