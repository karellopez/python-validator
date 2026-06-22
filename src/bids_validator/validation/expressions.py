"""The BIDS schema expression language: evaluation.

Parsing a schema expression into an abstract syntax tree is already solved by
``bidsschematools.expressions.parse``. What the ecosystem lacks - and what this
module provides - is an *evaluator* that walks that tree against a runtime
context and returns a value.

* :func:`evaluate` walks an already-parsed tree.
* :func:`evaluate_string` parses then evaluates (parsing is memoized).

The helper functions and value coercions (JavaScript-style truthiness and null
propagation, and the schema built-ins ``exists`` / ``match`` / ``sorted`` ...)
live in the same module so the expression language is one self-contained unit.
Their semantics mirror the canonical JavaScript implementation in the reference
validator (``bids-validator``'s ``schema/expressionLanguage.ts``) and are pinned
by the schema's own ``meta.expression_tests``.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from functools import cmp_to_key, lru_cache
from typing import Any

from bidsschematools.expressions import (
    Array,
    BinOp,
    Element,
    Function,
    Object,
    Property,
    RightOp,
    parse,
)

Context = Mapping[str, Any]

# A resolver the host can install on the context under this key to give ``exists``
# access to the file tree. Until the file-tree layer is wired in, ``exists``
# reports "not found" (0), which matches the pure-expression test cases.
EXISTS_RESOLVER_KEY = '__exists_resolver__'

# Logical operators short-circuit and therefore must not eagerly evaluate their
# right-hand side; everything else uses the eager binary path.
_LOGICAL_OPS = frozenset({'&&', '||'})

# Arithmetic and ordering operators. Across the entire BIDS schema these only
# ever apply to numbers: tabular (string) columns are funneled through
# min/max/count/length first, and a missing field null-propagates. The engine
# evaluates hundreds of expressions against every file, so a malformed dataset (a
# number stored as a string, a zero denominator) must degrade to null rather than
# raise. These two groups implement that: coerce when sensible, return null
# instead of crashing.
_ARITHMETIC_OPS = frozenset({'-', '*', '/', '%', '**'})
_ORDERING_OPS = frozenset({'<', '<=', '>', '>='})


class EvaluationError(Exception):
    """Raised when an expression cannot be evaluated."""


class UnknownFunction(EvaluationError):
    """Raised when an expression calls a function the evaluator does not know.

    Surfacing this distinctly lets callers (for example a rule engine) treat an
    unfamiliar function in a newer-than-engine schema as a skipped construct
    rather than a hard failure.
    """


# ---------------------------------------------------------------------------
# Value model: truthiness and JavaScript-style coercions
# ---------------------------------------------------------------------------


def truthy(value: Any) -> bool:
    """Return JavaScript truthiness for ``value``.

    Note the differences from Python: empty lists and dicts are truthy; the
    empty string, ``0``, ``NaN`` and ``None`` are falsy.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0 and not (isinstance(value, float) and math.isnan(value))
    if isinstance(value, str):
        return len(value) > 0
    # Arrays, objects and any other reference type are truthy in JavaScript.
    return True


def js_string(value: Any) -> str:
    """Coerce a value to a string the way JavaScript's ``String()`` would.

    Used where the schema relies on stringification, for example building a
    regular expression out of a non-string argument.
    """
    if value is None:
        return 'null'
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    if isinstance(value, float):
        if math.isnan(value):
            return 'NaN'
        if math.isinf(value):
            return 'Infinity' if value > 0 else '-Infinity'
        if value.is_integer():
            return str(int(value))  # JavaScript prints 1.0 as "1"
    return str(value)


def to_number(value: Any) -> float:
    """Coerce a value to a number the way JavaScript's ``Number()`` would.

    Non-numeric strings (such as the BIDS ``n/a``) become ``NaN`` so callers can
    filter them out, matching the reference ``min`` / ``max`` / ``sorted``
    behaviour.
    """
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return 0.0
    if isinstance(value, str):
        text = value.strip()
        if text == '':
            return 0.0
        try:
            return float(text)
        except ValueError:
            return math.nan
    return math.nan


def _simplify_number(number: float) -> float | int:
    """Return an ``int`` for integral floats, else the float unchanged.

    Keeps results like ``min([-1, 'n/a', 1])`` reading as ``-1`` rather than
    ``-1.0`` without changing equality.
    """
    if number.is_integer():
        return int(number)
    return number


