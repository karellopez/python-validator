"""Tests for the report renderers (text / json / sarif / html)."""

from __future__ import annotations

import json as stdjson
from pathlib import Path

from bids_validator.validation.issues import DatasetIssues, Issue, Severity
from bids_validator.validation.render import to_dict, to_html, to_json, to_sarif, to_text
from bids_validator.validation.report import FileVerdict, ValidationReport


def _report() -> ValidationReport:
    report = ValidationReport(
        dataset_root=Path('/ds'), bids_version='1.11.1', schema_version='1.2.1'
    )
    report.dataset_issues = DatasetIssues(
        issues=[
            Issue(code='MISSING_DATASET_DESCRIPTION', severity=Severity.ERROR, message='no dd')
        ]
    )
    report.files = [
        FileVerdict(
            path=Path('sub-01/anat/sub-01_T1w.nii.gz'),
            issues=[
                Issue(
                    code='T1W_FILE_WITH_TOO_MANY_DIMENSIONS',
                    severity=Severity.ERROR,
                    location='sub-01/anat/sub-01_T1w.nii.gz',
                    message='too many dims',
                    suggestion='make it 3D',
                ),
                Issue(
                    code='SOME_WARNING',
                    severity=Severity.WARNING,
                    location='sub-01/anat/sub-01_T1w.nii.gz',
                    sub_code='RepetitionTime',
                ),
            ],
        )
    ]
    report.recompute()
    return report


def test_text_summary() -> None:
    out = to_text(_report())
    assert 'INVALID' in out
    assert 'T1W_FILE_WITH_TOO_MANY_DIMENSIONS' in out
    assert '2 error(s), 1 warning(s)' in out
    assert 'how to fix: make it 3D' in out


def test_json_shape() -> None:
    data = stdjson.loads(to_json(_report()))
    assert data['valid'] is False
    assert data['counts'] == {'error': 2, 'warning': 1, 'ignore': 0}
    by_code = {i['code']: i for i in data['issues']}
    assert 'MISSING_DATASET_DESCRIPTION' in by_code
    assert by_code['SOME_WARNING']['subCode'] == 'RepetitionTime'
    assert by_code['T1W_FILE_WITH_TOO_MANY_DIMENSIONS']['suggestion'] == 'make it 3D'


def test_to_dict_matches_json() -> None:
    report = _report()
    assert stdjson.loads(to_json(report)) == to_dict(report)


def test_sarif_shape() -> None:
    data = stdjson.loads(to_sarif(_report()))
    assert data['version'] == '2.1.0'
    run = data['runs'][0]
    assert run['tool']['driver']['name'] == 'bids-validator'
    levels = {result['level'] for result in run['results']}
    assert {'error', 'warning'} <= levels
    rule_ids = {rule['id'] for rule in run['tool']['driver']['rules']}
    assert 'T1W_FILE_WITH_TOO_MANY_DIMENSIONS' in rule_ids


def test_html_document() -> None:
    out = to_html(_report())
    assert out.startswith('<!doctype html>')
    assert 'INVALID' in out
    assert 'T1W_FILE_WITH_TOO_MANY_DIMENSIONS' in out
    assert 'How to fix:' in out


def test_html_escapes_dynamic_text() -> None:
    report = ValidationReport()
    report.files = [
        FileVerdict(path=Path('x'), issues=[Issue(code='X', message='<script>alert(1)</script>')])
    ]
    report.recompute()
    out = to_html(report)
    assert '<script>alert(1)</script>' not in out
    assert '&lt;script&gt;' in out


def test_clean_report_renders() -> None:
    clean = ValidationReport(dataset_root=Path('/ds'))
    clean.recompute()
    assert 'VALID' in to_text(clean)
    assert 'No findings.' in to_html(clean)
    assert stdjson.loads(to_json(clean))['valid'] is True
