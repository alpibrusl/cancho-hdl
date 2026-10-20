"""Test-only oracle driver for stage 7 (docs/cancho-port.md, 29.5): compare the cancho SystemVerilog generator
(`chw generate FILE --target systemverilog`) with the Python tool (`tools/generate/generate.py --target systemverilog FILE`).

The same three parts as generate_binding.py (which this file copies the shape of; that file runs on import, so it cannot
be imported), with the same difference from the earlier generators: **there is no tool for the output on this machine**
(no iverilog, verilator, yosys or slang), so the oracle is the Python tool's bytes alone, and a known-difference class is
admitted only for a structural reason stated here, never by "it parses". Where both tools write invalid SystemVerilog,
nothing here says so (docs/cancho-port.md 29.1).

  1. Fixtures: every valid example, refusal fixture, tests/stage1 and tests/stage2 file through both command lines;
     exit status, standard output and standard error compared byte for byte.
  2. Mutants: the mutants of tests/differential/check_json.py (imported, not copied).
  3. Hand-made inputs only a generator can get wrong: every access kind, enums with equal and different label lists,
     names that collide as types, empty enums, `a__b` names, every linkage, DMA owners, register order.

Known classes, each with its reason:

  checker-known      the two checkers differ on this input in a class check_json.py already explains.
  python-crash       the Python tool raised; cancho must still answer with exit 0 or 1 and never a trap.
  non-ascii-name     a name has a non-ASCII byte or a JSON escape; cancho writes ASCII only and refuses the rest. A
                     narrowing, stated in the document, admitted only if the input really holds such a byte or escape.
  both-internal      both tools answer `internal`; each says it in its own words.
  float-bus-width    `"bus_width": 3.2e1`: an integer to the schema; Python writes `32.0` where SystemVerilog needs
                     `32`, cancho writes `32`. Admitted only if that is the whole difference.

Usage:

    python3 tests/differential/generate_sv.py /path/to/built/chw [--jobs N] [--fixtures-only | --handmade-only]

This file is oracle code only: it decides nothing about the product."""
import collections
import concurrent.futures
import contextlib
import importlib.util
import io
import pathlib
import re
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location("check_json", HERE / "check_json.py")
check_json = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_json)

sys.path.insert(0, str(ROOT / "tools" / "generate"))
import generate as pygen  # noqa: E402  (the oracle)

EXE = sys.argv[1]
TARGET = "systemverilog"


def cancho(path):
    p = subprocess.run([EXE, "generate", path, "--target", TARGET], capture_output=True, errors="replace", cwd=ROOT)
    return p.returncode, p.stdout.decode("utf-8", "replace") if isinstance(p.stdout, bytes) else p.stdout, \
        p.stderr.decode("utf-8", "replace") if isinstance(p.stderr, bytes) else p.stderr


def cancho_run(path):
    p = subprocess.run([EXE, "generate", path, "--target", TARGET], capture_output=True, cwd=ROOT)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def python_run(path):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = pygen.main(["--target", TARGET, path])
        except SystemExit as e:
            rc = e.code
        except Exception as e:  # the oracle assumes a schema-valid shape
            return "crash", "", f"{type(e).__name__}"
    return rc, out.getvalue(), err.getvalue()


def checker_known(tmp, label, text):
    """Is this input one on which the two checkers differ in a known class?"""
    tags, problem = check_json.judge(tmp, label, text)
    return problem is None and any(t.startswith("known:") for t in tags)


