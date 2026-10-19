"""Test-only oracle driver for the textual parser: run the Python parser (the legacy
reference implementation) and the cancho port over the same inputs and compare
stdout, stderr and exit status byte for byte.

Inputs: the two textual examples, then mutants of each (truncation at every
byte offset, and deletion of every token-sized run). Usage:

    python3 tests/differential/text_parse.py /path/to/built/chwparse

This file is oracle code only: it decides nothing about the product."""
import pathlib, re, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "parse"))
sys.path.insert(0, str(ROOT / "tools" / "check"))
from parser import parse_source_text  # noqa: E402
import json  # noqa: E402


def python_side(src: str, path: str):
    ir, diags = parse_source_text(src, path)
    if ir is None:
        d = diags[0]
        span = f"{d.span.start.line}:{d.span.start.column}"
        return "", f"error[{d.code}]: {d.message}  {path}:{span}\n", 1
    return json.dumps(ir) + "\n", "", 0


def cancho_side(exe: str, path: str):
    p = subprocess.run([exe, "parse", path], capture_output=True, text=True)
    return p.stdout, p.stderr, p.returncode


HANDMADE = [
    # attribute and linkage order is insertion order in the Python dicts
    "register-block B @ 0x1_0000, width 8, big-endian {\n register R @ 0X0A : RW, polling, volatile, reset 0xAB, reset 0x0F { }\n"
    " register S @ 0x1 : RO, volatile { field F : bits [3] enum { } constraint a \"q\" \\ b\t// c }\n"
    " interrupt i from R.F { clear : RC @ S.F, number 3; status @ S.F enable @ R.F source @ S.F number 4 } }",
    # non-ASCII in constraint text (ensure_ascii escapes), astral plane
    "register-block B @ 0x0, width 32, little { register R @ 0x0 : RW { field F : bits [0] constraint caf\u00e9 \u65e5 \U0001F600 } }",
    # dma: every attribute, repeated, in odd order
    "register-block B @ 0x0, width 32, little { }\ndma-buffer D { field a : @ 0xFF, written as 4, aligned 8, owned by GPU, coherent true, aligned 16, coherent false, constraint len <= 4 }",
    "register-block B @ 0x0, width 32, little { }\ndma-buffer D { field a : @ 0x0 }",
    "register-block B @ 0x0, width 32, little { }\nregister-block C @ 0x0, width 32, little { }",
    "",
    "register-block B @ 0x0, width 99999999999999999999, little { }",
    "register-block B @ 0x0, width 32, little { register R @ 0x0 : RW { field F : bits [0] enum { A=0, B=1, A=2 } } }",
    "register-block B @ 0x0, width 32, little { } $ ",
    "register-block B @ 0x0, width 32, little { register R @ 0x0 : RW { field F : bits [0] constraint",
]


# The two differences the design document lists (docs/cancho-port.md,
# "Known differences"); anything else is a failure.
KNOWN = {
    "handmade1": "columns count bytes, Python counts characters (non-ASCII source)",
    "handmade6": "decimal literals over 18 digits are refused, Python's int is unbounded",
}


def mutants(src: str, first: bool):
    if first:
        for i, h in enumerate(HANDMADE):
            yield f"handmade{i}", h
    yield "original", src
    for i in range(len(src)):
        yield f"truncate@{i}", src[:i]
    for m in re.finditer(r"\S+", src):
        yield f"delete-token@{m.start()}", src[: m.start()] + src[m.end():]


def main():
    exe = sys.argv[1]
    files = sorted((ROOT / "examples" / "textual").glob("*.chw"))
    ok = bad = known = 0
    total = same = 0
    first_diffs = []
    with tempfile.TemporaryDirectory() as tmp:
        for n, f in enumerate(files):
            src = f.read_text()
            for label, text in mutants(src, n == 0):
                # the same path string on both sides, so messages compare
                path = str(pathlib.Path(tmp) / "m.chw")
                pathlib.Path(path).write_text(text)
                a = python_side(text, path)
                b = cancho_side(exe, path)
                total += 1
                if a[2] == 0:
                    ok += 1
                else:
                    bad += 1
                if a == b:
                    same += 1
                elif label in KNOWN:
                    known += 1
                elif len(first_diffs) < 5:
                    first_diffs.append((f.name, label, a, b))
    print(f"{same}/{total} identical (stdout, stderr, exit status); {known} known differences; {ok} parse, {bad} refused")
    for d in first_diffs:
        print("DIFF", d)
    sys.exit(0 if same + known == total else 1)


main()