# ---------------------------------------------------------------------------
# Built-in functions
# ---------------------------------------------------------------------------


def type_of(value: Any) -> str:
    """Return the schema ``type`` function result: a JavaScript-style type tag."""
    if isinstance(value, list):
        return 'array'
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, (int, float)):
        return 'number'
    if isinstance(value, str):
        return 'string'
    return 'object'


def intersects(left: Any, right: Any) -> Any:
    """Return the intersection of two lists, or ``False`` when there is none.

    Single values are tolerated by treating them as one-element lists. The order
    of the result follows the longer input, matching the reference behaviour.
    """
    a = left if isinstance(left, list) else [left]
    b = right if isinstance(right, list) else [right]
    if len(a) < len(b):
        a, b = b, a
    if len(b) == 0:
        return False
    # Membership via ``==`` (not hashing) so unhashable or mixed values are safe.
    intersection = [item for item in a if item in b]
    return intersection if intersection else False


def match(target: Any, pattern: Any) -> Any:
    """Search ``target`` for ``pattern`` (regex). A ``null`` target yields ``null``.

    A non-string ``pattern`` is stringified first (so ``null`` becomes the
    literal pattern ``'null'``), matching the reference implementation.
    """
    if target is None:
        return None
    try:
        return re.search(js_string(pattern), js_string(target)) is not None
    except re.error:  # an invalid pattern degrades to null rather than raising
        return None


def substr(value: Any, start: Any, end: Any) -> Any:
    """Return the substring from ``start`` (inclusive) to ``end`` (exclusive).

    Any ``null`` argument yields ``null``.
    """
    if value is None or start is None or end is None:
        return None
    try:
        return js_string(value)[int(start) : int(end)]
    except (TypeError, ValueError):  # non-integer bounds degrade to null
        return None


def min_(values: Any) -> Any:
    """Return the minimum of a list, ignoring non-numbers (for example ``'n/a'``).

    ``null`` yields ``null``.
    """
    numbers = _numeric_entries(values)
    if numbers is None or not numbers:
        return None
    return _simplify_number(min(numbers))


def max_(values: Any) -> Any:
    """Return the maximum of a list, ignoring non-numbers (for example ``'n/a'``).

    ``null`` yields ``null``.
    """
    numbers = _numeric_entries(values)
    if numbers is None or not numbers:
        return None
    return _simplify_number(max(numbers))


def _numeric_entries(values: Any) -> list[float] | None:
    """Coerce ``values`` to numbers, dropping ``NaN``; ``None`` if input is null."""
    if values is None:
        return None
    items = values if isinstance(values, list) else [values]
    return [n for n in (to_number(v) for v in items) if not math.isnan(n)]


def length(value: Any) -> Any:
    """Return the length of a list or string; ``null`` for anything else."""
    if isinstance(value, (list, str)):
        return len(value)
    return None


def unique(values: Any) -> Any:
    """Return a first-seen-order de-duplication of a list. ``null`` -> ``null``.

    Uses ``==`` for equality, so ``1`` and ``1.0`` collapse and the first
    occurrence (with its type) is kept.
    """
    if values is None:
        return None
    seen: list[Any] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def count(values: Any, target: Any) -> int:
    """Return the number of elements in ``values`` equal to ``target``."""
    if not isinstance(values, list):
        return 0
    return sum(1 for value in values if value == target)


def index(values: Any, item: Any) -> Any:
    """Return the index of the first ``item`` in ``values``, or ``null`` if absent."""
    if not isinstance(values, list):
        return None
    try:
        return values.index(item)
    except ValueError:
        return None


def allequal(left: Any, right: Any) -> bool:
    """Return True if both are lists of equal length with element-wise equality."""
    if not isinstance(left, list) or not isinstance(right, list):
        return False
    return len(left) == len(right) and all(a == b for a, b in zip(left, right, strict=False))


def sorted_(values: Any, method: str = 'auto') -> Any:
    """Return a new sorted list. ``null`` -> ``null``.

    ``method`` selects the comparison: ``'numeric'`` (numeric order, with
    non-numbers left in place), ``'lexical'`` (string order), or ``'auto'``
    (natural ordering of the values). A stable sort is used so that entries the
    comparison treats as equal keep their original order, matching the reference.
    """
    if not isinstance(values, list):
        return None  # null, or any non-list input, has nothing to sort
    if method == 'numeric':
        return _numeric_sorted(values)
    comparator = _lexical_comparator if method == 'lexical' else _auto_comparator
    return sorted(values, key=cmp_to_key(comparator))


