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

from bidsschematools.schema import load_schema

from ..types.files import FileTree
from .context import eval_context, iter_file_contexts
from .engine import apply_rules
from .issues import Issue, Severity
from .report import FileVerdict, ValidationReport

if TYPE_CHECKING:
    import os

    from bidsschematools.types.namespace import Namespace

    from ..context import Context

__all__ = ['validate', 'validate_file']


def validate(
    root: str | os.PathLike[str],
    *,
    schema: Namespace | None = None,
    read_headers: bool = True,
    max_rows: int = 1000,
) -> ValidationReport:
    """Validate the BIDS dataset at ``root``.

    Parameters
    ----------
    root : str or os.PathLike
        The dataset root.
    schema : Namespace, optional
        A pre-loaded schema. Defaults to the ``bidsschematools`` bundled schema
        (BIDS 1.11.1), which matches the reference validator's bundled schema.
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
    schema_ns = schema if schema is not None else load_schema()
    tree = FileTree.read_from_filesystem(root)
    report = ValidationReport(
        dataset_root=Path(root),
        bids_version=str(schema_ns['bids_version']),
        schema_version=str(schema_ns['schema_version']),
    )
    for context in iter_file_contexts(tree, schema_ns):
        report.files.append(_validate_one(schema_ns, context, read_headers=read_headers))
    report.recompute()
    return report


def validate_file(
    root: str | os.PathLike[str],
    relpath: str,
    *,
    schema: Namespace | None = None,
    read_headers: bool = True,
    max_rows: int = 1000,
) -> FileVerdict:
    """Validate one file within a dataset.

    The rest of the dataset is indexed so inheritance and association checks still
    work, but only the named file's findings are returned. A path that is not
    under the dataset root yields a single ``FILE_NOT_FOUND`` finding.
    """
    schema_ns = schema if schema is not None else load_schema()
    tree = FileTree.read_from_filesystem(root)
    target = relpath.lstrip('/')
    for context in iter_file_contexts(tree, schema_ns):
        if context.path.lstrip('/') == target:
            return _validate_one(schema_ns, context, read_headers=read_headers)
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
    *,
    read_headers: bool,
) -> FileVerdict:
    """Run the engine for one file, capturing any read failure as a warning."""
    location = context.path.lstrip('/')
    verdict = FileVerdict(path=Path(location))
    try:
        verdict.issues.extend(
            apply_rules(schema_ns, eval_context(context, read_headers=read_headers))
        )
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
