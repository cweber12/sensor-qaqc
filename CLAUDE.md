# CLAUDE.md

Instructions for Claude Code in this repository.

## What this is

`sensor-qaqc` verifies in-water temperature records from low-cost loggers against
reference stations. It answers two different questions with two different kinds of output:

- **QC** — is each observation plausible? Per-observation QARTOD flags, via `ioos_qc`.
- **QA** — is this record measuring the ocean, or measuring itself? Record-level verdicts
  from quantisation, spectral, autocorrelation, astronomical and cross-sensor evidence.

Four verdicts: PASS / MARGINAL / FAIL / INCONCLUSIVE. `ok = verdict == "PASS"` is banned.
Nothing is gated: no check suppresses another, no overall pass/fail, and exit 0 means the
run completed, not that the record passed.

## Where the design lives

Architecture and scope are recorded in **GitHub issues #1–#13**, not in this file. Read the
relevant PRD *and its comments* before starting work — audit findings and corrections live
in the comments, and several supersede the body they are attached to. Decisions are written
up as ADRs in `docs/decisions/` (MADR-lite: Status / Context / Decision / Consequences),
each landing in the same commit as the artifact it constrains.

PRDs here are audited cold by a fresh session before implementation. Push back on anything
unjustified rather than implementing it.

## Layout

`src/` layout, four layers, three domains under `marine/`:

```
src/sensor_qaqc/
├── core/            check protocol, verdicts, thresholds + provenance, run machinery
├── instruments/     vendor export formats and datasheet facts (onset/)
├── marine/          plausibility/ (#6), integrity/ (#7), coherence/ (#8), stations/ (#5)
└── cli/             command surface — the only layer that may import everything
```

The layer dependency graph is data — `src/sensor_qaqc/layers.toml` — and enforced by
`tests/test_layers.py` on both axes: intra-package and third-party imports alike.
Allowances are explicit and non-transitive. Growing an allowance is a one-line diff to
`layers.toml` in the commit whose code needs it (ADR 0001).

Thresholds are injected into checks, never imported by them. No module under a domain may
import a marine constant.

## Development

```
uv sync                            # environment + dev tools, from the committed lock
uv run pytest                      # network/battery markers excluded by default
uv run pre-commit run --all-files
uv run mypy                        # strict
```

- **Dependencies land with the first import** (ADR 0005). pyproject.toml is the sole
  declaration; each floor arrives in the commit whose code imports it, with its reason.
- Tests must pass from the committed state on Windows: paths through `pathlib`, filesystem
  tests through `tmp_path`. The Windows CI leg is load-bearing, not box-ticking.
- Fixtures under `tests/data/` and `docs/data/` are byte-exact (`-text` in
  `.gitattributes`); `tests/test_fixture_hashes.py` asserts committed SHA-256 values. If it
  goes red, fix the attribute, never the hash.

## Locations outside this repo

- `../vendor/` — cloned support repos (erddapy, ioos_qc, ioos_code_lab,
  ioos-python-package-skeleton). Reference only; not part of the working tree.
- `../hobo_toolkit` — the prior prototype. **Not authoritative; its architecture is not to
  be ported.** External facts carry over as citations; measurements of this setup carry
  over as claims the tool re-verifies; chosen thresholds are re-derived with a written
  reason, never inherited.
- `docs/qc_refs/` and `docs/verification_refs/` — sourced compendia justifying most
  thresholds. On disk but gitignored pending the citations-only publication pass (#11).

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

Optional. Use the layer, domain or config file the change belongs to: `core`,
`instruments`, `marine`, `cli`, `stations`, `config`.

### Description

Imperative mood, lowercase, no trailing period. `add spike threshold`, not
`Added spike threshold.`

### Body

Explain **why**, not what — the diff already says what. State what the change does *not*
do if that is likely to be assumed.

### Footers

- `Refs: #12` — the issue this belongs to. Include one wherever an issue exists.
- `BREAKING CHANGE: <description>` — or a `!` after the type/scope: `feat(core)!: ...`
- `Co-Authored-By: <the model that wrote it> <noreply@anthropic.com>`

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

**`check_id`s are never renamed.** They live in archived run folders forever; the registry
id set may only grow.
