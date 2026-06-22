"""Full, schema-driven BIDS dataset validation.

This subpackage is the engine that validates dataset *content* (sidecar fields,
tabular columns, associations, dataset-level rules ...), as opposed to the
filename-only :class:`bids_validator.BIDSValidator.is_bids` check. It is built by
porting the ``bidsval`` engine onto this package's :class:`~bids_validator.types.files.FileTree`
and ``bidsschematools`` foundations.

The public result types are re-exported here; higher-level entry points
(``validate`` / ``validate_file`` / ``validate_dataset``) are added as the engine
lands.
"""

from __future__ import annotations

from .context import EvalContext, eval_context, iter_file_contexts
from .engine import apply_rules
from .expressions import EvaluationError, UnknownFunction, evaluate, evaluate_string
from .issues import DatasetIssues, Fix, Issue, RuleProvenance, Severity
from .render import to_html, to_json, to_sarif, to_text
from .report import FileVerdict, ValidationReport
from .schema import (
    SchemaNotAvailable,
    SchemaSelector,
    available_versions,
    bids_version,
    resolve,
    schema_version,
)
from .validate import validate, validate_file

__all__ = [
    'DatasetIssues',
    'EvalContext',
    'EvaluationError',
    'FileVerdict',
    'Fix',
    'Issue',
    'RuleProvenance',
    'SchemaNotAvailable',
    'SchemaSelector',
    'Severity',
    'UnknownFunction',
    'ValidationReport',
    'apply_rules',
    'available_versions',
    'bids_version',
    'eval_context',
    'evaluate',
    'evaluate_string',
    'iter_file_contexts',
    'resolve',
    'schema_version',
    'to_html',
    'to_json',
    'to_sarif',
    'to_text',
    'validate',
    'validate_file',
]
