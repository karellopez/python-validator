# python-validator documentation

A full, schema-driven BIDS validator for Python. It validates a dataset's
*content* (sidecar fields, tabular columns, file associations, dataset-level
rules, NIfTI headers) against the official BIDS schema, reproducing the output of
the reference [Deno validator](https://github.com/bids-standard/bids-validator)
without a separate runtime, and it keeps the lightweight
`BIDSValidator.is_bids` filename check that pybids and mne-bids depend on.

This package is the official `bids-validator` distribution on PyPI. The
full-validation engine documented here is the schema-interpreting core ported
from [bidsval](https://github.com/karellopez/bidsval); the legacy filename-only
check is preserved and unchanged.

## What it does

It reads a whole dataset and reports problems with its contents, not only its
filenames:

- Required and recommended sidecar fields, and the types of JSON values.
- TSV columns and the types of their cells.
- File associations: events, bval/bvec, channels, ASL context, coordinate
  systems, and so on.
- The inheritance principle, and dataset-level rules.
- NIfTI headers, empty files, and case collisions.

A few other things worth knowing:

- The rules, entities, suffixes, extensions, and field definitions all come from
  the BIDS schema at runtime, so the validator follows the standard as the schema
  changes. You can validate against any of six bundled BIDS versions (1.8.0
  through 1.11.1), or a local or remote schema. See
  [Schema selection](#schema-selection).
- It does not raise on a bad dataset: every problem is recorded as a finding, and
  one unreadable file cannot stop a run.
- It is built to produce the same findings as the reference
  [Deno validator](https://github.com/bids-standard/bids-validator). On a
  115-dataset corpus it reaches 99.9% of that validator's error findings at the
  latest stable schema. See [benchmarks.md](benchmarks.md).
- Output can be plain text, JSON, SARIF 2.1.0, or a self-contained HTML report.

## Documentation map

| Document | Read it for |
|---|---|
| [what-changed.md](what-changed.md) | How the previous filename check worked, what this added, how, and why. Start here if you know the old `is_bids` and want to understand the new engine. |
| [tutorial.md](tutorial.md) | A hands-on walkthrough of the command line and the Python API, with runnable examples: validate a dataset or a single file, choose a schema, every output format, inspect findings in Python, and CI integration. |
| [cli-reference.md](cli-reference.md) | The complete command-line reference: every option, every output format, exit codes, and recipes. |
| [architecture.md](architecture.md) | How the validator works internally, stage by stage, with code references and flowcharts. |
| [benchmarks.md](benchmarks.md) | The testing results against the Deno reference validator, at the latest stable schema and several older versions. |

## Install

The full-validation engine is not yet on a released version, so install from
source with the optional CLI dependency:

```bash
pip install "bids-validator[cli] @ git+https://github.com/karellopez/python-validator@main"
```

Or from a local checkout:

```bash
git clone https://github.com/karellopez/python-validator
cd python-validator
pip install -e ".[cli]"
```

The `[cli]` extra installs `typer`, which the `bids-validator` command needs. The
Python API (`from bids_validator import validate`) works without it.

Requires Python 3.10 or newer.

## Sixty-second quickstart

Command line:

```bash
# validate a dataset against the latest stable schema
bids-validator /path/to/bids/dataset

# only errors, machine-readable
bids-validator /path/to/bids/dataset --show error --output-type json

# validate against a specific BIDS version
bids-validator /path/to/bids/dataset --schema 1.10.0

# list the bundled schema versions
bids-validator --list-schemas
```

Python:

```python
from bids_validator import validate

report = validate("/path/to/bids/dataset")
print(report.is_valid, report.counts)        # e.g. False {'error': 3, 'warning': 41, 'ignore': 0}

for file in report.files:
    for issue in file.issues:
        print(issue.severity.value, issue.code, issue.location)
```

## Schema selection

The validator is fully schema-driven, so "which BIDS version" is a single choice
that flows through everything. By default it uses the schema bundled with the
installed `bidsschematools` (the latest stable BIDS version, the same schema the
reference validator bundles). You can also pin any bundled version, or point at a
local, forked, or remote schema:

```bash
bids-validator DATASET                      # default: installed bidsschematools (latest stable)
bids-validator DATASET --schema 1.10.0      # a bundled version, offline
bids-validator DATASET --schema v1.9.0      # a leading "v" is accepted
bids-validator DATASET --schema ./schema.json          # a local dereferenced schema
bids-validator DATASET --schema ./bids-specification/src/schema   # a YAML source directory
bids-validator DATASET --schema latest      # the development tip (fetched and cached)
```

Bundled versions: 1.8.0, 1.9.0, 1.10.0, 1.10.1, 1.11.0, 1.11.1. Full Deno-parity
coverage targets 1.10.0 and newer; 1.8.0 and 1.9.0 are bundled for completeness
and validate with reduced coverage (their schema predates the machine-readable
rules the engine evaluates). See [benchmarks.md](benchmarks.md) for the
per-version results.

## Two validators in one package

| API | Purpose | Dependencies |
|---|---|---|
| `BIDSValidator().is_bids(path)` | The legacy, lightweight filename check used by pybids and mne-bids. Unchanged. | none beyond the base package |
| `validate(root)` / the `bids-validator` CLI | The full content validator documented here. | the base package (CLI adds `typer`) |

The full engine is imported lazily, so `import bids_validator` and the `is_bids`
check stay fast even though the package now ships a complete validator.
