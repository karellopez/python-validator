"""Tests for the attrs-based report models."""

from __future__ import annotations

from pathlib import Path

from bids_validator.validation.issues import DatasetIssues, Issue, Severity
from bids_validator.validation.report import FileVerdict, ValidationReport


def test_file_verdict_recompute_severity() -> None:
    verdict = FileVerdict(path=Path('sub-01/anat/sub-01_T1w.nii.gz'))
    assert verdict.severity is None
    verdict.issues.append(Issue(code='A', severity=Severity.WARNING))
    verdict.issues.append(Issue(code='B', severity=Severity.ERROR))
    verdict.recompute_severity()
    assert verdict.severity is Severity.ERROR


def test_report_recompute_counts_per_finding() -> None:
    report = ValidationReport(dataset_root=Path('/ds'))
    report.dataset_issues = DatasetIssues(
        issues=[Issue(code='MISSING_DATASET_DESCRIPTION', severity=Severity.ERROR)]
    )
    report.files = [
        FileVerdict(
            path=Path('a.json'),
            issues=[
                Issue(code='X', severity=Severity.WARNING),
                Issue(code='Y', severity=Severity.WARNING),
            ],
        ),
        FileVerdict(
            path=Path('b.nii.gz'),
            issues=[Issue(code='Z', severity=Severity.ERROR)],
        ),
    ]
    report.recompute()
    # Per-finding counts: 2 errors (dataset + b), 2 warnings (a).
    assert report.counts == {'error': 2, 'warning': 2, 'ignore': 0}
    assert report.severity is Severity.ERROR
    assert report.is_valid is False


def test_report_is_valid_when_no_errors() -> None:
    report = ValidationReport()
    report.files = [
        FileVerdict(path=Path('a.json'), issues=[Issue(code='W', severity=Severity.WARNING)])
    ]
    report.recompute()
    assert report.counts == {'error': 0, 'warning': 1, 'ignore': 0}
    assert report.severity is Severity.WARNING
    assert report.is_valid is True


def test_report_filtered_keeps_only_selected_severities() -> None:
    report = ValidationReport()
    report.dataset_issues = DatasetIssues(issues=[Issue(code='D', severity=Severity.WARNING)])
    report.files = [
        FileVerdict(
            path=Path('a.json'),
            issues=[
                Issue(code='E', severity=Severity.ERROR),
                Issue(code='W', severity=Severity.WARNING),
            ],
        ),
        FileVerdict(
            path=Path('clean.json'),
            issues=[Issue(code='W2', severity=Severity.WARNING)],
        ),
    ]
    report.recompute()

    errors_only = report.filtered({Severity.ERROR})
    assert errors_only.counts == {'error': 1, 'warning': 0, 'ignore': 0}
    # Only the file that still has an error survives.
    assert [str(f.path) for f in errors_only.files] == ['a.json']
    assert len(errors_only.dataset_issues) == 0
    # The original report is untouched.
    assert report.counts == {'error': 1, 'warning': 3, 'ignore': 0}


def test_report_derivatives_nesting() -> None:
    child = ValidationReport(dataset_root=Path('/ds/derivatives/fmriprep'))
    child.files = [
        FileVerdict(path=Path('x.json'), issues=[Issue(code='C', severity=Severity.ERROR)])
    ]
    child.recompute()
    parent = ValidationReport(dataset_root=Path('/ds'))
    parent.derivatives['fmriprep'] = child
    assert parent.derivatives['fmriprep'].counts['error'] == 1
