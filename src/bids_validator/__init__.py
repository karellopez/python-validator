"""BIDS validator common Python package."""

from typing import TYPE_CHECKING, Any

from .bids_validator import BIDSValidator

__all__ = ['BIDSValidator', 'validate', 'validate_file']

from . import _version

__version__ = _version.get_versions()['version']

if TYPE_CHECKING:
    from .validation import validate, validate_file


def __getattr__(name: str) -> Any:
    """Lazily expose the full-validation entry points.

    ``validate`` / ``validate_file`` pull in the validation engine (and its
    dependencies), so they are imported on first access rather than at
    ``import bids_validator`` time. This keeps importing the package - and the
    ``is_bids`` filename check that pybids and mne-bids rely on - lightweight.
    """
    if name in ('validate', 'validate_file'):
        from . import validation

        return getattr(validation, name)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
