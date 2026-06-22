"""Regression tests for the parity fixes found by the full-corpus comparison.

Directory-recording descent, .bidsignore honoring, and TSV trailing-blank-line
handling were each surfaced as false positives when validating the full
bids-examples corpus against the Deno reference.
"""

from __future__ import annotations

import json
from pathlib import Path

from bids_validator.validation import validate


def _base(tmp_path: Path) -> None:
    (tmp_path / 'dataset_description.json').write_text(
        json.dumps({'Name': 'fixes', 'BIDSVersion': '1.11.1'})
    )


def test_directory_recording_internals_not_validated(tmp_path: Path) -> None:
    # A .ome.zarr directory recording is one unit; its internal chunks must not be
    # walked (and so not flagged EMPTY_FILE / NOT_INCLUDED).
    _base(tmp_path)
    rec = tmp_path / 'sub-01' / 'micr' / 'sub-01_sample-brain_XPCT.ome.zarr'
    (rec / '0' / '0').mkdir(parents=True)
    (rec / '.zattrs').write_text('{}')
    (rec / '0' / '0' / '0').write_bytes(b'')  # an empty internal chunk
    report = validate(tmp_path)
    paths = {str(v.path) for v in report.files}
    assert not any('.ome.zarr/' in p for p in paths), 'descended into the directory recording'
    codes_on_zarr = {i.code for v in report.files if '.ome.zarr' in str(v.path) for i in v.issues}
    assert 'EMPTY_FILE' not in codes_on_zarr


def test_bidsignore_is_honored(tmp_path: Path) -> None:
    # A file matched by .bidsignore must not be flagged NOT_INCLUDED.
    _base(tmp_path)
    (tmp_path / 'sub-01' / 'anat').mkdir(parents=True)
    (tmp_path / 'sub-01' / 'anat' / 'sub-01_extra.foo').write_text('x')
    (tmp_path / '.bidsignore').write_text('*.foo\n')
    report = validate(tmp_path)
    paths = {str(v.path) for v in report.files}
    assert 'sub-01/anat/sub-01_extra.foo' not in paths
    codes = {i.code for v in report.files for i in v.issues}
    assert 'NOT_INCLUDED' not in codes


def test_tsv_trailing_blank_line_is_ignored(tmp_path: Path) -> None:
    # A trailing blank line must not add a spurious value or truncate columns.
    _base(tmp_path)
    (tmp_path / 'sub-01' / 'anat').mkdir(parents=True)
    (tmp_path / 'sub-01' / 'anat' / 'sub-01_T1w.nii.gz').write_bytes(b'')
    (tmp_path / 'participants.tsv').write_text('participant_id\tage\nsub-01\t30\n\n')
    report = validate(tmp_path)
    verdict = next(v for v in report.files if str(v.path) == 'participants.tsv')
    codes = {i.code for i in verdict.issues}
    assert 'TSV_VALUE_INCORRECT_TYPE' not in codes
