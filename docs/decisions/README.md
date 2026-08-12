# Architecture decision records

Decisions that outlive the task that produced them. Each lands in the same
commit as the artifact it constrains, so the reasoning and the code arrive
together and a reviewer can check one against the other.

Format is MADR-lite: **Status / Context / Decision / Consequences**. Context
carries the failure the decision is defending against, not a summary of the
decision — if the Context could be deleted without changing what a reader
would do, it is not doing its job.

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-layer-graph.md) | The layer graph is data, enforced on both axes | Accepted 2026-08-11 |
| [0002](0002-cli-grammar-and-exit-codes.md) | CLI grammar and exit codes | Accepted 2026-08-11 |
| 0003 | *never issued — see below* | — |
| [0004](0004-version-and-provenance.md) | Static version; git state recorded separately | Accepted 2026-08-11, extended by #4 |
| [0005](0005-dependency-policy.md) | Dependency policy: `pyproject.toml` is the sole declaration | Accepted 2026-08-11 |
| [0006](0006-conformance-battery.md) | The conformance battery is two-tiered and is the FAR bound's provenance | Accepted 2026-08-12 |

## 0003 was never issued

There is no ADR 0003. It was not written, withdrawn or renamed — the number
was skipped when 0004 and 0005 landed together in `9f1749b`. Confirmed
against the full history: no file was ever added, deleted or renamed at that
number, and nothing in the tree references it.

It is recorded here so the gap reads as answered rather than as a missing
document someone should go looking for.

## Numbers are permanent

A number, once issued, identifies that decision forever. It is never reused
and never reassigned, so gaps stay open rather than being closed by
renumbering — `CLAUDE.md` cites 0001 and 0005, and `layers.toml` cites 0001,
so shifting numbers to tidy a sequence would silently break live references
in exchange for nothing.

A decision that stops being true is **superseded, not deleted**: the original
keeps its number and gains a `Superseded by NNNN` status, because the reason
it was once right is usually the fastest way to understand why its
replacement is shaped as it is.
