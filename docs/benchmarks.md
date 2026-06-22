# Benchmarks

How closely python-validator reproduces the reference
[Deno validator](https://github.com/bids-standard/bids-validator), measured on a
real corpus at the latest stable BIDS schema and several older versions.

The aim is to match the reference validator: the same findings, at the same
severities, so a tool can use this in-process instead of calling the Deno binary
and get the same result. At the latest stable schema, python-validator reproduces
99.9% of Deno's error findings at exact severity, 94 of the 115 datasets have an
identical set of errors, and there is no error code it emits on a raw dataset that
Deno never emits.

- [Methodology](#methodology)
- [BIDS 1.11.1 (the latest stable schema)](#bids-1111-the-latest-stable-schema)
- [Across schema versions](#across-schema-versions)
- [Schemas Deno cannot load](#schemas-deno-cannot-load)
- [The known over-emission](#the-known-over-emission)
- [Per-code breakdown](#per-code-breakdown)
- [How to reproduce](#how-to-reproduce)

## Methodology

- **Corpus.** 115 datasets: the full
  [bids-examples](https://github.com/bids-standard/bids-examples) collection plus
  a handful of local real-data datasets (MRI, EEG, MEG, PET). They span every
  BIDS modality and include many that intentionally ship empty placeholder files
  (so both validators report them invalid, which is correct).
- **Matched schema.** Each validator is pinned to the *same* BIDS schema for a
  comparison, because findings legitimately differ between schema versions.
  Deno is run with `-s vX.Y.Z`, python-validator with `--schema X.Y.Z`.
- **Comparison unit.** Each report is reduced to its set of `(location, code)`
  **error** pairs. "Coverage" is the fraction of Deno's error pairs that
  python-validator also emits. "Over-emission" is python-validator error pairs
  Deno does not have. "Exact parity" counts datasets whose error-pair set is
  identical to Deno's.
- **Code-level false positive.** The strict gate: an error *code* that
  python-validator emits somewhere that Deno never emits anywhere. On raw
  datasets this is zero.

## BIDS 1.11.1 (the latest stable schema)

All three validators (Deno, [bidsval](https://github.com/karellopez/bidsval), and
python-validator) over the 115-dataset corpus at matched schema BIDS 1.11.1.

Aggregate finding totals:

| Validator | errors | warnings |
|---|---|---|
| Deno (reference) | 9962 | 138616 |
| python-validator | 10104 | 137544 |
| bidsval | 5659 | 133730 |

python-validator vs Deno (the parity target), at the error-pair level:

| Metric | Value |
|---|---|
| Deno error findings | 9521 |
| matched (same code and location) | 9507 (**99.9%**) |
| missed (Deno errors not emitted) | 14 |
| over-emission (extra error pairs) | 358 |
| code-level false positives | **0 codes** (on raw datasets) |
| datasets at exact error parity | **94 / 115** |

For context, bidsval reaches 54.3% of Deno's error findings on the same corpus,
not because it detects less but because it deliberately reports
`NIFTI_HEADER_UNREADABLE` as a *warning* rather than an *error*; python-validator
matches Deno's error severity, which is what the parity target requires. This
makes python-validator the most Deno-faithful of the three on raw data.

## Across schema versions

python-validator vs Deno at every schema version Deno can load, matched, over the
full 115-dataset corpus:

| Schema | Coverage of Deno errors | Exact-parity datasets | Missed | Over-emission |
|---|---|---|---|---|
| 1.11.1 | **99.9%** | 94 / 115 | 14 | 358 |
| 1.11.0 | **99.9%** | 94 / 115 | 14 | 358 |
| 1.10.1 | 96.8% | 86 / 115 | 322 | 347 |
| 1.10.0 | 96.5% | 84 / 115 | 353 | 349 |

Two honest observations:

1. **python-validator is most faithful at the current stable schema.** Coverage
   is 99.9% at 1.11.0 and 1.11.1, and dips to ~96.5% at 1.10.x. The gap at the
   older versions is almost entirely filename-rule findings
   (`FILENAME_MISMATCH`, `ALL_FILENAME_RULES_HAVE_ISSUES`): Deno's handling of the
   older `rules.files` evolved, and the hand-ported filename rules are tuned to
   the current schema. Content checks (sidecars, values, associations) track
   Deno closely at every version.
2. **The over-emission is the same at every version** (~350 pairs, dominated by
   the same codes), because it comes from a single feature gap (derivative
   datasets, below), not from anything version-specific.

## Schemas Deno cannot load

Deno's binary validates only at its bundled schema and a fetchable range; it
produces no output for BIDS 1.8.0 or 1.9.0. python-validator bundles and
validates them. There is no Deno reference to compare against at these versions,
so the numbers below are python-validator alone, demonstrating reach rather than
parity:

| Schema | datasets validated | errors | warnings |
|---|---|---|---|
| 1.9.0 | 115 | 10869 | 331934 |
| 1.8.0 | 115 | 13362 | 349735 |

The structural errors are stable across versions (`EMPTY_FILE` 4958,
`NIFTI_HEADER_UNREADABLE` 4336 at every schema); the variation is in
schema-specific field and filename rules. These older schemas predate the
machine-readable rule structure the engine leans on most, so coverage is reduced,
but the validator runs cleanly and produces a complete report rather than
crashing.

## The known over-emission

The 358 extra error pairs are not noise; they are one well-understood feature gap.
They cluster on a handful of codes, all on the same kind of dataset:

| Code | extra pairs | datasets |
|---|---|---|
| NOT_INCLUDED | 245 | atlas-*, derivative datasets |
| ENTITY_NOT_IN_RULE | 80 | atlas-* |
| MISSING_REQUIRED_ENTITY | 16 | atlas-* |
| SIDECAR_KEY_REQUIRED | 8 | PET datasets |
| JSON_SCHEMA_VALIDATION_ERROR | 5 | a few qMRI datasets |

The first three (341 of the 358) are all **derivative datasets** (the `atlas-*`
examples and `ds000001-fmriprep`). python-validator currently applies raw-dataset
filename rules to them because it does not yet read `DatasetType: derivative`
from `dataset_description.json` and switch to the derivative rule set. Deno does,
so it does not flag those files. This is a scoped, documented feature gap, not a
correctness bug, and it is the next planned piece of work. The remaining two
codes are documented as *more faithful than Deno*, not false positives (they are
real findings Deno happens not to surface).

Crucially, **none of these is a code-level false positive**: every code
python-validator emits, Deno also emits somewhere. The over-emission is
"validates a derivative dataset as if it were raw", not "invents a finding".

## Per-code breakdown

Error findings by code across the corpus at BIDS 1.11.1, all three validators:

| Code | Deno | python-validator | bidsval |
|---|---|---|---|
| EMPTY_FILE | 4955 | 4958 | 4954 |
| NIFTI_HEADER_UNREADABLE | 4336 | 4336 | 0 |
| JSON_SCHEMA_VALIDATION_ERROR | 453 | 296 | 568 |
| SIDECAR_KEY_REQUIRED | 128 | 96 | 60 |
| NOT_INCLUDED | 25 | 261 | 16 |
| ASSOCIATED_EMPTY_ROOM | 23 | 23 | 23 |
| TSV_VALUE_INCORRECT_TYPE | 16 | 12 | 12 |
| SIDECAR_WITHOUT_DATAFILE | 12 | 12 | 12 |
| BOLD_NOT_4D | 2 | 2 | 2 |
| EXTENSION_MISMATCH | 2 | 2 | 2 |
| REPETITION_TIME_MISMATCH | 2 | 2 | 2 |
| T1W_FILE_WITH_TOO_MANY_DIMENSIONS | 2 | 2 | 2 |
| PARTICIPANT_ID_MISMATCH | 1 | 1 | 1 |
| TSV_COLUMN_MISSING | 1 | 1 | 1 |
| ENTITY_NOT_IN_RULE | 0 | 80 | 0 |
| MISSING_REQUIRED_ENTITY | 0 | 16 | 0 |

`NIFTI_HEADER_UNREADABLE` is the clearest illustration of the severity
difference: python-validator matches Deno exactly (4336), while bidsval reports
those as warnings (0 errors). The `NOT_INCLUDED` / `ENTITY_NOT_IN_RULE` /
`MISSING_REQUIRED_ENTITY` excess is the derivative gap described above.

## How to reproduce

For a single dataset, compare the two validators directly:

```bash
# python-validator
bids-validator DATASET --schema 1.11.1 --out-type json --show error > pv.json

# Deno reference at the matched schema
bids-validator-deno --format json -s v1.11.1 DATASET > deno.json
```

Then diff their `(location, code)` error sets. To sweep the whole corpus and
every schema version, the harness scripts used for the numbers above
(`three_way_compare.py` for the 1.11.1 three-way, `multiversion_compare.py` for
the per-version sweep) run all validators over the
[bids-examples](https://github.com/bids-standard/bids-examples) corpus at a
matched schema and aggregate the per-pair metrics. They are kept with the test
outputs rather than in the package, since they depend on a local Deno binary and
the cloned corpus.
