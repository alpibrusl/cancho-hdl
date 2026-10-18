"""Roundtrip test: the textual `.chw` parser.

Asserts that:

1. For every valid_example pair (JSON wire form + textual form),
   the parser's IR is identical to the JSON file's IR — modulo hex
   case, which the parser normalizes to lowercase. This pins the
   frozen text syntax to the wire format: the two describe the
   same contract, byte for byte.
2. Parsing is deterministic (same source → same IR).
3. The textual valid examples pass the full checker with zero
   Error-severity diagnostics.
4. The `parse-error` refusal fixture is refused with a real
   line/column span (not a whole-file span).
5. Synthetic syntax errors land at the right line and column, so
   spans do not drift.

Exits 0 on pass, 1 on any failure.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
for p in (ROOT / "tools" / "parse", ROOT / "tools" / "check"):
    sys.path.insert(0, str(ROOT / p))

from parser import parse_source_text  # noqa: E402
from checker import check_file  # noqa: E402

EXAMPLES = ROOT / "examples"
MANIFEST = json.loads((EXAMPLES / "MANIFEST.json").read_text())

# The parser preserves hex digit widths literally but normalizes case.
# JSON examples written before the parser existed use e.g. `0x0C`.
# The comparison below is therefore case-insensitive on hex strings.
_HEX = re.compile(r"^0x[0-9a-fA-F]+$")


def canon(x):
    if isinstance(x, dict):
        return {k: canon(v) for k, v in x.items()}
    if isinstance(x, list):
        return [canon(v) for v in x]
    if isinstance(x, str) and _HEX.match(x):
        return "0x" + x[2:].lower()
    return x


def main() -> int:
    failures: list[str] = []
    print("== parser roundtrip ==")

    # 1. Textual parses to the JSON twin's IR
    print()
    print("## textual == JSON wire form ##")
    pairs = list(zip(MANIFEST["valid"], MANIFEST.get("textual_valid", [])))
    if not pairs:
        failures.append("  FAIL  no JSON/textual pairs in MANIFEST")
    for json_rel, text_rel in pairs:
        json_ir = json.loads((ROOT / json_rel).read_text())
        text_src = (ROOT / text_rel).read_text()
        ir, diags = parse_source_text(text_src, text_rel)
        if ir is None:
            failures.append(f"  FAIL  {text_rel}: parse error: {diags[0].message}")
            continue
        if canon(json_ir) != canon(ir):
            failures.append(f"  FAIL  {text_rel}: parsed IR differs from {json_rel}")
            continue
        print(f"  PASS  {text_rel} == {json_rel}")

    # 2. Determinism
    print()
    print("## determinism ##")
    for _, text_rel in pairs:
        src = (ROOT / text_rel).read_text()
        ir1, _ = parse_source_text(src, text_rel)
        ir2, _ = parse_source_text(src, text_rel)
        if ir1 != ir2:
            failures.append(f"  FAIL  {text_rel}: parser is not deterministic")
        else:
            print(f"  PASS  {text_rel}: deterministic")

    # 3. Textual valid examples pass the checker with 0 errors
    print()
    print("## checker on textual examples ##")
    for _, text_rel in pairs:
        diags = check_file(str(ROOT / text_rel))
        errors = [d for d in diags if d.severity == "Error"]
        if errors:
            failures.append(f"  FAIL  {text_rel}: {len(errors)} checker error(s): "
                            + "; ".join(f"{d.code}: {d.message}" for d in errors))
        else:
            print(f"  PASS  {text_rel}: 0 errors")

    # 4. The refusal fixture emits parse-error with a real span
    print()
    print("## parse-error refusal fixture ##")
    fixture = ROOT / "examples" / "refusal" / "parse-error.chw"
    diags = check_file(str(fixture))
    if len(diags) != 1 or diags[0].code != "parse-error":
        failures.append("  FAIL  parse-error.chw: expected exactly one parse-error, got "
                        + ", ".join(sorted({d.code for d in diags})))
    else:
        d = diags[0]
        if d.tier != "Static":
            failures.append(f"  FAIL  parse-error fixture tier is {d.tier}, expected Static")
        if d.span is None or d.span.start.line != 2 or d.span.start.column != 26:
            at = (d.span.start.line, d.span.start.column) if d.span else None
            failures.append(f"  FAIL  parse-error.chw span is {at}, expected (2, 26)")
        else:
            print(f"  PASS  parse-error.chw: span {d.span.start.line}:{d.span.start.column}, "
                  f"message: {d.message}")

    # 5. Synthetic span checks: errors land at the right line/column
    print()
    print("## span positions on synthetic inputs ##")
    synthetic = [
        # (source, expected line, expected column, message fragment)
        (
            "register-block B @ 0x1000, width 32, little-endian {\n"
            "  register C @ 0x00 : RW {\n"
            "    field f : bits [0] .\n"        # stray '.' inside the register
            "  }\n"
            "}\n",
            3, 24, "expected 'field' inside the register",
        ),
        (
            "\n\nnot-a-contract\n",
            3, 1, "expected a 'register-block' or 'dma-buffer' declaration",
        ),
        (
            "dma-buffer T {\n"
            "  field a : @0x00, aligned 8\n"
            "}\n",
            3, 1, "must state its owner",
        ),
    ]
    for src, exp_line, exp_col, frag in synthetic:
        ir, diags = parse_source_text(src, "synthetic.chw")
        ok_msg = bool(diags) and frag in diags[0].message
        got = diags[0].span.start.to_dict() if (diags and diags[0].span) else None
        ok_span = got == {"line": exp_line, "column": exp_col}
        if not ok_msg or not ok_span or ir is not None:
            failures.append(
                f"  FAIL  synthetic ({exp_line}:{exp_col} {frag!r}): "
                f"message_ok={ok_msg} span={got} ir={ir is not None}"
            )
        else:
            print(f"  PASS  synthetic {exp_line}:{exp_col} — {diags[0].message}")

    print()
    if failures:
        print(f"== {len(failures)} failure(s) ==")
        for f in failures:
            print(f)
        return 1
    print("== parser roundtrip: all checks pass ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
