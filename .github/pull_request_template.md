<!-- Conventional Commits (see CLAUDE.md); one logical change per commit. -->

#### What this changes, and why

<!-- Use closing keywords (Fixes #N, Closes #N) where an issue exists. -->

#### Checklist

- [ ] Every changed number carries its provenance, in a commit of its own
- [ ] New behaviour has tests; new decisions have an ADR in the same commit as the artifact
- [ ] `uv run pre-commit run --all-files`, `uv run mypy` and `uv run pytest` are clean
