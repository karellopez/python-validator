"""Tests for TSV column rules (tabular_data)."""

from __future__ import annotations

import json
from pathlib import Path

from bids_validator.validation import validate


def _participants_dataset(tmp_path: Path, participants_tsv: str) -> Path:
    (tmp_path / 'sub-01' / 'anat').mkdir(parents=True)
    (tmp_path / 'dataset_description.json').write_text(
        json.dumps({'Name': 'tables', 'BIDSVersion': '1.11.1'})
    )
    (tmp_path / 'participants.tsv').write_text(participants_tsv)
    (tmp_path / 'sub-01' / 'anat' / 'sub-01_T1w.nii.gz').write_bytes(b'')
    return tmp_path


def _field_codes(tmp_path: Path, relpath: str) -> set[tuple[str, str | None]]:
    report = validate(tmp_path)
    verdict = next(v for v in report.files if str(v.path) == relpath)
    return {(i.code, i.sub_code) for i in verdict.issues}


def test_incorrect_value_type_flagged(tmp_path: Path) -> None:
    # age is numeric; a non-numeric value is TSV_VALUE_INCORRECT_TYPE.
    root = _participants_dataset(tmp_path, 'participant_id\tage\nsub-01\tnotanumber\n')
    assert ('TSV_VALUE_INCORRECT_TYPE', 'age') in _field_codes(root, 'participants.tsv')


def test_valid_values_clean(tmp_path: Path) -> None:
    root = _participants_dataset(tmp_path, 'participant_id\tage\nsub-01\t30\n')
    codes = {code for code, _sub in _field_codes(root, 'participants.tsv')}
    assert 'TSV_VALUE_INCORRECT_TYPE' not in codes


def test_na_value_allowed(tmp_path: Path) -> None:
    # 'n/a' is always acceptable for a typed column.
    root = _participants_dataset(tmp_path, 'participant_id\tage\nsub-01\tn/a\n')
    codes = {code for code, _sub in _field_codes(root, 'participants.tsv')}
    assert 'TSV_VALUE_INCORRECT_TYPE' not in codes


def test_lines_lists_every_bad_row(tmp_path: Path) -> None:
    root = _participants_dataset(
        tmp_path,
        'participant_id\tage\nsub-01\tbad\nsub-02\t40\nsub-03\talso_bad\n',
    )
    report = validate(root)
    verdict = next(v for v in report.files if str(v.path) == 'participants.tsv')
    finding = next(
        i for i in verdict.issues if i.code == 'TSV_VALUE_INCORRECT_TYPE' and i.sub_code == 'age'
    )
    # Rows are 1-based including the header: bad cells are data rows 1 and 3.
    assert finding.line == 2
    assert finding.lines == [2, 4]
