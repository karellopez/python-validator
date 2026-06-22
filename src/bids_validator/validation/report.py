"""The top-level validation result.

A :class:`ValidationReport` is what a full run returns: the schema it ran
against, the findings (dataset-wide and per file), a rolled-up severity, and
counts. It is pure data, so it serialises cleanly and binds directly to a CLI
summary, a GUI, or a machine-readable report.
"""

from __future__ import annotations

from pathlib import Path

import attrs

from .issues import DatasetIssues, Issue, Severity


@attrs.define(kw_only=True)
class FileVerdict:
    """The outcome for one file in the dataset.

    Attributes
    ----------
    path : Path
        The file path, relative to the dataset root.
    severity : Severity or None
        The rollup of this file's own findings. ``None`` means the file is
        clean. Kept per-file so a tree view or editor can show a status next to
        each path without re-scanning the whole report.
    issues : list of Issue
        The findings attached to this file.

    """

    path: Path
    severity: Severity | None = None
    issues: list[Issue] = attrs.field(factory=list)

    def recompute_severity(self) -> None:
        """Set :attr:`severity` from the file's current issues."""
        self.severity = _highest([issue.severity for issue in self.issues])


@attrs.define(kw_only=True)
class ValidationReport:
    """The result of validating a dataset.

    Attributes
    ----------
    dataset_root : Path or None
        The validated dataset root.
    bids_version : str
        The BIDS specification version validated against.
    schema_version : str
        The schema's own version (recorded alongside ``bids_version`` so a
        report is unambiguous about what it was checked against).
    severity : Severity or None
        Dataset-wide severity rollup. ``None`` means clean.
    counts : dict of str to int
        Per-finding counts keyed by severity name (``error``, ``warning``,
        ``ignore``).
    dataset_issues : DatasetIssues
        Findings that are not tied to a single file.
    files : list of FileVerdict
        Per-file outcomes.
    derivatives : dict of str to ValidationReport
        Nested BIDS derivative datasets, validated on their own (only populated
        when validation is recursive).

    """

    dataset_root: Path | None = None
    bids_version: str = ''
    schema_version: str = ''
    severity: Severity | None = None
    counts: dict[str, int] = attrs.field(factory=lambda: {'error': 0, 'warning': 0, 'ignore': 0})
    dataset_issues: DatasetIssues = attrs.field(factory=DatasetIssues)
    files: list[FileVerdict] = attrs.field(factory=list)
    derivatives: dict[str, ValidationReport] = attrs.field(factory=dict)

    def recompute(self) -> None:
        """Refresh :attr:`severity` and :attr:`counts` from current findings.

        Call after all findings have been added. Counts every finding once,
        whether it sits on a file or at the dataset level.
        """
        all_severities: list[Severity] = [issue.severity for issue in self.dataset_issues.issues]
        for verdict in self.files:
            all_severities.extend(issue.severity for issue in verdict.issues)
        self.severity = _highest(all_severities)
        self.counts = {
            'error': sum(s is Severity.ERROR for s in all_severities),
            'warning': sum(s is Severity.WARNING for s in all_severities),
            'ignore': sum(s is Severity.IGNORE for s in all_severities),
        }

    @property
    def is_valid(self) -> bool:
        """True when the dataset has no error-level findings."""
        return self.counts.get('error', 0) == 0

    def filtered(self, severities: set[Severity]) -> ValidationReport:
        """Return a copy keeping only findings whose severity is in ``severities``.

        Used to show only selected requirement levels; the original report's
        validity/exit status is unaffected (validity always depends on errors).

        Parameters
        ----------
        severities : set of Severity
            The severities to keep.

        Returns
        -------
        ValidationReport
            A new report with only the matching findings, with counts and
            severity recomputed.

        """
        kept = ValidationReport(
            dataset_root=self.dataset_root,
            bids_version=self.bids_version,
            schema_version=self.schema_version,
        )
        kept.dataset_issues = DatasetIssues(
            issues=[i for i in self.dataset_issues.issues if i.severity in severities]
        )
        for verdict in self.files:
            keep = [i for i in verdict.issues if i.severity in severities]
            if keep:
                kept.files.append(FileVerdict(path=verdict.path, issues=keep))
        kept.recompute()
        return kept


def _highest(severities: list[Severity]) -> Severity | None:
    """Return the most serious severity, or ``None`` for an empty list.

    Parameters
    ----------
    severities : list of Severity
        The severities to roll up.

    Returns
    -------
    Severity or None
        The most serious severity present, or ``None`` if the list is empty.

    """
    if not severities:
        return None
    return max(severities, key=lambda s: s.rank)


__all__ = ['FileVerdict', 'ValidationReport']
