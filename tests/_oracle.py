"""Shared test oracle: every set relationship's FK columns equal the linked parent's PK."""

from seedgraph.verification import verify_graph


def assert_referentially_consistent(objects):
    verify_graph(objects)
