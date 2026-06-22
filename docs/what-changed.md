# From a filename check to a full validator

This package used to do one thing: given a file path, tell you whether the path
looks like a valid BIDS filename. It still does that, unchanged. On top of it we
added a second, much larger capability: reading a whole dataset and checking its
contents against the BIDS schema, the way the reference validator does.

This page explains what the old behaviour was, what the new behaviour is, how the
two fit together, and why we built it the way we did. It is meant to be read
before [architecture.md](architecture.md), which goes through the new engine in
detail.

## What the package did before

The original entry point is `BIDSValidator.is_bids(path)` in
[`bids_validator.py`](../src/bids_validator/bids_validator.py). You give it one
path, relative to the dataset root with a leading slash, and it returns a boolean:

```python
from bids_validator import BIDSValidator

BIDSValidator().is_bids("/sub-01/anat/sub-01_T1w.nii.gz")   # True
BIDSValidator().is_bids("/sub-01/anat/sub-01_T1.nii.gz")    # False (no such suffix)
```

It works entirely on the path string. On first use it builds a list of regular
expressions from the BIDS schema, by calling
`bidsschematools.rules.regexify_filename_rules` on the `common` and `raw`
filename-rule groups (`bids_validator.py:98`, `_init_regexes`). `parse(path)`
(`bids_validator.py:110`) then tries each regex against the path and returns the
entities it captured (or an empty dict if none matched); `is_bids` is just
"did anything match" (`bids_validator.py:172`). A handful of helper predicates
(`is_top_level`, `is_session_level`, `is_phenotypic`, and so on) read the same
parsed entities.

```mermaid
flowchart LR
    P["one path string,<br/>e.g. /sub-01/anat/sub-01_T1w.nii.gz"] --> RX["try each filename regex<br/>built from schema.rules.files<br/>(common + raw)"]
    RX -- "a regex matches" --> T["True<br/>(plus the parsed entities)"]
    RX -- "nothing matches" --> F["False"]
```

This is exactly what tools like pybids and mne-bids need: a fast, dependency-light
way to ask "is this a BIDS file name?" for a path they already have in hand.

What it does **not** do is everything else a validator is usually expected to do.
It looks at one path at a time, never opens the file, and never looks at any other
file. So it cannot tell you that a required sidecar field is missing, that a TSV
column has the wrong type, that an `events.tsv` references a stimulus that is not
there, that a NIfTI is empty, or that two files collide on a case-insensitive
filesystem. And it answers only yes or no: there are no findings, no severities,
and no message explaining what is wrong.

## What we added

The new code, all under [`validation/`](../src/bids_validator/validation/), reads
a whole dataset and produces a list of findings, matching the output of the
reference [Deno validator](https://github.com/bids-standard/bids-validator). The
public entry point is `validate(root)`:

```python
from bids_validator import validate

report = validate("/path/to/dataset")
print(report.is_valid, report.counts)     # e.g. False {'error': 3, 'warning': 41, 'ignore': 0}
for verdict in report.files:
    for issue in verdict.issues:
        print(issue.severity.value, issue.code, issue.location)
```

Where the old check took a path and returned a boolean, the new one takes a
directory and returns a structured report:

```mermaid
flowchart TD
    D["a dataset directory"] --> TREE["read the whole file tree"]
    TREE --> PERFILE["for each file: build a context,<br/>then run the schema's rules<br/>and the checks written in Python"]
    PERFILE --> CROSS["look across files:<br/>orphan sidecars, unused stimuli,<br/>case collisions"]
    CROSS --> REP["a report: every finding<br/>with a code, severity, and location"]
```

The new capability covers what the old one could not:

| Question | Old `is_bids` | New `validate` |
|---|---|---|
| Is this filename valid? | yes | yes |
| Is a required sidecar field present? | no | yes |
| Does a TSV column have the right type? | no | yes |
| Does `events.tsv` reference a missing stimulus? | no | yes |
| Is a NIfTI empty or unreadable? | no | yes |
| Do two paths collide on case? | no | yes |
| What exactly is wrong, and how serious? | no (boolean only) | yes (findings with severity and a message) |
| Which BIDS version? | the installed schema | any bundled or supplied schema |

## How the two fit together

We did not replace the old behaviour or rewrite it. `bids_validator.py` is
unchanged, and a test (`tests/test_is_bids_canary.py`) pins `is_bids` so it cannot
drift. The two live side by side in the same package:

```mermaid
flowchart TD
    IMP["import bids_validator"] --> ISB["BIDSValidator().is_bids(path)<br/>regex filename check,<br/>no engine loaded"]
    IMP -. "first call to validate()" .-> LAZY["lazily import validation/"]
    LAZY --> VAL["validate(root) / validate_file(root, path)<br/>the full content engine"]
```

The full engine is imported lazily (`__init__.py`, the `__getattr__` hook): just
importing `bids_validator`, or calling `is_bids`, does not pull in the validation
engine or its dependencies. The first call to `validate` or `validate_file` is
what loads it. This keeps the original, lightweight use case as fast as it was
before, while making the new capability available from the same import.

So a consumer chooses by what it needs:

- `BIDSValidator().is_bids(path)` to ask about one filename, cheaply, as pybids
  and mne-bids do.
- `validate(root)` (or the `bids-validator` command) to validate a whole dataset.

## How the new engine was built

The engine is a port of [bidsval](https://github.com/karellopez/bidsval), a
schema-driven Python validator, adapted onto the pieces this package already had.
Three decisions shaped it.

**It reuses this package's file model.** Rather than introduce a second way to
read files, the engine builds on the existing `FileTree`
([`types/files.py`](../src/bids_validator/types/files.py)) and the cached content
loaders in [`context.py`](../src/bids_validator/context.py). A file is read at
most once, through one set of loaders, whether the read is for the base context or
for an associated file. See
[architecture.md](architecture.md#turning-one-file-into-a-context) for how that
context is assembled.

**It reads the schema instead of hardcoding BIDS.** Every datatype, entity,
suffix, extension, field definition, and most of the rules come from the
`bidsschematools` schema at runtime, the same schema the old regex builder used.
Because the schema is just data that flows in, the validator can run against a
different BIDS version: six versions are bundled, and a local or remote schema
also works (see [Schema selection](cli-reference.md#schema-selection)).

**It is built to agree with the reference validator.** The target is to produce
the same findings as the Deno validator. A practical consequence runs through the
whole engine: when a check cannot determine an answer from what is available, it
does nothing rather than guess, because a wrong complaint is worse than a missed
one. That choice is explained where it comes up in
[architecture.md](architecture.md). The measured result is on
[benchmarks.md](benchmarks.md): 99.9% of the reference validator's error findings
at the latest stable schema, with no invented error codes on raw datasets.

## Why we did it

The reference BIDS validator is excellent but ships as a Deno binary, which is an
extra runtime to install and call out to. A Python tool that wants to validate a
dataset in-process, as part of a larger workflow, previously had only the filename
check in this package (which is not a full validator) or a subprocess call to
Deno. The goal here was a complete, schema-driven validator that runs as a normal
Python import and library call, produces the same findings as the reference, and
still ships the lightweight filename check the existing ecosystem relies on. That
is what the `validation/` engine provides, and what the rest of these docs
describe.

## Where to go next

- [architecture.md](architecture.md) walks through the new engine in detail, with
  flowcharts for each stage.
- [tutorial.md](tutorial.md) shows the command line and the Python API in use.
- [benchmarks.md](benchmarks.md) reports how closely it matches the reference
  validator.