def judge(tmp, label, text, py, path):
    """-> (tags, unexplained or None)"""
    ca = cancho_run(path)
    if ca[0] not in (0, 1, 2, 3):
        return [], f"{label}: cancho exited {ca[0]} (a trap or a signal): {ca[2].strip()[:120]}"
    if py[0] == "crash":
        return [f"python-crash:{py[2]}"], None if ca[0] in (0, 1) else f"{label}: python raised and cancho exited {ca[0]}"
    if py == ca:
        return ["identical", f"rc{ca[0]}"], None
    if py[0] == 0 and ca[0] == 1 and "error[generator-unimplemented]: target systemverilog:" in ca[2]:
        if (re.search(r"[^\x00-\x7f]|\\", text) or re.search(r"[^\x00-\x7f]", path)) and "cannot be written as it stands" in ca[2]:
            return ["known:non-ascii-name"], None
        return [], f"{label}: cancho refused ({ca[2].strip()[:100]}) but Python wrote the declarations"
    if py[0] == 3 and ca[0] == 3:
        return ["known:both-internal"], None
    if py[0] == 0 and ca[0] == 0 and re.search(r"DATA_WIDTH = \d+\.0\n", py[1]):
        # `"bus_width": 3.2e1` is an integer to the schema; this Python generator uses it without int(), so it writes
        # `DATA_WIDTH = 32.0` and `32.0'h...` (not SystemVerilog). cancho reads the integer. Admitted only if that is
        # the whole difference.
        fixed = re.sub(r"DATA_WIDTH = (\d+)\.0\n", r"DATA_WIDTH = \1\n", py[1])
        fixed = re.sub(r"= (\d+)\.0'h", r"= \1'h", fixed)
        if fixed == ca[1] and py[2] == ca[2]:
            return ["known:float-bus-width"], None
    if checker_known(tmp, label, text):
        return ["known:checker"], None
    return [], f"{label}: rc python={py[0]} cancho={ca[0]}\n   python stderr: {py[2].strip()[:140]}\n   cancho stderr: {ca[2].strip()[:140]}"


# hand-made inputs a generator can get wrong (docs/cancho-port.md 29.5)
def doc(**over):
    d = {"version": "0.1.0", "block": {"name": "Blk", "base_address": "0x40000000", "bus_width": 32, "endianness": "little",
                                      "registers": [{"name": "CTRL", "offset": "0x0", "kind": "RW", "reset": "0x1",
                                                     "fields": [{"name": "EN", "lsb": 0, "msb": 0}]}]}}
    for k, v in over.items():
        d["block"][k] = v
    return d


def regs(*rs, **over):
    return doc(registers=list(rs), **over)


def reg(name="R", offset="0x0", kind="RW", fields=None, **extra):
    r = {"name": name, "offset": offset, "kind": kind}
    if fields is not None:
        r["fields"] = fields
    r.update(extra)
    return r


def fld(name="F", lsb=0, msb=0, **extra):
    f = {"name": name, "lsb": lsb, "msb": msb}
    f.update(extra)
    return f


