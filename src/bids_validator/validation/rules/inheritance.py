"""Inheritance-principle findings for a data file.

A JSON sidecar applies to a data file when it sits in the same directory or an
ancestor, its entities are a subset of the data file's (with matching values), and
its suffix matches. More specific sidecars (deeper directory, more entities)
override less specific ones. This reports the two problems the reference validator
reports:

* ``MULTIPLE_INHERITABLE_FILES`` - a directory has more than one applicable sidecar
  and none is an exact match, so which one applies is ambiguous;
* ``SIDECAR_FIELD_OVERRIDE`` - a less specific sidecar sets a field that a more
  specific sidecar overrides (the more specific one wins, silently).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from bidsschematools.types.namespace import Namespace

from ...context import FileParts, load_json
from ..issues import Issue, Severity

if TYPE_CHECKING:
    from ...types.files import FileTree


def inheritance_checks(schema: Namespace, file: FileTree) -> list[Issue]:
    """Return inheritance findings for a data file."""
    if file.name.endswith('.json'):
        return []
    source_entities, source_suffix = _parts(schema, file)
    if not source_suffix:
        return []

    issues: list[Issue] = []
    merged_value: dict[str, Any] = {}
    merged_origin: dict[str, str] = {}
    for dir_tree in _ancestor_dirs(file):  # closest first
        candidates: list[tuple[dict[str, str], FileTree]] = []
        exact: FileTree | None = None
        for candidate in _json_sidecars_in(dir_tree):
            cand_entities, cand_suffix = _parts(schema, candidate)
            if cand_suffix != source_suffix or not _is_subset(cand_entities, source_entities):
                continue
            if cand_entities == source_entities:
                exact = candidate
            candidates.append((cand_entities, candidate))

        if exact is None and len(candidates) > 1:
            paths = sorted(c.relative_path for _e, c in candidates)
            issues.append(
                Issue(
                    code='MULTIPLE_INHERITABLE_FILES',
                    severity=Severity.ERROR,
                    location=paths[0],
                    message='more than one sidecar in this directory applies, and none matches '
                    'exactly, so the metadata is ambiguous: ' + ', '.join(paths),
                    suggestion='Keep a single applicable sidecar per directory, or name one to '
                    "match the data file's entities exactly.",
                )
            )
            break  # ambiguous: stop merging (the reference stops here too)

        chosen = exact
        if chosen is None and candidates:
            candidates.sort(key=lambda item: (len(item[0]), item[1].relative_path))
            chosen = candidates[-1][1]
        if chosen is None:
            continue

        data: Any = load_json(chosen)
        if not isinstance(data, dict):
            continue
        for key, value in data.items():
            if key in merged_value and merged_value[key] != value:
                issues.append(
                    Issue(
                        code='SIDECAR_FIELD_OVERRIDE',
                        sub_code=key,
                        severity=Severity.WARNING,
                        location=merged_origin[key],
                        message=f'field {key!r} is overridden by a more specific sidecar; '
                        'this value is ignored',
                        suggestion='Remove the duplicate field from one sidecar, or make the '
                        'values agree. The more specific sidecar takes precedence.',
                    )
                )
            merged_value.setdefault(key, value)
            merged_origin.setdefault(key, chosen.relative_path)
    return issues


def applicable_sidecar_files(schema: Namespace, file: FileTree) -> list[str]:
    """Return the relpaths of the JSON sidecars that apply to ``file`` (one per level).

    Used to mark sidecars as "in use", so a sidecar that applies to no data file
    can be reported. Empty for a JSON file or a file with no suffix.
    """
    if file.name.endswith('.json'):
        return []
    source_entities, source_suffix = _parts(schema, file)
    if not source_suffix:
        return []
    out: list[str] = []
    for dir_tree in _ancestor_dirs(file):
        chosen = _best_sidecar(schema, dir_tree, source_entities, source_suffix)
        if chosen is not None:
            out.append(chosen.relative_path)
    return out


def _best_sidecar(
    schema: Namespace,
    dir_tree: FileTree,
    source_entities: dict[str, str],
    source_suffix: str,
) -> FileTree | None:
    """Return the single most-specific sidecar in one directory that applies, or None."""
    candidates: list[tuple[dict[str, str], FileTree]] = []
    for candidate in _json_sidecars_in(dir_tree):
        cand_entities, cand_suffix = _parts(schema, candidate)
        if cand_suffix != source_suffix or not _is_subset(cand_entities, source_entities):
            continue
        if cand_entities == source_entities:  # exact match: use it directly
            return candidate
        candidates.append((cand_entities, candidate))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (len(item[0]), item[1].relative_path))
    return candidates[-1][1]


def _parts(schema: Namespace, file: FileTree) -> tuple[dict[str, str], str]:
    """Return (real entities, suffix) for a file (dropping no-hyphen phantom tokens)."""
    parts = FileParts.from_file(file, schema)
    entities = {key: value for key, value in parts.entities.items() if value is not None}
    return entities, parts.suffix or ''


def _ancestor_dirs(file: FileTree) -> Iterator[FileTree]:
    """Yield the file's directory and its ancestors, closest first."""
    node = file.parent
    while node is not None:
        yield node
        node = node.parent


def _json_sidecars_in(dir_tree: FileTree) -> list[FileTree]:
    """Return the .json files directly inside a directory."""
    return [
        child
        for child in dir_tree.children.values()
        if not child.is_dir and child.name.endswith('.json')
    ]


def _is_subset(candidate: dict[str, str], source: dict[str, str]) -> bool:
    """Return True if every entity in ``candidate`` is in ``source`` with the same value."""
    return all(source.get(key) == value for key, value in candidate.items())
