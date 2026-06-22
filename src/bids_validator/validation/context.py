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


class EvalContext(Mapping[str, Any]):
    """A schema-keyed mapping the rule engine evaluates expressions against.

    Every base context variable is delegated to a built
    :class:`bids_validator.context.Context` (reusing its FileTree-backed
    loaders). ``associations`` is overlaid here and built lazily; an ``exists``
    resolver, when supplied, is exposed under the evaluator's reserved key.
    """

    def __init__(
        self,
        base: Context,
        *,
        exists_resolver: Callable[[str, str], bool] | None = None,
    ) -> None:
        self._base = base
        self._exists_resolver = exists_resolver
        self._associations: Namespace | None = None
        self._associations_built = False
        self._keys: tuple[str, ...] = tuple(base.schema['meta']['context']['properties'].keys())

    def __getitem__(self, key: str) -> Any:
        if key == 'associations':
            if not self._associations_built:
                self._associations = Namespace(build_associations(self._base))
                self._associations_built = True
            return self._associations
        if key == EXISTS_RESOLVER_KEY:
            if self._exists_resolver is None:
                raise KeyError(key)
            return self._exists_resolver
        try:
            return getattr(self._base, key)
        except AttributeError as exc:
            raise KeyError(key) from exc

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
) -> EvalContext:
    """Wrap a per-file :class:`~bids_validator.context.Context` for the rule engine."""
    return EvalContext(context, exists_resolver=exists_resolver)


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
