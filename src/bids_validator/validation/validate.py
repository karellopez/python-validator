"""Validate a dataset or a single file.

These are the orchestration entry points. Each resolves a schema, indexes the
files, builds a context per file, and runs the rule engine, returning a typed
result (:class:`~bids_validator.validation.report.ValidationReport`,
:class:`~bids_validator.validation.report.FileVerdict`). They never raise on an
invalid dataset: problems are recorded as findings, and one unvalidatable file
cannot abort the whole run.

This is the foundation wiring. The bespoke rule families (filename rules,
sidecar-field presence, tabular columns, value types, dataset-level checks) and
``.bidsignore`` / derivatives handling are layered on in later phases; today the
engine evaluates the schema's ``rules.checks`` for every file.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from bidsschematools.types.namespace import Namespace

from ..bidsignore import filter_file_tree
from ..types.files import FileTree
from .context import eval_context, iter_file_contexts
from .engine import apply_rules
from .issues import Issue, Severity
from .report import FileVerdict, ValidationReport
from .rules import filename_checks, inheritance_checks, integrity_checks
from .rules.dataset_checks import collect_viewed, dataset_checks
from .schema import SchemaSelector, resolve

if TYPE_CHECKING:
    import os
    from collections.abc import Mapping
    from typing import Any

    from ..context import Context

__all__ = ['validate', 'validate_file']

# Top-level directories the reference validator does not validate as BIDS by
# default (their contents are associated data, not BIDS files), plus hidden paths
# (a component starting with "."). Full .bidsignore handling lands with the
# dataset-level checks.
_IGNORED_TOP_DIRS = frozenset({'sourcedata', 'derivatives', 'code', 'stimuli'})


def _is_ignored(path: str) -> bool:
    """Return True if a dataset-relative path is outside default BIDS validation."""
    parts = path.lstrip('/').split('/')
    if any(part.startswith('.') for part in parts):
        return True
    return bool(parts) and parts[0] in _IGNORED_TOP_DIRS


def _read_tree(root: str | os.PathLike[str]) -> FileTree:
    """Read the dataset tree and drop the files its ``.bidsignore`` excludes."""
    tree = FileTree.read_from_filesystem(root)
    try:
        return filter_file_tree(tree)
    except ValueError:
        # An unsupported .bidsignore pattern (for example an inverted "!" line);
        # fall back to validating the unfiltered tree rather than aborting.
        return tree


def validate(
    root: str | os.PathLike[str],
    *,
    schema: Namespace | SchemaSelector = None,
    read_headers: bool = True,
    max_rows: int = 1000,
) -> ValidationReport:
    """Validate the BIDS dataset at ``root``.

    Parameters
    ----------
    root : str or os.PathLike
        The dataset root.
    schema : Namespace or str or os.PathLike or None, optional
        Which schema to validate against. A pre-loaded ``Namespace`` is used
        as-is; a *selector* (a bundled version such as ``"1.10.0"``, ``"latest"``,
        a URL, or a local ``schema.json`` / source directory) is resolved by
        :func:`bids_validator.validation.schema.resolve`. ``None`` (the default)
        uses the installed ``bidsschematools`` schema, the latest stable BIDS
        version, matching the reference validator's bundled schema.
    read_headers : bool, default True
        Read NIfTI headers for header checks (needs nibabel). When False, header
        checks select on a null ``nifti_header`` and are skipped.
    max_rows : int, default 1000
        Reserved for the tabular value checks added in a later phase; accepted now
        for a stable signature.

    Returns
    -------
    ValidationReport
        The findings, with severity and counts recomputed.

    """
    schema_ns = schema if isinstance(schema, Namespace) else resolve(schema)
    tree = _read_tree(root)
    report = ValidationReport(
        dataset_root=Path(root),
        bids_version=str(schema_ns['bids_version']),
        schema_version=str(schema_ns['schema_version']),
    )
    viewed_json: set[str] = set()
    viewed_stimuli: set[str] = set()
    validated: list[FileTree] = []
    for context in iter_file_contexts(tree, schema_ns):
        if _is_ignored(context.path):
            continue
        evaluation = eval_context(context, read_headers=read_headers)
        report.files.append(
            _validate_one(schema_ns, context, evaluation, read_headers=read_headers)
        )
        validated.append(context.file)
        _collect_viewed(schema_ns, context.file, evaluation, viewed_json, viewed_stimuli)
    report.dataset_issues.extend(dataset_checks(tree, validated, viewed_json, viewed_stimuli))
    if not _has_subjects(tree):
        report.dataset_issues.add(
            Issue(
                code='NO_SUBJECTS',
                severity=Severity.WARNING,
                message='no sub-* directories found under the dataset root',
            )
        )
    report.recompute()
    return report


def validate_file(
    root: str | os.PathLike[str],
    relpath: str,
    *,
    schema: Namespace | SchemaSelector = None,
    read_headers: bool = True,
    max_rows: int = 1000,
) -> FileVerdict:
    """Validate one file within a dataset.

    The rest of the dataset is indexed so inheritance and association checks still
    work, but only the named file's findings are returned. A path that is not
    under the dataset root yields a single ``FILE_NOT_FOUND`` finding. The
    ``schema`` argument accepts the same forms as :func:`validate`.
    """
    schema_ns = schema if isinstance(schema, Namespace) else resolve(schema)
    tree = _read_tree(root)
    target = relpath.lstrip('/')
    for context in iter_file_contexts(tree, schema_ns):
        if context.path.lstrip('/') == target:
            evaluation = eval_context(context, read_headers=read_headers)
            return _validate_one(schema_ns, context, evaluation, read_headers=read_headers)
    verdict = FileVerdict(path=Path(relpath))
    verdict.issues.append(
        Issue(
            code='FILE_NOT_FOUND',
            severity=Severity.ERROR,
            location=target,
            message=f'{relpath} is not under the dataset root',
        )
    )
    verdict.recompute_severity()
    return verdict


def _validate_one(
    schema_ns: Namespace,
    context: Context,
    evaluation: Mapping[str, Any],
    *,
    read_headers: bool,
) -> FileVerdict:
    """Run the per-file checks for one file, capturing any read failure as a warning."""
    location = context.path.lstrip('/')
    verdict = FileVerdict(path=Path(location))
    try:
        verdict.issues.extend(
            integrity_checks(context.file, evaluation, read_headers=read_headers)
        )
        verdict.issues.extend(filename_checks(schema_ns, evaluation, context.file))
        verdict.issues.extend(inheritance_checks(schema_ns, context.file))
        verdict.issues.extend(apply_rules(schema_ns, evaluation))
    except Exception as error:  # noqa: BLE001 - never let one file abort the whole run
        verdict.issues.append(
            Issue(
                code='bids_validator.internal_error',
                severity=Severity.WARNING,
                location=location,
                message=f'could not fully validate this file: {error}',
            )
        )
    verdict.recompute_severity()
    return verdict


def _collect_viewed(
    schema_ns: Namespace,
    file: FileTree,
    evaluation: Mapping[str, Any],
    viewed_json: set[str],
    viewed_stimuli: set[str],
) -> None:
    """Record the sidecars/stimuli one file uses; never abort validation on error."""
    try:
        collect_viewed(schema_ns, file, evaluation, viewed_json, viewed_stimuli)
    except Exception:  # noqa: BLE001 - viewed-collection is best-effort
        return


def _has_subjects(tree: FileTree) -> bool:
    """Return True if the dataset has at least one ``sub-*`` directory."""
    return any(child.is_dir and child.name.startswith('sub-') for child in tree.children.values())
