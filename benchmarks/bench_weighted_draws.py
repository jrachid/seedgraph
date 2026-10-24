"""Time seed() with Faker's weighted tables drawn as Faker draws them, then from cached cumulative weights; run it by hand."""

import json
import statistics
import subprocess
import sys
import time
from typing import Any

from sqlalchemy import ForeignKey, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

from seedgraph import generators, seed


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    email: Mapped[str] = mapped_column(unique=True)
    posts: Mapped[list["Post"]] = relationship(back_populates="author")


class Post(Base):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    subtitle: Mapped[str | None]
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    author: Mapped[User] = relationship(back_populates="posts")
    comments: Mapped[list["Comment"]] = relationship(back_populates="post")


class Comment(Base):
    __tablename__ = "comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    body: Mapped[str]
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"))
    post: Mapped[Post] = relationship(back_populates="comments")


class Member(Base):
    __tablename__ = "members"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(120), unique=True)


class Person(Base):
    __tablename__ = "people"
    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(60))
    last_name: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(120))
    username: Mapped[str] = mapped_column(String(60), unique=True)
    email: Mapped[str] = mapped_column(String(120), unique=True)
    company: Mapped[str] = mapped_column(String(120))
    city: Mapped[str] = mapped_column(String(60))
    phone: Mapped[str] = mapped_column(String(40))


SCENARIOS: dict[str, tuple[type[Base], dict[str, int], int]] = {
    "readme_27": (User, {"user": 3, "post": 2, "post__comment": 3}, 41),
    "readme_11100": (User, {"user": 100, "post": 10, "post__comment": 10}, 9),
    "members_10000": (Member, {"member": 10000}, 9),
    "people_5000": (Person, {"person": 5000}, 9),
}

VARIANTS = ["untouched", "cached"]


def _once(scenario: str) -> float:
    model, shape, _ = SCENARIOS[scenario]
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        start = time.perf_counter()
        seed(session, model, **shape)
        elapsed = time.perf_counter() - start
    engine.dispose()
    return elapsed


def worker(variant: str, scenario: str) -> None:
    if variant == "untouched":
        generators.install_cumulative_sampling = lambda fake: None
    _once(scenario)
    samples = [_once(scenario) for _ in range(SCENARIOS[scenario][2])]
    print(json.dumps({"median": statistics.median(samples), "quartiles": statistics.quantiles(samples, n=4)}))


def main() -> None:
    for scenario in SCENARIOS:
        medians: dict[str, Any] = {}
        for variant in VARIANTS:
            command = [sys.executable, __file__, variant, scenario]
            result = json.loads(subprocess.run(command, capture_output=True, text=True, check=True).stdout)
            medians[variant] = result["median"]
            q1, _, q3 = result["quartiles"]
            print(f"{scenario:>14} {variant:>9}: {result['median'] * 1000:8.1f} ms  IQR [{q1 * 1000:.1f}, {q3 * 1000:.1f}]")
        print(f"{scenario:>14}   speedup: x{medians['untouched'] / medians['cached']:.2f}", flush=True)


if __name__ == "__main__":
    if len(sys.argv) == 3:
        worker(sys.argv[1], sys.argv[2])
    else:
        main()