GENERATOR_INPUTS = [
    ("plain", doc()),
    ("kind-RO", regs(reg(kind="RO"))),
    ("kind-WO", regs(reg(kind="WO"))),
    ("kind-RW", regs(reg(kind="RW"))),
    ("kind-RC", regs(reg(kind="RC"))),
    ("kind-W0C", regs(reg(kind="W0C"))),
    ("kind-W0S", regs(reg(kind="W0S"))),
    ("kind-W1C", regs(reg(kind="W1C"))),
    ("kind-W1S", regs(reg(kind="W1S"))),
    ("kind-unknown", regs(reg(kind="XX"))),
    ("kind-unknown-quote", regs(reg(kind="X'Y"))),
    ("kinds-all", regs(*[reg(f"R{i}", hex(i * 4), k) for i, k in enumerate(["RO", "WO", "RW", "RC", "W0C", "W0S", "W1C", "W1S"])])),
    ("width-8", doc(bus_width=8)),
    ("width-16", doc(bus_width=16)),
    ("width-32", doc(bus_width=32)),
    ("width-64", doc(bus_width=64)),
    ("reset-none", regs(reg())),
    ("reset-zero", regs(reg(reset="0x0"))),
    ("reset-wide", regs(reg(reset="0xdeadbeef"))),
    ("reset-past-width", regs(reg(reset="0x1ffffffff"))),
    ("reset-underscore", regs(reg(reset="0xab_cd"))),
    ("reset-upper", regs(reg(reset="0xABCDEF01"))),
    ("reset-width-8", doc(bus_width=8, registers=[reg(reset="0x5")])),
    ("reset-width-16", doc(bus_width=16, registers=[reg(reset="0x5")])),
    ("reset-big", regs(reg(reset="0x1ffffffffffffffffff"))),
    ("enum", regs(reg(fields=[fld("Mode", 0, 1, enum={"A": 0, "B": 1, "C": 3})]))),
    ("enum-mixed-case", regs(reg(fields=[fld("Mode", 0, 1, enum={"None": 0, "evenParity": 1, "ODD": 2})]))),
    ("enum-negative", regs(reg(fields=[fld("Mode", 0, 1, enum={"A": -1})]))),
    ("enum-empty", regs(reg(fields=[fld("Mode", 0, 1, enum={})]))),
    ("enum-two-fields", regs(reg("A", "0x0", fields=[fld("M", 0, 1, enum={"X": 0})]), reg("B", "0x4", fields=[fld("M", 0, 1, enum={"X": 0})]))),
    ("enum-on-ro", regs(reg(kind="RO", fields=[fld("Mode", 0, 1, enum={"A": 0})]))),
    ("enum-big-value", regs(reg(fields=[fld("Mode", 0, 31, enum={"A": 4294967295})]))),
    ("names-camel", regs(reg("TxFifoLevel", "0x0"), reg("rxFifo", "0x4"))),
    ("names-caps-run", regs(reg("HTTPServer", "0x0"), reg("UARTRx", "0x4"))),
    ("names-digits", regs(reg("Reg2Name", "0x0"), reg("Fld3X", "0x4"))),
    ("names-underscore", regs(reg("a__b", "0x0"), reg("_a", "0x4"), reg("a_", "0x8"))),
    ("names-all-caps", regs(reg("CTRL", "0x0"))),
    ("names-lower", regs(reg("ctrl", "0x0"))),
    ("names-same-snake", regs(reg("TxEn", "0x0"), reg("tx_en", "0x4"))),
    ("block-camel", doc(name="UartRegs")),
    ("block-caps-run", doc(name="UartCTRLx")),
    ("block-lower", doc(name="uart")),
    ("block-underscore", doc(name="Uart_Regs")),
    ("block-digit", doc(name="Uart2Block")),
    ("block-digit-capital", doc(name="Server2Name")),
    ("block-dash", doc(name="A-B")),
    ("block-space", doc(name="x y")),
    ("block-empty", doc(name="")),
    ("block-non-ascii", doc(name="Écrit")),
    ("register-non-ascii", regs(reg("Régistre"))),
    ("field-non-ascii", regs(reg("R", fields=[fld("Fé")]))),
    ("enum-non-ascii", regs(reg("R", fields=[fld("M", 0, 1, enum={"É": 0})]))),
    ("block-backslash", doc(name="a\\b")),
    ("registers-descending", regs(reg("B", "0x8"), reg("A", "0x0"))),
    ("registers-equal-offsets", regs(reg("B", "0x4"), reg("A", "0x4"))),
    ("registers-offset-case", regs(reg("A", "0xAB"), reg("B", "0xab0"))),
    ("registers-far", regs(reg("A", "0x10000"), reg("B", "0x0"))),
    ("registers-no-fields", regs(reg("A", "0x0"), reg("B", "0x4", fields=[fld()]))),
    ("base-zero", doc(base_address="0x0")),
    ("base-small", doc(base_address="0x10")),
    ("base-upper", doc(base_address="0x4000ABCD")),
    ("base-underscore", doc(base_address="0x4000_0000")),
    ("base-past-32", doc(base_address="0x100000000")),
    ("base-past-2^60", doc(base_address="0x1ffffffffffffffffff")),
    ("offset-past-2^60", regs(reg("Z", "0x1000000000000000000", "WO"))),
    ("no-registers", doc(registers=[])),
    ("big-endian", doc(endianness="big")),
    ("float-bus-width", doc(bus_width=32.0, registers=[reg()])),
]


def hostile_inputs():
    """Large contracts: the answer must be linear and equal to Python's."""
    def block(regs, name="Big", intrs=None):
        d = {"version": "0.1.0", "block": {"name": name, "base_address": "0x1000", "bus_width": 32, "endianness": "little", "registers": regs}}
        if intrs:
            d["block"]["interrupts"] = intrs
        return d
    regs = [{"name": f"R{i}", "offset": hex(i * 4), "kind": "RW"} for i in range(20000)]
    intrs = [{"name": f"i{i}", "number": i} for i in range(5000)]
    return [
        ("20000 registers, reversed", block(list(reversed(regs)))),
        ("5000 interrupts", block([{"name": "R", "offset": "0x0", "kind": "RW"}], "B", intrs)),
        ("a 100000-byte block name", block([{"name": "R", "offset": "0x0", "kind": "RW"}], "B" * 100000)),
        ("a 100000-letter camel-case name", block([{"name": "R", "offset": "0x0", "kind": "RW"}], "Ab" * 50000)),
    ]


