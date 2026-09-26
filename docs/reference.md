# API reference

Everything below is importable from `seedgraph`, except the fixtures, which the pytest plugin registers on its own.

## Seeding

::: seedgraph.seed

::: seedgraph.seed_async

::: seedgraph.Graph

## Custom generators

`generators=` and `overrides=` are keyed by model, then by column name: `{User: {"name": ...}}`. A generator, or a callable override, receives this context:

::: seedgraph.generators.GenerationContext

## pytest fixtures

::: seedgraph.pytest_plugin
    options:
      show_root_heading: false
      show_root_toc_entry: false

## Errors

Every error derives from `SeedgraphError`, so one `except SeedgraphError` catches them all.

::: seedgraph.SeedgraphError

::: seedgraph.UnknownShapeKeyError

::: seedgraph.AmbiguousShapeKeyError

::: seedgraph.InvalidShapeCountError

::: seedgraph.UnsupportedShapeDirectionError

::: seedgraph.MissingRequiredParentError

::: seedgraph.AmbiguousParentError

::: seedgraph.UnattachedParentError

::: seedgraph.UnsupportedPlaceholderError

::: seedgraph.UniqueValueExhaustedError

::: seedgraph.UnknownGeneratorColumnError

::: seedgraph.UnknownOverrideColumnError

::: seedgraph.IncoherentGraphError
