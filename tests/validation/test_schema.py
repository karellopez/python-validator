"""Tests for schema selection: bundled versions, selectors, and validation.

The validator can validate against the installed ``bidsschematools`` schema (the
default), any of the bundled BIDS versions, or a local schema file/directory.
These tests pin the resolver's behaviour and confirm every bundled version loads
and validates a dataset without crashing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from bidsschematools.types.namespace import Namespace

from bids_validator.validation import (
    SchemaNotAvailable,
    available_versions,
    bids_version,
    resolve,
    schema_version,
    validate,
)

# Every BIDS version shipped under validation/schema/bundled/.
BUNDLED = ['1.8.0', '1.9.0', '1.10.0', '1.10.1', '1.11.0', '1.11.1']


def test_available_versions_lists_bundled() -> None:
    assert available_versions() == BUNDLED  # sorted numerically, not lexically


def test_available_versions_is_numerically_sorted() -> None:
    # The numeric sort must place 1.9.0 before 1.10.0 (lexical sort would not).
    versions = available_versions()
    assert versions.index('1.9.0') < versions.index('1.10.0')


def test_resolve_none_is_installed_default() -> None:
    schema = resolve(None)
    assert isinstance(schema, Namespace)
    # The bundled bidsschematools tracks the latest stable BIDS version.
    assert bids_version(schema) == '1.11.1'


@pytest.mark.parametrize('version', BUNDLED)
def test_resolve_bundled_version(version: str) -> None:
    schema = resolve(version)
    assert bids_version(schema) == version
    assert schema_version(schema)  # a non-empty structural version string


def test_resolve_accepts_leading_v() -> None:
    assert bids_version(resolve('v1.10.0')) == '1.10.0'


def test_resolve_caches_same_object() -> None:
    # Two resolves of the same selector return the cached object (id-stable).
    assert resolve('1.10.0') is resolve('1.10.0')


def test_resolve_local_path(tmp_path: Path) -> None:
    # A dereferenced schema.json copied out of the bundle resolves by path.
    source = resolve('1.11.0')
    target = tmp_path / 'my_schema.json'
    target.write_text(json.dumps(source.to_dict()))
    schema = resolve(str(target))
    assert bids_version(schema) == '1.11.0'


def test_resolve_unknown_selector_raises() -> None:
    with pytest.raises(SchemaNotAvailable):
        resolve('not-a-version-or-path')


@pytest.mark.parametrize('version', BUNDLED)
def test_validate_with_each_bundled_version(tmp_path: Path, version: str) -> None:
    # A minimal dataset validates against every bundled version without crashing.
    (tmp_path / 'dataset_description.json').write_text(
        json.dumps({'Name': 'schema-test', 'BIDSVersion': version})
    )
    (tmp_path / 'sub-01' / 'anat').mkdir(parents=True)
    (tmp_path / 'sub-01' / 'anat' / 'sub-01_T1w.nii.gz').write_bytes(b'')
    report = validate(tmp_path, schema=version, read_headers=False)
    assert report.bids_version == version


def test_validate_accepts_preloaded_namespace(tmp_path: Path) -> None:
    # Passing a resolved Namespace bypasses resolution and is used as-is.
    (tmp_path / 'dataset_description.json').write_text(
        json.dumps({'Name': 'ns', 'BIDSVersion': '1.10.0'})
    )
    schema = resolve('1.10.0')
    report = validate(tmp_path, schema=schema, read_headers=False)
    assert report.bids_version == '1.10.0'
