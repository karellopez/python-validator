"""Filename and path legality, ported from the reference validator.

The schema's ``rules.files`` describes every legal filename: which suffix goes in
which datatype folder, which entities are required or allowed, and which
extensions. This module identifies which rule(s) a file matches and then checks
the file against them, reporting the same findings the reference validator does:

* ``NOT_INCLUDED`` - the file matches no BIDS rule (a typo, or a file that belongs
  in ``sourcedata`` / ``derivatives``, or one that should be in ``.bidsignore``);
* ``ENTITY_WITH_NO_LABEL`` - an entity present with no label (``acq-``);
* ``INVALID_ENTITY_LABEL`` - an entity's label breaks the schema's value pattern;
* ``MISSING_REQUIRED_ENTITY`` / ``ENTITY_NOT_IN_RULE`` - too few / too many entities;
* ``DATATYPE_MISMATCH`` / ``EXTENSION_MISMATCH`` / ``INVALID_LOCATION`` - right name,
  wrong folder / extension / place;
* ``FILENAME_MISMATCH`` - entities duplicated or out of order;
* ``ALL_FILENAME_RULES_HAVE_ISSUES`` - several rules matched and each had a problem.

The no-false-positives discipline is preserved: directory recordings (``.ds`` ...)
are not name-checked as files, and the rule-matching mirrors the reference so this
flags exactly what the reference flags. This is the schema-rule companion to
:meth:`bids_validator.BIDSValidator.is_bids`; ``validate`` uses this one, so the
two never double-report.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from bidsschematools.types.namespace import Namespace

from .. import schema_introspect as introspect
from ..issues import Issue, Severity

if TYPE_CHECKING:
    from ...types.files import FileTree

# Per-schema caches (schema objects are cached for the process, so id() is stable).
_RULES_MEMO: dict[int, list[tuple[str, Mapping[str, Any]]]] = {}
_ENTITY_BY_SHORT_MEMO: dict[int, dict[str, Mapping[str, Any]]] = {}
_ORDERED_SHORT_MEMO: dict[int, list[str]] = {}


def filename_checks(schema: Namespace, context: Mapping[str, Any], file: FileTree) -> list[Issue]:
    """Identify the matching ``rules.files`` rule(s) and validate the filename."""
    name = file.name
    location = file.relative_path
    # Directory recordings (.ds, .mefd, ...) are single units, not files to be
    # name-parsed; the reference validates them through a different (directory)
    # path. Skip here to avoid spurious findings.
    if any(name.endswith(ext) for ext in introspect.directory_recordings(schema)):
        return []

    matched = _find_rule_matches(schema, context, name)

    if not matched:
        return [
            Issue(
                code='NOT_INCLUDED',
                severity=Severity.ERROR,
                location=location,
                message=f'{name} does not match any BIDS naming rule for this dataset',
                suggestion=(
                    'Check the file name against the BIDS specification (a typo in the suffix or '
                    'an entity is the usual cause). Source data belongs in sourcedata/, processed '
                    'data in derivatives/, and anything intentionally outside BIDS can be listed '
                    'in a .bidsignore file at the dataset root.'
                ),
            )
        ]

    matched = _narrow(schema, context, matched)
    issues: list[Issue] = []
    issues += _missing_label(context, location, matched)
    issues += _entity_label_check(schema, context, location)
    issues += _check_rules(schema, context, name, location, matched)
    issues += _reconstruction_failure(schema, context, name, location)
    return issues


# --- rule identification --------------------------------------------------


def _file_rules(schema: Namespace) -> list[tuple[str, Mapping[str, Any]]]:
    """Flatten ``rules.files`` to ``[(path, leaf_rule)]`` once per schema."""
    cached = _RULES_MEMO.get(id(schema))
    if cached is not None:
        return cached
    out: list[tuple[str, Mapping[str, Any]]] = []
    files = schema['rules'].get('files', {})
    for group in files:
        _collect(files[group], f'rules.files.{group}', out)
    _RULES_MEMO[id(schema)] = out
    return out


def _collect(node: Any, path: str, out: list[tuple[str, Mapping[str, Any]]]) -> None:
    if not isinstance(node, Mapping):
        return
    if 'path' in node or 'stem' in node or 'suffixes' in node:
        out.append((path, node))
        return
    for key in node:
        _collect(node[key], f'{path}.{key}', out)


def _find_rule_matches(
    schema: Namespace, context: Mapping[str, Any], name: str
) -> list[tuple[str, Mapping[str, Any]]]:
    out: list[tuple[str, Mapping[str, Any]]] = []
    for path, node in _file_rules(schema):
        # Derivatives are skipped by default file selection, so only raw rules apply.
        if path.startswith('rules.files.deriv'):
            continue
        if _rule_matches(node, context, name):
            out.append((path, node))
    return out


def _rule_matches(node: Mapping[str, Any], context: Mapping[str, Any], name: str) -> bool:
    if 'path' in node and '/' + str(node['path']) == context.get('path'):
        return True
    if 'stem' in node and _match_stem(node, context, name):
        return True
    return 'suffixes' in node and context.get('suffix') in list(node['suffixes'])


def _match_stem(node: Mapping[str, Any], context: Mapping[str, Any], name: str) -> bool:
    stem = name.split('.')[0]
    if not fnmatch.fnmatchcase(stem, str(node['stem'])):
        return False
    if 'datatypes' in node:
        return context.get('datatype') in list(node['datatypes'])
    return True


def _narrow(
    schema: Namespace,
    context: Mapping[str, Any],
    matched: list[tuple[str, Mapping[str, Any]]],
) -> list[tuple[str, Mapping[str, Any]]]:
    """When several rules match, prefer the datatype-sharing then entity/extension-fitting one."""
    if len(matched) <= 1:
        return matched
    datatype = context.get('datatype')
    by_datatype = [
        (p, n) for p, n in matched if 'datatypes' in n and datatype in list(n['datatypes'])
    ]
    if by_datatype:
        matched = by_datatype
    if len(matched) <= 1:
        return matched
    by_ent_ext = [(p, n) for p, n in matched if _entities_extensions_fit(schema, context, n)]
    return by_ent_ext or matched


def _entities_extensions_fit(
    schema: Namespace, context: Mapping[str, Any], rule: Mapping[str, Any]
) -> bool:
    ext_ok = 'extensions' not in rule or context.get('extension') in list(rule['extensions'])
    if 'entities' not in rule:
        return ext_ok
    rule_entities = {_short(schema, key) for key in rule['entities']}
    file_entities = set(context.get('entities', {}).keys())
    return ext_ok and file_entities.issubset(rule_entities)


# --- per-file checks ------------------------------------------------------


def _missing_label(
    context: Mapping[str, Any],
    location: str,
    matched: list[tuple[str, Mapping[str, Any]]],
) -> list[Issue]:
    if not any('suffixes' in node for _p, node in matched):
        return []
    empty = [key for key, value in context.get('entities', {}).items() if value == '']
    if not empty:
        return []
    return [
        Issue(
            code='ENTITY_WITH_NO_LABEL',
            sub_code=', '.join(empty),
            severity=Severity.ERROR,
            location=location,
            message=f'entit{"y" if len(empty) == 1 else "ies"} with no label: {", ".join(empty)}',
            suggestion=(
                "Every entity needs a label, written as 'key-label'. For example, write "
                "'acq-highres' rather than 'acq-'."
            ),
        )
    ]


def _entity_label_check(
    schema: Namespace, context: Mapping[str, Any], location: str
) -> list[Issue]:
    formats = schema['objects'].get('formats', {})
    by_short = _entity_by_short(schema)
    issues: list[Issue] = []
    for short, label in context.get('entities', {}).items():
        if label == '':
            continue  # an empty label is reported as ENTITY_WITH_NO_LABEL instead
        definition = by_short.get(short)
        fmt = definition.get('format') if isinstance(definition, Mapping) else None
        if not fmt or str(fmt) not in formats:
            continue
        pattern = str(formats[str(fmt)].get('pattern', ''))
        if pattern and not re.fullmatch(pattern, label):
            issues.append(
                Issue(
                    code='INVALID_ENTITY_LABEL',
                    sub_code=short,
                    severity=Severity.ERROR,
                    location=location,
                    message=f'label {label!r} for entity {short!r} does not match /{pattern}/',
                    suggestion=(
                        f"The value after '{short}-' must match the pattern /{pattern}/. "
                        f"For example, '{short}-01' if labels are zero-padded numbers."
                    ),
                )
            )
    return issues


def _check_rules(
    schema: Namespace,
    context: Mapping[str, Any],
    name: str,
    location: str,
    matched: list[tuple[str, Mapping[str, Any]]],
) -> list[Issue]:
    if len(matched) == 1:
        return _rule_issues(schema, context, name, location, matched[0])
    # Several rules still match: if any matches cleanly, accept it (no finding);
    # otherwise report that every candidate had a problem.
    per_rule = [
        _rule_issues(schema, context, name, location, (path, node)) for path, node in matched
    ]
    if any(not issues for issues in per_rule):
        return []
    return [
        Issue(
            code='ALL_FILENAME_RULES_HAVE_ISSUES',
            severity=Severity.ERROR,
            location=location,
            message='the file resembles several BIDS rules but fully satisfies none',
            suggestion=(
                'The name is close to more than one valid pattern but matches none exactly. '
                'Compare it to the specification for the suffix you intend.'
            ),
        )
    ]


def _rule_issues(
    schema: Namespace,
    context: Mapping[str, Any],
    name: str,
    location: str,
    matched: tuple[str, Mapping[str, Any]],
) -> list[Issue]:
    path, rule = matched
    issues: list[Issue] = []
    issues += _entity_rule_issue(schema, context, location, path, rule)
    issues += _datatype_mismatch(context, location, path, rule)
    issues += _extension_mismatch(context, location, path, rule)
    issues += _invalid_location(context, location)
    return issues


def _entity_rule_issue(
    schema: Namespace,
    context: Mapping[str, Any],
    location: str,
    path: str,
    rule: Mapping[str, Any],
) -> list[Issue]:
    if 'entities' not in rule:
        return []
    file_entities = list(context.get('entities', {}).keys())
    rule_entities = [_short(schema, key) for key in rule['entities']]
    issues: list[Issue] = []

    # Required-entity checks do not apply to a file at the dataset root (a shared
    # sidecar inherited downward), matching the reference.
    if '/' in location:
        required = [
            _short(schema, key)
            for key, level in rule['entities'].items()
            if str(level) == 'required'
        ]
        missing = [ent for ent in required if ent not in file_entities]
        if missing:
            issues.append(
                Issue(
                    code='MISSING_REQUIRED_ENTITY',
                    sub_code=', '.join(missing),
                    severity=Severity.ERROR,
                    location=location,
                    message=f'missing required entit{"y" if len(missing) == 1 else "ies"}: '
                    f'{", ".join(missing)}',
                    suggestion=f"Add the missing entity, for example '{missing[0]}-01'.",
                    rule=path,
                )
            )

    extra = [ent for ent in file_entities if ent not in rule_entities]
    if extra:
        issues.append(
            Issue(
                code='ENTITY_NOT_IN_RULE',
                sub_code=', '.join(extra),
                severity=Severity.ERROR,
                location=location,
                message=f'entit{"y" if len(extra) == 1 else "ies"} not allowed for this file '
                f'type: {", ".join(extra)}',
                suggestion=(
                    'Remove the entity, or check that you are using the right suffix; '
                    'this entity is not part of the rule for this file type.'
                ),
                rule=path,
            )
        )
    return issues


def _datatype_mismatch(
    context: Mapping[str, Any], location: str, path: str, rule: Mapping[str, Any]
) -> list[Issue]:
    datatype = context.get('datatype')
    if datatype and 'datatypes' in rule and datatype not in list(rule['datatypes']):
        allowed = ', '.join(str(d) for d in rule['datatypes'])
        return [
            Issue(
                code='DATATYPE_MISMATCH',
                severity=Severity.ERROR,
                location=location,
                message=f"the file is in the '{datatype}' folder but its suffix belongs in: "
                f'{allowed}',
                suggestion=f'Move the file into one of: {allowed}.',
                rule=path,
            )
        ]
    return []


def _extension_mismatch(
    context: Mapping[str, Any], location: str, path: str, rule: Mapping[str, Any]
) -> list[Issue]:
    if 'extensions' in rule and context.get('extension') not in list(rule['extensions']):
        allowed = ', '.join(str(e) for e in rule['extensions'])
        return [
            Issue(
                code='EXTENSION_MISMATCH',
                severity=Severity.ERROR,
                location=location,
                message=f'extension {context.get("extension")!r} is not allowed for this file '
                f'type; allowed: {allowed}',
                suggestion=f'Use one of the allowed extensions: {allowed}.',
                rule=path,
            )
        ]
    return []


def _invalid_location(context: Mapping[str, Any], location: str) -> list[Issue]:
    entities = context.get('entities', {})
    path = str(context.get('path', ''))
    issues: list[Issue] = []
    if 'tpl' not in entities:
        issues += _validate_location(entities, path, location, 'sub', 'ses')
    if 'sub' not in entities:
        issues += _validate_location(entities, path, location, 'tpl', 'cohort')
    return issues


def _validate_location(
    entities: Mapping[str, str], path: str, location: str, top: str, sub: str
) -> list[Issue]:
    issues: list[Issue] = []
    top_val = entities.get(top)
    sub_val = entities.get(sub)
    if top_val:
        expected = f'/{top}-{top_val}/'
        if sub_val:
            expected += f'{sub}-{sub_val}/'
        if not path.startswith(expected):
            issues.append(_location_issue(location, f'expected to be under {expected}'))
    if not top_val and re.match(rf'^/{top}-', path):
        issues.append(_location_issue(location, f"a '{top}-' folder but no '{top}' in the name"))
    if not sub_val and re.search(rf'/{sub}-', path):
        issues.append(_location_issue(location, f"a '{sub}-' folder but no '{sub}' in the name"))
    return issues


def _location_issue(location: str, detail: str) -> Issue:
    return Issue(
        code='INVALID_LOCATION',
        severity=Severity.ERROR,
        location=location,
        message=f'the file has a valid name but is in the wrong place ({detail})',
        suggestion=(
            'BIDS files live under sub-<label>/[ses-<label>/]<datatype>/. Move the file so its '
            'folders match the sub- (and ses-) entities in its name.'
        ),
    )


def _reconstruction_failure(
    schema: Namespace, context: Mapping[str, Any], name: str, location: str
) -> list[Issue]:
    entities = context.get('entities', {})
    if not entities:
        return []
    ordered = [short for short in _ordered_short(schema) if short in entities]
    parts = [f'{short}-{entities[short]}' for short in ordered]
    suffix = context.get('suffix', '') or ''
    extension = context.get('extension', '') or ''
    expected = '_'.join([*parts, suffix + extension])
    if name != expected:
        return [
            Issue(
                code='FILENAME_MISMATCH',
                severity=Severity.ERROR,
                location=location,
                message=f'the filename is not in canonical form; expected {expected!r}',
                suggestion=(
                    'Entities must appear once each, in the BIDS order, before the suffix. '
                    f'Rename the file to {expected!r}.'
                ),
            )
        ]
    return []


# --- schema helpers (memoised) --------------------------------------------


def _entity_by_short(schema: Namespace) -> dict[str, Mapping[str, Any]]:
    cached = _ENTITY_BY_SHORT_MEMO.get(id(schema))
    if cached is not None:
        return cached
    out: dict[str, Mapping[str, Any]] = {}
    for definition in schema['objects']['entities'].values():
        entity_name = definition.get('name')
        if entity_name:
            out[str(entity_name)] = definition
    _ENTITY_BY_SHORT_MEMO[id(schema)] = out
    return out


def _ordered_short(schema: Namespace) -> list[str]:
    cached = _ORDERED_SHORT_MEMO.get(id(schema))
    if cached is not None:
        return cached
    entities = schema['objects']['entities']
    out: list[str] = []
    for long_name in schema['rules'].get('entities', []):
        if long_name in entities:
            entity_name = entities[long_name].get('name')
            if entity_name:
                out.append(str(entity_name))
    _ORDERED_SHORT_MEMO[id(schema)] = out
    return out


def _short(schema: Namespace, long_name: str) -> str:
    entities = schema['objects']['entities']
    if long_name in entities:
        return str(entities[long_name].get('name', long_name))
    return long_name
