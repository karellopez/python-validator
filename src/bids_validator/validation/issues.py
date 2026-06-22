"""Typed validation findings.

Every problem the validator reports is an :class:`Issue`. The field set mirrors
the reference (Deno) validator's issue shape (``code``, ``severity``,
``location``, ``rule`` ...) so that output can be made interchangeable, and adds
a few optional fields that enable features the reference validator does not
offer:

* :attr:`Issue.suggestion` - a human-readable hint on how to fix the finding.
* :attr:`Issue.provenance` - the schema rule that produced the finding, so a
  user can be shown *why* something is an error ("explain" mode).
* :attr:`Issue.fix` - a machine-actionable remediation hint, so a tool or GUI
  can offer a one-click fix.

These are pure-data ``attrs`` models with no I/O, suitable for serialising to
JSON, SARIF, or binding directly to a GUI. The extra fields are all optional, so
the core shape stays interchangeable with the reference validator.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum
from typing import Any

import attrs


class Severity(str, Enum):
    """How serious a finding is.

    Ordered by attention, low to high: ``IGNORE`` < ``WARNING`` < ``ERROR``.
    ``IGNORE`` is used for findings that are explicitly silenced (for example by
    a waiver or a severity override) but kept in the record for transparency.
    """

    IGNORE = 'ignore'
    WARNING = 'warning'
    ERROR = 'error'

    @property
    def rank(self) -> int:
        """Numeric attention rank, for rolling several severities up to one."""
        return _SEVERITY_RANK[self]


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.IGNORE: 0,
    Severity.WARNING: 1,
    Severity.ERROR: 2,
}


@attrs.define(kw_only=True)
class RuleProvenance:
    """Where a finding came from in the schema, for "explain" mode.

    Lets the validator answer "why is this an error?" by pointing at the exact
    rule, its selectors and checks, and the relevant field description.

    Attributes
    ----------
    rule_path : str or None
        Dotted schema path of the rule, e.g.
        ``rules.checks.anat.T1wFileWithTooManyDimensions``.
    selectors : list of str
        The selector expressions that made the rule apply.
    checks : list of str
        The check expressions the rule asserts.
    field_definition : str or None
        The schema description of a metadata field, when relevant.

    """

    rule_path: str | None = None
    selectors: list[str] = attrs.field(factory=list)
    checks: list[str] = attrs.field(factory=list)
    field_definition: str | None = None


@attrs.define(kw_only=True)
class Fix:
    """A machine-actionable remediation hint attached to a finding.

    ``action`` is an opaque token a consumer maps to a handler (the validator
    never applies fixes itself). ``field`` / ``value`` carry the specifics where
    relevant, e.g. ``action='add_field'``, ``field='RepetitionTime'``.

    Attributes
    ----------
    action : str
        Opaque handler token.
    label : str or None
        Human-readable label for the action.
    field : str or None
        The metadata field the action targets, when relevant.
    value : Any or None
        The value the action would set, when relevant.

    """

    action: str
    label: str | None = None
    field: str | None = None
    value: Any | None = None


@attrs.define(kw_only=True)
class Issue:
    """A single validation finding.

    Attributes
    ----------
    code : str
        The issue code (aligned to the reference validator catalog).
    severity : Severity
        How serious the finding is. Defaults to :attr:`Severity.ERROR`.
    location : str or None
        Dataset-relative path of the offending file.
    sub_code : str or None
        Finer category within ``code`` (for example a field name).
    message : str or None
        Human-readable description of the finding.
    suggestion : str or None
        Human-readable hint on how to fix the finding (an extra beyond the
        reference validator).
    affects : list of str
        Entity or participant labels affected by the finding.
    rule : str or None
        Schema rule path that produced the finding.
    line : int or None
        1-based line/row for tabular or text findings (the first offending one).
    lines : list of int
        All 1-based rows a column finding spans (an extra beyond the reference
        validator, enabling whole-column highlighting).
    character : int or None
        1-based character offset, when relevant.
    provenance : RuleProvenance or None
        Where the finding came from in the schema (an extra, for explain mode).
    fix : Fix or None
        A machine-actionable remediation hint (an extra).

    """

    code: str
    severity: Severity = Severity.ERROR
    location: str | None = None
    sub_code: str | None = None
    message: str | None = None
    suggestion: str | None = None
    affects: list[str] = attrs.field(factory=list)
    rule: str | None = None
    line: int | None = None
    lines: list[int] = attrs.field(factory=list)
    character: int | None = None
    provenance: RuleProvenance | None = None
    fix: Fix | None = None


@attrs.define
class DatasetIssues:
    """An ordered collection of findings, with small query helpers.

    A thin wrapper rather than a bare list so reports have a stable, typed
    container that is easy to extend (filtering, grouping, severity rollup)
    without changing call sites.

    Attributes
    ----------
    issues : list of Issue
        The findings, in insertion order.

    """

    issues: list[Issue] = attrs.field(factory=list)

    def add(self, issue: Issue) -> None:
        """Append a single finding.

        Parameters
        ----------
        issue : Issue
            The finding to record.

        """
        self.issues.append(issue)

    def extend(self, issues: Iterable[Issue]) -> None:
        """Append several findings.

        Parameters
        ----------
        issues : Iterable of Issue
            The findings to record.

        """
        self.issues.extend(issues)

    def by_severity(self, severity: Severity) -> list[Issue]:
        """Return the findings at exactly one severity.

        Parameters
        ----------
        severity : Severity
            The severity to filter on.

        Returns
        -------
        list of Issue
            The matching findings, in insertion order.

        """
        return [issue for issue in self.issues if issue.severity is severity]

    def highest_severity(self) -> Severity | None:
        """Return the most serious severity present, or ``None`` if there are none."""
        if not self.issues:
            return None
        return max((issue.severity for issue in self.issues), key=lambda s: s.rank)

    def __len__(self) -> int:
        return len(self.issues)

    def __iter__(self) -> Iterable[Issue]:
        return iter(self.issues)


__all__ = ['Severity', 'RuleProvenance', 'Fix', 'Issue', 'DatasetIssues']
