"""Schema loading and version selection.

This subpackage is the single place that knows how to *find* a BIDS schema. The
rest of the validator receives one resolved schema object and reads all
vocabulary and rules from it, so it never branches on the BIDS version. That
isolation is what lets a user point the validator at any schema (the installed
default, a bundled version, or a local/forked schema) and have everything
downstream work unchanged.
"""

from __future__ import annotations

from .resolve import (
    DEFAULT_BUNDLED_VERSION,
    SchemaNotAvailable,
    SchemaSelector,
    available_versions,
    bids_version,
    resolve,
    schema_version,
)

__all__ = [
    'DEFAULT_BUNDLED_VERSION',
    'SchemaNotAvailable',
    'SchemaSelector',
    'available_versions',
    'bids_version',
    'resolve',
    'schema_version',
]
