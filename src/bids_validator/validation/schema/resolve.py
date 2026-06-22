"""Resolve a schema *selector* to one in-memory schema object.

Every other module in the validator receives one resolved schema and reads its
vocabulary and rules from it (see
:mod:`bids_validator.validation.schema_introspect`), so nothing else ever
branches on the BIDS version. This module is the single place that decides
*which* schema that is.

A selector is one of:

* ``None`` - the default. The schema bundled with the installed
  ``bidsschematools`` (``load_schema()``), which tracks the latest stable BIDS
  version and matches the schema the reference (Deno) validator bundles. Keeping
  this the default means a fresh install validates against current BIDS with no
  configuration.
* a bundled version tag (a BIDS version such as ``"1.11.1"`` or ``"v1.10.0"``) -
  loaded from a dereferenced ``schema.json`` shipped in this package, offline.
  :func:`available_versions` lists what is bundled. Bundling pins validation to a
  known BIDS version regardless of which ``bidsschematools`` is installed.
* a local path - a dereferenced ``schema.json`` file or a schema source
  directory, for a custom or forked schema.
* ``"latest"``, a published version that is not bundled, or a URL - fetched from
  the BIDS specification site and cached on disk (see
  :mod:`bids_validator.validation.schema.cache`).

The returned object is a ``bidsschematools`` ``Namespace``. Loads are cached, so
resolving the same selector repeatedly is free.
"""

from __future__ import annotations

import importlib.resources as resources
import re
from functools import lru_cache
from pathlib import Path

from bidsschematools.schema import load_schema
from bidsschematools.types.namespace import Namespace

from . import cache

SchemaSelector = str | Path | None

#: The newest BIDS version bundled in this package (used by ``--list-schemas``
#: and the docs). The *runtime* default with no selector is the installed
#: ``bidsschematools`` schema, which normally matches this.
DEFAULT_BUNDLED_VERSION = '1.11.1'

#: Matches a bare ``X.Y.Z`` version, with an optional leading ``v``.
_VERSION_RE = re.compile(r'^v?\d+\.\d+\.\d+$')


class SchemaNotAvailable(Exception):
    """Raised when a requested schema cannot be located or loaded."""


def resolve(selector: SchemaSelector = None) -> Namespace:
    """Return the schema named by ``selector`` as a ``Namespace``.

    Parameters
    ----------
    selector : str or pathlib.Path or None, optional
        See the module docstring for the accepted forms. ``None`` (the default)
        resolves to the schema bundled with the installed ``bidsschematools``.

    Returns
    -------
    bidsschematools.types.namespace.Namespace
        The resolved schema.

    Raises
    ------
    SchemaNotAvailable
        If ``selector`` is not a bundled version, a local path, a published
        version, or a reachable URL.

    """
    if selector is None:
        # The installed bidsschematools' bundled schema: the latest stable BIDS
        # version, matching the reference validator's bundled schema.
        return _load_default()

    sel = str(selector)

    # A URL: fetch and cache.
    if cache.is_url(sel):
        return _load(_fetched(sel))

    # A local schema.json file or source directory.
    path = Path(selector)
    if path.exists():
        # Normalise so a str and an equivalent Path share one cached load.
        return _load(str(path.resolve()))

    # A version tag bundled in the package (offline, no network). Accept an
    # optional leading "v" (``v1.11.1`` == ``1.11.1``).
    bundled = _bundled_file(sel.lstrip('v') if _looks_like_version(sel) else sel)
    if bundled is not None:
        return _load(str(bundled))

    # A published version ("latest" or "X.Y.Z" not bundled): fetch and cache.
    url = cache.published_url(sel.lstrip('v') if _looks_like_version(sel) else sel)
    if url is not None:
        return _load(_fetched(url))

    raise SchemaNotAvailable(
        f'schema {selector!r} is not a bundled version, a local path, a published '
        f'version, or a URL. Bundled versions: {", ".join(available_versions()) or "none"}.'
    )


def available_versions() -> list[str]:
    """Return the BIDS versions bundled in this package, sorted ascending."""
    return sorted((p.stem for p in _bundled_dir().glob('*.json')), key=_version_key)


def schema_version(schema: Namespace | None = None) -> str:
    """Return the schema's own structural version (the ``SCHEMA_VERSION`` axis)."""
    return str((schema or resolve()).schema_version)


def bids_version(schema: Namespace | None = None) -> str:
    """Return the BIDS specification version the schema describes."""
    return str((schema or resolve()).bids_version)


def _looks_like_version(selector: str) -> bool:
    """Return ``True`` for ``X.Y.Z`` or ``vX.Y.Z`` strings."""
    return bool(_VERSION_RE.match(selector))


def _fetched(url: str) -> str:
    try:
        return str(cache.fetch(url))
    except Exception as error:  # network / TLS / HTTP
        raise SchemaNotAvailable(f'could not fetch schema from {url}: {error}') from error


@lru_cache(maxsize=1)
def _load_default() -> Namespace:
    """Load and cache the installed ``bidsschematools`` bundled schema."""
    return load_schema()


@lru_cache(maxsize=16)
def _load(path_key: str) -> Namespace:
    """Load and cache a schema from a filesystem path.

    ``load_schema`` accepts both a dereferenced ``schema.json`` file and a schema
    source directory, picking the loader by inspecting the path, so this single
    call covers bundled, local, and forked schemas.
    """
    return load_schema(Path(path_key))


def _bundled_dir() -> Path:
    """Return the filesystem directory holding the bundled schema files."""
    return Path(str(resources.files('bids_validator.validation.schema'))) / 'bundled'


def _bundled_file(version: str) -> Path | None:
    """Return the bundled schema file for ``version``, or ``None`` if not bundled."""
    candidate = _bundled_dir() / f'{version}.json'
    return candidate if candidate.is_file() else None


def _version_key(version: str) -> tuple[int, ...]:
    """Sort key that orders ``1.9.0`` before ``1.10.0`` (numeric, not lexical)."""
    parts: list[int] = []
    for piece in version.split('.'):
        digits = ''.join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


__all__ = [
    'DEFAULT_BUNDLED_VERSION',
    'SchemaNotAvailable',
    'SchemaSelector',
    'available_versions',
    'bids_version',
    'resolve',
    'schema_version',
]
