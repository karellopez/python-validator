"""Validate a dataset's ``CITATION.cff`` file.

``CITATION.cff`` is an optional Citation File Format file. This does the
conservative subset that cannot produce a false positive: the file must be valid
YAML, be a mapping, and carry the keys CFF always requires (``cff-version``,
``message``, ``title``). Anything beyond that is left to a future, schema-complete
check.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..issues import Issue, Severity

if TYPE_CHECKING:
    from ...types.files import FileTree

_REQUIRED = ('cff-version', 'message', 'title')


def _issue(message: str, suggestion: str) -> Issue:
    return Issue(
        code='CITATION_CFF_VALIDATION_ERROR',
        severity=Severity.ERROR,
        location='CITATION.cff',
        message=message,
        suggestion=suggestion,
    )


def citation_checks(tree: FileTree) -> list[Issue]:
    """Validate ``CITATION.cff`` at the dataset root, if present."""
    cff = tree.children.get('CITATION.cff')
    if cff is None or cff.is_dir:
        return []
    try:
        if cff.path_obj.is_symlink() or cff.path_obj.stat().st_size == 0:
            return []
    except OSError:
        return []
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:  # pragma: no cover - pyyaml ships with bidsschematools
        return []
    try:
        text = cff.path_obj.read_text(encoding='utf-8')
    except OSError:
        return []
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return [
            _issue(
                'CITATION.cff is not valid YAML',
                'Fix the YAML syntax. See https://citation-file-format.github.io for the format.',
            )
        ]
    if not isinstance(data, dict):
        return [
            _issue(
                'CITATION.cff must be a YAML mapping of fields',
                'Use top-level keys: cff-version, message, title (and authors).',
            )
        ]
    missing = [key for key in _REQUIRED if key not in data]
    if missing:
        return [
            _issue(
                f'CITATION.cff is missing required key(s): {", ".join(missing)}',
                'Add the required CFF keys: cff-version, message, and title (and authors).',
            )
        ]
    return []
