"""Test-only oracle driver for the SystemVerilog output of both tools (docs/cancho-port.md, 34): does a SystemVerilog
parser accept what `chw generate --target systemverilog` and `oracle/legacy/tools/generate/generate.py --target systemverilog` write?

Byte equality of the two tools (tests/differential/generate_sv.py) shows the port is faithful to the Python tool; it shows
nothing about whether the RTL is RTL. This runs `iverilog -g2012 -tnull` (parse and elaborate, write nothing) on the output
of each tool for every example and fixture that both tools generate, and prints the verdict of each with the first
diagnostic of the parser.

The step fails only if

  * `--require` is given and `iverilog` is not on the PATH, or
  * the two tools' outputs for one contract get different verdicts (accepted by one, refused by the other) or different
    first diagnostics, which equal bytes cannot do; so it is a guard for the day the generators are changed on one side, or
  * `iverilog` refuses a module of either tool. It refused every one until issue 14 was fixed in both tools (34.1, 34.5);
    now a refusal is a regression of the generator, and the step says which contract and the first diagnostic.

Usage:

    python3 tests/differential/sv_parse.py /path/to/built/chw [--require]

Oracle code only: it decides nothing about the product."""
import collections
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import check_json as cj  # for the list of fixtures; it reads sys.argv[1] as the chw binary

ROOT = cj.ROOT


def generate_cancho(path):
    p = subprocess.run([cj.EXE, "generate", str(path), "--target", "systemverilog", "--schema", cj.SCHEMA],
                       capture_output=True, text=True, errors="replace", cwd=ROOT)
    return p.returncode, p.stdout


def generate_python(path):
    p = subprocess.run([sys.executable, "oracle/legacy/tools/generate/generate.py", str(path), "--target", "systemverilog"],
                       capture_output=True, text=True, errors="replace", cwd=ROOT)
    return p.returncode, p.stdout


def parse(sv_text, tmp, label):
    f = pathlib.Path(tmp) / f"{label}.sv"
    f.write_text(sv_text, encoding="utf-8")
    p = subprocess.run(["iverilog", "-g2012", "-tnull", str(f)], capture_output=True, text=True, errors="replace")
    first = ""
    for line in (p.stderr or "").splitlines():
        m = re.match(r"^.*?\.sv:\d+: (.*)$", line)
        if m:
            first = m.group(1)
            break
    return p.returncode == 0, first


def main():
    require = "--require" in sys.argv
    if shutil.which("iverilog") is None:
        print("iverilog is not on the PATH" + ("" if not require else ": required"))
        sys.exit(1 if require else 0)
    tally = collections.Counter()
    first_errors = collections.Counter()
    bad = []
    with tempfile.TemporaryDirectory() as tmp:
        for f in cj.fixture_files():
            crc, cout = generate_cancho(f)
            prc, pout = generate_python(f)
            if crc != 0 or prc != 0:
                continue
            tally["generated"] += 1
            cok, cerr = parse(cout, tmp, "cancho")
            pok, perr = parse(pout, tmp, "python")
            tally["accepted by iverilog (cancho)"] += cok
            tally["accepted by iverilog (python)"] += pok
            first_errors[cerr or "(accepted)"] += 1
            print(f"{'accepted' if cok else 'refused '} {f.relative_to(ROOT)}: {cerr or 'ok'}")
            if (cok, cerr) != (pok, perr):
                bad.append(f"{f.name}: cancho {(cok, cerr)} python {(pok, perr)}")
    print(f"{tally['generated']} contracts generate in both tools; iverilog accepts "
          f"{tally['accepted by iverilog (cancho)']} of the port's modules and {tally['accepted by iverilog (python)']} of the Python tool's")
    for e, n in first_errors.most_common():
        print(f"  first diagnostic x{n}: {e}")
    print(f"{len(bad)} contracts on which the two tools' verdicts differ")
    for b in bad:
        print("DIFFERENT", b)
    refused = tally["generated"] * 2 - tally["accepted by iverilog (cancho)"] - tally["accepted by iverilog (python)"]
    print(f"{refused} modules refused by iverilog")
    sys.exit(1 if bad or refused else 0)


if __name__ == "__main__":
    main()
