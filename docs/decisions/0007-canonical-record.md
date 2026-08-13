# 0007 — The canonical record: native units, a grid that refuses, provenance per field

## Status

Accepted 2026-08-12. Constrains `src/sensor_qaqc/core/records.py` (#3).

## Context

#3 makes the canonical record the contract: extraction and operator prompting are
both just ways of filling it, so a second export format is one adapter and nothing
downstream changes. That only holds if the record's own shape is decided once. Three
parts of that shape were still open, each with a recorded failure behind it.

**Units.** The prototype measured quantisation after converting to Celsius. That put
the reporting grid on a non-integer multiple of the encoder step and inflated the
SD/quantum ratio by roughly a factor of two. The pristine export is 3,029 values that
are all exact multiples of 0.01 °F, with 50.5% of occupied levels on *odd* hundredths
— evidence that only survives in the unit the logger encoded in. A record stored in
°C and converted back for that one measurement re-introduces float error into exactly
those digits, and the Details statistics the ingest gate reproduces are published in
°F, so the raw parse has to stay °F regardless.

**The grid.** `interpolate().dropna()` fills values without restoring missing rows.
Measured on a 21-day record with 2.8 days of rows removed, it reported an 18.21-day
span and mapped every tidal constituent into the wrong frequency bin
(`TIDAL_LINES_REVIEW.md`, D6 — a review demonstration, not a field incident).
Interpolation is also low-pass filtering, with 33–54% variance loss in the cited
literature, and it manufactures increment autocorrelation of exactly +1.0, which is
the statistic #7 measures. Splicing is not a milder version of the same thing: it
breaks the k·dt lag relationship every spectral method assumes.

**Metadata sources.** #3 splits metadata three ways: authoritative in the file
(model, serial, interval, native unit), sometimes in the file (position — this
deployment had `Location: Off`), and never in any file (depth, datum, mounting, the
in-water window). Typing `MX2204` by hand is strictly worse than reading it: a typo
applies the wrong device specs and nothing detects it. But a record that does not say
which fields were read and which were typed cannot report the difference, and "the
number of prompts shrinks as extractors improve" becomes an assertion rather than a
number.

## Decision

**1. `CanonicalRecord` lives in `core`**, in the same module as `RecordView`.
`core/synthetic.py` constructs records for the conformance battery and cannot import
`instruments`; the schema is the vendor-neutral contract operator input also fills;
it needs nothing beyond `core`'s existing allowance.

**2. The series stays in the source's native unit**, named by `units` as a UDUNITS-2
symbol (`degF`, `degC`). Ingest never converts. Consumers that need another unit
convert explicitly, reading `units` — which is why the field is mandatory and why
thresholds carry units of their own.

**3. The constructor owns the grid.** `to_uniform_grid` places parsed samples on the
true first-to-last span at exactly `interval_s`, leaving gaps as NaN in place. There
is no fill path, and a test asserts by AST that the module calls no
`interpolate`/`fillna`/`ffill`/`bfill`/`dropna`/`resample`. Off-grid, duplicated and
out-of-order timestamps are **refused, not reindexed away** — silently dropping a
sample is the failure the Details checksum gate exists to catch, so the parse must
not be able to cause it. `interval_s` is the only interval on the record; `dt` is
derived from it. `n_valid` and `gap_fraction` are computed from the grid, so
significance arithmetic can never reach for `len()`.

**4. Every populated field carries a `FieldSource`** — `extracted` or `supplied` —
in a mapping the record freezes at construction. A populated field with no entry is
refused; an entry naming an unpopulated field is refused too, since it would print
"operator-supplied" for a value nobody supplied.

## Consequences

- A check that assumes °C is now a unit bug rather than a silent scale error. This is
  the real cost of decision 2: `units` must be read, not assumed. It is mitigated by
  `units` being mandatory and by thresholds carrying their own unit, and it is
  preferred to the alternative, where the conversion error is invisible because every
  record looks alike.
- Adapters do more work: they must resolve local stamps to UTC and refuse a parse
  they cannot place on a grid, rather than handing over whatever they read. That is
  the intent — a parse that cannot be gridded is a parse that is wrong.
- `source_timezone_label` keeps the export's own declaration (`PDT`) as provenance.
  An abbreviation is not a zone, and the record must not pretend it resolved one it
  was never given.
- The vocabularies (`LoggingMode`, `EventType`) are closed enums seeded from what a
  real export was verified to contain. Growing either is a one-line diff in the
  commit whose parser produces the new member — the rule `Channel` already follows.
- Recording provenance per field costs every constructor a mapping. In exchange,
  "which fields still need an operator" is a property of the record
  (`missing_operator_fields`), not a guess made by the reporting layer.
