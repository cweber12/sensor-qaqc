# sensor-qaqc

Verifies in-water temperature records from low-cost loggers against
reference stations.

Today that means: marine water temperature from Onset HOBO TidbiT
MX2203/MX2204 loggers, exported by HOBOconnect, compared against ERDDAP
reference stations. Nothing else — no air sensors, no other variables.

## Status

The command grammar, packaging and enforcement mechanisms exist; the check
logic is being built issue by issue. Every command below parses today and
exits 1 with `not implemented yet` until its issue lands.

## What it answers

Two different questions, with two different kinds of output:

- **QC — is each observation plausible?** Per-observation QARTOD flags,
  via `ioos_qc`.
- **QA — is this record measuring the ocean, or measuring itself?**
  Record-level verdicts from quantisation, spectral, autocorrelation,
  astronomical and cross-sensor evidence.

Verdicts are PASS / MARGINAL / FAIL / INCONCLUSIVE, and **nothing is
gated**: no check suppresses another, and there is no overall pass/fail.
The product of a run is the run folder — inputs, resolved config, results,
arrays and manifest — not the report rendered from it.

## Commands

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

Exit codes: `0` the command produced its output (**not** "the record
passed" — a FAIL verdict is a result), `1` the tool could not produce a
result, `2` an assertion failed (`stations diff` on catalogue drift). See
[ADR 0002](docs/decisions/0002-cli-grammar-and-exit-codes.md).

## Install

Requires Python 3.11+.

```
pip install .
```

## Development

```
uv sync            # environment + dev tools, from the committed lock
uv run pytest      # network/battery-marked suites are excluded by default
uv run pre-commit run --all-files
uv run mypy
```

Architecture and scope live in GitHub issues #1–#13; decisions are recorded
in [docs/decisions/](docs/decisions/). The layer dependency graph is
declared in [layers.toml](src/sensor_qaqc/layers.toml) and enforced by a
test.

## License

[BSD-3-Clause](LICENSE)
