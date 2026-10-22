"""Text formatter for `Diagnostic`.

The human-facing parallel of the JSON form. Rule from
`spec/diagnostics/README.md` §5: **the text form is derived from
the JSON form**, not the other way around. The formatter therefore
takes a `Diagnostic`, immediately projects it onto its `to_dict()`
shape, and renders only what the JSON carries. If the JSON has no
span, the text has no `-->` line; if the JSON has no remediation,
the text has no `help:` line. Nothing is invented here.

Layout:

    error[field-overlap]: field 'PARITY' bits [2..4] overlap with
    ENABLE bits [0..3] in register 'CTRL'.
       --> examples/refusal/field-overlap.chw
       = related[field-overlap]: field 'ENABLE' occupies bits
       [0..3] in register 'CTRL'.

and, for a diagnostic whose span carries a real line/column (the
textual-syntax parser's `parse-error` values are the only source
of these today — the JSON wire form carries no positions, so a
whole-file pseudo-span is rendered file-only):

    error[parse-error]: parse error: expected ':' after the
    register offset (before the access kind), found 'RW'.
       --> examples/refusal/parse-error.chw:2:26
       |
     2 | register CTRL @ 0x00 RW, reset 0x00000000 {
       |                          ^
    help: Add ': <kind>' after the register offset, e.g.
    'RW, reset 0x00000000'.

Lanes:

- header: `severity[code]: message` — one line, unwrapped. The
  JSON `message` is one line (§4.2); the text form does not
  re-wrap it.
- span lane: `   --> path[:line:col]`. Real span → source snippet
  (3 gutter lines: separator, the line itself, the caret). Point
  span (start == end == 1:1), which is what the JSON wire form's
  `file_span` produces, or an unreadable file → path only, no
  snippet. A snippet is never guessed.
- related lane: one `   = related[code]: message` per related entry.
- notes lane: one `   = note: <text>` per note.
- help lane: `help: <remediation.description>` when the diagnostic
  carries a remediation.

`format_diagnostics` renders a list into a report string, one
blank line between blocks, one trailing newline. `cancho-hdl
check` without `--output json` prints exactly this.
"""

from __future__ import annotations

import pathlib
from typing import Any


def _severity_word(severity: str) -> str:
    return {"Error": "error", "Warning": "warning"}.get(severity, severity.lower())


def _is_point_span(span: dict[str, Any]) -> bool:
    """True for the whole-file pseudo-span the JSON wire form uses:
    start == end == (1, 1). Such a span locates a file, not a token."""
    start = span.get("start", {})
    end = span.get("end", {})
    return (
        start.get("line", 1) == 1 and start.get("column", 1) == 1
        and end.get("line", 1) == 1 and end.get("column", 1) == 1
    )


def _read_snippet_line(span: dict[str, Any]) -> str | None:
    """The source line the span names, or None if it cannot be read.
    A snippet is never guessed: unreadable file → None."""
    try:
        lines = pathlib.Path(span["file"]).read_text().splitlines()
    except OSError:
        return None
    line_no = span["start"]["line"]
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1]
    return None


def _render_span(out: list[str], span: dict[str, Any]) -> None:
    file = span["file"]
    start = span["start"]
    if _is_point_span(span):
        out.append(f"   --> {file}")
        return
    out.append(f"   --> {file}:{start['line']}:{start['column']}")
    src_line = _read_snippet_line(span)
    if src_line is None:
        return
    num_w = max(len(str(start["line"])), 2)
    out.append("   |")
    out.append(f" {start['line']:>{num_w}} | {src_line}")
    caret = " " * (start["column"] - 1) + "^"
    out.append(f"   | {caret}")


def format_diagnostics(diags) -> str:
    """Render a list of Diagnostic values as one report string."""
    blocks = [format_diagnostic(d) for d in diags]
    return "\n".join("\n".join(b) for b in blocks) + "\n" if blocks else ""


def format_diagnostic(diag) -> list[str]:
    """Render one Diagnostic as a list of lines.

    The rule from spec §5: derive from the JSON form. This function
    projects the diagnostic onto its dict and works on the dict —
    the same value `--output json` would print. Attributes that are
    not in the dict are never rendered.
    """
    d: dict[str, Any] = diag.to_dict() if hasattr(diag, "to_dict") else dict(diag)

    out: list[str] = [f"{_severity_word(d['severity'])}[{d['code']}]: {d['message']}"]

    span = d.get("span")
    if span is not None:
        _render_span(out, span)

    for rel in d.get("related", []):
        out.append(f"   = related[{rel['code']}]: {rel['message']}")

    for note in d.get("notes", []):
        out.append(f"   = note: {note}")

    rem = d.get("remediation")
    if rem is not None and rem.get("description"):
        out.append(f"help: {rem['description']}")

    return out
