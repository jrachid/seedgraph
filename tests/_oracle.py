"""Shared test oracle: every set relationship's FK columns equal the linked parent's PK."""

from sqlalchemy import inspect
from sqlalchemy.orm import class_mapper


def _column_value(obj, column):
    return getattr(obj, class_mapper(type(obj)).get_property_by_column(column).key)


def assert_referentially_consistent(objects):
    """Test oracle: for every set relationship, the child FK columns equal the linked parent's PK."""
    for obj in objects:
        state = inspect(obj)
        for rel in state.mapper.relationships:
            if rel.direction.name == "MANYTOMANY" or rel.key in state.unloaded:
                continue
            value = getattr(obj, rel.key)
            if value is None:
                continue
            linked = list(value) if rel.direction.name == "ONETOMANY" else [value]
            for other in linked:
                for local_column, remote_column in rel.local_remote_pairs:
                    owner_value = _column_value(obj, local_column)
                    other_value = _column_value(other, remote_column)
                    assert owner_value == other_value, (
                        f"{type(obj).__name__}.{rel.key}: {local_column.name}={owner_value}"
                        f" vs {remote_column.name}={other_value}"
                    )
