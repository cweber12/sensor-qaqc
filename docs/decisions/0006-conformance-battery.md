# 0006 — The conformance battery is two-tiered and is the FAR bound's provenance

## Status

Accepted (2026-08-12).

## Context

The prior prototype certified pure white noise as "SENSOR ARTIFACT RULED
OUT": three checks that could not run were indistinguishable from three
that passed. #2 therefore requires a battery that runs against every
registered check, and the 2026-08-11 audit on #2 found two ways the
battery as first specified could itself pass while testing nothing:
twenty AR(1) draws cannot measure a 5 % false-alarm bound (a check three
times worse than its bound slips a 20-draw test almost half the time),
and the decimation/gap ladders assert what PASS may degrade to without
anything guaranteeing a PASS exists to degrade from.

## Decision

- **Two tiers.** *Smoke* — n = 20 fixed-seed AR(1) realisations, every
  PR, asserting only gross violation (observed FAR ≤ 3× declared),
  labelled a smoke test, not a measurement. *Full* — n ≥ 200, weekly via
  `-m battery`, an exact-binomial test at α = 0.01 against the declared
  bound. **The full run's `FarMeasurement` is the bound's provenance**:
  a declared false-alarm bound may not change without a full run, which
  places it under the existing rule that a number never moves in a
  refactoring commit.
- **A false alarm is a FAIL on the AR(1) null.** MARGINAL on the null is
  measured and recorded beside it but not bounded — a suspect flag on
  healthy data is a false suspicion, not a false alarm, and the recorded
  marginal rate keeps drift visible. INCONCLUSIVE on the null is a
  battery failure, never a data point: an undecidable null leaves the
  rate unmeasured.
- **Every check declares a positive control** (enforced at registration):
  a seeded synthetic record it must PASS at native resolution. The
  ladders decimate and gap-inject that record. Degrading to INCONCLUSIVE
  is fine; degrading to MARGINAL **or** FAIL is a bug — the stricter of
  the two wordings in #2, adopted deliberately.
- **Vacuity guards.** Negative controls and nulls are asserted
  *admissible* (the check's declared requirements all met) before any
  verdict is inspected, so INCONCLUSIVE can never silently satisfy "must
  not PASS". The guard currently covers the target's own requirements;
  when capability-consuming checks arrive (#8) it extends to provider
  chains.
- **Seeds** derive from `sha256(check_id/case/realisation_index)` —
  never a shared stream (registering a check would shift every later
  check's draws and blame the wrong commit), never the builtin `hash`
  (process-salted).
- **Battery parameters carry their reasons** (constants in
  `core/synthetic.py`): dt 6 min — the finest #2 ladder rung, above the
  MX2204's 4-min stirred-water t90 (Onset spec digest); duration 21 d —
  the recorded prior-failure deployment length, above the 15 d
  constituent floor (Zervas 1999 via #8); AR(1) τ = 1 h — the coastal
  decorrelation floor recorded in #2, with AR(1) as the standard
  geophysical null per the autocorrelation compendium (Part G); quantised
  step 0.01 °C — the MX2204's stated resolution. Amplitudes are
  documented order-of-magnitude choices; a check must be scale-aware
  through its thresholds, not through the battery's choice of scale.
- **The battery lives in `core`** (importable machinery), with thin
  pytest wrappers parametrised over `build_registry()` — a registered
  check is battery-covered with no further wiring, and there is no
  opt-out.

Related enforcement recorded here so it is not dropped: ADR 0001's
"thresholds are injected, never imported" is currently structural —
`compute` receives thresholds as an argument and no threshold catalog
module exists for a domain to import. The AST-based rule lands when the
first catalog module does (#6/#7).

## Consequences

- A new check inherits all five case classes by registering; a check
  that cannot beat the battery cannot ship.
- Changing a declared false-alarm bound requires a full battery run and
  shows up as a reviewable diff whose provenance names that run.
- Fixed seeds make every battery outcome deterministic: a battery
  failure is a real property of the check, reproducible anywhere.
- The full tier costs minutes weekly, not per-PR latency.
