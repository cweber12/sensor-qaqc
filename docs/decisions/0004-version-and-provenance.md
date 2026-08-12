# 0004 — Static version; git state recorded separately

## Status

Accepted (2026-08-11). Extended by #4, whose manifest carries the fields
named under Consequences.

## Context

The tool version is written into every run manifest and read back months or
years later, so it must be stable and honest. `setuptools-scm` derives the
version from git state at build time: a tarball without a `.git` directory
gets a different version than the same source with one, and a dirty tree
emits a version embedding the build date (`0.1.dev5+g98ad33e.d20260811`).
Both make the recorded version depend on how and when the package was built
rather than on what the code is.

## Decision

The version is a static string in `pyproject.toml`, bumped by hand in a
release commit. Git state is recorded separately and honestly in each run
manifest: `version`, `git_commit`, `git_dirty`.

## Consequences

- A release is an explicit, reviewable diff of one line.
- A manifest can say "0.1.0, commit abc1234, dirty tree" — which is the
  truth — instead of encoding all three into one mangled version string.
- Nothing about the recorded version changes with the presence of `.git`,
  the build day, or the packaging path (wheel, sdist, editable).
