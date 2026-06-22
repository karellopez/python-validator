# CLI reference

The command-line interface is `bids-validator`. It validates a dataset's content
against the BIDS schema and reports the findings in your chosen format.

The command is installed by the `[cli]` extra (`pip install "bids-validator[cli]"`),
which pulls in `typer`. Without it, use the [Python API](tutorial.md#part-2-the-python-api)
instead.

```
bids-validator [OPTIONS] BIDS_PATH
```

A second console entry point, `bids-validator-python`, is an alias for the same
command (useful when another `bids-validator` is on the PATH).

## Argument

| Argument | Description |
|---|---|
| `BIDS_PATH` | Path to the dataset root (the directory containing `dataset_description.json`). Required, except when `--list-schemas` or `--version` is given. |

## Options

| Option | Default | Description |
|---|---|---|
| `--schema SELECTOR` | installed `bidsschematools` (latest stable) | Which schema to validate against. See [Schema selection](#schema-selection). |
| `--list-schemas` | | Print the default and bundled schema versions, then exit. |
| `--out-type {text,json,sarif,html,all}` | `text` | The report format, or `all` to write every format at once. See [Output formats](#output-formats) and [Where output goes](#where-output-goes). |
| `--out-dir DIR` | | Directory to write the report file(s) into, as `DIR/bids-validator-report.<ext>` (`txt`, `json`, `sarif`, `html`). See [Where output goes](#where-output-goes). |
| `--show {error,warning,all}` | `all` | Which severities to include in the *output*. Does not change the exit code (validity always depends on errors). |
| `--no-headers` | off | Skip reading NIfTI headers. Faster, but header checks (for example `NIFTI_HEADER_UNREADABLE`, dimension checks) are then skipped. |
| `--max-rows N` | `1000` | Intended cap on TSV rows scanned per table during value-type checks. Accepted for a stable interface; row scanning is not yet bounded (value typing currently reads every row), so this is a no-op today. |
| `--filenames-only` | off | Run only the legacy `is_bids` filename check (no content validation). Prints any non-compliant filename. |
| `-v`, `--verbose` | off | Print the validator version banner before validating. |
| `--version` | | Print the version and exit. |
| `--install-completion` | | Install shell completion (a `typer` built-in). |
| `--show-completion` | | Print the shell completion script (a `typer` built-in). |
| `--help` | | Show the help and exit. |

## Exit codes

The exit code is meant for scripts and CI:

| Code | Meaning |
|---|---|
| `0` | Valid: no error-level findings (warnings do not affect this). |
| `1` | Invalid: at least one error-level finding. |
| `2` | Usage error: an unknown `--out-type`. |

`--show` only filters what is displayed; the exit code is computed from the
unfiltered result, so `--show warning` still exits `1` when there are errors.

## Schema selection

`--schema` takes one selector, resolved in this order:

| Selector | Example | Behaviour |
|---|---|---|
| (omitted) | | The schema bundled with the installed `bidsschematools`: the latest stable BIDS version, matching the reference validator's bundled schema. |
| a bundled version | `--schema 1.10.0`, `--schema v1.11.1` | Loaded offline from the package. A leading `v` is accepted. |
| a local file | `--schema ./schema.json` | A dereferenced `schema.json`. |
| a source directory | `--schema ./bids-specification/src/schema` | A schema YAML source tree (a custom or forked schema). |
| `latest` | `--schema latest` | The development tip, fetched from the BIDS specification site and cached. |
| a non-bundled version | `--schema 1.7.0` | Fetched from the specification site (`vX.Y.Z`) and cached. |
| a URL | `--schema https://.../schema.json` | Fetched and cached. |

Fetched schemas are cached under `$XDG_CACHE_HOME/bids-validator/schemas` (or
`~/.cache/bids-validator/schemas`), so a version is downloaded at most once.

List what is bundled:

```console
$ bids-validator --list-schemas
default (installed bidsschematools): BIDS 1.11.1 (schema 1.2.1)
bundled versions: 1.8.0, 1.9.0, 1.10.0, 1.10.1, 1.11.0, 1.11.1
select one with '--schema X.Y.Z'; a local schema.json, a source directory, 'latest', or a URL also work.
```

## Where output goes

By default a single format is printed to **stdout**, so it composes with the
shell: pipe it to another tool, or redirect it to a file with `>`. The validator
does not write a file unless you ask it to.

```bash
bids-validator DATASET --out-type json            # prints to stdout
bids-validator DATASET --out-type json > out.json # you choose the file
bids-validator DATASET --out-type json | jq .     # or pipe it onward
```

`--out-dir` opts into writing a file instead, named
`bids-validator-report.<ext>` for the chosen format:

```bash
bids-validator DATASET --out-type html --out-dir ./reports
# writes ./reports/bids-validator-report.html
```

`--out-type all` writes every format at once, so it cannot stream to stdout. It
always writes files: into `--out-dir` if given, otherwise into the current
directory. Each path it writes is printed.

```bash
bids-validator DATASET --out-type all --out-dir ./reports
# Wrote ./reports/bids-validator-report.txt
# Wrote ./reports/bids-validator-report.json
# Wrote ./reports/bids-validator-report.sarif
# Wrote ./reports/bids-validator-report.html
```

## Output formats

`--out-type` selects one of four renderers (or `all` to write them all). Each is
a pure function of the result, so the same run can be printed or written to any
number of files.

### text (default)

A human-readable summary. A version banner, the dataset root, one line per
finding with its severity, code, optional sub-code in brackets, location, and
message, then a `how to fix` hint, and a final `N error(s), M warning(s)` tally
with `VALID` or `INVALID`.

```console
$ bids-validator DATASET --show error
bids-validator 2.0.0  schema 1.2.1  BIDS 1.11.1
/path/to/DATASET
  ERROR   EMPTY_FILE  sub-13/anat/sub-13_T1w.nii.gz - file is empty (0 bytes): it exists but contains no data
           how to fix: The file name and location are valid, but there is no content. Replace it with real data.

1 error(s), 0 warning(s)
INVALID
```

### json

A flat, stable shape: run metadata, counts, and one list of every finding
(dataset-level and per-file together). Two-space indented.

```json
{
  "validatorVersion": "2.0.0",
  "bidsVersion": "1.11.1",
  "schemaVersion": "1.2.1",
  "datasetRoot": "/path/to/DATASET",
  "valid": true,
  "counts": { "error": 0, "warning": 29, "ignore": 0 },
  "issues": [
    {
      "severity": "warning",
      "code": "SIDECAR_KEY_RECOMMENDED",
      "location": "sub-01/anat/sub-01_T1w.nii.gz",
      "subCode": "Manufacturer",
      "message": "missing recommended field 'Manufacturer'",
      "suggestion": "Manufacturer of the equipment that produced the measurements. Add it to the JSON, for example {\"Manufacturer\": \"text\"}.",
      "rule": "rules.sidecars.mri.MRIHardware"
    }
  ]
}
```

Each issue carries `severity`, `code`, and `location` always, and
`subCode`, `message`, `suggestion`, and `rule` when present.

### sarif

SARIF 2.1.0, the Static Analysis Results Interchange Format. Use this to surface
findings in GitHub code scanning or any SARIF-aware tool. The findings land in
`runs[0].results[]`, each with its `ruleId` (the issue code), `level`, `message`,
and `locations`.

### html

A single self-contained HTML file (styles inline, no external assets) with the
summary and a table of findings. Good for sharing a report or attaching it as a
CI artifact.

```bash
bids-validator DATASET --out-type html --out-dir ./reports
# writes ./reports/bids-validator-report.html
```

### all

Writes all four formats in one run (see [Where output goes](#where-output-goes)).
Useful in CI when you want a machine-readable report and a human-readable one from
a single validation.

## Recipes

Validate and fail a CI job on errors:

```bash
bids-validator "$DATASET" --show error || exit 1
```

Write all four reports as CI artifacts:

```bash
bids-validator "$DATASET" --out-type all --out-dir ./reports
```

Fast structural pass (skip header reads) during iteration:

```bash
bids-validator "$DATASET" --no-headers --show error
```

Validate against an older BIDS version:

```bash
bids-validator "$DATASET" --schema 1.10.0 --show error
```

Check filenames only (the legacy behaviour, no content validation):

```bash
bids-validator "$DATASET" --filenames-only
```

Pipe JSON to `jq` to count findings by code:

```bash
bids-validator "$DATASET" --out-type json --show error \
  | jq -r '.issues[].code' | sort | uniq -c | sort -rn
```