def _numeric_sorted(values: list[Any]) -> list[Any]:
    """Sort the numeric entries of ``values`` while non-numbers hold their slots.

    Non-numeric entries (for example the BIDS ``'n/a'``) keep their original
    absolute position; the numeric entries are sorted (stably, by numeric value)
    and placed back into the remaining slots in order. This matches the reference
    behaviour for ``sorted(..., 'numeric')``.

    A comparator that maps every ``NaN`` comparison to "equal" is *not* a valid
    total order, so a ``cmp_to_key`` sort gives an algorithm-dependent result -
    it happens to match the reference under CPython 3.10's merge policy but not
    under the 3.11+ policy. This position-preserving implementation is
    deterministic across Python versions.
    """
    positions = [i for i, value in enumerate(values) if not math.isnan(to_number(value))]
    ordered = sorted((values[i] for i in positions), key=to_number)
    result = list(values)
    for position, value in zip(positions, ordered, strict=True):
        result[position] = value
    return result


def _lexical_comparator(a: Any, b: Any) -> int:
    sa, sb = js_string(a), js_string(b)
    return (sa > sb) - (sa < sb)


def _auto_comparator(a: Any, b: Any) -> int:
    try:
        return int(a > b) - int(a < b)
    except TypeError:  # mixed types: fall back to string comparison
        sa, sb = js_string(a), js_string(b)
        return (sa > sb) - (sa < sb)


def exists(values: Any, rule: str = 'dataset', context: Mapping[str, Any] | None = None) -> int:
    """Count how many of ``values`` exist as paths, per the given ``rule`` mode.

    ``rule`` is one of ``'dataset'``, ``'subject'``, ``'stimuli'``,
    ``'bids-uri'`` or ``'file'``. Resolution needs a file tree, which the host
    supplies by installing a callable on the context under
    :data:`EXISTS_RESOLVER_KEY`. Without it (or for ``null`` / empty input) the
    function reports ``0``, which is the correct answer for the pure-expression
    cases and a safe default until the file-tree layer is wired in.
    """
    if values is None:
        return 0
    items = values if isinstance(values, list) else [values]
    if not items:
        return 0
    resolver = None
    if isinstance(context, Mapping):
        resolver = context.get(EXISTS_RESOLVER_KEY)
    if resolver is None:
        return 0
    return sum(1 for item in items if resolver(item, rule))


# ---------------------------------------------------------------------------
# Function dispatch
# ---------------------------------------------------------------------------

# Each entry receives the already-evaluated argument list and the context.
# Keeping a single table makes the supported function set explicit and easy to
# audit against the schema.
_FUNCTIONS: dict[str, Callable[[list[Any], Mapping[str, Any] | None], Any]] = {
    'type': lambda args, ctx: type_of(args[0]),
    'intersects': lambda args, ctx: intersects(args[0], args[1]),
    'match': lambda args, ctx: match(args[0], args[1]),
    'substr': lambda args, ctx: substr(args[0], args[1], args[2]),
    'min': lambda args, ctx: min_(args[0]),
    'max': lambda args, ctx: max_(args[0]),
    'length': lambda args, ctx: length(args[0]),
    'unique': lambda args, ctx: unique(args[0]),
    'count': lambda args, ctx: count(args[0], args[1]),
    'index': lambda args, ctx: index(args[0], args[1]),
    'allequal': lambda args, ctx: allequal(args[0], args[1]),
    'sorted': lambda args, ctx: sorted_(args[0], args[1] if len(args) > 1 else 'auto'),
    'exists': lambda args, ctx: exists(args[0], args[1] if len(args) > 1 else 'dataset', ctx),
}


def is_known(name: str) -> bool:
    """Return whether ``name`` is a built-in the evaluator can call."""
    return name in _FUNCTIONS


def call(name: str, args: list[Any], context: Mapping[str, Any] | None) -> Any:
    """Invoke built-in ``name`` with already-evaluated ``args``.

    Raises :class:`KeyError` for an unknown function; the evaluator turns that
    into its own, more descriptive error so an unfamiliar function in a newer
    schema degrades gracefully rather than crashing the run.
    """
    return _FUNCTIONS[name](args, context)


