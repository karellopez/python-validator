# Tutorial

A hands-on guide to validating BIDS datasets with python-validator, from the
command line and from Python. Every example is runnable. The two halves are
independent: read [Part 1](#part-1-the-command-line) if you live on the command
line, [Part 2](#part-2-the-python-api) if you are scripting or building a tool.

- [Setup](#setup)
- [Part 1: the command line](#part-1-the-command-line)
- [Part 2: the Python API](#part-2-the-python-api)
- [Part 3: choosing a schema](#part-3-choosing-a-schema)
- [Part 4: continuous integration](#part-4-continuous-integration)

## Setup

Install the package with the CLI extra:

```bash
pip install "bids-validator[cli] @ git+https://github.com/karellopez/python-validator@main"
```

For a sample dataset to validate, the
[bids-examples](https://github.com/bids-standard/bids-examples) repository is the
canonical source:

```bash
git clone https://github.com/bids-standard/bids-examples
```

The examples below use `bids-examples/ds102` (a small fMRI dataset). You can also
build a minimal dataset by hand to follow along:

```bash
mkdir -p mydataset/sub-01/anat
cat > mydataset/dataset_description.json <<'JSON'
{ "Name": "My dataset", "BIDSVersion": "1.11.1" }
JSON
# a real dataset would have a real NIfTI here; an empty file is reported invalid
: > mydataset/sub-01/anat/sub-01_T1w.nii.gz
```

## Part 1: the command line

### Your first validation

Point `bids-validator` at a dataset root:

```bash
bids-validator bids-examples/ds102
```

By default it validates against the latest stable schema and prints a text
report: a banner, then one line per finding, then a tally.

```
bids-validator 2.0.0  schema 1.2.1  BIDS 1.11.1
bids-examples/ds102
  ERROR   EMPTY_FILE  sub-13/anat/sub-13_T1w.nii.gz - file is empty (0 bytes): it exists but contains no data
           how to fix: The file name and location are valid, but there is no content. Replace it with real data.
  ...
78 error(s), 2461 warning(s)
INVALID
```

(The bids-examples datasets ship empty placeholder files, so they are reported
invalid for that reason. That is expected and is exactly what the reference
validator reports too.)

### Reading a finding

Each finding line has, in order:

- a **severity** (`ERROR`, `WARNING`),
- a **code** (for example `EMPTY_FILE`, `SIDECAR_KEY_RECOMMENDED`), the stable
  identifier you can filter and count on,
- an optional **sub-code** in brackets (for example a field name),
- the **location** (the dataset-relative path),
- a **message**, and a `how to fix` **suggestion**.

### Showing only what you care about

`--show` filters the displayed severities. It does not change the exit code,
which always reflects errors.

```bash
bids-validator bids-examples/ds102 --show error      # errors only
bids-validator bids-examples/ds102 --show warning     # warnings only
bids-validator bids-examples/ds102 --show all         # everything (default)
```

### Choosing an output format

Four formats are available with `--output-type`:

```bash
bids-validator bids-examples/ds102 --output-type text    # human-readable (default)
bids-validator bids-examples/ds102 --output-type json    # machine-readable
bids-validator bids-examples/ds102 --output-type sarif    # SARIF 2.1.0 for code scanning
bids-validator bids-examples/ds102 --output-type html    # a self-contained HTML report
```

The JSON shape is flat and stable: run metadata, counts, then one `issues` list.

```bash
bids-validator bids-examples/ds102 --output-type json --show error | head -20
```

```json
{
  "validatorVersion": "2.0.0",
  "bidsVersion": "1.11.1",
  "schemaVersion": "1.2.1",
  "datasetRoot": "bids-examples/ds102",
  "valid": false,
  "counts": { "error": 78, "warning": 2461, "ignore": 0 },
  "issues": [
    { "severity": "error", "code": "EMPTY_FILE", "location": "sub-13/anat/sub-13_T1w.nii.gz", "message": "..." }
  ]
}
```

Write a report to a file instead of stdout with `--out-dir`:

```bash
bids-validator bids-examples/ds102 --output-type html --out-dir ./reports
# writes ./reports/bids-validator-report.html
```

### Summarising with jq

Because the JSON is flat, common questions are one `jq` line:

```bash
# how many of each error code?
bids-validator bids-examples/ds102 --output-type json --show error \
  | jq -r '.issues[].code' | sort | uniq -c | sort -rn

# list the files with errors
bids-validator bids-examples/ds102 --output-type json --show error \
  | jq -r '.issues[].location' | sort -u
```

### Going faster while iterating

Reading NIfTI headers is the slow part on real (non-placeholder) data. Skip it
for a quick structural pass:

```bash
bids-validator bids-examples/ds102 --no-headers --show error
```

Header checks (such as `NIFTI_HEADER_UNREADABLE` and dimension checks) are then
skipped; everything else still runs. `--max-rows` is accepted for a stable
interface (intended to bound how many TSV rows value-type checks scan) but is not
yet enforced.

### Legacy filename-only check

The original `is_bids` filename check (used by pybids and mne-bids) is still
available:

```bash
bids-validator bids-examples/ds102 --filenames-only
```

This prints any path that is not a valid BIDS filename and exits non-zero if any
are found. It does no content validation.

## Part 2: the Python API

### Validate a dataset

```python
from bids_validator import validate

report = validate("bids-examples/ds102")

print(report.is_valid)          # False
print(report.counts)            # {'error': 78, 'warning': 2461, 'ignore': 0}
print(report.bids_version)      # '1.11.1'
print(report.schema_version)    # '1.2.1'
```

`validate()` returns a `ValidationReport`. It never raises on a bad dataset:
every problem is a finding, and an unreadable file becomes a finding rather than
an exception.

### Inspect the findings

Findings live in two places: `report.files` (per-file) and
`report.dataset_issues` (not tied to one file). Each finding is an `Issue`.

```python
from bids_validator import validate
from bids_validator.validation import Severity

report = validate("bids-examples/ds102")

# every error, file by file
for verdict in report.files:
    for issue in verdict.issues:
        if issue.severity is Severity.ERROR:
            print(f"{issue.code:24} {issue.location}")
            if issue.suggestion:
                print(f"    fix: {issue.suggestion}")

# dataset-level findings (README, citation, orphaned sidecars, ...)
for issue in report.dataset_issues:
    print(issue.severity.value, issue.code, issue.message)
```

An `Issue` carries: `code`, `severity` (a `Severity` enum; `.value` is the
string `"error"`/`"warning"`/`"ignore"`), `location`, `sub_code`, `message`,
`suggestion`, `rule` (the schema rule path that produced it), and for tabular
findings `line` / `lines`. Two extras beyond the reference validator help tools:
`provenance` (the exact selectors and checks, for an "explain" feature) and `fix`
(a machine-actionable remediation hint).

### Count findings by code

```python
from collections import Counter
from bids_validator import validate
from bids_validator.validation import Severity

report = validate("bids-examples/ds102")
by_code = Counter(
    issue.code
    for verdict in report.files
    for issue in verdict.issues
    if issue.severity is Severity.ERROR
)
for code, n in by_code.most_common():
    print(f"{n:5}  {code}")
```

### Validate a single file

`validate_file()` indexes the whole dataset (so inheritance and association
checks still work) but returns only the named file's `FileVerdict`:

```python
from bids_validator import validate_file

verdict = validate_file("bids-examples/ds102", "sub-13/anat/sub-13_T1w.nii.gz")
print(verdict.path, verdict.severity)
for issue in verdict.issues:
    print(issue.code, issue.message)
```

### Render a report yourself

The renderers are exposed as pure functions, so you can produce any format from a
report you already have in memory:

```python
from bids_validator import validate
from bids_validator.validation import to_text, to_json, to_html, to_sarif

report = validate("bids-examples/ds102")

print(to_text(report))                       # the same text the CLI prints
json_str = to_json(report)                   # 2-space indented JSON
json_min = to_json(report, pretty=False)     # compact
html_str = to_html(report)                   # a self-contained HTML document
sarif_str = to_sarif(report)                 # SARIF 2.1.0
```

### Filter by severity

`report.filtered()` returns a new report keeping only the chosen severities. The
original report's validity is unaffected (validity always depends on errors):

```python
from bids_validator import validate
from bids_validator.validation import Severity, to_text

report = validate("bids-examples/ds102")
errors_only = report.filtered({Severity.ERROR})
print(to_text(errors_only))
```

### Skip headers

The same performance controls as the CLI are keyword arguments. `read_headers`
skips the NIfTI header reads; `max_rows` is accepted for a stable signature but
is not yet enforced:

```python
report = validate("bids-examples/ds102", read_headers=False, max_rows=500)
```

### The legacy filename check

Unchanged, and still import-light:

```python
from bids_validator import BIDSValidator

BIDSValidator().is_bids("/sub-01/anat/sub-01_T1w.nii.gz")   # True
BIDSValidator().is_bids("/sub-01/anat/sub-01_T1.nii.gz")    # False
```

`import bids_validator` and `is_bids` stay fast: the full engine is only imported
the first time you call `validate` / `validate_file`.

## Part 3: choosing a schema

The validator reads the BIDS standard from a schema, so the BIDS version is a
single choice. The default is the schema bundled with the installed
`bidsschematools` (the latest stable version, matching the reference validator).

On the command line:

```bash
bids-validator DATASET --schema 1.10.0       # a bundled version, offline
bids-validator DATASET --schema v1.9.0       # a leading "v" is fine
bids-validator DATASET --schema ./schema.json            # a local dereferenced schema
bids-validator DATASET --schema ./bids-specification/src/schema   # a YAML source tree
bids-validator DATASET --schema latest        # the dev tip (fetched and cached)
bids-validator --list-schemas                 # what is bundled
```

In Python, pass the same selector to `schema=`:

```python
from bids_validator import validate

validate("DATASET", schema="1.10.0")           # a bundled version
validate("DATASET", schema="./schema.json")    # a local schema
```

Or resolve a schema once and reuse it (resolution is cached, so this is also a
small optimisation when validating many datasets):

```python
from bids_validator.validation import resolve, available_versions, bids_version, schema_version

print(available_versions())          # ['1.8.0', '1.9.0', '1.10.0', '1.10.1', '1.11.0', '1.11.1']

schema = resolve("1.10.0")
print(bids_version(schema), schema_version(schema))   # 1.10.0 0.11.3

report = validate("DATASET", schema=schema)
```

Bundled versions 1.10.0 and newer are validated at full Deno parity. 1.8.0 and
1.9.0 are bundled for completeness and validate with reduced coverage. See
[benchmarks.md](benchmarks.md).

## Part 4: continuous integration

The exit code is built for CI: `0` valid, `1` invalid (errors present), `2`
usage error. A minimal GitHub Actions step:

```yaml
- name: Validate BIDS dataset
  run: |
    pip install "bids-validator[cli] @ git+https://github.com/karellopez/python-validator@main"
    bids-validator "$GITHUB_WORKSPACE/dataset" --show error
```

Upload the SARIF report so findings appear in the GitHub Security tab:

```yaml
- name: Validate and emit SARIF
  run: bids-validator dataset --output-type sarif --out-dir sarif-out
- uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: sarif-out/bids-validator-report.sarif
```

Or gate a job from Python, which gives you the counts to log:

```python
import sys
from bids_validator import validate

report = validate("dataset")
print(f"{report.counts['error']} errors, {report.counts['warning']} warnings")
sys.exit(0 if report.is_valid else 1)
```

## Where to next

- The complete option list and recipes: [cli-reference.md](cli-reference.md).
- How the validator works inside, with flowcharts: [architecture.md](architecture.md).
- How it compares to the Deno reference validator: [benchmarks.md](benchmarks.md).
