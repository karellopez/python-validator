# Deno parity benchmark (`tools/deno_bench`)

This harness is the acceptance instrument for the full-validation port. It runs
the reference Deno `bids-validator` and this package's full validator over the
same datasets, **at a matched schema**, and reports the metrics that gate every
capability phase.

## Why a matched schema

The Deno validator always validates against its *bundled* schema unless told
otherwise. To compare fairly we force `-s v1.11.1` on Deno and run the new
validator at the same schema. A schema-matched run is the only valid benchmark:
mismatched runs hide real false positives.

## Metrics

- **False positives** (the hard gate, target `0`): `ERROR` `(code, location)`
  pairs the new validator emits that Deno does not. A PR that increases this
  fails CI.
- **Coverage / recall**: the fraction of Deno's `ERROR` findings the new
  validator also emits. Tracked upward as rules land; intentional misses (for
  example HED disabled) are documented.
- **Per-code confusion matrix**: matched / extra / missed counts per issue code.

## Requirements

- The Deno validator on `PATH` as `bids-validator-deno`, or pass `--deno-bin`,
  or set `$BIDS_VALIDATOR_DENO`. Pin **v2.4.1** (bundled schema BIDS 1.11.1).
- A dataset corpus. The repo submodule `tests/data/bids-examples` is the default
  corpus; any directory of `*/dataset_description.json` works via `--corpus`.

## Usage

```bash
# Explicit datasets
python tools/deno_bench/run_bench.py path/to/ds1 path/to/ds2

# Whole corpus
python tools/deno_bench/run_bench.py --corpus tests/data/bids-examples

# CI gate (non-zero exit on any false positive)
python tools/deno_bench/run_bench.py --corpus tests/data/bids-examples --fail-on-fp

# Exclude a documented, intentional bidsval-only signal from the FP gate
python tools/deno_bench/run_bench.py path/to/ds --accept JSON_SCHEMA_VALIDATION_ERROR
```

Output: a markdown summary on stdout plus `comparison.json` (raw per-dataset
metrics) in `--out-dir` (default: current directory).

## Baseline ("before")

Until the full-validation engine exposes `bids_validator.validation.validate`,
the new-validator arm reports "engine not available" and the run captures the
Deno-only picture. That is the baseline the port improves on, phase by phase.
