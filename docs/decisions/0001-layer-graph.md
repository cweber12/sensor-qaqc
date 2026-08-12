# 0001 — The layer graph is data, enforced on both axes

## Status

Accepted (2026-08-11).

## Context

The prior prototype had no import boundaries at all; the original version of
PRD 1 enforced a boundary nobody had drawn. Boundaries stated in prose decay
because nothing fails when they are crossed. Two specific failure classes
motivate the shape of the rule:

- **A name-based intra-package rule misses the third-party axis entirely.**
  `core` importing `erddapy` couples the generic check machinery to a marine
  network dependency exactly as hard as `core` importing `marine` — and it
  is the breach a reviewer is least likely to notice.
- **Text-level or import-time checks miss lazy imports.** An import inside a
  function body or an `if TYPE_CHECKING:` block is still a coupling.

## Decision

The graph lives in `src/sensor_qaqc/layers.toml`, shipped as package data,
and `tests/test_layers.py` enforces it by walking every AST node of every
module — so function-level and `TYPE_CHECKING` imports are caught. Intra-
package and third-party imports are checked against the same graph.

| Layer | May import layers | May import third-party |
|---|---|---|
| `core` | — | numpy, pandas, jinja2, matplotlib, yaml |
| `instruments` | core | numpy, pandas, openpyxl |
| `marine` | core, instruments | numpy, pandas, scipy, ioos_qc, erddapy |
| `cli` | core, instruments, marine | anything |

The stdlib is always allowed. Files at the package root belong to no layer
and may import only the stdlib.

**Allowances are explicit and non-transitive.** A layer may import another
layer's modules without inheriting its third-party allowance — transitive
allowances would hand `marine` an openpyxl licence through `instruments`.
This is why `instruments` and `marine` list numpy and pandas themselves
(2026-08-11 audit, finding 3, which also added `yaml` to `core`: the
system's config surface is YAML and `tomllib` covers only TOML).

**The test ships with negative tests.** Acceptance item 3 of #1: a test
that introduces a violating import and asserts it is caught, for each
evasion class — plain, attribute-form (`from sensor_qaqc import marine`),
function-level, `TYPE_CHECKING`-guarded, and relative.

Related rules this graph deliberately does *not* express:

- **Thresholds are injected into checks, never imported by them.** No module
  under a domain may import a marine constant. This is what keeps
  `plausibility/` and `integrity/` cheap to promote out of `marine/`; it is
  enforced from #2 when thresholds exist as objects.
- **Untyped dependencies are confined to one adapter module each**
  (`marine/stations/_erddap.py`, `marine/plausibility/_ioos_qc.py`) — the
  only places `no-untyped-call` is disabled. Enforceable by the same test
  when those modules exist.
- `matplotlib.use("Agg")` belongs in `cli`, never in an importable module.

## Consequences

- Growing an allowance is a one-line, reviewable diff to `layers.toml` in
  the commit whose code needs it — not a silent import.
- A new layer directory must be declared in the graph or the test fails.
- The graph shipping as package data means the wheel carries its own
  architecture record; the CI build job asserts it is present.
