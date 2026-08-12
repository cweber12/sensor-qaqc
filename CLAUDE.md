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

## Repo facts

- **Default branch:** `main` — protected: PRs required, green checks required, no force
  pushes, admins bound. Never commit to it directly; protection enforces this.
- **Issue tracker:** GitHub Issues via `gh`. `ready-for-agent` labels work that is scoped
  and unblocked.
- **Toolchain:** Python ≥ 3.11 in the uv-managed venv (`.venv`). Never the system
  interpreter.
- **Setup:** `uv sync`
- **Gate command:** `uv run python scripts/gate.py`
- **Merge strategy:** merge or rebase commits, never squash (disabled repo-wide) — every
  slice stays revertible and bisectable on its own.

## How to work: confirm, plan, branch, slice, PR

Follow this for any task beyond a one-line fix.

1. **Confirm understanding before doing anything.** Say back the ask in your own words,
   name the ambiguities and how you intend to read them, and say what you believe is *out*
   of scope. If two readings lead to materially different work, ask.
2. **Plan in slices.** A slice does one thing nameable in a short sentence, leaves the
   gates passing, and can be committed and understood alone. Rename, refactor, bugfix and
   feature are separate slices. Slices are vertical — a complete path through the layers,
   not one layer across the feature.
3. **Confirm the plan before implementing.** When it changes mid-flight — and verification
   will change it — say so and re-confirm rather than quietly expanding scope.
4. **The plan is written down before slice 1.** *In this repo the PRD issues are the plan
   files*: plans for PRD work live in the issue and its comments, amended there. Work no
   PRD covers gets `docs/plans/<slug>.md`, committed first, stating the problem, decisions,
   test seams, rejected alternatives, and what is out of scope. Decisions that outlive the
   task get an ADR in `docs/decisions/` (not `docs/adr/`), in the same commit as the
   artifact it constrains.
5. **Split into issues only when it earns its keep** — the test is whether two people could
   pick up two issues without colliding. One slice, one issue is overhead.
6. **Branch per unit of work**, cut from up-to-date `main`: `issue-<n>-<slug>`, or a short
   slug when no issue exists. One issue per branch; adjacent fixes you notice get their own
   issue, not a ride-along commit. Rebase onto moved `main` *before* opening the PR; after
   the PR is open, never rewrite pushed history.
7. **One slice, one commit, verified.** Behaviour changes ship tests in the same commit; a
   bugfix starts with a regression test proven to fail first (`must_fail` rows in the gate
   table support this). Before each commit: run the gate, read its output, check
   `git status` and `git diff --staged` for only-this-slice content. Do not batch commits.
8. **Push, open a PR, wait.** The PR body carries `Closes #<n>`, the what and why at slice
   level, **the actual gate output** (a claim is not evidence), and anything not done.
   Keep PRs reviewable (~400 changed lines / ~5 slices as a guide). **Do not merge, approve
   or bypass checks yourself** — wait for confirmation. On confirmation: merge (never
   squash), branches delete on merge, return to `main` and pull.
9. **Report honestly.** Blocked slices are named, failing output is shown, and bugs found
   in your own earlier work are stated plainly.

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
uv run python scripts/gate.py     # every gate, one command, a row per gate
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

## Verification

Don't claim something works because it ran without raising. Assert the property that
matters: the output is correct, not merely produced; the state changed, not merely that
the call returned; the parser produced the right value, not merely no exception.

**The gate set lives in the table in `scripts/gate.py`, not in prose.** Add a gate by
adding a row. Every row runs even when an earlier one fails, so a failure cannot hide
behind another.

**Recorded deviation:** CI does not invoke the gate script. `ci.yml` fans the same rows
out as separate jobs — a #1 decision, so a type error cannot hide behind a test failure —
and adds packaging assertions the local build row skips. The gate rows and the CI jobs
must stay the same set; if they drift, the drift is the first bug to fix.

## Security

- **Never commit secrets** — no keys, tokens, passwords or `.env` contents, not in
  fixtures, not "temporarily". Secrets come from the environment.
- If a secret lands in a commit, say so immediately; it is compromised on push and
  removing the commit does not un-leak it.
- No `curl | sh`, no dependencies from unverified sources, no widening permissions or
  scopes to make an error go away.

## General discipline

- **Never invent an identifier, path, URL or API.** If you can't confirm it, leave
  `TODO(verify)` and say so in your summary.
- **Nothing fails silently.** Anything skipped, empty or unusable is reported.
- **Read-only stays read-only.** Never write into an input directory; never let generated
  output become next run's input.
- **Don't fix a symptom with a constant.** If a value is off, find why — and remember
  every number here carries provenance.
- **When this file is wrong, fixing it is a slice** — propose the edit in its own commit
  rather than silently working around it.

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
