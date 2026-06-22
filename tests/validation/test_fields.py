"""Tests for sidecar / dataset_description field presence and value validation."""

from __future__ import annotations

import json
from pathlib import Path

import nibabel as nb
import numpy as np

from bids_validator.validation import validate


def _verdict_codes(tmp_path: Path, relpath: str) -> set[str]:
    report = validate(tmp_path)
    verdict = next(v for v in report.files if str(v.path) == relpath)
    return {i.code for i in verdict.issues}


def _verdict_field_codes(tmp_path: Path, relpath: str) -> set[tuple[str, str | None]]:
    report = validate(tmp_path)
    verdict = next(v for v in report.files if str(v.path) == relpath)
    return {(i.code, i.sub_code) for i in verdict.issues}


def test_bad_value_type_flagged(tmp_path: Path) -> None:
    # Authors must be an array; a string value is a JSON_SCHEMA_VALIDATION_ERROR.
    (tmp_path / 'sub-01' / 'anat').mkdir(parents=True)
    (tmp_path / 'dataset_description.json').write_text(
        json.dumps({'Name': 'x', 'BIDSVersion': '1.11.1', 'Authors': 'not a list'})
    )
    nb.save(
        nb.Nifti1Image(np.zeros((4, 4, 4), dtype=np.int16), np.eye(4)),
        str(tmp_path / 'sub-01' / 'anat' / 'sub-01_T1w.nii.gz'),
    )
    codes = _verdict_field_codes(tmp_path, 'dataset_description.json')
    assert ('JSON_SCHEMA_VALIDATION_ERROR', 'Authors') in codes


def test_valid_value_not_flagged(tmp_path: Path) -> None:
    (tmp_path / 'sub-01' / 'anat').mkdir(parents=True)
    (tmp_path / 'dataset_description.json').write_text(
        json.dumps({'Name': 'x', 'BIDSVersion': '1.11.1', 'Authors': ['A. Person']})
    )
    nb.save(
        nb.Nifti1Image(np.zeros((4, 4, 4), dtype=np.int16), np.eye(4)),
        str(tmp_path / 'sub-01' / 'anat' / 'sub-01_T1w.nii.gz'),
    )
    assert 'JSON_SCHEMA_VALIDATION_ERROR' not in _verdict_codes(
        tmp_path, 'dataset_description.json'
    )


def test_missing_required_sidecar_field_is_error(tmp_path: Path) -> None:
    # A bold recording requires RepetitionTime / TaskName; an empty sidecar misses
    # them, which is a required-field error.
    (tmp_path / 'sub-01' / 'func').mkdir(parents=True)
    (tmp_path / 'dataset_description.json').write_text(
        json.dumps({'Name': 'x', 'BIDSVersion': '1.11.1'})
    )
    nb.save(
        nb.Nifti1Image(np.zeros((4, 4, 4, 2), dtype=np.int16), np.eye(4)),
        str(tmp_path / 'sub-01' / 'func' / 'sub-01_task-rest_bold.nii.gz'),
    )
    (tmp_path / 'sub-01' / 'func' / 'sub-01_task-rest_bold.json').write_text(json.dumps({}))
    report = validate(tmp_path)
    verdict = next(
        v for v in report.files if str(v.path) == 'sub-01/func/sub-01_task-rest_bold.nii.gz'
    )
    required = [i for i in verdict.issues if i.code == 'SIDECAR_KEY_REQUIRED']
    assert required, 'expected a required-field error for the empty bold sidecar'
    assert all(i.severity.value == 'error' for i in required)
    assert {i.sub_code for i in required} >= {'RepetitionTime'}


def test_complete_sidecar_no_required_findings(tmp_path: Path) -> None:
    (tmp_path / 'sub-01' / 'func').mkdir(parents=True)
    (tmp_path / 'dataset_description.json').write_text(
        json.dumps({'Name': 'x', 'BIDSVersion': '1.11.1'})
    )
    nb.save(
        nb.Nifti1Image(np.zeros((4, 4, 4, 2), dtype=np.int16), np.eye(4)),
        str(tmp_path / 'sub-01' / 'func' / 'sub-01_task-rest_bold.nii.gz'),
    )
    (tmp_path / 'sub-01' / 'func' / 'sub-01_task-rest_bold.json').write_text(
        json.dumps({'RepetitionTime': 2.0, 'TaskName': 'rest'})
    )
    codes = _verdict_codes(tmp_path, 'sub-01/func/sub-01_task-rest_bold.nii.gz')
    assert 'SIDECAR_KEY_REQUIRED' not in codes
