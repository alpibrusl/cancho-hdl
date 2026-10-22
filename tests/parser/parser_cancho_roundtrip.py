"""Roundtrip claims of the textual `.chw` parser, held against the cancho binary.

The claims of the Python parser's roundtrip test, unchanged in what they require, over `chw parse` and `chw check`:

1. For every JSON/textual pair of examples/MANIFEST.json, `chw parse` of the text is the JSON twin's IR, modulo the case of
   hex digits (the parser normalizes them to lower case).
2. Parsing is deterministic.
3. The textual valid examples pass `chw check` with no Error-severity diagnostic.
4. The `parse-error` refusal fixture is refused with one Static `parse-error` at a real line and column (2:26), not a
   whole-file span.
5. Synthetic syntax errors land at the right line and column.

Oracle code: it decides nothing about the product.

    python3 tests/parser/parser_cancho_roundtrip.py /path/to/built/chw
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
EXE = sys.argv[1]
MANIFEST = json.loads((ROOT / "examples" / "MANIFEST.json").read_text())
_HEX = re.compile(r"^0x[0-9a-fA-F]+$")


def canon(x):
    if isinstance(x, dict):
        return {k: canon(v) for k, v in x.items()}
    if isinstance(x, list):
        return [canon(v) for v in x]
    if isinstance(x, str) and _HEX.match(x):
        return "0x" + x[2:].lower()
    return x


def chw(*args: str, cwd=ROOT) -> subprocess.CompletedProcess:
    return subprocess.run([EXE, *args], capture_output=True, text=True, cwd=cwd)


def diagnostics(text: str) -> list[dict]:
    out, dec, i = [], json.JSONDecoder(), 0
    while i < len(text):
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            break
        obj, i = dec.raw_decode(text, i)
        out.append(obj)
    return out


def main() -> int:
    failures: list[str] = []
    print("== chw parse roundtrip ==")

    print()
    print("## textual == JSON wire form ##")
    pairs = list(zip(MANIFEST["valid"], MANIFEST.get("textual_valid", [])))
    if not pairs:
        failures.append("  FAIL  no JSON/textual pairs in MANIFEST")
    for json_rel, text_rel in pairs:
        json_ir = json.loads((ROOT / json_rel).read_text())
        p = chw("parse", text_rel)
        if p.returncode != 0:
            failures.append(f"  FAIL  {text_rel}: parse error: {p.stderr.strip()}")
            continue
        if canon(json.loads(p.stdout)) != canon(json_ir):
            failures.append(f"  FAIL  {text_rel}: parsed IR differs from {json_rel}")
            continue
        print(f"  PASS  {text_rel} == {json_rel}")

    print()
    print("## determinism ##")
    for _, text_rel in pairs:
        if chw("parse", text_rel).stdout != chw("parse", text_rel).stdout:
            failures.append(f"  FAIL  {text_rel}: parser is not deterministic")
        else:
            print(f"  PASS  {text_rel}: deterministic")

    print()
    print("## checker on textual examples ##")
    for _, text_rel in pairs:
        p = chw("check", text_rel, "--output", "json")
        errors = [d for d in diagnostics(p.stdout) if d["severity"] == "Error"]
        if p.returncode != 0 or errors:
            failures.append(f"  FAIL  {text_rel}: exit {p.returncode}, {len(errors)} checker error(s): "
                            + "; ".join(f"{d['code']}: {d['message']}" for d in errors))
        else:
            print(f"  PASS  {text_rel}: 0 errors")

    print()
    print("## parse-error refusal fixture ##")
    p = chw("check", "examples/refusal/parse-error.chw", "--output", "json")
    ds = diagnostics(p.stdout)
    if p.returncode != 1 or len(ds) != 1 or ds[0]["code"] != "parse-error":
        failures.append("  FAIL  parse-error.chw: expected exit 1 and exactly one parse-error, got "
                        + f"exit {p.returncode}: " + ", ".join(sorted({d['code'] for d in ds})))
    else:
        d = ds[0]
        start = d["span"]["start"] if d.get("span") else None
        if d["tier"] != "Static":
            failures.append(f"  FAIL  parse-error fixture tier is {d['tier']}, expected Static")
        if start != {"line": 2, "column": 26}:
            failures.append(f"  FAIL  parse-error.chw span is {start}, expected 2:26")
        else:
            print(f"  PASS  parse-error.chw: span {start['line']}:{start['column']}, message: {d['message']}")

    print()
    print("## span positions on synthetic inputs ##")
    synthetic = [
        ("register-block B @ 0x1000, width 32, little-endian {\n"
         "  register C @ 0x00 : RW {\n"
         "    field f : bits [0] .\n"
         "  }\n"
         "}\n", 3, 24, "expected 'field' inside the register"),
        ("\n\nnot-a-contract\n", 3, 1, "expected a 'register-block' or 'dma-buffer' declaration"),
        ("dma-buffer T {\n"
         "  field a : @0x00, aligned 8\n"
         "}\n", 3, 1, "must state its owner"),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "synthetic.chw"
        for src, line, col, frag in synthetic:
            path.write_text(src)
            p = chw("check", str(path), "--output", "json")
            ds = diagnostics(p.stdout)
            start = ds[0]["span"]["start"] if ds and ds[0].get("span") else None
            ok = (p.returncode == 1 and len(ds) == 1 and ds[0]["code"] == "parse-error" and frag in ds[0]["message"]
                  and start == {"line": line, "column": col})
            if not ok:
                failures.append(f"  FAIL  synthetic ({line}:{col} {frag!r}): exit {p.returncode} span={start} "
                                f"diagnostics={[d['code'] for d in ds]}")
            else:
                print(f"  PASS  synthetic {line}:{col} - {ds[0]['message']}")

    print()
    if failures:
        print(f"== {len(failures)} failure(s) ==")
        for f in failures:
            print(f)
        return 1
    print("== chw parse roundtrip: all checks pass ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
