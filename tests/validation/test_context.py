"""Tests for the engine-facing validation context (associations + EvalContext)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from bidsschematools.types.context import Subject
from bidsschematools.types.namespace import Namespace

from bids_validator.context import Context, Dataset, Sessions
from bids_validator.types.files import FileTree
from bids_validator.validation.associations import build_associations
from bids_validator.validation.context import EvalContext, eval_context, iter_file_contexts
from bids_validator.validation.expressions import evaluate_string


@pytest.fixture
def dataset(tmp_path: Path) -> FileTree:
    """Build a tiny multi-datatype BIDS dataset on the real filesystem."""
    (tmp_path / 'sub-01' / 'func').mkdir(parents=True)
    (tmp_path / 'sub-01' / 'dwi').mkdir(parents=True)
    (tmp_path / 'dataset_description.json').write_text(
        json.dumps({'Name': 'assoc-fixture', 'BIDSVersion': '1.11.1'})
    )
    # Inheritable sidecar at the root (applies to the bold below).
    (tmp_path / 'task-rest_bold.json').write_text(
        json.dumps({'RepetitionTime': 2.0, 'TaskName': 'rest'})
    )
    (tmp_path / 'sub-01' / 'func' / 'sub-01_task-rest_bold.nii.gz').write_bytes(b'')
    (tmp_path / 'sub-01' / 'func' / 'sub-01_task-rest_events.tsv').write_text(
        'onset\tduration\ttrial_type\n1.0\t0.5\ta\n2.0\t0.5\tb\n3.0\t0.5\ta\n'
    )
    (tmp_path / 'sub-01' / 'dwi' / 'sub-01_dwi.nii.gz').write_bytes(b'')
    (tmp_path / 'sub-01' / 'dwi' / 'sub-01_dwi.bval').write_text('0 1000 2000 3000\n')
    (tmp_path / 'sub-01' / 'dwi' / 'sub-01_dwi.bvec').write_text('1 0 0 0\n0 1 0 0\n0 0 1 0\n')
    return FileTree.read_from_filesystem(tmp_path)


def _context_for(tree: FileTree, schema: Namespace, *parts: str) -> Context:
    node = tree
    for part in parts:
        node = node / part
    subject = Subject(Sessions(tree / parts[0])) if parts[0].startswith('sub-') else None
    return Context(node, Dataset(tree, schema), subject)


def test_base_context_variables(dataset: FileTree, schema: Namespace) -> None:
    bold = _context_for(dataset, schema, 'sub-01', 'func', 'sub-01_task-rest_bold.nii.gz')
    assert bold.path == '/sub-01/func/sub-01_task-rest_bold.nii.gz'
    assert bold.entities == {'sub': '01', 'task': 'rest'}
    assert bold.datatype == 'func'
    assert bold.suffix == 'bold'
    assert bold.extension == '.nii.gz'
    assert bold.modality == 'mri'
    assert bold.subject is not None
    # Sidecar comes from the inherited root task-rest_bold.json.
    assert bold.sidecar is not None
    assert bold.sidecar.to_dict() == {'RepetitionTime': 2.0, 'TaskName': 'rest'}


def test_associations_events(dataset: FileTree, schema: Namespace) -> None:
    bold = _context_for(dataset, schema, 'sub-01', 'func', 'sub-01_task-rest_bold.nii.gz')
    assoc = build_associations(bold)
    assert 'events' in assoc
    events = assoc['events']
    assert events['onset'] == ['1.0', '2.0', '3.0']
    assert events['n_rows'] == 3
    assert events['n_cols'] == 3
    assert events['path'] == '/sub-01/func/sub-01_task-rest_events.tsv'
    assert isinstance(events['sidecar'], dict)


def test_associations_bval_bvec(dataset: FileTree, schema: Namespace) -> None:
    dwi = _context_for(dataset, schema, 'sub-01', 'dwi', 'sub-01_dwi.nii.gz')
    assoc = build_associations(dwi)
    assert {'bval', 'bvec'} <= set(assoc)
    assert assoc['bval']['values'] == [0.0, 1000.0, 2000.0, 3000.0]
    assert assoc['bval']['n_rows'] == 1
    assert assoc['bval']['n_cols'] == 4
    assert assoc['bval']['path'] == '/sub-01/dwi/sub-01_dwi.bval'
    assert assoc['bvec']['n_rows'] == 3
    assert assoc['bvec']['n_cols'] == 4
    assert len(assoc['bvec']['values']) == 12


def test_no_associations_for_plain_anat(dataset: FileTree, schema: Namespace) -> None:
    # A bold with no events/bval should not invent associations; here a dwi file
    # gets bval/bvec but never events.
    dwi = _context_for(dataset, schema, 'sub-01', 'dwi', 'sub-01_dwi.nii.gz')
    assert 'events' not in build_associations(dwi)


def test_eval_context_delegates_and_overlays(dataset: FileTree, schema: Namespace) -> None:
    bold = _context_for(dataset, schema, 'sub-01', 'func', 'sub-01_task-rest_bold.nii.gz')
    ctx = eval_context(bold)
    assert isinstance(ctx, EvalContext)
    # Base variables delegate to the underlying Context.
    assert ctx['suffix'] == 'bold'
    assert 'suffix' in ctx
    assert ctx.get('does_not_exist') is None
    # The evaluator can resolve base vars, the sidecar `in`, and associations.
    assert evaluate_string("suffix == 'bold'", ctx) is True
    assert evaluate_string("datatype == 'func'", ctx) is True
    assert evaluate_string("'RepetitionTime' in sidecar", ctx) is True
    assert evaluate_string('length(associations.events.onset)', ctx) == 3
    assert evaluate_string("associations.events.onset[0] == '1.0'", ctx) is True


def test_iter_file_contexts(dataset: FileTree, schema: Namespace) -> None:
    contexts = list(iter_file_contexts(dataset, schema))
    paths = {c.path for c in contexts}
    assert '/dataset_description.json' in paths
    assert '/sub-01/func/sub-01_task-rest_bold.nii.gz' in paths
    assert '/sub-01/dwi/sub-01_dwi.bval' in paths
    # Files under sub-01 carry a subject; directories are not yielded. (Note the
    # root task-rest_bold.json also has suffix 'bold' but sits outside a subject.)
    bold = next(c for c in contexts if c.path == '/sub-01/func/sub-01_task-rest_bold.nii.gz')
    assert bold.subject is not None
    root_sidecar = next(c for c in contexts if c.path == '/task-rest_bold.json')
    assert root_sidecar.subject is None
