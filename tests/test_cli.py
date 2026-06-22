"""Tests for the full-validation command-line interface."""

from __future__ import annotations

import json
from pathlib import Path

import nibabel as nb
import numpy as np
from typer.testing import CliRunner

from bids_validator.__main__ import app

runner = CliRunner()


def _dataset(tmp_path: Path, *, n_dims: int) -> Path:
    (tmp_path / 'sub-01' / 'anat').mkdir(parents=True)
    (tmp_path / 'dataset_description.json').write_text(
        json.dumps({'Name': 'cli', 'BIDSVersion': '1.11.1'})
    )
    shape = (4, 4, 4) if n_dims == 3 else (4, 4, 4, 2)
    nb.save(
        nb.Nifti1Image(np.zeros(shape, dtype=np.int16), np.eye(4)),
        str(tmp_path / 'sub-01' / 'anat' / 'sub-01_T1w.nii.gz'),
    )
    return tmp_path


def test_cli_version() -> None:
    result = runner.invoke(app, ['--version'])
    assert result.exit_code == 0
    assert 'bids-validator' in result.stdout


def test_cli_valid_dataset_exit_zero(tmp_path: Path) -> None:
    result = runner.invoke(app, [str(_dataset(tmp_path, n_dims=3)), '--show', 'error'])
    assert result.exit_code == 0


def test_cli_invalid_dataset_exit_one_json(tmp_path: Path) -> None:
    # A 4D T1w is an error; JSON output and a non-zero exit code.
    result = runner.invoke(app, [str(_dataset(tmp_path, n_dims=4)), '--output-type', 'json'])
    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data['valid'] is False
    assert any(i['code'] == 'T1W_FILE_WITH_TOO_MANY_DIMENSIONS' for i in data['issues'])


def test_cli_out_dir(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path, n_dims=3)
    out = tmp_path / 'report'
    result = runner.invoke(app, [str(dataset), '--output-type', 'html', '--out-dir', str(out)])
    assert result.exit_code == 0
    written = out / 'bids-validator-report.html'
    assert written.is_file()
    assert written.read_text().startswith('<!doctype html>')


def test_cli_unknown_output_type(tmp_path: Path) -> None:
    result = runner.invoke(app, [str(_dataset(tmp_path, n_dims=3)), '--output-type', 'bogus'])
    assert result.exit_code == 2
