"""Tests for the per-file structural integrity checks."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import nibabel as nb
import numpy as np
import pytest

from bids_validator.validation import validate


def _dataset(tmp_path: Path) -> Path:
    (tmp_path / 'sub-01' / 'anat').mkdir(parents=True)
    (tmp_path / 'dataset_description.json').write_text(
        json.dumps({'Name': 'integrity', 'BIDSVersion': '1.11.1'})
    )
    return tmp_path


def _codes_by_file(tmp_path: Path) -> dict[str, set[str]]:
    report = validate(tmp_path)
    return {str(v.path): {i.code for i in v.issues} for v in report.files}


def test_empty_file_flagged(tmp_path: Path) -> None:
    _dataset(tmp_path)
    (tmp_path / 'sub-01' / 'anat' / 'sub-01_T1w.nii.gz').write_bytes(b'')
    codes = _codes_by_file(tmp_path)
    assert 'EMPTY_FILE' in codes['sub-01/anat/sub-01_T1w.nii.gz']


def test_corrupt_nifti_unreadable(tmp_path: Path) -> None:
    _dataset(tmp_path)
    # Non-empty garbage so EMPTY_FILE does not fire first.
    (tmp_path / 'sub-01' / 'anat' / 'sub-01_T1w.nii.gz').write_bytes(b'not a nifti at all')
    found = _codes_by_file(tmp_path)['sub-01/anat/sub-01_T1w.nii.gz']
    assert 'NIFTI_HEADER_UNREADABLE' in found
    assert 'EMPTY_FILE' not in found


def test_valid_nifti_clean(tmp_path: Path) -> None:
    _dataset(tmp_path)
    path = tmp_path / 'sub-01' / 'anat' / 'sub-01_T1w.nii.gz'
    nb.save(nb.Nifti1Image(np.zeros((4, 4, 4), dtype=np.int16), np.eye(4)), str(path))
    found = _codes_by_file(tmp_path)['sub-01/anat/sub-01_T1w.nii.gz']
    assert 'NIFTI_HEADER_UNREADABLE' not in found
    assert 'EMPTY_FILE' not in found


def test_read_headers_false_skips_nifti_unreadable(tmp_path: Path) -> None:
    _dataset(tmp_path)
    (tmp_path / 'sub-01' / 'anat' / 'sub-01_T1w.nii.gz').write_bytes(b'not a nifti at all')
    report = validate(tmp_path, read_headers=False)
    codes = {i.code for v in report.files for i in v.issues}
    assert 'NIFTI_HEADER_UNREADABLE' not in codes


def test_invalid_gzip_flagged(tmp_path: Path) -> None:
    _dataset(tmp_path)
    (tmp_path / 'sub-01' / 'func').mkdir(parents=True)
    # Named .tsv.gz but not a gzip stream.
    (tmp_path / 'sub-01' / 'func' / 'sub-01_task-rest_physio.tsv.gz').write_bytes(b'not gzip')
    found = _codes_by_file(tmp_path)['sub-01/func/sub-01_task-rest_physio.tsv.gz']
    assert 'INVALID_GZIP' in found


def test_valid_gzip_clean(tmp_path: Path) -> None:
    _dataset(tmp_path)
    (tmp_path / 'sub-01' / 'func').mkdir(parents=True)
    path = tmp_path / 'sub-01' / 'func' / 'sub-01_task-rest_physio.tsv.gz'
    with gzip.open(path, 'wt') as handle:
        handle.write('a\tb\n1\t2\n')
    found = _codes_by_file(tmp_path)['sub-01/func/sub-01_task-rest_physio.tsv.gz']
    assert 'INVALID_GZIP' not in found


def test_symlink_to_empty_is_skipped(tmp_path: Path) -> None:
    _dataset(tmp_path)
    target = tmp_path / '.placeholder'
    target.write_bytes(b'')
    link = tmp_path / 'sub-01' / 'anat' / 'sub-01_T1w.nii.gz'
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip('symlinks not supported on this platform')
    found = _codes_by_file(tmp_path)['sub-01/anat/sub-01_T1w.nii.gz']
    assert 'EMPTY_FILE' not in found