# ---------------------------------------------------------------------------
# Evaluator entry points
# ---------------------------------------------------------------------------


def evaluate_string(expression: str, context: Context) -> Any:
    """Parse ``expression`` and evaluate it against ``context``.

    Parsing is memoized, so repeatedly evaluating the same expression text (the
    common case across many files) parses only once. A string that cannot be
    parsed raises :class:`EvaluationError` rather than leaking the underlying
    parser exception.
    """
    try:
        node = _parse_cached(expression)
    except Exception as exc:  # noqa: BLE001 - pyparsing raises its own exception types
        raise EvaluationError(f'could not parse expression {expression!r}: {exc}') from exc
    return evaluate(node, context)


@lru_cache(maxsize=4096)
def _parse_cached(expression: str) -> Any:
    return parse(expression)


def evaluate(node: Any, context: Context) -> Any:
    """Evaluate a parsed ``node`` (or leaf atom) against ``context``."""
    handler = _NODE_HANDLERS.get(type(node))
    if handler is not None:
        return handler(node, context)
    # Leaf atoms. Booleans are excluded from the numeric branch because ``bool``
    # is a subclass of ``int`` in Python; the parser never emits bare Python
    # booleans anyway (it uses the identifiers ``true`` / ``false``).
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        return node
    if isinstance(node, str):
        return _atom(node, context)
    # An already-evaluated Python value passed straight through.
    return node


# ---------------------------------------------------------------------------
# Leaf atoms
# ---------------------------------------------------------------------------


def _atom(text: str, context: Context) -> Any:
    """Resolve a leaf string token.

    The parser hands back identifiers and quoted strings as plain ``str``. A
    quoted token is a string literal (the quotes are preserved by the parser);
    ``null`` / ``true`` / ``false`` are keywords; anything else is a reference to
    a context variable.
    """
    if len(text) >= 2 and text[0] in '"\'' and text[-1] == text[0]:
        return text[1:-1]
    if text == 'null':
        return None
    if text == 'true':
        return True
    if text == 'false':
        return False
    return _lookup(context, text)


def _lookup(container: Any, name: str) -> Any:
    """Read ``name`` from a mapping (or attribute), ``None`` when absent."""
    if isinstance(container, Mapping):
        return container.get(name)
    return getattr(container, name, None)


# ---------------------------------------------------------------------------
# Compound nodes
# ---------------------------------------------------------------------------


def _eval_array(node: Any, context: Context) -> list[Any]:
    return [evaluate(element, context) for element in node.elements]


def _eval_object(node: Any, context: Context) -> dict[str, Any]:
    # Object literals only ever appear as the empty ``{}`` in the schema.
    return {}


def _eval_property(node: Any, context: Context) -> Any:
    target = evaluate(node.name, context)
    if target is None:  # null propagation: null.anything == null
        return None
    return _lookup(target, node.field)


def _eval_element(node: Any, context: Context) -> Any:
    target = evaluate(node.name, context)
    if target is None:  # null propagation: null[i] == null
        return None
    idx = evaluate(node.index, context)
    if isinstance(target, (list, str)) and isinstance(idx, int) and not isinstance(idx, bool):
        if 0 <= idx < len(target):
            return target[idx]
    return None


def _eval_function(node: Any, context: Context) -> Any:
    # Check known-ness before evaluating arguments: an unfamiliar function in a
    # newer-than-engine schema is reported as such without doing argument work.
    if not is_known(node.name):
        raise UnknownFunction(node.name)
    args = [evaluate(arg, context) for arg in node.args]
    try:
        return call(node.name, args, context)
    except (IndexError, TypeError, ValueError):
        # Wrong arity or an unexpected argument type (for example a newer schema
        # changed a signature) degrades to null rather than crashing the run.
        return None


def _eval_rightop(node: Any, context: Context) -> Any:
    if node.op == '!':
        return not truthy(evaluate(node.rh, context))
    raise EvaluationError(f'unsupported unary operator {node.op!r}')


