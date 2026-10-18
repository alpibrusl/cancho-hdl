"""Golden test: the `Diagnostic` text formatter.

Pins `cancho-hdl check`'s text output for representative lanes so
the schema does not drift:

- point-span lane (`--> path` only, no snippet): every checker
  diagnostic over a JSON wire file — the JSON wire form carries no
  source positions.
- related lane (`   = related[code]: ...`).
- remedy lane (`help: ...`, tool-derived, spec §2.3).
- note lane (`   = note: ...`).
- warning lane.
- real-span lane (`--> path:line:column` + gutter + caret): the
  only producer of real spans is `parse-error` on textual files.

Also asserts the §5 derivation rule mechanically: the rendered
text is a function of `Diagnostic.to_dict()` alone — formatting
the same diagnostic through a re-projected dict yields identical
bytes.

Run from the repo root: `python3 tests/text_format/golden.py`
(spans name relative example paths by design).
"""

from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "check"))

from checker import check_file  # noqa: E402
from diagnostic import Diagnostic, Position, Span, Subject  # noqa: E402
from text_format import format_diagnostics  # noqa: E402

os.chdir(ROOT)


GOLDEN_FIELD_OVERLAP = """\
error[field-overlap]: field 'PARITY' bits [2..4] overlap with ENABLE bits [0..3] in register 'CTRL'.
   --> examples/refusal/field-overlap.chw
   = related[field-overlap]: field 'ENABLE' occupies bits [0..3] in register 'CTRL'.
help: start PARITY at bits [4..6] (just after ENABLE, bits [0..3]), or shrink / move either field — the toolchain cannot say which side the hardware semantics live on
"""

GOLDEN_PARSE_ERROR = """\
error[parse-error]: parse error: expected ':' after the register offset (before the access kind), found 'RW'.
   --> examples/refusal/parse-error.chw:2:26
   |
  2 |     register CTRL @ 0x00 RW, reset 0x00000000 {
   |                          ^
"""

GOLDEN_CONSTRAINT_WARNING = """\
warning[field-constraint-ignored]: field 'BAUD_DIV' declares constraint 'nonzero when ENABLE == 1'; the Phase 0 checker does not parse constraint semantics (see docs/contract-design.md §5 question 3).
   --> examples/textual/uart.chw
   = note: constraints are documented but not enforced until 0.2.0
"""

GOLDEN_REGISTER_OVERLAP = """\
error[register-offset-duplicate]: registers A and B share offset 0x00 in block BadUart.
   --> examples/refusal/register-overlap.chw
   = related[register-offset-duplicate]: register B is also at offset 0x00.
"""

CASES = [
    ("field-overlap (related + remedy lanes)", "examples/refusal/field-overlap.chw", GOLDEN_FIELD_OVERLAP),
    ("parse-error (real-span lane)", "examples/refusal/parse-error.chw", GOLDEN_PARSE_ERROR),
    ("constraint warning (warning + note lanes)", "examples/textual/uart.chw", GOLDEN_CONSTRAINT_WARNING),
    ("register-overlap (duplicate rule)", "examples/refusal/register-overlap.chw", GOLDEN_REGISTER_OVERLAP),
]


def main() -> int:
    failures: list[str] = []
    print("== diagnostic text formatter golden ==")

    for label, path, golden in CASES:
        got = format_diagnostics(check_file(path))
        if got == golden:
            print(f"  PASS  {label}")
        else:
            failures.append(f"  FAIL  {label}\n--- golden ---\n{golden}--- rendered ---\n{got}")

    # Derivation property: the formatter is a pure function of the
    # JSON dict shape (what --output json prints). Render the same
    # diagnostic from the object and from its re-projected dict —
    # both renders must be byte identical, and together they pin the
    # real-span snippet lane against a readable file.
    synthetic = Diagnostic(
        code="synthetic",
        severity="Warning",
        tier="Tested",
        subject=Subject("Generator", {"target": "c-header"}),
        span=Span(file="examples/textual/uart.chw", start=Position(4, 15), end=Position(4, 20)),
        message="synthetic diagnostic for the derivation property.",
        notes=["a note"],
    )
    once = format_diagnostics([synthetic])
    from text_format import format_diagnostic
    again = "\n".join(format_diagnostic(synthetic.to_dict())) + "\n"
    GOLDEN_SYNTHETIC = """\
warning[synthetic]: synthetic diagnostic for the derivation property.
   --> examples/textual/uart.chw:4:15
   |
  4 |         field ENABLE   : bits [0]
   |               ^
   = note: a note
"""
    if once != again or once != GOLDEN_SYNTHETIC:
        failures.append("  FAIL  derivation property\n"
                        "--- golden ---\n" + GOLDEN_SYNTHETIC +
                        "--- rendered ---\n" + once)
    else:
        print("  PASS  derivation property: text is a pure function of the JSON form")

    print()
    if failures:
        for f in failures:
            print(f)
        print("== golden: FAILED ==")
        return 1
    print("== golden: all blocks match ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
