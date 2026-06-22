"""Render a validation report in different formats.

Each renderer turns a :class:`~bids_validator.validation.report.ValidationReport`
into text a consumer wants:

* :func:`~bids_validator.validation.render.text.to_text` - a human-readable summary.
* :func:`~bids_validator.validation.render.json.to_json` - machine-readable JSON.
* :func:`~bids_validator.validation.render.sarif.to_sarif` - SARIF 2.1.0.
* :func:`~bids_validator.validation.render.html.to_html` - a self-contained HTML report.

The renderers are pure functions of the report, so the same result can be emitted
to stdout or written to any number of files.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .html import to_html
from .json import to_dict, to_json
from .sarif import to_sarif
from .text import to_text

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..report import ValidationReport

# Format name -> renderer + file extension. The single source for the CLI.
RENDERERS: dict[str, Callable[[ValidationReport], str]] = {
    'text': to_text,
    'json': to_json,
    'sarif': to_sarif,
    'html': to_html,
}
EXTENSIONS = {'text': 'txt', 'json': 'json', 'sarif': 'sarif', 'html': 'html'}

__all__ = ['EXTENSIONS', 'RENDERERS', 'to_dict', 'to_html', 'to_json', 'to_sarif', 'to_text']
