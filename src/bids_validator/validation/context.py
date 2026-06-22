"""The engine-facing validation context.

The rule engine evaluates schema expressions (selectors and checks) against a
*context*: a mapping from the names an expression may reference (``suffix``,
``sidecar``, ``nifti_header``, ``associations`` ...) to their values.

Rather than build a second context model, this reuses the package's
:class:`bids_validator.context.Context` for every base variable (so the
FileTree-backed loaders are the single I/O path) and overlays the computed
``associations`` (and, later, the ``exists`` resolver) through a lightweight
:class:`Mapping` view. The view is lazy: associations are built only when a rule
actually reads them.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Any

from bidsschematools.types.context import Subject
from bidsschematools.types.namespace import Namespace

from ..context import Context, Dataset, Sessions
from .associations import build_associations
from .expressions import EXISTS_RESOLVER_KEY

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..types.files import FileTree

__all__ = ['EvalContext', 'eval_context', 'iter_file_contexts']


def _nifti_header_to_native(header: Any) -> dict[str, Any]:
    """Convert the context NiftiHeader to native Python types for the evaluator.

    The package's ``load_nifti_header`` keeps numpy arrays and tuples, but the
    schema expression language treats these fields as arrays of plain numbers.
    Converting here keeps numpy out of the evaluator, where an un-indexable numpy
    array would silently make ``nifti_header.dim[0]`` null and produce a false
    positive on every NIfTI.

    Parameters
    ----------
    header : Any
        A ``bidsschematools.types.context.NiftiHeader``.

    Returns
    -------
    dict
        The header fields the schema references, as native lists / numbers.

    """
    return {
        'dim': [int(x) for x in header.dim],
        'pixdim': [float(x) for x in header.pixdim],
        'shape': [int(x) for x in header.shape],
        'voxel_sizes': [float(x) for x in header.voxel_sizes],
        'qform_code': int(header.qform_code),
        'sform_code': int(header.sform_code),
        'xyzt_units': {'xyz': header.xyzt_units.xyz, 't': header.xyzt_units.t},
        'axis_codes': list(header.axis_codes),
        'mrs': header.mrs,
    }


class EvalContext(Mapping[str, Any]):
    """A schema-keyed mapping the rule engine evaluates expressions against.

    Every base context variable is delegated to a built
    :class:`bids_validator.context.Context` (reusing its FileTree-backed
    loaders). Three variables are adapted so the expression language only ever
    sees native types: ``associations`` is overlaid and built lazily;
    ``nifti_header`` is converted from numpy to native lists (an unreadable header
    degrades to null rather than raising); ``columns`` are converted from tuples
    to lists. An ``exists`` resolver, when supplied, is exposed under the
    evaluator's reserved key. Resolved values are cached per key (the context is
    immutable for the duration of a file's evaluation).
    """

    def __init__(
        self,
        base: Context,
        *,
        exists_resolver: Callable[[str, str], bool] | None = None,
        read_headers: bool = True,
    ) -> None:
        self._base = base
        self._exists_resolver = exists_resolver
        self._read_headers = read_headers
        self._keys: tuple[str, ...] = tuple(base.schema['meta']['context']['properties'].keys())
        self._cache: dict[str, Any] = {}

    def __getitem__(self, key: str) -> Any:
        if key == EXISTS_RESOLVER_KEY:
            if self._exists_resolver is None:
                raise KeyError(key)
            return self._exists_resolver
        if key in self._cache:
            return self._cache[key]
        value: Any
        if key == 'associations':
            value = Namespace(build_associations(self._base))
        elif key == 'nifti_header':
            value = self._nifti_header()
        elif key == 'columns':
            value = self._columns()
        elif key == 'sidecar' and self._base.extension == '.json':
            # A JSON file is itself a sidecar; per the inheritance principle it has
            # no sidecar of its own, so recording rules that read `sidecar` do not
            # apply to it (this is also what avoids double-reporting on a data
            # file's metadata once via the data file and once via its sidecar).
            value = Namespace()
        elif key == 'entities':
            # FileParts records a no-hyphen filename token (for example the
            # "dataset" in dataset_description.json) as an entity with a None
            # value. Those are not BIDS entities; drop them so rules see only real
            # key-label entities (an empty label "" is kept; it is its own finding).
            value = {k: v for k, v in self._base.entities.items() if v is not None}
        else:
            try:
                value = getattr(self._base, key)
            except AttributeError as exc:
                raise KeyError(key) from exc
        self._cache[key] = value
        return value

    def _nifti_header(self) -> dict[str, Any] | None:
        if not self._read_headers:
            return None  # header checks select on `nifti_header != null`, so they skip
        try:
            header = self._base.nifti_header
        except Exception:  # noqa: BLE001 - an unreadable header degrades to null
            return None
        return _nifti_header_to_native(header) if header is not None else None

    def _columns(self) -> dict[str, list[Any]] | None:
        columns = self._base.columns
        if columns is None:
            return None
        return {name: list(values) for name, values in columns.items()}

    def __iter__(self) -> Iterator[str]:
        return iter(self._keys)

    def __len__(self) -> int:
        return len(self._keys)

    @property
    def base(self) -> Context:
        """The underlying per-file context."""
        return self._base


def eval_context(
    context: Context,
    *,
    exists_resolver: Callable[[str, str], bool] | None = None,
    read_headers: bool = True,
) -> EvalContext:
    """Wrap a per-file :class:`~bids_validator.context.Context` for the rule engine.

    When no resolver is supplied, one is built from the context so the schema's
    ``exists`` function can resolve referenced paths against the dataset tree.
    """
    if exists_resolver is None:
        exists_resolver = _make_exists_resolver(context)
    return EvalContext(context, exists_resolver=exists_resolver, read_headers=read_headers)


def _make_exists_resolver(base: Context) -> Callable[[str, str], bool]:
    """Build the ``(item, rule) -> bool`` resolver the schema ``exists`` function uses.

    Resolves a referenced path relative to the dataset root, the subject, the
    stimuli directory, or the file's own directory, per the ``rule`` mode, and
    reports whether it exists in the dataset tree.
    """
    root = base.dataset.tree
    parent = base.file.parent.relative_path.rstrip('/') if base.file.parent is not None else ''
    sub = base.entities.get('sub') or ''

    def resolver(item: Any, rule: str = 'dataset') -> bool:
        if not isinstance(item, str):
            return False
        if rule == 'bids-uri':
            return item.startswith('bids:')
        if rule == 'file':
            target = f'{parent}/{item}' if parent else item
        elif rule == 'subject':
            target = f'sub-{sub}/{item}' if sub else item
        elif rule == 'stimuli':
            target = f'stimuli/{item}'
        else:  # dataset
            target = item
        return target.lstrip('/') in root

    return resolver


def iter_file_contexts(tree: FileTree, schema: Namespace) -> Iterator[Context]:
    """Yield a :class:`~bids_validator.context.Context` for every file in ``tree``.

    Directories are walked depth-first; the enclosing ``sub-*`` directory seeds a
    :class:`~bidsschematools.types.context.Subject` so each file's context knows
    its subject (mirrors the walk in ``bids_validator.__main__``).

    Parameters
    ----------
    tree : FileTree
        The dataset root.
    schema : Namespace
        The BIDS schema to validate against.

    Yields
    ------
    Context
        One context per file (directories are not yielded).

    """
    dataset = Dataset(tree, schema)
    yield from _walk(tree, dataset, None)


def _walk(tree: FileTree, dataset: Dataset, subject: Subject | None) -> Iterator[Context]:
    if subject is None and tree.name.startswith('sub-'):
        subject = Subject(Sessions(tree))
    for child in tree.children.values():
        if child.is_dir:
            yield from _walk(child, dataset, subject)
        else:
            yield Context(child, dataset, subject)
