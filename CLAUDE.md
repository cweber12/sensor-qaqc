# CLAUDE.md

Instructions for Claude Code in this repository.

## What this is

`sensor-qaqc` verifies in-water temperature records from low-cost loggers against
reference stations. It answers two different questions with two different kinds of output:

- **QC** — is each observation plausible? Per-observation QARTOD flags, via `ioos_qc`.
- **QA** — is this record measuring the ocean, or measuring itself? Record-level verdicts
  from quantisation, spectral, autocorrelation, astronomical and cross-sensor evidence.

## Where the design lives

Architecture and scope are recorded in **GitHub issues #1–#13**, not in this file. Read the
relevant PRD before starting work. Decisions are written up as ADRs in `docs/decisions/` as
PRDs and issues close.

This file is expanded by #1 (Foundation & packaging). Until then it covers commit
conventions only.

## Commit messages

**Use [Conventional Commits](https://www.conventionalcommits.org/) for every commit.**

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

### Types

| Type | Use for |
|---|---|
| `feat` | a new capability |
| `fix` | a bug fix |
| `docs` | documentation only |
| `refactor` | restructuring that changes no behaviour and no number |
| `test` | tests only |
| `perf` | performance |
| `build` | packaging, dependencies |
| `ci` | CI configuration |
| `chore` | anything else — repo setup, config, housekeeping |

### Scope

Optional. Use the subpackage or the config file the change belongs to: `core`, `marine`,
`config`, `ingest`, `report`, `stations`.

### Description

Imperative mood, lowercase, no trailing period. `add spike threshold`, not
`Added spike threshold.`

### Body

Explain **why**, not what — the diff already says what. State what the change does *not*
do if that is likely to be assumed.

### Footers

- `Refs: #12` — the issue this belongs to. Include one wherever an issue exists.
- `BREAKING CHANGE: <description>` — or a `!` after the type/scope: `feat(core)!: ...`
- `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

### Example

```
fix(marine): use native units when measuring the quantum

Quantisation was measured after conversion to Celsius, which put the
reporting grid on a non-integer multiple of the encoder step and inflated
the SD/q ratio. Measure in the logger's native unit, then convert.

Refs: #7
```

## Rules that constrain commits

**Never change a number in a refactoring commit.** Every threshold carries a written
reason for its value. A commit that both restructures code and moves a threshold cannot
be reviewed, because the diff hides which of the two changed the result. Change the number
in a separate, single-purpose commit that states what changed, from what to what, and why.

**Never commit a threshold without its provenance.** If you cannot say where a number came
from, it is not ready to commit.

**One logical change per commit.** If the description needs an "and", it is two commits.
