"""Bespoke rule families layered on top of the schema rule engine.

The engine in :mod:`bids_validator.validation.engine` evaluates the schema's
``rules.checks``. The modules here add the checks that are not expressed as schema
boolean rules: structural integrity (this phase), and - in later phases - filename
rules, sidecar-field presence, tabular columns, value types and dataset-level
checks. Each is a pure function of a file's context that returns a list of issues.
"""

from __future__ import annotations

from .filenames import filename_checks
from .inheritance import inheritance_checks
from .integrity import integrity_checks

__all__ = ['filename_checks', 'inheritance_checks', 'integrity_checks']
