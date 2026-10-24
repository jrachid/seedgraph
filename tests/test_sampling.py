"""An untouched Faker is the oracle: seedgraph's faster weighted draws give the same values and leave the generator in the same state."""

from collections import OrderedDict

import pytest
from faker import Faker
from faker.providers import BaseProvider
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import Column, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base, relationship

from seedgraph import generators, seed
from seedgraph.generators import DEFAULT_LOCALE, GenerationState
from seedgraph.sampling import install_cumulative_sampling

Base = declarative_base()


class Person(Base):
    __tablename__ = "people"
    id = Column(Integer, primary_key=True)
    first_name = Column(String(60), nullable=False)
    last_name = Column(String(60), nullable=False)
    name = Column(String(120), nullable=False)
    username = Column(String(60), nullable=False, unique=True)
    email = Column(String(120), nullable=False, unique=True)
    company = Column(String(120), nullable=False)
    city = Column(String(60), nullable=False)
    notes = relationship("Note", back_populates="person")


class Note(Base):
    __tablename__ = "notes"
    id = Column(Integer, primary_key=True)
    title = Column(String(80), nullable=False)
    body = Column(String, nullable=False)
    person_id = Column(Integer, ForeignKey("people.id"), nullable=False)
    person = relationship("Person", back_populates="notes")


FORMATTERS = [
    "name", "first_name", "last_name", "user_name", "email", "company", "city", "phone_number",
    "address", "name_female", "name_male", "name_nonbinary", "prefix", "job", "street_name", "sentence",
]
LOCALES = ["en_US", "fr_FR", "de_DE", "ja_JP", "es_ES", "en_GB"]


class CountingTable(OrderedDict):
    reads = 0

    def values(self):
        self.reads += 1
        return super().values()


def _pair(locale, seed_value):
    untouched = Faker(locale)
    untouched.seed_instance(seed_value)
    seedgraph_fake = GenerationState().fake
    if locale != DEFAULT_LOCALE:
        seedgraph_fake = Faker(locale)
        generators.install_cumulative_sampling(seedgraph_fake)
    seedgraph_fake.seed_instance(seed_value)
    return untouched, seedgraph_fake


def test_a_weighted_table_drawn_many_times_reads_its_weights_once():
    table = CountingTable([("rare", 1), ("common", 8), ("medium", 3)])
    fake = GenerationState().fake

    for _ in range(50):
        fake.random_element(table)

    assert table.reads == 1


@given(
    locale=st.sampled_from(LOCALES),
    seed_value=st.integers(0, 2**32 - 1),
    calls=st.lists(st.sampled_from(FORMATTERS), min_size=1, max_size=60),
)
def test_provider_calls_return_the_values_of_an_untouched_faker(locale, seed_value, calls):
    untouched, seedgraph_fake = _pair(locale, seed_value)

    assert [getattr(seedgraph_fake, name)() for name in calls] == [getattr(untouched, name)() for name in calls]
    assert seedgraph_fake.random.getstate() == untouched.random.getstate()


def _outcome(fake, elements, length, unique, use_weighting):
    try:
        return fake.random_elements(elements, length=length, unique=unique, use_weighting=use_weighting)
    except (AssertionError, ValueError, ZeroDivisionError) as error:
        return type(error)


weights = st.one_of(st.integers(0, 10**6), st.floats(0, 1e6, allow_nan=False, allow_infinity=False))


@given(
    seed_value=st.integers(0, 2**32 - 1),
    table=st.lists(weights, min_size=1, max_size=300),
    length=st.one_of(st.none(), st.integers(1, 50)),
    unique=st.booleans(),
    use_weighting=st.sampled_from([None, True, False]),
    rounds=st.integers(1, 5),
)
def test_any_weighted_table_draws_what_an_untouched_faker_draws(seed_value, table, length, unique, use_weighting, rounds):
    elements = OrderedDict((f"k{i}", weight) for i, weight in enumerate(table))
    untouched, seedgraph_fake = _pair(DEFAULT_LOCALE, seed_value)

    for _ in range(rounds):
        expected = _outcome(untouched, elements, length, unique, use_weighting)
        assert _outcome(seedgraph_fake, elements, length, unique, use_weighting) == expected
    assert seedgraph_fake.random.getstate() == untouched.random.getstate()


def test_a_plain_dict_is_refused_like_an_untouched_faker_refuses_it():
    with pytest.raises(ValueError, match="OrderedDict"):
        GenerationState().fake.random_elements({"a": 1, "b": 2})


def _graph_values(shape):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        graph = seed(session, Person, **shape)
        rows = [tuple(getattr(person, c.key) for c in Person.__table__.columns) for person in graph.people]
        rows += [tuple(getattr(note, c.key) for c in Note.__table__.columns) for note in graph.notes]
        rows += [tuple(getattr(person, c.key) for c in Person.__table__.columns) for person in seed(session, Person).people]
    engine.dispose()
    return rows


@given(people=st.integers(0, 120), notes=st.integers(0, 4))
def test_seed_builds_the_same_graph_as_with_an_untouched_faker(people, notes):
    expected_shape = {"person": people, "notes": notes}
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(generators, "install_cumulative_sampling", lambda fake: None)
        expected = _graph_values(expected_shape)

    assert _graph_values(expected_shape) == expected



def test_nothing_is_installed_when_faker_changes_the_signature_it_relies_on(monkeypatch):
    original = BaseProvider.random_elements
    monkeypatch.setattr(BaseProvider, "random_elements", lambda self, elements, length=None, unique=False: original(self, elements, length, unique))
    fake = Faker(DEFAULT_LOCALE)

    install_cumulative_sampling(fake)

    assert all("random_elements" not in vars(provider) for provider in fake.factories[0].providers)
