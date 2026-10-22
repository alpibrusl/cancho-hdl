"""Golden test of `chw check`'s text form (spec/diagnostics/README.md, 5), held against the cancho binary.

The goldens are the four of the Python formatter's test (the lanes: related and remedy, a real source span with its
snippet, warning and note, a duplicate rule), unchanged: the bytes `chw check FILE` writes must equal them, and its exit
status must be 1 for a refused contract and 0 for one with only a warning. Oracle code: it decides nothing about the
product.

    python3 tests/text_format/golden_cancho.py /path/to/built/chw

Not carried over: the "derivation property" case of the Python test, which formats a hand-built `Diagnostic` object; the
cancho renderer takes the record `check` produces, which gate step 8b compares with the oracle's text on every fixture and
every mutant.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
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
    ("field-overlap (related + remedy lanes)", "examples/refusal/field-overlap.chw", GOLDEN_FIELD_OVERLAP, 1),
    ("parse-error (real-span lane)", "examples/refusal/parse-error.chw", GOLDEN_PARSE_ERROR, 1),
    ("constraint warning (warning + note lanes)", "examples/textual/uart.chw", GOLDEN_CONSTRAINT_WARNING, 0),
    ("register-overlap (duplicate rule)", "examples/refusal/register-overlap.chw", GOLDEN_REGISTER_OVERLAP, 1),
]


def main() -> int:
    exe = sys.argv[1]
    failures: list[str] = []
    print("== chw check text form golden ==")
    for label, path, golden, status in CASES:
        p = subprocess.run([exe, "check", path], capture_output=True, text=True)
        if p.stdout == golden and p.returncode == status:
            print(f"  PASS  {label}")
        else:
            failures.append(f"  FAIL  {label} (exit {p.returncode}, expected {status})\n--- golden ---\n{golden}--- rendered ---\n{p.stdout}")
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
