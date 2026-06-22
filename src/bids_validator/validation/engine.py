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

from . import schema_introspect as introspect
from .expressions import EvaluationError, evaluate_string, truthy
from .issues import Fix, Issue, RuleProvenance, Severity
from .rules.guidance import field_guidance, value_guidance
from .rules.tables import eval_columns
from .rules.values import validate_value

# Rule groups this engine evaluates. ``checks`` is the generic selector-gated
# boolean group; ``sidecars`` and ``dataset_metadata`` carry required/recommended
# field rules; ``tabular_data`` carries TSV column rules.
_EVALUATED_GROUPS: tuple[str, ...] = ('checks', 'sidecars', 'dataset_metadata', 'tabular_data')

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

# Field requirement level -> severity (for sidecar / dataset_description fields).
_FIELD_LEVEL_TO_SEVERITY: dict[str, Severity] = {
    'required': Severity.ERROR,
    'recommended': Severity.WARNING,
    'optional': Severity.IGNORE,
    'prohibited': Severity.IGNORE,
}

# Files that cannot themselves carry a sidecar, so sidecar field rules do not apply.
_SIDECAR_EXEMPT_EXTENSIONS = ('.json', '', '.md', '.txt', '.rst', '.cff')

_ADDENDUM_RE = re.compile(r'(required|recommended) if `(\w+)` is `(\w+)`')


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
            _descend(schema, rules[group], context, issues, f'rules.{group}')
    issues.extend(_validate_present_values(schema, context))
    return _dedupe(issues)


def _descend(
    schema: Namespace,
    node: Any,
    context: Mapping[str, Any],
    issues: list[Issue],
    path: str,
) -> None:
    """Walk a rule subtree, evaluating each selector-bearing rule it contains."""
    if not isinstance(node, Mapping):
        return
    if 'selectors' in node:
        _eval_rule(schema, node, context, issues, path)
        return
    for key, child in node.items():
        _descend(schema, child, context, issues, f'{path}.{key}')


def _eval_rule(
    schema: Namespace,
    rule: Mapping[str, Any],
    context: Mapping[str, Any],
    issues: list[Issue],
    path: str,
) -> None:
    """Apply one rule: if its selectors pass, evaluate its checks and field rules."""
    if not _is_evaluable(rule):
        return
    if not _selectors_pass(rule.get('selectors', []), context):
        return
    if 'checks' in rule:
        _eval_checks(rule, context, issues, path)
    if 'fields' in rule:
        _eval_fields(schema, rule, context, issues, path)
    if 'columns' in rule and path.startswith('rules.tabular_data'):
        issues.extend(eval_columns(schema, rule, context, path))


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


def _eval_fields(
    schema: Namespace,
    rule: Mapping[str, Any],
    context: Mapping[str, Any],
    issues: list[Issue],
    path: str,
) -> None:
    """Emit a finding for each required/recommended field the file is missing.

    Sidecar rules (``rules.sidecars``) read the inheritance-merged sidecar of a
    data file; dataset_metadata rules read the JSON of dataset_description.json.
    Presence is checked here; the value of a present field is validated by
    :func:`_validate_present_values`.
    """
    is_sidecar_rule = path.startswith('rules.sidecars')
    if is_sidecar_rule and context.get('extension') in _SIDECAR_EXEMPT_EXTENSIONS:
        return
    data = context.get('sidecar') if is_sidecar_rule else context.get('json')
    if not isinstance(data, Mapping):
        return

    metadata = schema['objects'].get('metadata', {})
    for field_key, requirement in rule['fields'].items():
        meta_def = metadata.get(field_key, {})
        field_name = str(meta_def.get('name', field_key))
        if field_name in data:
            continue  # present; value validation is a separate global pass
        severity = _field_severity(requirement, context)
        if severity is Severity.IGNORE:
            continue
        issues.append(
            _missing_field_issue(
                schema, requirement, field_name, severity, context, path, is_sidecar_rule
            )
        )


def _field_severity(requirement: Any, context: Mapping[str, Any]) -> Severity:
    """Resolve a field requirement (a level string or a level object) to a severity."""
    if isinstance(requirement, str):
        return _FIELD_LEVEL_TO_SEVERITY.get(requirement, Severity.IGNORE)
    if isinstance(requirement, Mapping):
        severity = _FIELD_LEVEL_TO_SEVERITY.get(str(requirement.get('level', '')), Severity.IGNORE)
        addendum = requirement.get('level_addendum')
        if addendum:
            match = _ADDENDUM_RE.search(str(addendum))
            if match:
                conditional_level, key, value = match.groups()
                sidecar = context.get('sidecar') or {}
                if isinstance(sidecar, Mapping) and str(sidecar.get(key)) == value:
                    severity = _FIELD_LEVEL_TO_SEVERITY.get(conditional_level, severity)
        return severity
    return Severity.IGNORE


def _missing_field_issue(
    schema: Namespace,
    requirement: Any,
    field_name: str,
    severity: Severity,
    context: Mapping[str, Any],
    path: str,
    is_sidecar_rule: bool,
) -> Issue:
    """Build the missing-field finding (a per-field code override is honoured)."""
    requirement_issue = requirement.get('issue') if isinstance(requirement, Mapping) else None
    if isinstance(requirement_issue, Mapping) and requirement_issue.get('code'):
        code = str(requirement_issue['code'])
    else:
        kind = 'SIDECAR' if is_sidecar_rule else 'JSON'
        tier = 'REQUIRED' if severity is Severity.ERROR else 'RECOMMENDED'
        code = f'{kind}_KEY_{tier}'
    tier_word = 'required' if severity is Severity.ERROR else 'recommended'
    return Issue(
        code=code,
        sub_code=field_name,
        severity=severity,
        location=_location(context),
        message=f'missing {tier_word} field {field_name!r}',
        suggestion=field_guidance(schema, field_name),
        rule=path,
        fix=Fix(action='add_field', field=field_name),
    )


def _validate_present_values(schema: Namespace, context: Mapping[str, Any]) -> list[Issue]:
    """Validate the value of every present sidecar / json field against its schema def.

    A field whose name maps to several definitions is valid if it matches any of
    them, so context-specific duplicate names never cause a false positive.
    """
    is_json = context.get('extension') == '.json'
    data = context.get('json') if is_json else context.get('sidecar')
    if not isinstance(data, Mapping):
        return []
    by_name = introspect.metadata_by_name(schema)
    location = _location(context)
    issues: list[Issue] = []
    for field_name, value in data.items():
        definitions = by_name.get(field_name)
        if not definitions:
            continue
        problems = [validate_value(value, definition) for definition in definitions]
        if all(problems):  # the value fails every definition for this name
            issues.append(
                Issue(
                    code='JSON_SCHEMA_VALIDATION_ERROR',
                    sub_code=field_name,
                    severity=Severity.ERROR,
                    location=location,
                    message=f'{field_name} {problems[0][0]}',
                    suggestion=value_guidance(field_name, definitions[0]),
                    rule='objects.metadata',
                )
            )
    return issues
