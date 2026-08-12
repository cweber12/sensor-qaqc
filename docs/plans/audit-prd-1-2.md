# Audit of PRD 1 and PRD 2, before PRD 3 starts

## The problem

#1 and #2 are closed and every gate is green, but green gates prove the tests
pass — not that the tests would fail if the code were wrong. #3 builds ingest
on top of both: the check framework, the threshold and provenance model, the
registry, and the conformance battery. A defect in that foundation gets more
expensive with every PRD that lands on it, and the battery in particular is
the thing that is *supposed* to catch defects, so a hole there is invisible by
construction.

The precedent is recorded in #2: the prior prototype's negative controls ran
against a gappy index, returned INCONCLUSIVE for all four cases, and passed
their assertion while testing nothing. Every one of those tests was green.

## Two activities, not one

This is the decision that shapes the rest of the document. **A diff review
cannot answer the question that matters most here.** "Does this guard fail
when it should?" is answered by breaking something and watching for red, not
by reading a hunk. So the audit is two passes with different tools:

| | Activity | Answers | Tool |
|---|---|---|---|
| **A** | Diff review | Does the code follow the documented standards, and does it match what #1 and #2 asked for? | `mattpocock-skills:code-review`, two axes in parallel |
| **B** | Active verification | Do the guards fail when they should? | Run the code. Break things deliberately. |

Run **A** first: if an acceptance item turns out unmeetable as written — item 6
of #1 already was — that should be resolved before B spends effort on code
about to be rescoped.

## Fixed point

`f39171b`, the root commit. #1 and #2 span the whole history, so the review
diff is `git diff f39171b...HEAD` — 62 files, ~5,300 insertions.

## Sources

**Standards axis: `CLAUDE.md`.** There is no `CONTRIBUTING.md` and no
`CODING_STANDARDS.md`, so this must be named explicitly or the axis will find
nothing to review against.

**Spec axis: issues #1 and #2, *including their comments*.** Several comments
supersede the body they are attached to — this is stated in `CLAUDE.md` and it
is load-bearing here, because #1's acceptance list was revised twice by audit
findings. Reviewing against the bodies alone will produce wrong findings.

Also read `docs/decisions/0001`–`0006` and their index.

## Standards axis — what to look for

Beyond whatever the tool's baseline flags:

- Layer discipline: allowances non-transitive, third-party axis enforced as
  hard as the intra-package one.
- Thresholds injected into checks, never imported. No module under a domain
  imports a marine constant.
- `matplotlib.use("Agg")` confined to `cli`, never in an importable module.
- Dependencies landing with their first import, each with a stated reason.
- No import-time side effects, no module-level mutable state.
- Docstrings carrying reasoning — why the threshold is what it is, what the
  failure mode is, what the result does *not* prove — rather than restating
  the signature.

## Spec axis — what to produce

Walk every acceptance item in #1 and #2 and mark it **met** / **unmet** /
**unmeetable as written**. The third category is real and is not a failure of
the implementation: #1's item 6 required three YAML files that the layer split
assigns to #3 and #5. When an item is unmeetable, propose the rescope rather
than forcing it.

Also report behaviour present in the diff that neither PRD asked for.

## Active verification — the checklist that needs a running interpreter

Each of these is a place where a passing test would most easily be lying.

- **Is any battery case vacuous?** For each case, make it fail on purpose and
  confirm red. A control that cannot fail is worse than no control.
- **Do the negative controls run on a clean regular index**, as #2 requires —
  not on a gappy one that shatters the record into one-sample segments?
- **Is `MinOfFloors` genuinely absent from the codebase**, not merely unused?
- **Can a threshold be constructed without provenance by any route** — a
  default argument, a dataclass default, a `None` filled in later?
- **Can a threshold be looked up for a variable that has none and get a
  fallback?** #2 says it must refuse. Try it.
- **Does the layer test catch third-party breaches?** Add `import erddapy` to
  a module under `core` and confirm red. Confirm `marine` does not inherit
  `openpyxl` through `instruments`.
- **Are all four verdict states reachable and distinguishable end-to-end?**
  Search for any boolean derived from a verdict.
- **Does admissibility live in the runner?** Grep for length or NaN guards
  inside check bodies that should be declared requirements.
- **Determinism:** run the battery twice and diff; then run it again under a
  different `PYTHONHASHSEED`.
- **Is `checks show` reading the registry or reproducing it?** #10's
  "renderers may not compute" rule has the same shape and starts here.
- **Both OS legs:** confirm the fixture-hash test actually runs on Windows and
  Linux rather than skipping silently.

## Output

Findings ranked most-severe first. Each carries the file, the acceptance item
or `CLAUDE.md` rule it violates, and a concrete failure scenario — inputs or
state, and the wrong result that follows. Not a style opinion.

Push back on anything unjustified rather than implementing it. If #1 or #2 is
wrong, that is a finding.

## Out of scope

- PRDs #3–#13. Their acceptance items are not being audited.
- `docs/qc_refs/` and `docs/verification_refs/` content — the citations-only
  pass is #11.
- Performance. Nothing here is hot, and no PRD has stated a budget.
- Anything the gate already enforces: `ruff`, `mypy --strict`, the build. If
  those are green, do not re-litigate them by eye.

## Rejected alternatives

**Passing this file as the "spec" to the review skill.** Its Spec axis
compares a diff against what was *asked for*, and the specs are #1 and #2.
This document is a brief for the auditor, not a requirements source; feeding
it as the spec would produce findings measured against the wrong artifact.

**One combined pass.** The diff review runs as fixed-prompt sub-agents under
400 words per axis. The active-verification checklist neither fits that budget
nor is answerable from a diff.

**Deferring the audit until after #3.** #3's ingest work sits directly on the
framework and the battery. Finding a framework defect after #3 means
re-verifying #3 as well.
