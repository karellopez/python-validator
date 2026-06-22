"""Tests for the filename / path rules (rules.files)."""

from __future__ import annotations

import json
from pathlib import Path

import nibabel as nb
import numpy as np

from bids_validator.validation import validate


def _dataset(tmp_path: Path) -> None:
    (tmp_path / 'sub-01' / 'anat').mkdir(parents=True)
    (tmp_path / 'dataset_description.json').write_text(
        json.dumps({'Name': 'fn', 'BIDSVersion': '1.11.1'})
    )


def _codes(tmp_path: Path, relpath: str) -> set[str]:
    report = validate(tmp_path)
    verdict = next(v for v in report.files if str(v.path) == relpath)
    return {i.code for i in verdict.issues}


def test_not_included_for_unrecognised_suffix(tmp_path: Path) -> None:
    _dataset(tmp_path)
    (tmp_path / 'sub-01' / 'anat' / 'sub-01_bogussuffix.txt').write_text('x')
    assert 'NOT_INCLUDED' in _codes(tmp_path, 'sub-01/anat/sub-01_bogussuffix.txt')


def test_extension_mismatch(tmp_path: Path) -> None:
    _dataset(tmp_path)
    # A T1w with an extension the rule does not allow.
    (tmp_path / 'sub-01' / 'anat' / 'sub-01_T1w.xyz').write_text('x')
    codes = _codes(tmp_path, 'sub-01/anat/sub-01_T1w.xyz')
    assert 'EXTENSION_MISMATCH' in codes
    assert 'NOT_INCLUDED' not in codes


def test_valid_file_has_no_filename_findings(tmp_path: Path) -> None:
    _dataset(tmp_path)
    nb.save(
        nb.Nifti1Image(np.zeros((4, 4, 4), dtype=np.int16), np.eye(4)),
        str(tmp_path / 'sub-01' / 'anat' / 'sub-01_T1w.nii.gz'),
    )
    codes = _codes(tmp_path, 'sub-01/anat/sub-01_T1w.nii.gz')
    for code in (
        'NOT_INCLUDED',
        'FILENAME_MISMATCH',
        'EXTENSION_MISMATCH',
        'MISSING_REQUIRED_ENTITY',
        'ENTITY_NOT_IN_RULE',
    ):
        assert code not in codes


def test_dataset_description_no_filename_mismatch(tmp_path: Path) -> None:
    # Regression: the no-hyphen "dataset" token must not be read as an entity, so
    # dataset_description.json is not flagged FILENAME_MISMATCH.
    _dataset(tmp_path)
    nb.save(
        nb.Nifti1Image(np.zeros((4, 4, 4), dtype=np.int16), np.eye(4)),
        str(tmp_path / 'sub-01' / 'anat' / 'sub-01_T1w.nii.gz'),
    )
    assert 'FILENAME_MISMATCH' not in _codes(tmp_path, 'dataset_description.json')


def test_missing_required_entity(tmp_path: Path) -> None:
    # A bold without the required task entity, in a subject folder.
    (tmp_path / 'sub-01' / 'func').mkdir(parents=True)
    (tmp_path / 'dataset_description.json').write_text(
        json.dumps({'Name': 'fn', 'BIDSVersion': '1.11.1'})
    )
    nb.save(
        nb.Nifti1Image(np.zeros((4, 4, 4, 2), dtype=np.int16), np.eye(4)),
        str(tmp_path / 'sub-01' / 'func' / 'sub-01_bold.nii.gz'),
    )
    assert 'MISSING_REQUIRED_ENTITY' in _codes(tmp_path, 'sub-01/func/sub-01_bold.nii.gz')