def generator_inputs():
    import json
    for label, d in GENERATOR_INPUTS + hostile_inputs():
        yield f"gen:{label}", json.dumps(d, indent=2, ensure_ascii=False)


def main():
    jobs = 4
    if "--jobs" in sys.argv:
        jobs = int(sys.argv[sys.argv.index("--jobs") + 1])
    bad = []
    tally = collections.Counter()
    with tempfile.TemporaryDirectory() as tmp:
        # 1. fixtures
        for f in ([] if "--handmade-only" in sys.argv else check_json.fixture_files()):
            rel = str(f.relative_to(ROOT))
            text = f.read_text()
            py = python_run(rel)
            tags, problem = judge(tmp, rel, text, py, rel)
            tally["fixtures"] += 1
            tally.update(f"fixture:{t}" for t in tags)
            if problem:
                bad.append(problem)
        print(f"fixtures: {tally['fixtures']} files; identical to generate.py on {tally['fixture:identical']}"
              f" ({tally['fixture:rc0']} generate declarations, {tally['fixture:rc1']} are refused, {tally['fixture:rc2']} exit 2),"
              f" {sum(v for k, v in tally.items() if k.startswith('fixture:known:'))} known differences")
        if "--fixtures-only" in sys.argv:
            for b in bad:
                print("UNEXPLAINED", b)
            sys.exit(1 if bad else 0)

        # 2 and 3. mutants and hand-made inputs
        inputs = []
        seen = set()
        pool_of_inputs = list(generator_inputs()) if "--handmade-only" in sys.argv else list(check_json.mutants()) + list(generator_inputs())
        for label, text in pool_of_inputs:
            if text in seen:
                tally["duplicate-input-skipped"] += 1
                continue
            seen.add(text)
            inputs.append((label, text))
        work = pathlib.Path(tmp) / "m"
        work.mkdir()
        pys = []
        for n, (label, text) in enumerate(inputs):
            path = str(work / f"m{n}.chw")
            pathlib.Path(path).write_text(text, encoding="utf-8")
            pys.append(python_run(path))
        with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
            futs = []
            for n, (label, text) in enumerate(inputs):
                path = str(work / f"m{n}.chw")
                cdir = pathlib.Path(tmp) / f"c{n % jobs}"
                cdir.mkdir(exist_ok=True)
                futs.append(pool.submit(judge, str(cdir), label, text, pys[n], path))
            for fu in futs:
                tags, problem = fu.result()
                tally["inputs"] += 1
                tally.update(tags)
                if problem:
                    bad.append(problem)
    # A source path is a third input of the generator (the banner carries it).
    import json as _json
    with tempfile.TemporaryDirectory() as tmp2:
        for name in ("a&b.chw", "a<b.chw", "a--b.chw", "a b.chw", "\u00e9.chw"):
            path = str(pathlib.Path(tmp2) / name)
            text = _json.dumps(GENERATOR_INPUTS[0][1])
            pathlib.Path(path).write_text(text, encoding="utf-8")
            tags, problem = judge(tmp2, f"path:{name}", text, python_run(path), path)
            tally["inputs"] += 1
            tally.update(tags)
            if problem:
                bad.append(problem)
    print(f"inputs: {tally['inputs']} distinct ({tally['duplicate-input-skipped']} repeats skipped)")
    print(f"  stdout, stderr and exit status identical to generate.py: {tally['identical']}"
          f" (declarations written on {tally['rc0']}, refused on {tally['rc1']})")
    print(f"  known differences: checker {tally['known:checker']}, non-ASCII name {tally['known:non-ascii-name']},"
          f" both internal {tally['known:both-internal']}, float bus width {tally['known:float-bus-width']}")
    crashes = sum(v for k, v in tally.items() if k.startswith("python-crash:"))
    print(f"  generate.py raised, cancho answered with exit 0 or 1 and no trap: {crashes}")
    for k in sorted(tally):
        if k.startswith("python-crash:"):
            print(f"  {k}: {tally[k]}")
    print(f"{len(bad)} unexplained differences")
    for b in bad[:400]:
        print("UNEXPLAINED", b)
    sys.exit(1 if bad else 0)


main()
