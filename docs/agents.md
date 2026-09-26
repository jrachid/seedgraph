# Using seedgraph with coding agents

A coding agent writes better test data when it knows seedgraph exists and how to call it. Pick the form your agent reads.

## Claude Code: install the plugin

The seedgraph repository is also a Claude Code plugin marketplace. In a terminal:

```bash
claude plugin marketplace add jrachid/seedgraph
claude plugin install seedgraph@seedgraph
```

Or inside a session: `/plugin marketplace add jrachid/seedgraph`, then `/plugin install seedgraph@seedgraph`.

The plugin carries one skill, which Claude loads on its own when a task needs SQLAlchemy test data: the call, the shape syntax, the pytest fixtures and the fix for each error. It follows the repository's commits; `/plugin marketplace update seedgraph` fetches the latest.

To keep the skill in a project without the plugin, copy [`SKILL.md`](https://github.com/jrachid/seedgraph/blob/main/plugins/seedgraph/skills/seedgraph/SKILL.md) to `.claude/skills/seedgraph/SKILL.md` and commit it.

## Any agent: a paragraph in AGENTS.md or CLAUDE.md

Paste this into the instructions file your agent reads (`AGENTS.md`, `CLAUDE.md`, `.cursor/rules`, `.github/copilot-instructions.md`):

```markdown
## Test data

Create SQLAlchemy test data with seedgraph, never by hand-building objects or setting foreign key ids: `seed(session, User, post=2, post__comment=3)` builds 3 users with 2 posts each and 3 comments per post, flushes, and verifies every foreign key. Existing rows go in `parents=[...]`; required JSON or custom-type columns need `generators={Model: {"column": lambda ctx: ...}}`. In pytest, use the `seedgraph_graph` fixture.

Docs for agents: https://jrachid.github.io/seedgraph/llms-full.txt
```

## Documentation in a form agents read

- [`llms.txt`](https://jrachid.github.io/seedgraph/llms.txt): a summary with one link per page.
- [`llms-full.txt`](https://jrachid.github.io/seedgraph/llms-full.txt): the whole documentation in one Markdown file.

Both are rebuilt with the site on each release, so they describe the version on PyPI.
