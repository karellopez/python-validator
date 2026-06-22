# ruff: noqa: D100
# ruff: noqa: D103

try:
    import typer
except ImportError:
    print('⚠️ CLI dependencies are not installed. Install "bids_validator[cli]"')
    raise SystemExit(1) from None

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

from bidsschematools.schema import load_schema
from bidsschematools.types.context import Subject
from bidsschematools.types.namespace import Namespace

from bids_validator import BIDSValidator
from bids_validator.context import Context, Dataset, Sessions
from bids_validator.types.files import FileTree
from bids_validator.validation import Severity, validate
from bids_validator.validation.render import EXTENSIONS, RENDERERS

app = typer.Typer()


def is_subject_dir(tree: FileTree) -> bool:
    return tree.name.startswith('sub-')


def walk(tree: FileTree, dataset: Dataset, subject: Subject | None = None) -> Iterator[Context]:
    """Iterate over children of a FileTree and check if they are a directory or file.

    If it's a directory then run again recursively, if it's a file file check the file name is
    BIDS compliant.

    Parameters
    ----------
    tree : FileTree
        FileTree object to iterate over
    dataset: Dataset
        Object containing properties for entire dataset
    subject: Subject
        object containing subject and session info

    """
    if subject is None and is_subject_dir(tree):
        subject = Subject(Sessions(tree))

    for child in tree.children.values():
        if child.is_dir:
            yield from walk(child, dataset, subject)
        else:
            yield Context(child, dataset, subject)


def validate_filenames(tree: FileTree, schema: Namespace) -> bool:
    """Check that every file path is a BIDS-compliant filename (legacy is_bids mode).

    Parameters
    ----------
    tree : FileTree
        Full FileTree object to iterate over and check
    schema : Namespace
        Schema object to validate dataset against

    Returns
    -------
    bool
        True when every filename is BIDS-compliant.

    """
    validator = BIDSValidator()
    dataset = Dataset(tree, schema)
    ok = True
    for file in walk(tree, dataset):
        if not validator.is_bids(file.path):
            print(f'{file.path} is not a valid bids filename')
            ok = False
    return ok


def show_version() -> None:
    """Show bids-validator version."""
    from . import __version__

    print(f'bids-validator {__version__} (Python {sys.version.split()[0]})')


def version_callback(value: bool) -> None:
    """Run the callback for CLI version flag.

    Parameters
    ----------
    value : bool
        value received from --version flag

    Raises
    ------
    typer.Exit
        Exit without any errors

    """
    if value:
        show_version()
        raise typer.Exit()


def _severity_filter(show: str) -> set[Severity]:
    if show == 'error':
        return {Severity.ERROR}
    if show == 'warning':
        return {Severity.WARNING}
    return {Severity.ERROR, Severity.WARNING, Severity.IGNORE}


@app.command()
def main(
    bids_path: str,
    schema_path: str | None = None,
    output_type: Annotated[
        str,
        typer.Option('--output-type', help='Output format: text, json, sarif or html.'),
    ] = 'text',
    out_dir: Annotated[
        str | None,
        typer.Option('--out-dir', help='Write the report into this directory instead of stdout.'),
    ] = None,
    show: Annotated[
        str,
        typer.Option('--show', help='Which severities to report: error, warning or all.'),
    ] = 'all',
    no_headers: Annotated[
        bool,
        typer.Option('--no-headers', help='Skip reading NIfTI headers (faster).'),
    ] = False,
    max_rows: Annotated[
        int,
        typer.Option('--max-rows', help='Maximum number of TSV rows to scan per table.'),
    ] = 1000,
    filenames_only: Annotated[
        bool,
        typer.Option('--filenames-only', help='Only check filenames (the legacy is_bids check).'),
    ] = False,
    verbose: Annotated[bool, typer.Option('--verbose', '-v', help='Show verbose output')] = False,
    version: Annotated[
        bool,
        typer.Option('--version', help='Show version', callback=version_callback, is_eager=True),
    ] = False,
) -> None:
    if verbose:
        show_version()

    schema = load_schema(schema_path) if schema_path else None

    if filenames_only:
        root = FileTree.read_from_filesystem(bids_path)
        ok = validate_filenames(root, schema if schema is not None else load_schema())
        raise typer.Exit(code=0 if ok else 1)

    renderer = RENDERERS.get(output_type)
    if renderer is None:
        print(f'Unknown output type {output_type!r}; use one of: {", ".join(RENDERERS)}.')
        raise typer.Exit(code=2)

    report = validate(bids_path, schema=schema, read_headers=not no_headers, max_rows=max_rows)
    rendered = renderer(report.filtered(_severity_filter(show)))

    if out_dir:
        directory = Path(out_dir)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f'bids-validator-report.{EXTENSIONS.get(output_type, "txt")}'
        target.write_text(rendered, encoding='utf-8')
        print(f'Wrote {target}')
    else:
        print(rendered)

    raise typer.Exit(code=0 if report.is_valid else 1)


if __name__ == '__main__':
    app()