def _eval_binop(node: Any, context: Context) -> Any:
    op = node.op
    # Short-circuit logical operators, returning the operand value (not a coerced
    # boolean), matching JavaScript's ``&&`` / ``||``.
    if op in _LOGICAL_OPS:
        left = evaluate(node.lh, context)
        if op == '&&':
            return evaluate(node.rh, context) if truthy(left) else left
        return left if truthy(left) else evaluate(node.rh, context)

    left = evaluate(node.lh, context)
    right = evaluate(node.rh, context)
    return _binary(op, left, right)


def _binary(op: str, left: Any, right: Any) -> Any:
    """Evaluate a non-short-circuiting binary operator."""
    if op == '==':
        return _equal(left, right)
    if op == '!=':
        return not _equal(left, right)
    if op == 'in':
        return _contains(left, right)

    # Arithmetic and ordering propagate null: any null operand yields null.
    if left is None or right is None:
        return None
    if op == '+':
        return _add(left, right)
    if op in _ARITHMETIC_OPS:
        return _arithmetic(op, left, right)
    if op in _ORDERING_OPS:
        return _ordering(op, left, right)
    raise EvaluationError(f'unsupported operator {op!r}')


def _contains(left: Any, right: Any) -> Any:
    """Return the ``in`` operator result: membership in an object's keys / a sequence.

    In the schema ``in`` is used exclusively as key membership on an object
    (``'FlipAngle' in sidecar``), which Python's ``in`` on a mapping matches
    exactly. A null right operand yields null; anything else degrades to a safe
    result rather than raising.
    """
    if right is None:
        return None
    if isinstance(right, (Mapping, list, str)):
        try:
            return left in right
        except TypeError:  # for example an unhashable left operand against a mapping
            return False
    return None


def _equal(left: Any, right: Any) -> bool:
    """Return equality with null treated specially: null equals only null.

    The schema only ever compares like with like (string to string, number to
    number), so plain equality is correct here; JavaScript's looser cross-type
    coercion is not exercised by any schema rule.
    """
    if left is None or right is None:
        return left is None and right is None
    return bool(left == right)


def _add(left: Any, right: Any) -> Any:
    """Return ``+``: numeric addition, or string concatenation if either side is text."""
    if isinstance(left, str) or isinstance(right, str):
        return js_string(left) + js_string(right)
    try:
        return left + right
    except TypeError:
        return None


def _arithmetic(op: str, left: Any, right: Any) -> Any:
    """Compute numeric ``-`` ``*`` ``/`` ``%`` ``**``; null on non-numbers or zero division."""
    a, b = _as_number(left), _as_number(right)
    if a is None or b is None:
        return None
    try:
        if op == '-':
            return _simplify(a - b)
        if op == '*':
            return _simplify(a * b)
        if op == '/':
            return _simplify(a / b)
        if op == '%':
            return _simplify(a % b)
        if op == '**':
            return _simplify(a**b)
    except (ZeroDivisionError, ValueError, OverflowError):
        return None
    return None


def _ordering(op: str, left: Any, right: Any) -> Any:
    """Compute ``<`` ``<=`` ``>`` ``>=``: lexical for two strings, numeric otherwise.

    Returns null (rather than raising) when an operand is not a number and the
    pair is not two strings.
    """
    if isinstance(left, str) and isinstance(right, str):
        a: Any = left
        b: Any = right
    else:
        a = _as_number(left)
        b = _as_number(right)
        if a is None or b is None:
            return None
    if op == '<':
        return bool(a < b)
    if op == '<=':
        return bool(a <= b)
    if op == '>':
        return bool(a > b)
    return bool(a >= b)


def _as_number(value: Any) -> float | None:
    """Coerce to a float, or ``None`` if the value is not a number/numeric string."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _simplify(number: float) -> float | int:
    """Present integral floats as ``int`` (so ``4 / 2`` reads as ``2``)."""
    if number.is_integer():
        return int(number)
    return number


# Dispatch by node type. Defined after the handlers so the functions exist.
_NODE_HANDLERS: dict[type[Any], Any] = {
    Array: _eval_array,
    Object: _eval_object,
    Property: _eval_property,
    Element: _eval_element,
    Function: _eval_function,
    RightOp: _eval_rightop,
    BinOp: _eval_binop,
}


__all__ = [
    'EXISTS_RESOLVER_KEY',
    'Context',
    'EvaluationError',
    'UnknownFunction',
    'evaluate',
    'evaluate_string',
]
