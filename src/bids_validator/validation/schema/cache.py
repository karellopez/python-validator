"""Fetch and cache ``schema.json`` from a URL or a published BIDS version.

This lets the validator use a schema that is not bundled in the package: a
specific published version (``--schema 1.7.0``), the development tip
(``--schema latest``), or any URL (``--schema https://.../schema.json``). Each
fetch is cached on disk, so repeated runs and offline reuse cost nothing.

The cache is intentionally tiny and dependency-free (only the standard library),
and honours ``XDG_CACHE_HOME`` when set.
"""

from __future__ import annotations

import hashlib
import os
import re
import ssl
import urllib.request
from pathlib import Path

#: Where fetched schemas are cached (``$XDG_CACHE_HOME`` or ``~/.cache``).
_CACHE_DIR = (
    Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'bids-validator' / 'schemas'
)

#: The BIDS specification publishes a dereferenced ``schema.json`` per version.
_PUBLISHED = 'https://bids-specification.readthedocs.io/en/{ref}/schema.json'
_VERSION_RE = re.compile(r'^\d+\.\d+\.\d+$')


def is_url(selector: str) -> bool:
    """Return ``True`` if ``selector`` looks like an HTTP(S) URL."""
    return selector.startswith(('http://', 'https://'))


def published_url(selector: str) -> str | None:
    """Return the canonical ``schema.json`` URL for a version tag or ``"latest"``.

    ``"latest"`` maps to the development tip; ``"X.Y.Z"`` maps to the ``vX.Y.Z``
    published schema. Anything else returns ``None`` (not a published reference).
    """
    if selector == 'latest':
        return _PUBLISHED.format(ref='latest')
    if _VERSION_RE.match(selector):
        return _PUBLISHED.format(ref=f'v{selector}')
    return None


def fetch(url: str) -> Path:
    """Download ``url`` to the cache (once) and return the local file path.

    The cache key is a hash of the URL, so two different URLs never collide and
    the same URL is only fetched once. The underlying network/TLS/HTTP exception
    propagates on failure, so the caller can turn it into a clear message.
    """
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(url.encode('utf-8')).hexdigest()[:16]  # noqa: S324 - cache key, not security
    dest = _CACHE_DIR / f'{key}.json'
    if dest.is_file():
        return dest
    request = urllib.request.Request(url, headers={'User-Agent': 'bids-validator'})  # noqa: S310
    with urllib.request.urlopen(request, timeout=30, context=_ssl_context()) as response:  # noqa: S310
        data = response.read()
    dest.write_bytes(data)
    return dest


def _ssl_context() -> ssl.SSLContext:
    """Return an SSL context, preferring ``certifi``'s CA bundle when available.

    Using ``certifi`` avoids the common macOS "unable to get local issuer
    certificate" failure; the system default is used when ``certifi`` is absent.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001  # pragma: no cover - certifi is normally present
        return ssl.create_default_context()
