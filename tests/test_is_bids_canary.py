"""Golden canary for ``BIDSValidator.is_bids``.

``BIDSValidator.is_bids`` is a public contract: pybids, mne-bids and many other
tools depend on it. The full-validation engine must never change its behaviour.

This test runs ``is_bids`` over a fixed, network-free fixture set and asserts the
boolean results are identical to a committed golden snapshot
(``tests/canary/is_bids_golden.json``). The snapshot is generated once from the
upstream ``main`` behaviour and frozen.

To regenerate the snapshot after an *intentional* upstream change to ``is_bids``
(not as part of the full-validation work)::

    python -m tests.test_is_bids_canary

The fixture set deliberately includes many invalid filenames (typos, wrong
directory order, missing entities) so a wide range of the schema-derived
filename regexes are exercised.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bids_validator import BIDSValidator

GOLDEN_PATH = Path(__file__).parent / 'canary' / 'is_bids_golden.json'

# Valid-by-construction filenames across datatypes and levels. Whatever
# ``is_bids`` actually returns is captured in the golden file; the point is
# breadth of coverage, not asserting a hand-labelled expectation here.
_VALID_LIKE = [
    # Top level
    '/dataset_description.json',
    '/README',
    '/README.md',
    '/README.rst',
    '/CHANGES',
    '/LICENSE',
    '/participants.tsv',
    '/participants.json',
    '/samples.tsv',
    '/samples.json',
    '/T1w.json',
    '/task-rest_bold.json',
    '/task-rest_events.json',
    # Associated data
    '/code/',
    '/derivatives/',
    '/sourcedata/',
    '/stimuli/',
    '/code/my_analysis/analysis.py',
    '/derivatives/preproc/sub-01/anat/sub-01_desc-preproc_T1w.nii.gz',
    '/sourcedata/dicom_dir/xyz.dcm',
    '/stimuli/pic.jpg',
    # Subject / session level
    '/sub-01/sub-01_sessions.tsv',
    '/sub-01/sub-01_sessions.json',
    '/sub-01/sub-01_scans.tsv',
    '/sub-01/sub-01_scans.json',
    '/sub-01/ses-1/sub-01_ses-1_scans.tsv',
    # Phenotype
    '/phenotype/measure.tsv',
    '/phenotype/measure.json',
    # anat
    '/sub-01/anat/sub-01_T1w.nii.gz',
    '/sub-01/anat/sub-01_T1w.json',
    '/sub-01/anat/sub-01_T2w.nii.gz',
    '/sub-01/anat/sub-01_FLAIR.nii.gz',
    '/sub-01/anat/sub-01_acq-mprage_T1w.nii.gz',
    '/sub-01/ses-pre/anat/sub-01_ses-pre_run-1_T1w.nii.gz',
    # func
    '/sub-01/func/sub-01_task-rest_bold.nii.gz',
    '/sub-01/func/sub-01_task-rest_bold.json',
    '/sub-01/func/sub-01_task-rest_events.tsv',
    '/sub-01/func/sub-01_task-rest_sbref.nii.gz',
    '/sub-01/ses-1/func/sub-01_ses-1_task-nback_run-1_bold.nii.gz',
    # dwi
    '/sub-01/dwi/sub-01_dwi.nii.gz',
    '/sub-01/dwi/sub-01_dwi.bval',
    '/sub-01/dwi/sub-01_dwi.bvec',
    '/sub-01/dwi/sub-01_dwi.json',
    # fmap
    '/sub-01/fmap/sub-01_magnitude1.nii.gz',
    '/sub-01/fmap/sub-01_phasediff.nii.gz',
    '/sub-01/fmap/sub-01_phasediff.json',
    '/sub-01/fmap/sub-01_dir-AP_epi.nii.gz',
    # eeg
    '/sub-01/eeg/sub-01_task-rest_eeg.edf',
    '/sub-01/eeg/sub-01_task-rest_eeg.json',
    '/sub-01/eeg/sub-01_task-rest_channels.tsv',
    '/sub-01/eeg/sub-01_task-rest_events.tsv',
    '/sub-01/eeg/sub-01_space-CapTrak_electrodes.tsv',
    '/sub-01/eeg/sub-01_coordsystem.json',
    # meg
    '/sub-01/meg/sub-01_task-rest_meg.json',
    '/sub-01/meg/sub-01_task-rest_channels.tsv',
    '/sub-01/meg/sub-01_coordsystem.json',
    # ieeg
    '/sub-01/ieeg/sub-01_task-rest_ieeg.edf',
    '/sub-01/ieeg/sub-01_task-rest_channels.tsv',
    # pet
    '/sub-01/pet/sub-01_pet.nii.gz',
    '/sub-01/pet/sub-01_pet.json',
    # perf
    '/sub-01/perf/sub-01_asl.nii.gz',
    '/sub-01/perf/sub-01_asl.json',
    '/sub-01/perf/sub-01_aslcontext.tsv',
    '/sub-01/perf/sub-01_m0scan.nii.gz',
    # beh
    '/sub-01/beh/sub-01_task-test_beh.tsv',
    '/sub-01/beh/sub-01_task-test_events.tsv',
]

# Invalid filenames (typos, wrong order, missing entities). Drawn from the
# existing regex test suite to exercise many failure branches.
_INVALID_LIKE = [
    '/RADME',
    '/CANGES',
    '/CODE/',
    '/derivatves/',
    '/source/',
    '/.git/',
    '/sub-01/anat/sub-1_T1w.json',
    '/sub-01/anat/sub-01_dwi.nii.gz',
    '/sub-01/anat/sub-01_acq-23_T1W.json',
    '/sub-01/anat/sub-01_acq-23_rec-CSD_T1w.exe',
    '/sub-01/anat/sub-01_run-2-3_T1w.json',
    '/sub-1/anat/sub-01_rec-CSD_run-23_t1w.nii.gz',
    '/sub-01/ses-test/anat/sub-01_ses-retest_T1w.json',
    '/sub-01/01_dwi.bvec',
    '/sub-01/sub_dwi.json',
    '/sub-01/sub-01_run-01_dwi.vec',
    '/sub-01/sub-01_acq_dwi.bval',
    '/sub_01/sub-01_acq-singleband_run-01_dwi.bvec',
    '/sub-01/sub-01_acq-singleband__run-01_dwi.json',
    '/ses-test/sub-01/sub-01_ses-test_acq-singleband_dwi.json',
    '/sub-01/dwi/sub-01_acq_run-01_dwi.bval',
    '/sub_01/ses-test/dwi/sub-01_ses-test_dwi.nii.gz',
    '/sub-01/ses-retest/dwi/sub-01_ses-test_dwi.bvec',
    '/sub-01/ses-test/dwi/sub-01_ses-test_run-01_brain.nii.gz',
    '/sub-01/ses-test/func/sub-01_task-task_rec-rec_run-01_bold.nii.gz',
    '/sub-01/ses-retest/func/sub-01_ses-test_task-task_rec-rec_run-01_sbref.nii.gz',
    '/sub-01/ses-test/func/sub-01_ses-test_task-task_rec-rec_run-01.json',
    '/sub-01/func/sub-01_task-coding_sbref.ni.gz',
    '/sub-01/func/sub-02_task-coding_run-23_bold.nii.gz',
    '/sub-01/ses-test/anat/sub-01_ses-test_task-coding_run-23_bold.nii.gz',
    '/sub-01/beeh/sub-01_task-task_events.tsv',
    '/sub-01/beh/sub-02_task-task_beh.json',
    '/sub-01/beh/sub-01_task-task.tsv.gz',
    '/sub-01/ses-test/fmap/sub-01_ses-test_acq-singleband_run-01_magnitude3.nii.gz',
    '/sub-01/ses-test/fmap/sub-01_ses-test_acq-singleband_run-01.json',
    '/ses-test/fmap/sub-01_ses-test_acq-singleband_dir-dirlabel_run-01_epi.nii',
    '/sub-02/sub-01_sessions.tsv',
    '/sub-01_sessions.tsv',
    '/sub-01/sub-01_sesions.tsv',
    '/measurement_tool_name.tsv',
    '/phentype/measurement_tool_name.josn',
]

FIXTURES: list[str] = sorted(set(_VALID_LIKE) | set(_INVALID_LIKE))


def _generate() -> dict[str, bool]:
    """Compute ``is_bids`` for every fixture, returning a fname -> bool mapping."""
    validator = BIDSValidator()
    return {fname: validator.is_bids(fname) for fname in FIXTURES}


@pytest.fixture(scope='module')
def golden() -> dict[str, bool]:
    """Load the committed golden snapshot."""
    with GOLDEN_PATH.open(encoding='utf-8') as handle:
        return json.load(handle)


def test_golden_covers_exactly_the_fixtures(golden: dict[str, bool]) -> None:
    """The golden file and the fixture list must stay in sync."""
    assert set(golden) == set(FIXTURES)


@pytest.mark.parametrize('fname', FIXTURES)
def test_is_bids_matches_golden(fname: str, golden: dict[str, bool]) -> None:
    """``is_bids`` must return the frozen value for every fixture."""
    assert BIDSValidator().is_bids(fname) == golden[fname]


if __name__ == '__main__':
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    with GOLDEN_PATH.open('w', encoding='utf-8') as handle:
        json.dump(_generate(), handle, indent=2, sort_keys=True)
        handle.write('\n')
    print(f'wrote {GOLDEN_PATH} ({len(FIXTURES)} fixtures)')
