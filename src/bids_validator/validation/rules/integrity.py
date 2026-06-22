"""Per-file structural integrity checks.

These catch files that are broken before any schema rule can apply: a file that is
empty, a NIfTI whose header cannot be read, or a ``.tsv.gz`` that is not a valid
gzip stream. They mirror what the reference validator hard-codes
(``EMPTY_FILE``, ``NIFTI_HEADER_UNREADABLE``, ``INVALID_GZIP``) and report at the
same severity, but add an explanation and a machine-actionable fix.

They are deliberately conservative: a finding fires only on a genuine problem, and
a symlink (an unfetched git-annex file with no local content) is skipped so an
unavailable file is never reported as empty or unreadable.
"""

from __future__ import annotations

import gzip
from typing import TYPE_CHECKING, Any

from ..issues import Fix, Issue, Severity

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ...types.files import FileTree


def integrity_checks(
    file: FileTree,
    context: Mapping[str, Any],
    *,
    read_headers: bool,
) -> list[Issue]:
    """Run the non-schema structural checks for one file.

    Parameters
    ----------
    file : FileTree
        The file node (its path is used for size, symlink and content reads).
    context : Mapping
        The file's evaluation context (``extension`` and ``nifti_header`` are read).
    read_headers : bool
        Whether NIfTI headers were read; the header check is skipped when False.

    Returns
    -------
    list of Issue
        Structural findings for this file.

    """
    location = file.relative_path

    # A symlink (for example an unfetched git-annex file) has no local content to
    # judge; do not flag it as empty or try to read its header.
    if _is_symlink(file):
        return []

    size = _size(file)
    extension = str(context.get('extension', ''))
    issues: list[Issue] = []

    if size == 0:
        issues.append(
            Issue(
                code='EMPTY_FILE',
                severity=Severity.ERROR,
                location=location,
                message='file is empty (0 bytes): it exists but contains no data',
                suggestion=(
                    'The file name and location are valid, but there is no content. Replace it '
                    'with real data. (Some example datasets ship empty placeholder files; those '
                    'datasets are reported invalid for this reason.)'
                ),
                fix=Fix(action='replace_empty_file', label='Provide real data for this file'),
            )
        )

    # An empty or truncated NIfTI also has an unreadable header; the reference
    # validator reports both, so this is independent of the empty-file check.
    if read_headers and extension.startswith('.nii') and context.get('nifti_header') is None:
        issues.append(
            Issue(
                code='NIFTI_HEADER_UNREADABLE',
                severity=Severity.ERROR,
                location=location,
                message='the NIfTI header could not be read',
                suggestion=(
                    'The file may be truncated, compressed oddly, or not a valid NIfTI. '
                    'Verify it opens in a NIfTI reader.'
                ),
                fix=Fix(action='inspect_file', label='Check that the file is a valid NIfTI'),
            )
        )

    # A non-empty .tsv.gz must be a valid gzip stream (an empty one is already
    # reported as EMPTY_FILE).
    if size > 0 and extension == '.tsv.gz':
        issues.extend(_gzip_integrity(file, location))

    return issues


def _gzip_integrity(file: FileTree, location: str) -> list[Issue]:
    """Confirm a gzipped TSV decompresses (the reference's ``INVALID_GZIP``)."""
    try:
        with file.path_obj.open('rb') as raw, gzip.GzipFile(fileobj=raw) as handle:
            while handle.read(1 << 20):  # decompress fully so truncation is caught
                pass
    except (OSError, EOFError):
        return [
            Issue(
                code='INVALID_GZIP',
                severity=Severity.ERROR,
                location=location,
                message=f'{file.name}: the gzip stream could not be decompressed',
                suggestion=(
                    'The file is named .tsv.gz but is not a valid gzip stream (it may be '
                    'truncated or corrupted). Re-create it with proper gzip compression.'
                ),
            )
        ]
    return []


def _is_symlink(file: FileTree) -> bool:
    try:
        return bool(file.path_obj.is_symlink())
    except (OSError, NotImplementedError):
        return False


def _size(file: FileTree) -> int:
    try:
        return int(file.path_obj.stat().st_size)
    except OSError:
        return 0
