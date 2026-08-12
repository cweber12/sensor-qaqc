# 0002 — CLI grammar and exit codes

## Status

Accepted (2026-08-11).

## Context

The command surface is the tool's public vocabulary, and renames break
scripts, cron jobs and documentation. The prior prototype grew its CLI
command by command, so its grammar encoded implementation history rather
than the domain. Separately, automation needs exit codes it can branch on:
a cron job must be able to tell "the network is down" from "the catalogue
drifted" — and, in a tool whose central rule is *nothing is gated*, from
"the record failed", which is not an error at all.

## Decision

The full `argparse` tree lands before any command body exists, every body
raising `NotImplementedError`. `--help` is the reviewable spec; later PRDs
fill in bodies without renaming anything.

```
sensor-qaqc stations discover --lat --lon --radius-km
sensor-qaqc stations diff   [--site]
sensor-qaqc stations update [--site]
sensor-qaqc stations show   <id>
sensor-qaqc baseline  build --site --from --to
sensor-qaqc baseline  show  <site>
sensor-qaqc inspect   <file>
sensor-qaqc run       <deployment-id> [--check <id>]...
sensor-qaqc report    render <run-folder> [--pdf]
sensor-qaqc checks    list | show <id> | docs --out <dir>
```

Grammar decisions carried from #1 and the #5 audit:

- `run` is the only command that computes a verdict; everything else feeds
  it or reads it.
- `inspect` and `run` are separate because their preconditions differ:
  `inspect` runs on a file straight off a logger, before any
  `sensor_deployments.yaml` entry exists; `run` requires one. Both call one
  library ingest function.
- `stations diff` (read-only, detects drift) and `stations update` (accepts
  drift, writes) are split because detecting and accepting have different
  blast radii: a cron job that mutates the catalogue on every 404 destroys
  the evidence instead of reporting it.
- `diff`, not `check`: *check* is the central domain noun and spending it
  as a verb makes `--help` ambiguous.
- `report render` reads a finished run folder and nothing else, which is
  what makes #10's "renderers may not compute" structural.

**Exit codes.** Two categories of command, three codes:

| Category | Commands | Exit 0 means |
|---|---|---|
| producer | `run`, `baseline build`, `baseline show`, `report render`, `stations discover`, `stations update`, `stations show`, `inspect`, `checks *` | output was produced |
| assertion | `stations diff` | the assertion held |

- `0` — the command produced its output, or its assertion held. **Exit 0
  does not mean the record passed**: a FAIL verdict is a result, and a tool
  that exits nonzero on one has reintroduced an overall pass/fail gate
  through the back door.
- `1` — the tool could not produce a result (bad parse, checksum gate
  tripped, unpromoted station requested, no thresholds for the variable).
  **Usage errors land here too**: argparse hardwires exit 2 for them, so the
  parser's error path is remapped, because an unmapped typo in a
  `stations diff` cron line would read as drift.
- `2` — an assertion failed (`stations diff` only: the catalogue drifted).

Two codes, not a taxonomy; the reason goes to stderr and into the manifest.

## Consequences

- Later PRDs (#4, #5, #9, #10) implement bodies; any rename is a visible,
  reviewable breaking change to this ADR.
- Every parser in the tree subclasses the remapping parser, so usage errors
  anywhere in the tree exit 1.
- Until a body lands, its command exits 1 with
  `not implemented yet: <command>` on stderr — an unimplemented command is
  literally "the tool could not produce a result".
- Automation can branch on `0 / 1 / 2` without parsing stderr.
