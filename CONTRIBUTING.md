# Contributing to seedgraph

Bug reports, questions and pull requests are welcome. For a change of behaviour, open an issue first so we can agree on it before you write the code.

## Set up

```bash
git clone https://github.com/jrachid/seedgraph.git
cd seedgraph
uv sync --all-extras
```

## Check your change

```bash
uv run pytest        # the PostgreSQL tests need Docker and are skipped without it
uv run ruff check .
uv run mypy
```

CI runs the same three commands on Python 3.11, 3.12 and 3.13, with PostgreSQL required.

## What a pull request needs

- A test that fails without the change and passes with it; each guarantee of the README names the test that proves it.
- Every `python` block of the README still runs: `tests/test_readme.py` executes them in order.
- A commit message in the [Angular convention](https://github.com/angular/angular/blob/main/CONTRIBUTING.md#commit): `fix(shape): …`, `feat(generators): …`.

## Where to start

Issues labelled [`good first issue`](https://github.com/jrachid/seedgraph/labels/good%20first%20issue) are small and self-contained.
