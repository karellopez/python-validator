"""The schema rule interpreter.

The engine evaluates the schema's ``rules.checks`` against one file's context:
each rule is a set of selectors (when it applies) and checks (what must hold).
When every selector passes and a check evaluates to a determinate failure, the
rule's issue is emitted.

Robustness against a partial context is the core invariant: a check that
evaluates to ``null`` (because some content was not available, for example an
associated file the engine does not load) is treated as "not determinable" and
skipped, never reported; a selector or check that cannot be evaluated at all (an
unknown function in a newer-than-engine schema) skips the rule. Only an explicit,
non-null falsy result raises a finding. This is what keeps the validator from
emitting false positives.

This module is the orchestrator. The bespoke rule families that need more than a
boolean schema expression (filename rules, sidecar-field presence, tabular
columns, value-type validation, dataset-level checks) are layered on top in later
phases; ``rules.checks`` is the schema-driven core they extend.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from bidsschematools.types.namespace import Namespace

from .expressions import EvaluationError, evaluate_string, truthy
from .issues import Issue, RuleProvenance, Severity

# Rule groups this engine evaluates today. ``checks`` is the generic
# selector-gated boolean group. The field/column/value groups (``sidecars``,
# ``dataset_metadata``, ``tabular_data``) are added with their rule families in a
# later phase.
_EVALUATED_GROUPS: tuple[str, ...] = ('checks',)

# Context fields/aggregates not yet populated with real data. A rule that depends
# on one of these cannot be determined, so it is skipped rather than evaluated
# against empty data (which would otherwise produce false findings). nifti_header
# is NOT listed: the schema's selectors gate header checks on
# ``nifti_header != null``, and the context loads it on demand.
_UNPOPULATED_FIELDS = re.compile(r'\b(gzip|ome|tiff)\b')

# The ``exists`` function needs a file-tree resolver that is wired in a later
# phase. Until then it reports 0, which is a determinate (and wrong) result that
# would make existence checks (README presence, IntendedFor ...) false-positive.
# Skip any rule that calls it so those checks wait for the resolver.
_NEEDS_EXISTS = re.compile(r'\bexists\s*\(')

_LEVEL_TO_SEVERITY: dict[str, Severity] = {
    'error': Severity.ERROR,
    'warning': Severity.WARNING,
}


def apply_rules(schema: Namespace, context: Mapping[str, Any]) -> list[Issue]:
    """Evaluate the schema's ``rules.checks`` for one file.

    Parameters
    ----------
    schema : Namespace
        The BIDS schema.
    context : Mapping
        The file's evaluation context (typically an
        :class:`~bids_validator.validation.context.EvalContext`).

    Returns
    -------
    list of Issue
        The findings for this file, de-duplicated.

    """
    issues: list[Issue] = []
    rules = schema['rules']
    for group in _EVALUATED_GROUPS:
        if group in rules:
            _descend(rules[group], context, issues, f'rules.{group}')
    return _dedupe(issues)


def _descend(node: Any, context: Mapping[str, Any], issues: list[Issue], path: str) -> None:
    """Walk a rule subtree, evaluating each selector-bearing rule it contains."""
    if not isinstance(node, Mapping):
        return
    if 'selectors' in node:
        _eval_rule(node, context, issues, path)
        return
    for key, child in node.items():
        _descend(child, context, issues, f'{path}.{key}')


def _eval_rule(
    rule: Mapping[str, Any],
    context: Mapping[str, Any],
    issues: list[Issue],
    path: str,
) -> None:
    """Apply one rule: if its selectors pass, evaluate its checks."""
    if not _is_evaluable(rule):
        return
    if not _selectors_pass(rule.get('selectors', []), context):
        return
    if 'checks' in rule:
        _eval_checks(rule, context, issues, path)


def _is_evaluable(rule: Mapping[str, Any]) -> bool:
    """Return False if the rule references something we cannot determine yet."""
    text = ' '.join([*rule.get('selectors', []), *rule.get('checks', [])])
    return not _UNPOPULATED_FIELDS.search(text) and not _NEEDS_EXISTS.search(text)


def _selectors_pass(selectors: list[str], context: Mapping[str, Any]) -> bool:
    """Return True only if every selector evaluates truthy.

    A selector that cannot be evaluated (for example an unknown function in a
    newer-than-engine schema) means the rule's applicability is undeterminable, so
    the rule is skipped.
    """
    for selector in selectors:
        try:
            if not truthy(evaluate_string(selector, context)):
                return False
        except EvaluationError:
            return False
    return True


def _eval_checks(
    rule: Mapping[str, Any],
    context: Mapping[str, Any],
    issues: list[Issue],
    path: str,
) -> None:
    """Evaluate a rule's checks, emitting its issue on the first determinate failure."""
    for check in rule.get('checks', []):
        try:
            result = evaluate_string(check, context)
        except EvaluationError:
            continue  # unsupported construct: skip this check, do not report
        if result is None:
            continue  # not determinable from the available context
        if not truthy(result):
            issues.append(_issue_from_rule(rule, context, path))
            return  # one finding per rule (a rule's checks are an AND)


def _issue_from_rule(rule: Mapping[str, Any], context: Mapping[str, Any], path: str) -> Issue:
    """Build the :class:`Issue` for a failed rule from its schema ``issue`` block."""
    issue_def = rule.get('issue') or {}
    severity = _LEVEL_TO_SEVERITY.get(issue_def.get('level', 'error'), Severity.ERROR)
    return Issue(
        code=issue_def.get('code') or 'CHECK_ERROR',
        severity=severity,
        location=_location(context),
        message=(issue_def.get('message') or '').strip() or None,
        rule=path,
        provenance=RuleProvenance(
            rule_path=path,
            selectors=list(rule.get('selectors', [])),
            checks=list(rule.get('checks', [])),
        ),
    )


def _dedupe(issues: list[Issue]) -> list[Issue]:
    """Drop duplicate findings (the same file can trip equivalent rules)."""
    seen: set[tuple[str, str | None, str | None, str | None]] = set()
    out: list[Issue] = []
    for issue in issues:
        key = (issue.code, issue.sub_code, issue.location, issue.message)
        if key in seen:
            continue
        seen.add(key)
        out.append(issue)
    return out


def _location(context: Mapping[str, Any]) -> str:
    """Return the dataset-relative path of the file (no leading slash)."""
    return str(context.get('path', '')).lstrip('/')
