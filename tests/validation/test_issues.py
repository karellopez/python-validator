"""Tests for the attrs-based issue models."""

from __future__ import annotations

import attrs
import cattrs
import pytest

from bids_validator.validation.issues import (
    DatasetIssues,
    Fix,
    Issue,
    RuleProvenance,
    Severity,
)


def test_severity_rank_ordering() -> None:
    assert Severity.IGNORE.rank < Severity.WARNING.rank < Severity.ERROR.rank
    assert Severity('error') is Severity.ERROR


def test_issue_defaults() -> None:
    issue = Issue(code='EMPTY_FILE')
    assert issue.code == 'EMPTY_FILE'
    assert issue.severity is Severity.ERROR
    assert issue.location is None
    assert issue.affects == []
    assert issue.lines == []
    assert issue.provenance is None
    assert issue.fix is None


def test_issue_independent_mutable_defaults() -> None:
    a = Issue(code='A')
    b = Issue(code='B')
    a.affects.append('sub-01')
    a.lines.append(3)
    assert b.affects == []
    assert b.lines == []


def test_issue_full_payload() -> None:
    issue = Issue(
        code='TSV_VALUE_INCORRECT_TYPE',
        severity=Severity.WARNING,
        location='participants.tsv',
        sub_code='age',
        message='not a number',
        suggestion='use a numeric value',
        affects=['sub-02'],
        rule='rules.tabular_data.participants',
        line=4,
        lines=[4, 7, 9],
        character=1,
        provenance=RuleProvenance(rule_path='rules.x', selectors=['s'], checks=['c']),
        fix=Fix(action='set_value', field='age', value=42),
    )
    assert issue.line == 4
    assert issue.lines == [4, 7, 9]
    assert issue.fix is not None
    assert issue.fix.value == 42
    assert issue.provenance is not None
    assert issue.provenance.selectors == ['s']


def test_dataset_issues_helpers() -> None:
    bucket = DatasetIssues()
    assert len(bucket) == 0
    assert bucket.highest_severity() is None

    bucket.add(Issue(code='A', severity=Severity.WARNING))
    bucket.extend(
        [
            Issue(code='B', severity=Severity.ERROR),
            Issue(code='C', severity=Severity.IGNORE),
        ]
    )
    assert len(bucket) == 3
    assert [i.code for i in bucket] == ['A', 'B', 'C']
    assert bucket.highest_severity() is Severity.ERROR
    assert [i.code for i in bucket.by_severity(Severity.WARNING)] == ['A']


@pytest.mark.parametrize(
    'issue',
    [
        Issue(code='EMPTY_FILE'),
        Issue(
            code='TSV_VALUE_INCORRECT_TYPE',
            severity=Severity.WARNING,
            location='participants.tsv',
            lines=[2, 3],
            fix=Fix(action='set_value', field='age'),
        ),
    ],
)
def test_issue_asdict_roundtrip(issue: Issue) -> None:
    as_dict = attrs.asdict(issue)
    rebuilt = Issue(**{**as_dict, 'severity': Severity(as_dict['severity'])})
    # asdict turns nested attrs into dicts; rebuild fix/provenance manually.
    if as_dict['fix'] is not None:
        rebuilt.fix = Fix(**as_dict['fix'])
    rebuilt.provenance = None
    rebuilt_for_cmp = attrs.asdict(rebuilt)
    assert rebuilt_for_cmp == as_dict


def test_issue_cattrs_roundtrip() -> None:
    issue = Issue(
        code='TSV_VALUE_INCORRECT_TYPE',
        severity=Severity.WARNING,
        location='participants.tsv',
        lines=[2, 3],
        fix=Fix(action='set_value', field='age', value=7),
        provenance=RuleProvenance(rule_path='rules.x'),
    )
    conv = cattrs.Converter()
    data = conv.unstructure(issue)
    assert data['severity'] == 'warning'
    back = conv.structure(data, Issue)
    assert back == issue
