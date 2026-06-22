"""Tests for the schema rule engine (rules.checks evaluation)."""

from __future__ import annotations

import json
from pathlib import Path

import nibabel as nb
import numpy as np
import pytest
from bidsschematools.types.namespace import Namespace

from bids_validator.types.files import FileTree
from bids_validator.validation.context import eval_context, iter_file_contexts
from bids_validator.validation.engine import apply_rules
from bids_validator.validation.issues import Issue, Severity


def _write_nifti(path: Path, *, n_dims: int) -> None:
    shape = (4, 4, 4) if n_dims == 3 else (4, 4, 4, 2)
    img = nb.Nifti1Image(np.zeros(shape, dtype=np.int16), np.eye(4))
    nb.save(img, str(path))


@pytest.fixture
def dataset(tmp_path: Path) -> FileTree:
    """A dataset with one over-dimensional T1w (4D) and one valid T1w (3D)."""
    (tmp_path / 'sub-01' / 'anat').mkdir(parents=True)
    (tmp_path / 'sub-02' / 'anat').mkdir(parents=True)
    (tmp_path / 'dataset_description.json').write_text(
        json.dumps({'Name': 'engine-fixture', 'BIDSVersion': '1.11.1'})
    )
    _write_nifti(tmp_path / 'sub-01' / 'anat' / 'sub-01_T1w.nii.gz', n_dims=4)
    _write_nifti(tmp_path / 'sub-02' / 'anat' / 'sub-02_T1w.nii.gz', n_dims=3)
    return FileTree.read_from_filesystem(tmp_path)


def _issues_for(tree: FileTree, schema: Namespace, path: str) -> list[Issue]:
    for context in iter_file_contexts(tree, schema):
        if context.path == path:
            return apply_rules(schema, eval_context(context))
    raise AssertionError(f'no context found for {path}')


def test_overdimensional_t1w_is_flagged(dataset: FileTree, schema: Namespace) -> None:
    issues = _issues_for(dataset, schema, '/sub-01/anat/sub-01_T1w.nii.gz')
    flagged = [i for i in issues if i.code == 'T1W_FILE_WITH_TOO_MANY_DIMENSIONS']
    assert len(flagged) == 1
    assert flagged[0].severity is Severity.ERROR
    assert flagged[0].location == 'sub-01/anat/sub-01_T1w.nii.gz'
    assert flagged[0].rule is not None
    assert flagged[0].provenance is not None


def test_valid_t1w_not_flagged(dataset: FileTree, schema: Namespace) -> None:
    # The 3D T1w must NOT trip the dimension rule: this is the false-positive
    # guard that the numpy dim array is correctly converted to a native list.
    issues = _issues_for(dataset, schema, '/sub-02/anat/sub-02_T1w.nii.gz')
    codes = {i.code for i in issues}
    assert 'T1W_FILE_WITH_TOO_MANY_DIMENSIONS' not in codes


def test_engine_runs_over_every_file_without_error(dataset: FileTree, schema: Namespace) -> None:
    # The engine must build a context and evaluate rules for every file
    # (including dataset_description.json) without raising.
    for context in iter_file_contexts(dataset, schema):
        result = apply_rules(schema, eval_context(context))
        assert isinstance(result, list)
