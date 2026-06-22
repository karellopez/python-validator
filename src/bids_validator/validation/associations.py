"""Resolve a data file's associated files into the ``associations`` context.

Many schema checks look at files that travel with a data file: a ``dwi`` file's
``.bval`` / ``.bvec``, a task recording's ``events.tsv``, an electrophysiology
recording's ``channels.tsv``, an ASL run's ``aslcontext.tsv``, and so on. The
schema describes each of these in ``meta.associations`` (a selector saying when
it applies, a target suffix/extension to look for, and whether it inherits up the
tree).

This module finds those files using the same proximity walk as the inheritance
principle and exposes them under ``associations.<name>`` with the fields the
checks read: a TSV's columns plus ``n_rows`` / ``n_cols`` and its sidecar; a
``.bval`` / ``.bvec``'s ``values`` / ``n_rows`` / ``n_cols``; or just the path for
plain existence checks.

The file access is reused from :mod:`bids_validator.context` (the FileTree-backed
loaders), so there is one I/O path for the whole validator. Association names that
need a more complex aggregate (``coordsystems``, ``atlas_description``) are not
built here; the rule engine skips rules that reference them, so they are never
guessed at (this keeps the validator from emitting false positives).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from ..context import (
    FileParts,
    load_json,
    load_sidecar,
    load_tsv,
    load_tsv_gz,
)
from .expressions import EvaluationError, evaluate_string, truthy

if TYPE_CHECKING:
    from ..context import Context
    from ..types.files import FileTree

# Associations built here (the rule engine relies on these being populated).
_BUILT: frozenset[str] = frozenset(
    {
        'events',
        'bval',
        'bvec',
        'channels',
        'aslcontext',
        'm0scan',
        'magnitude',
        'magnitude1',
        'coordsystem',
        'electrodes',
        'physio',
    }
)


def build_associations(context: Context) -> dict[str, Any]:
    """Return the ``associations`` mapping for one data file.

    Parameters
    ----------
    context : Context
        The per-file context (its FileTree, entities, suffix, extension,
        datatype and schema are read).

    Returns
    -------
    dict
        Each key is an association name (``events``, ``bval`` ...) whose value is
        the object the schema checks read.

    """
    suffix = context.suffix
    if not suffix:
        return {}
    schema = context.schema
    specs: Any = schema['meta'].get('associations', {})
    # ``datatype`` is threaded into the selector context so datatype-scoped
    # associations (for example channels for an EEG recording) select correctly.
    selector_context: dict[str, Any] = {
        'suffix': suffix,
        'extension': context.extension,
        'entities': context.entities,
        'datatype': context.datatype,
    }
    out: dict[str, Any] = {}
    for name, spec in specs.items():
        if name not in _BUILT:
            continue
        if not _selectors_pass(spec.get('selectors', []), selector_context):
            continue
        target: Any = spec.get('target', {})
        found = _find_target(
            context.file,
            context.entities,
            target_suffix=str(target.get('suffix', suffix)),
            target_extensions=_as_list(target.get('extension')),
            inherit=bool(spec.get('inherit', False)),
        )
        if found is None:
            continue
        out[name] = _association_object(found)
    return out


def _selectors_pass(selectors: list[str], context: dict[str, Any]) -> bool:
    """Return True if every selector expression is truthy against ``context``."""
    for selector in selectors:
        try:
            if not truthy(evaluate_string(selector, context)):
                return False
        except EvaluationError:
            return False
    return True


def _ancestor_dirs(file: FileTree) -> Iterator[FileTree]:
    """Yield the file's directory and its ancestors, closest first."""
    node = file.parent
    while node is not None:
        yield node
        node = node.parent


def _find_target(
    file: FileTree,
    source_entities: dict[str, str | None],
    *,
    target_suffix: str,
    target_extensions: list[str],
    inherit: bool,
) -> FileTree | None:
    """Return the closest file matching the target suffix/extension.

    The match must have a subset of the source's entities. Within a directory the
    most specific candidate (most entities) wins; directories are searched closest
    first, walking up the tree only when the association inherits.
    """
    if inherit:
        dirs: Iterator[FileTree] = _ancestor_dirs(file)
    else:
        dirs = iter([file.parent] if file.parent is not None else [])
    for dir_tree in dirs:
        best: FileTree | None = None
        best_specificity = -1
        for candidate in dir_tree.children.values():
            if candidate.is_dir or candidate.relative_path == file.relative_path:
                continue
            parts = FileParts.from_file(candidate)
            if target_suffix and parts.suffix != target_suffix:
                continue
            if target_extensions and parts.extension not in target_extensions:
                continue
            if not _entities_subset(parts.entities, source_entities):
                continue
            if len(parts.entities) > best_specificity:
                best, best_specificity = candidate, len(parts.entities)
        if best is not None:
            return best
    return None


def _entities_subset(candidate: dict[str, str | None], source: dict[str, str | None]) -> bool:
    """Return True if every entity in ``candidate`` is in ``source`` with the same value."""
    return all(source.get(key) == value for key, value in candidate.items())


def _association_object(file: FileTree) -> dict[str, Any]:
    """Build the object exposed under ``associations.<name>`` for a found file."""
    parts = FileParts.from_file(file)
    path = parts.path
    extension = parts.extension
    if extension in ('.tsv', '.tsv.gz'):
        columns = _load_columns(file, extension)
        obj: dict[str, Any] = {key: list(values) for key, values in columns.items()}
        obj['n_rows'] = max((len(values) for values in columns.values()), default=0)
        obj['n_cols'] = len(columns)
        obj['sidecar'] = load_sidecar(file)
        obj['path'] = path
        return obj
    if extension in ('.bval', '.bvec'):
        return _numeric_matrix(file, path)
    if extension == '.json':
        # load_json is typed to return a JSON object; copy it so the cached
        # result is not mutated by the added path.
        result = dict(load_json(file))
        result['path'] = path
        return result
    # A plain data file (for example m0scan, magnitude): only existence/path matters.
    return {'path': path}


def _load_columns(file: FileTree, extension: str) -> dict[str, Any]:
    """Load the columns of an associated TSV (headers for ``.tsv.gz`` from its sidecar)."""
    if extension == '.tsv':
        return dict(load_tsv(file))
    headers = tuple(load_sidecar(file).get('Columns', ()))
    return dict(load_tsv_gz(file, headers))


def _numeric_matrix(file: FileTree, path: str) -> dict[str, Any]:
    """Parse a whitespace-delimited ``.bval`` / ``.bvec`` into values plus shape."""
    try:
        text = file.path_obj.read_text()
    except OSError:
        return {'values': [], 'n_rows': 0, 'n_cols': 0, 'path': path}
    rows = [line.split() for line in text.splitlines() if line.strip()]
    values: list[float] = []
    for row in rows:
        for token in row:
            try:
                values.append(float(token))
            except ValueError:
                continue
    return {
        'values': values,
        'n_rows': len(rows),
        'n_cols': len(rows[0]) if rows else 0,
        'path': path,
    }


def _as_list(value: Any) -> list[str]:
    """Normalise a schema target ``extension`` (string, list or absent) to a list."""
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)
