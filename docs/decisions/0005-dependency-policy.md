# 0005 — Dependency policy: pyproject.toml is the sole declaration

## Status

Accepted (2026-08-11).

## Context

The harvested skeleton declared dependencies twice — `pyproject.toml` and
`requirements*.txt` — and its CI installed from the requirements files via a
second package manager (micromamba). Two declarations drift; the one CI does
not install from becomes fiction. Separately, this project's rule that every
number carries a written reason applies to version floors: an unexplained
floor is an unexplained number.

## Decision

- **`pyproject.toml` is the sole dependency declaration.** No requirements
  files. CI installs what the package declares.
- **pip/uv, not conda.** Nothing in the dependency set needs a compiler or a
  system library. The one thing that would — `cf-units` → UDUNITS-2, a known
  pip-on-Windows failure — is deferred by #13 and stays an optional
  `[netcdf]` extra if it ever ships.
- **Build backend: hatchling** (`>=1.27`, the first release with PEP 639
  license expressions). Src-layout native, and it includes package files
  (`py.typed`, `layers.toml`, packaged data) by default, so rejecting
  `MANIFEST.in` costs nothing.
- **Dependencies land with the first import.** A dependency nothing imports
  is an unenforceable claim, and its floor would be a number without a
  reason. Each runtime dependency arrives in the commit whose code imports
  it, its floor (if any) carrying a written reason. A bare name is fine —
  no number, no provenance burden. Known-already: `pandas>=2.2` (lowercase
  offset aliases, recorded in #1) when pandas arrives; `ioos_qc` pinned
  exact when #6 lands, with the pin's reason.
- **`uv.lock` committed**, used by the locked CI legs via
  `uv sync --locked`, which fails on a stale lock rather than silently
  re-resolving. Excluded from the sdist, never read at runtime. Renovate
  batches lock-only updates into one weekly PR.
- Dev tools (`[dependency-groups] dev`) carry no floors: the lockfile pins
  what is actually used, and the weekly unlocked CI leg tests the latest
  releases so breakage surfaces as an issue, not as a blocked PR.

## Consequences

- One declaration; nothing to drift.
- Reproducible CI (locked legs) and an early-warning channel (weekly
  unlocked leg) are separate jobs with separate failure meanings.
- Adding a dependency is reviewable: the import, the declaration and the
  floor's reason arrive in one commit.
