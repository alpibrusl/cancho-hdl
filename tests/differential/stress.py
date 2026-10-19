"""Test-only: inputs that are large or hostile, run through `chw validate`.
Checks one thing: the program answers (exit 0 or 1, never a trap or a hang)
within a generous time. The sizes are the ones that exposed quadratic code
(docs/cancho-port.md, 10): 16,000 refusals in one file, an object of 5,000
keys, nesting at the limit. Usage:

    python3 tests/differential/stress.py /path/to/built/chw

Oracle code only: it generates inputs and reads an exit status."""
import json
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = json.loads((ROOT / "examples/uart-contract/uart.chw").read_text())
LIMIT_SECONDS = 20


def clone():
    return json.loads(json.dumps(BASE))


def cases():
    d = clone()
    d["block"]["registers"] = [
        {"name": f"R{i}", "offset": hex(i * 4), "kind": "RW", "fields": [{"name": "F", "lsb": 0, "msb": 7, "enum": {"A": 0, "B": 1}}]}
        for i in range(8000)
    ]
    yield "8000 valid registers (1 MB)", json.dumps(d), 0

    d = clone()
    d["block"]["registers"] = [
        {"name": f"R{i}", "offset": hex(i * 4), "kind": "WTF", "fields": [{"name": "F", "lsb": 0, "msb": 70}]}
        for i in range(8000)
    ]
    yield "16000 refusals, indented", json.dumps(d, indent=2), 1
    yield "16000 refusals, one line", json.dumps(d), 1

    d = clone()
    d["block"]["registers"][0]["fields"][0]["enum"] = {f"K{i}": i for i in range(5000)}
    yield "one object of 5000 keys", json.dumps(d), 0

    d = clone()
    d.update({f"unknown{i}": i for i in range(5000)})
    yield "5000 unknown keys (sorted in one message)", json.dumps(d), 1

    d = clone()
    x = []
    for _ in range(120):
        x = [x]
    d["extra"] = x
    yield "nesting 120", json.dumps(d), 1
    yield "nesting 129 (past std.json's limit)", '{"a":' + "[" * 129 + "]" * 129 + "}", 1

    d = clone()
    d["block"]["name"] = "x" * 1_000_000
    yield "a 1 MB name", json.dumps(d), 0

    yield "invalid UTF-8", b'{"version": "0.1.0", "block": {"name": "\xff\xfe"}}', 1
    yield "a number of 4000 digits", b'{"a": ' + b"9" * 4000 + b"}", 1
    yield "64 KB of '['", b"{" + b"[" * 65536, 1


def main():
    exe = sys.argv[1]
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        for label, body, want in cases():
            path = pathlib.Path(tmp) / "case.chw"
            path.write_bytes(body if isinstance(body, bytes) else body.encode())
            start = time.time()
            p = subprocess.run([exe, "validate", str(path), "--machine"], capture_output=True, timeout=300)
            took = time.time() - start
            ok = p.returncode == want and took < LIMIT_SECONDS
            print(f"  {'ok  ' if ok else 'FAIL'} {label}: exit {p.returncode} (want {want}), {took:.2f} s")
            bad += not ok
    sys.exit(1 if bad else 0)


main()
