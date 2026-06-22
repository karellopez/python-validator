"""Tests for the dataset-level checks (and CITATION.cff)."""

from __future__ import annotations

import json
from pathlib import Path

import nibabel as nb
import numpy as np

from bids_validator.validation import validate


def _dataset_codes(tmp_path: Path) -> set[str]:
    report = validate(tmp_path)
    codes = {i.code for v in report.files for i in v.issues}
    codes |= {i.code for i in report.dataset_issues.issues}
    return codes


def test_no_subjects_warning(tmp_path: Path) -> None:
    (tmp_path / 'dataset_description.json').write_text(
        json.dumps({'Name': 'empty', 'BIDSVersion': '1.11.1'})
    )
    report = validate(tmp_path)
    assert any(i.code == 'NO_SUBJECTS' for i in report.dataset_issues.issues)


def test_sidecar_without_datafile(tmp_path: Path) -> None:
    # A stray bold sidecar with no matching bold data file.
    (tmp_path / 'sub-01' / 'func').mkdir(parents=True)
    (tmp_path / 'dataset_description.json').write_text(
        json.dumps({'Name': 'stray', 'BIDSVersion': '1.11.1'})
    )
    (tmp_path / 'sub-01' / 'func' / 'sub-01_task-rest_bold.json').write_text(
        json.dumps({'RepetitionTime': 2.0, 'TaskName': 'rest'})
    )
    assert 'SIDECAR_WITHOUT_DATAFILE' in _dataset_codes(tmp_path)


def test_sidecar_with_datafile_clean(tmp_path: Path) -> None:
    (tmp_path / 'sub-01' / 'func').mkdir(parents=True)
    (tmp_path / 'dataset_description.json').write_text(
        json.dumps({'Name': 'paired', 'BIDSVersion': '1.11.1'})
    )
    nb.save(
        nb.Nifti1Image(np.zeros((4, 4, 4, 2), dtype=np.int16), np.eye(4)),
        str(tmp_path / 'sub-01' / 'func' / 'sub-01_task-rest_bold.nii.gz'),
    )
    (tmp_path / 'sub-01' / 'func' / 'sub-01_task-rest_bold.json').write_text(
        json.dumps({'RepetitionTime': 2.0, 'TaskName': 'rest'})
    )
    assert 'SIDECAR_WITHOUT_DATAFILE' not in _dataset_codes(tmp_path)


def test_unused_stimulus_warning(tmp_path: Path) -> None:
    (tmp_path / 'sub-01' / 'func').mkdir(parents=True)
    (tmp_path / 'stimuli').mkdir()
    (tmp_path / 'dataset_description.json').write_text(
        json.dumps({'Name': 'stim', 'BIDSVersion': '1.11.1'})
    )
    (tmp_path / 'stimuli' / 'unused.png').write_text('x')
    (tmp_path / 'sub-01' / 'func' / 'sub-01_task-rest_events.tsv').write_text(
        'onset\tduration\n1.0\t0.5\n'
    )
    report = validate(tmp_path)
    assert any(i.code == 'UNUSED_STIMULUS' for i in report.dataset_issues.issues)
    # The stimulus file itself is associated data, not flagged NOT_INCLUDED.
    assert not any(str(v.path).startswith('stimuli') for v in report.files)


def test_malformed_citation_cff(tmp_path: Path) -> None:
    (tmp_path / 'sub-01' / 'anat').mkdir(parents=True)
    (tmp_path / 'dataset_description.json').write_text(
        json.dumps({'Name': 'cff', 'BIDSVersion': '1.11.1'})
    )
    nb.save(
        nb.Nifti1Image(np.zeros((4, 4, 4), dtype=np.int16), np.eye(4)),
        str(tmp_path / 'sub-01' / 'anat' / 'sub-01_T1w.nii.gz'),
    )
    # Valid YAML mapping but missing the required CFF keys.
    (tmp_path / 'CITATION.cff').write_text('foo: bar\n')
    assert any(
        i.code == 'CITATION_CFF_VALIDATION_ERROR' for i in validate(tmp_path).dataset_issues.issues
    )


def test_valid_citation_cff_clean(tmp_path: Path) -> None:
    (tmp_path / 'sub-01' / 'anat').mkdir(parents=True)
    (tmp_path / 'dataset_description.json').write_text(
        json.dumps({'Name': 'cff', 'BIDSVersion': '1.11.1'})
    )
    nb.save(
        nb.Nifti1Image(np.zeros((4, 4, 4), dtype=np.int16), np.eye(4)),
        str(tmp_path / 'sub-01' / 'anat' / 'sub-01_T1w.nii.gz'),
    )
    (tmp_path / 'CITATION.cff').write_text(
        'cff-version: 1.2.0\nmessage: Please cite\ntitle: My dataset\n'
    )
    codes = {i.code for i in validate(tmp_path).dataset_issues.issues}
    assert 'CITATION_CFF_VALIDATION_ERROR' not in codes
