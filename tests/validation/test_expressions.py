"""Expression-evaluator tests.

The centerpiece is the schema's own ``meta.expression_tests``: the BIDS schema
ships a list of ``{'expression': ..., 'result': ...}`` cases that define the
expected behaviour of the expression language. Running them here means our
evaluator is checked against the authoritative source, and stays correct as the
schema evolves (a newer schema simply brings more cases).

Beyond the oracle we add a few targeted cases for behaviour the oracle does not
exercise directly: context-variable resolution and a realistic check expression.
"""

from __future__ import annotations

import json

import pytest
from bidsschematools import data

from bids_validator.validation.expressions import UnknownFunction, evaluate_string


def _oracle_cases() -> list[tuple[str, object]]:
    schema = json.loads(data.load.readable('schema.json').read_text())
    return [(case['expression'], case['result']) for case in schema['meta']['expression_tests']]


ORACLE = _oracle_cases()


@pytest.mark.parametrize(('expression', 'expected'), ORACLE, ids=[c[0] for c in ORACLE])
def test_schema_expression_oracle(expression: str, expected: object) -> None:
    # The only context name the oracle references is ``sidecar`` (an object with
    # no ``MissingValue`` key, so ``sidecar.MissingValue`` resolves to null).
    context = {'sidecar': {}}
    assert evaluate_string(expression, context) == expected


def test_oracle_is_non_trivial() -> None:
    # Guard against silently testing nothing if the schema layout changes.
    assert len(ORACLE) >= 50


def test_identifier_resolves_from_context() -> None:
    context = {'suffix': 'T1w', 'datatype': 'anat'}
    assert evaluate_string("suffix == 'T1w'", context) is True
    assert evaluate_string("datatype == 'func'", context) is False


def test_missing_identifier_is_null() -> None:
    assert evaluate_string('nonexistent', {}) is None
    # null compared to a value is False, so a check on an absent field is safe.
    assert evaluate_string("nonexistent == 'x'", {}) is False


def test_nested_property_and_index() -> None:
    # Mirrors a real schema check: a T1w must have exactly three dimensions.
    context = {'suffix': 'T1w', 'nifti_header': {'dim': [3, 256, 256, 170]}}
    assert evaluate_string('nifti_header.dim[0] == 3', context) is True
    assert evaluate_string('nifti_header.dim[0] == 4', context) is False


def test_missing_nested_path_propagates_null() -> None:
    # No nifti_header in context -> the whole path is null, not an error.
    assert evaluate_string('nifti_header.dim[0]', {}) is None


def test_selector_chain_with_and() -> None:
    context = {'suffix': 'T1w', 'nifti_header': {'dim': [3]}}
    assert evaluate_string("suffix == 'T1w' && nifti_header != null", context) is True
    assert evaluate_string("suffix == 'bold' && nifti_header != null", context) is False


def test_unknown_function_raises_distinct_error() -> None:
    # A newer-than-engine schema may call a function we do not know; the
    # evaluator must signal that distinctly so callers can skip rather than crash.
    with pytest.raises(UnknownFunction):
        evaluate_string('brandnewfunc(1, 2)', {})
