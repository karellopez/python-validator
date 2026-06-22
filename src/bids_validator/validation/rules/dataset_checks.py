"""Dataset-level checks that look across files, ported from the reference validator.

Unlike the per-file checks, these need the whole dataset at once:

* ``CASE_COLLISION`` - two files whose paths differ only by letter case (a hazard
  on case-insensitive filesystems);
* ``SIDECAR_WITHOUT_DATAFILE`` - a JSON sidecar that applies to no data file;
* ``UNUSED_STIMULUS`` - a file in ``stimuli/`` referenced by no ``events.tsv``;
* plus ``CITATION_CFF_VALIDATION_ERROR`` for a malformed ``CITATION.cff``.

``SIDECAR_WITHOUT_DATAFILE`` and ``UNUSED_STIMULUS`` rely on a "viewed" set gathered
while the per-file contexts are built (which sidecars a data file used through
inheritance or association, which stimuli an events table referenced), so a file
counts as used exactly when the reference validator would count it.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Any

from bidsschematools.types.namespace import Namespace

from ..issues import Issue, Severity
from .citation import citation_checks
from .inheritance import applicable_sidecar_files

if TYPE_CHECKING:
    from ...types.files import FileTree

# JSON files that legitimately stand alone (no data file), never reported.
_STANDALONE_JSON = {'dataset_description.json', 'genetic_info.json'}


def dataset_checks(
    tree: FileTree,
    files: list[FileTree],
    viewed_json: set[str],
    viewed_stimuli: set[str],
) -> list[Issue]:
    """Run the dataset-wide checks over the validated ``files``."""
    issues: list[Issue] = []
    issues += _case_collisions(files)
    issues += _sidecar_without_datafile(files, viewed_json)
    issues += _unused_stimulus(tree, viewed_stimuli)
    issues += citation_checks(tree)
    return issues


def _sidecar_without_datafile(files: list[FileTree], viewed_json: set[str]) -> list[Issue]:
    issues: list[Issue] = []
    for file in files:
        name = file.name
        if not name.endswith('.json') or name in _STANDALONE_JSON:
            continue
        # ``*_description.json`` (atlas / segmentation descriptors) describe an
        # entity, not a single data file, so they never pair with one.
        if name.endswith('_description.json'):
            continue
        if file.relative_path in viewed_json:
            continue
        issues.append(
            Issue(
                code='SIDECAR_WITHOUT_DATAFILE',
                severity=Severity.ERROR,
                location=file.relative_path,
                message='this JSON sidecar applies to no data file in the dataset',
                suggestion=(
                    'A sidecar must describe at least one data file it sits beside or above '
                    '(matching suffix and a subset of its entities), or be an association such '
                    'as coordsystem. Add the data file, or remove or rename the sidecar.'
                ),
            )
        )
    return issues


def _case_collisions(files: list[FileTree]) -> list[Issue]:
    by_lower: dict[str, list[str]] = {}
    for file in files:
        by_lower.setdefault(file.relative_path.lower(), []).append(file.relative_path)
    issues: list[Issue] = []
    for collisions in by_lower.values():
        if len(collisions) > 1:
            for relpath in sorted(collisions):
                others = ', '.join(sorted(set(collisions) - {relpath}))
                issues.append(
                    Issue(
                        code='CASE_COLLISION',
                        severity=Severity.ERROR,
                        location=relpath,
                        message=f'another file has the same name but a different case: {others}',
                        suggestion=(
                            'On a case-insensitive filesystem these files clash. Rename so the '
                            'paths differ by more than letter case.'
                        ),
                    )
                )
    return issues


def _unused_stimulus(tree: FileTree, viewed_stimuli: set[str]) -> list[Issue]:
    stimuli = [
        f.relative_path for f in _all_files(tree) if f.relative_path.split('/', 1)[0] == 'stimuli'
    ]
    unused = sorted(relpath for relpath in stimuli if relpath not in viewed_stimuli)
    if not unused:
        return []
    return [
        Issue(
            code='UNUSED_STIMULUS',
            severity=Severity.WARNING,
            location='stimuli',
            message=f'{len(unused)} file(s) in stimuli/ are not referenced by any events.tsv',
            suggestion=(
                "Reference each stimulus from an events.tsv 'stim_file' column, or remove the "
                'unused files. First few: ' + ', '.join(unused[:5])
            ),
            affects=unused,
        )
    ]


def collect_viewed(
    schema: Namespace,
    file: FileTree,
    evaluation: Mapping[str, Any],
    viewed_json: set[str],
    viewed_stimuli: set[str],
) -> None:
    """Record, from one data file's context, which sidecars and stimuli it uses."""
    if not file.name.endswith('.json'):
        for relpath in applicable_sidecar_files(schema, file):
            viewed_json.add(relpath)
        associations = evaluation.get('associations') or {}
        if isinstance(associations, Mapping):
            for obj in associations.values():
                path = obj.get('path') if isinstance(obj, Mapping) else None
                if isinstance(path, str) and path.endswith('.json'):
                    viewed_json.add(path.lstrip('/'))
        # A coordinate-system sidecar associates with a recording in the same
        # directory even with extra entities (space-), which the entity-subset
        # match does not capture; any recording in the directory marks them used.
        if file.parent is not None:
            for sidecar in file.parent.children.values():
                if sidecar.is_dir:
                    continue
                if (
                    sidecar.name.endswith('_coordsystem.json')
                    or sidecar.name == 'coordsystem.json'
                ):
                    viewed_json.add(sidecar.relative_path)
    columns = evaluation.get('columns') or {}
    if isinstance(columns, Mapping):
        for value in columns.get('stim_file', []):
            if value and value not in ('n/a', ''):
                viewed_stimuli.add('stimuli/' + str(value).lstrip('/'))


def _all_files(tree: FileTree) -> Iterator[FileTree]:
    for child in tree.children.values():
        if child.is_dir:
            yield from _all_files(child)
        else:
            yield child
