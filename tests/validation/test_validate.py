"""End-to-end tests for the validate entry points."""

from __future__ import annotations

import json
from pathlib import Path

import nibabel as nb
import numpy as np
import pytest

from bids_validator.validation import to_json, validate, validate_file
from bids_validator.validation.issues import Severity
from bids_validator.validation.report import ValidationReport


def _write_nifti(path: Path, *, n_dims: int) -> None:
    shape = (4, 4, 4) if n_dims == 3 else (4, 4, 4, 2)
    nb.save(nb.Nifti1Image(np.zeros(shape, dtype=np.int16), np.eye(4)), str(path))


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    (tmp_path / 'sub-01' / 'anat').mkdir(parents=True)
    (tmp_path / 'sub-02' / 'anat').mkdir(parents=True)
    (tmp_path / 'dataset_description.json').write_text(
        json.dumps({'Name': 'validate-fixture', 'BIDSVersion': '1.11.1'})
    )
    _write_nifti(tmp_path / 'sub-01' / 'anat' / 'sub-01_T1w.nii.gz', n_dims=4)
    _write_nifti(tmp_path / 'sub-02' / 'anat' / 'sub-02_T1w.nii.gz', n_dims=3)
    return tmp_path


def test_validate_returns_report_with_versions(dataset: Path) -> None:
    report = validate(dataset)
    assert isinstance(report, ValidationReport)
    assert report.bids_version == '1.11.1'
    assert report.schema_version == '1.2.1'
    assert report.dataset_root == dataset
    # One verdict per file (every file is visited).
    assert len(report.files) >= 3


def test_validate_flags_only_the_bad_file(dataset: Path) -> None:
    report = validate(dataset)
    flagged = {
        str(v.path)
        for v in report.files
        for i in v.issues
        if i.code == 'T1W_FILE_WITH_TOO_MANY_DIMENSIONS'
    }
    assert flagged == {'sub-01/anat/sub-01_T1w.nii.gz'}
    assert report.counts['error'] >= 1
    assert report.is_valid is False


def test_read_headers_false_skips_header_checks(dataset: Path) -> None:
    report = validate(dataset, read_headers=False)
    codes = {i.code for v in report.files for i in v.issues}
    assert 'T1W_FILE_WITH_TOO_MANY_DIMENSIONS' not in codes


def test_validate_file_one_file(dataset: Path) -> None:
    verdict = validate_file(dataset, 'sub-01/anat/sub-01_T1w.nii.gz')
    assert str(verdict.path) == 'sub-01/anat/sub-01_T1w.nii.gz'
    assert verdict.severity is Severity.ERROR
    assert any(i.code == 'T1W_FILE_WITH_TOO_MANY_DIMENSIONS' for i in verdict.issues)


def test_validate_file_not_found(dataset: Path) -> None:
    verdict = validate_file(dataset, 'sub-99/anat/sub-99_T1w.nii.gz')
    assert [i.code for i in verdict.issues] == ['FILE_NOT_FOUND']
    assert verdict.severity is Severity.ERROR


def test_report_renders(dataset: Path) -> None:
    report = validate(dataset)
    data = json.loads(to_json(report))
    assert data['valid'] is False
    assert any(i['code'] == 'T1W_FILE_WITH_TOO_MANY_DIMENSIONS' for i in data['issues'])


def test_exists_resolver_makes_readme_check_fire(dataset: Path) -> None:
    # With the exists() resolver wired, the missing-README check resolves against
    # the tree and fires (the fixture has no README), rather than being skipped.
    report = validate(dataset)
    codes = {i.code for v in report.files for i in v.issues}
    codes |= {i.code for i in report.dataset_issues.issues}
    assert 'README_FILE_MISSING' in codes


def test_exists_resolver_finds_present_readme(tmp_path: Path) -> None:
    # When a README is present, exists() resolves it and the check stays silent.
    (tmp_path / 'sub-01' / 'anat').mkdir(parents=True)
    (tmp_path / 'dataset_description.json').write_text(
        json.dumps({'Name': 'has-readme', 'BIDSVersion': '1.11.1'})
    )
    (tmp_path / 'README').write_text('A dataset.\n')
    _write_nifti(tmp_path / 'sub-01' / 'anat' / 'sub-01_T1w.nii.gz', n_dims=3)
    report = validate(tmp_path)
    codes = {i.code for v in report.files for i in v.issues}
    codes |= {i.code for i in report.dataset_issues.issues}
    assert 'README_FILE_MISSING' not in codes


def test_bom_participants_no_false_positive(tmp_path: Path) -> None:
    # A participants.tsv with a UTF-8 BOM on the header must not make
    # columns.participant_id null and trip PARTICIPANT_ID_MISMATCH.
    (tmp_path / 'sub-01' / 'anat').mkdir(parents=True)
    (tmp_path / 'dataset_description.json').write_text(
        json.dumps({'Name': 'bom', 'BIDSVersion': '1.11.1'})
    )
    (tmp_path / 'participants.tsv').write_text(
        '﻿participant_id\tage\nsub-01\t30\n', encoding='utf-8'
    )
    _write_nifti(tmp_path / 'sub-01' / 'anat' / 'sub-01_T1w.nii.gz', n_dims=3)
    report = validate(tmp_path)
    codes = {i.code for v in report.files for i in v.issues}
    assert 'PARTICIPANT_ID_MISMATCH' not in codes


def test_ignored_locations_are_not_validated(tmp_path: Path) -> None:
    # sourcedata/, derivatives/, code/ and hidden paths are skipped by default,
    # so empty files there are not flagged; an empty file in a validated location
    # still is.
    (tmp_path / 'sub-01' / 'anat').mkdir(parents=True)
    (tmp_path / 'sourcedata').mkdir()
    (tmp_path / 'derivatives').mkdir()
    (tmp_path / 'code').mkdir()
    (tmp_path / '.hidden').mkdir()
    (tmp_path / 'dataset_description.json').write_text(
        json.dumps({'Name': 'ignored', 'BIDSVersion': '1.11.1'})
    )
    (tmp_path / 'sourcedata' / 'raw.nii.gz').write_bytes(b'')
    (tmp_path / 'derivatives' / 'x.nii.gz').write_bytes(b'')
    (tmp_path / 'code' / 'run.py').write_bytes(b'')
    (tmp_path / '.hidden' / 'y.txt').write_bytes(b'')
    (tmp_path / 'sub-01' / 'anat' / 'sub-01_T1w.nii.gz').write_bytes(b'')

    report = validate(tmp_path)
    validated = {str(v.path) for v in report.files}
    assert 'sub-01/anat/sub-01_T1w.nii.gz' in validated
    assert not any(
        str(v.path).startswith(('sourcedata', 'derivatives', 'code', '.')) for v in report.files
    )
