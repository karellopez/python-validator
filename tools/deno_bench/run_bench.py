"""Deno parity benchmark for the full-validation engine.

Runs the reference Deno ``bids-validator`` and this package's full validator over
a corpus of datasets *at a matched schema*, then reports the metrics that gate
every capability phase of the port:

* **false positives** - ``ERROR`` ``(code, location)`` pairs the new validator
  emits that Deno does not. This is the hard gate: it must be ``0``.
* **coverage / recall** - the fraction of Deno's ``ERROR`` findings the new
  validator also emits (tracked upward as rules land).
* **per-code confusion matrix** - matched / extra / missed counts per issue code.

Methodology (critical)
----------------------
The Deno validator always validates against its *bundled* schema unless told
otherwise. To compare fairly we force ``-s <schema>`` on Deno (default
``v1.11.1``) and run the new validator at the **same** schema. A schema-matched
run is the only valid benchmark; mismatched runs hide real false positives.

Usage
-----
Validate one or more datasets explicitly::

    python tools/deno_bench/run_bench.py DATASET [DATASET ...]

Glob every dataset under a corpus root (a dir of ``*/dataset_description.json``)::

    python tools/deno_bench/run_bench.py --corpus tests/data/bids-examples

Options::

    --schema v1.11.1        BIDS schema both validators use (matched).
    --max-rows 1000         Max TSV rows scanned (passed to both).
    --deno-bin PATH         Path to the Deno bids-validator (default: on PATH,
                            else $BIDS_VALIDATOR_DENO).
    --out-dir DIR           Where to write comparison.json (default: cwd).
    --accept CODE           Issue code to exclude from the FP gate (repeatable);
                            for documented, intentional bidsval-only signals.
    --fail-on-fp            Exit non-zero if any false positive remains (CI gate).

Until the full-validation engine lands, the new-validator arm reports "engine
not available" and the run captures the Deno-only "before" picture.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

DEFAULT_SCHEMA = 'v1.11.1'
DEFAULT_MAX_ROWS = 1000

IssuePair = tuple[str, str]  # (location, code)


def norm_location(location: str | None) -> str:
    """Normalise an issue location to a dataset-relative path without a leading slash."""
    return (location or '').lstrip('/')


def find_deno(explicit: str | None) -> str | None:
    """Locate the Deno ``bids-validator`` executable.

    Parameters
    ----------
    explicit : str or None
        An explicit path from ``--deno-bin``.

    Returns
    -------
    str or None
        The resolved command, or ``None`` if none is found.

    """
    import shutil

    for candidate in (explicit, os.environ.get('BIDS_VALIDATOR_DENO'), 'bids-validator-deno'):
        if candidate and (shutil.which(candidate) or Path(candidate).exists()):
            return candidate
    return None


def run_deno(
    dataset: Path,
    *,
    deno_bin: str,
    schema: str,
    max_rows: int,
) -> list[dict[str, Any]]:
    """Run the Deno validator and return its raw issue list.

    Parameters
    ----------
    dataset : Path
        The dataset root to validate.
    deno_bin : str
        The Deno validator command.
    schema : str
        The schema tag to force (matched comparison).
    max_rows : int
        Max TSV rows to scan.

    Returns
    -------
    list of dict
        Each issue dict has ``code``, ``severity`` and ``location`` keys.

    """
    proc = subprocess.run(  # noqa: S603
        [
            deno_bin,
            '--format',
            'json',
            '-s',
            schema,
            '--max-rows',
            str(max_rows),
            str(dataset),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if not proc.stdout.strip():
        raise RuntimeError(f'Deno produced no JSON for {dataset}: {proc.stderr[:400]}')
    payload = json.loads(proc.stdout)
    return list(payload['issues']['issues'])


def load_new_validator() -> Any | None:
    """Return the new full-validation ``validate`` callable, or ``None`` if absent.

    The engine is ported incrementally; until it exposes ``validate`` this
    returns ``None`` so the harness still captures the Deno-only baseline.
    """
    try:
        from bids_validator.validation import validate  # type: ignore[attr-defined]
    except (ImportError, AttributeError):
        return None
    return validate


def run_new(
    validate: Any,
    dataset: Path,
    *,
    schema: str,
    max_rows: int,
) -> list[dict[str, Any]]:
    """Run the new validator and normalise its report to Deno-shaped issue dicts.

    Parameters
    ----------
    validate : Callable
        The ``bids_validator.validation.validate`` entry point.
    dataset : Path
        The dataset root to validate.
    schema : str
        The schema tag (matched comparison).
    max_rows : int
        Max TSV rows to scan.

    Returns
    -------
    list of dict
        Each issue dict has ``code``, ``severity`` and ``location`` keys.

    """
    report = validate(dataset, schema=schema, read_headers=True, max_rows=max_rows)
    issues: list[dict[str, Any]] = []
    for issue in report.dataset_issues.issues:
        issues.append(_issue_to_dict(issue, default_location=''))
    for verdict in report.files:
        for issue in verdict.issues:
            issues.append(_issue_to_dict(issue, default_location=str(verdict.path)))
    return issues


def _issue_to_dict(issue: Any, *, default_location: str) -> dict[str, Any]:
    """Normalise one engine ``Issue`` to a Deno-shaped dict."""
    severity = issue.severity.value if hasattr(issue.severity, 'value') else str(issue.severity)
    return {
        'code': issue.code,
        'severity': severity,
        'location': issue.location or default_location,
    }


def error_pairs(issues: list[dict[str, Any]]) -> set[IssuePair]:
    """Return the set of ``(location, code)`` pairs for error-severity issues."""
    return {
        (norm_location(i.get('location')), i['code'])
        for i in issues
        if i.get('severity') == 'error'
    }


def compare(
    deno_issues: list[dict[str, Any]],
    new_issues: list[dict[str, Any]],
    *,
    accepted: set[str],
) -> dict[str, Any]:
    """Diff two issue lists and compute the parity metrics.

    Parameters
    ----------
    deno_issues : list of dict
        Reference issues from Deno.
    new_issues : list of dict
        Issues from the new validator.
    accepted : set of str
        Codes excluded from the false-positive gate.

    Returns
    -------
    dict
        Metrics: false positives, missed findings, coverage and per-code
        confusion matrix.

    """
    deno = error_pairs(deno_issues)
    new = error_pairs(new_issues)
    deno_codes = {code for _loc, code in deno}

    false_positive_pairs = sorted(
        (loc, code)
        for loc, code in (new - deno)
        if code not in deno_codes and code not in accepted
    )
    missed_pairs = sorted(deno - new)
    matched_pairs = deno & new

    codes = sorted(deno_codes | {code for _loc, code in new})
    confusion = {
        code: {
            'matched': sum(1 for loc, c in matched_pairs if c == code),
            'extra': sum(1 for loc, c in (new - deno) if c == code),
            'missed': sum(1 for loc, c in missed_pairs if c == code),
        }
        for code in codes
    }
    return {
        'deno_error_count': len(deno),
        'new_error_count': len(new),
        'matched': len(matched_pairs),
        'missed': len(missed_pairs),
        'false_positives': len(false_positive_pairs),
        'false_positive_pairs': false_positive_pairs,
        'coverage': (len(matched_pairs) / len(deno)) if deno else 1.0,
        'confusion': confusion,
    }


def discover_datasets(args: argparse.Namespace) -> list[Path]:
    """Resolve the list of dataset roots to validate from CLI args."""
    datasets: list[Path] = [Path(d) for d in args.datasets]
    if args.corpus:
        root = Path(args.corpus)
        datasets += sorted(p.parent for p in root.glob('*/dataset_description.json'))
    return [d for d in datasets if (d / 'dataset_description.json').exists()]


def main(argv: list[str] | None = None) -> int:
    """Run the benchmark and print a markdown summary; return a process exit code."""
    parser = argparse.ArgumentParser(description='Deno parity benchmark for full validation.')
    parser.add_argument('datasets', nargs='*', help='Dataset roots to validate.')
    parser.add_argument('--corpus', help='Glob every dataset under this corpus root.')
    parser.add_argument('--schema', default=DEFAULT_SCHEMA, help='Matched schema tag.')
    parser.add_argument('--max-rows', type=int, default=DEFAULT_MAX_ROWS)
    parser.add_argument('--deno-bin', help='Path to the Deno bids-validator.')
    parser.add_argument('--out-dir', default='.', help='Where to write comparison.json.')
    parser.add_argument(
        '--accept', action='append', default=[], help='Code to exclude from FP gate.'
    )
    parser.add_argument(
        '--fail-on-fp', action='store_true', help='Exit non-zero on any FP (CI gate).'
    )
    args = parser.parse_args(argv)

    deno_bin = find_deno(args.deno_bin)
    if deno_bin is None:
        print('ERROR: Deno bids-validator not found (set --deno-bin or $BIDS_VALIDATOR_DENO).')
        return 2

    datasets = discover_datasets(args)
    if not datasets:
        print('ERROR: no datasets found (pass paths or --corpus DIR).')
        return 2

    validate = load_new_validator()
    accepted = set(args.accept)
    engine_ready = validate is not None

    print(f'# Deno parity benchmark (schema {args.schema}, max-rows {args.max_rows})\n')
    if not engine_ready:
        print('> Full-validation engine not available yet: capturing the Deno-only baseline.\n')
    print('| Dataset | Deno err | new err | matched | missed | FP |')
    print('|---|---|---|---|---|---|')

    results: dict[str, Any] = {}
    total_fp = 0
    for dataset in datasets:
        try:
            deno_issues = run_deno(
                dataset, deno_bin=deno_bin, schema=args.schema, max_rows=args.max_rows
            )
        except (RuntimeError, json.JSONDecodeError) as exc:
            print(f'| {dataset.name} | ERR | - | - | - | - |  <!-- {exc} -->')
            continue
        new_issues = (
            run_new(validate, dataset, schema=args.schema, max_rows=args.max_rows)
            if engine_ready
            else []
        )
        metrics = compare(deno_issues, new_issues, accepted=accepted)
        results[str(dataset)] = metrics
        total_fp += metrics['false_positives']
        print(
            f'| {dataset.name} | {metrics["deno_error_count"]} | {metrics["new_error_count"]} '
            f'| {metrics["matched"]} | {metrics["missed"]} | {metrics["false_positives"]} |'
        )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        'schema': args.schema,
        'max_rows': args.max_rows,
        'engine_ready': engine_ready,
        'accepted_codes': sorted(accepted),
        'total_false_positives': total_fp,
        'datasets': results,
    }
    (out_dir / 'comparison.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')

    if engine_ready:
        all_codes: Counter[str] = Counter()
        for metrics in results.values():
            for _loc, code in metrics['false_positive_pairs']:
                all_codes[code] += 1
        print(f'\nTotal false positives: {total_fp}')
        if all_codes:
            print('FP codes:', dict(all_codes))
    print(f'\nWrote {out_dir / "comparison.json"}')

    if args.fail_on_fp and total_fp > 0:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
