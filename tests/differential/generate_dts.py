"""Test-only oracle driver for stage 4 (docs/cancho-port.md, 20.5): compare the cancho device-tree generator
(`chw generate FILE --target devicetree`) with the Python tool (`oracle/legacy/tools/generate/generate.py --target devicetree FILE`).

The same three parts as generate_c.py (which this file copies the shape of; that file runs on import, so it cannot
be imported):

  1. Fixtures: every valid example, refusal fixture, tests/stage1 and tests/stage2 file through both command lines;
     exit status, standard output and standard error compared byte for byte. Each fragment either tool produces is
     compiled with `dtc -I dts -O dtb` inside a small tree that defines the `soc` node and the `intc` label the
     fragment refers to (the contract of spec/generators 4).
  2. Mutants: the mutants of tests/differential/check_json.py (imported, not copied).
  3. Hand-made inputs only a generator can get wrong: names a label cannot spell, versions, bases past 32 bits,
     interrupts, a block with no register.

Known classes, each with its reason:

  checker-known      the two checkers differ on this input in a class check_json.py already explains.
  python-crash       the Python tool raised; cancho must still answer with exit 0 or 1 and never a trap.
  unspellable        cancho refuses a name the fragment cannot carry and the Python tool wrote one anyway. Admitted only
                     if that fragment really does not compile with dtc.
  non-ascii-name     the Python fragment compiles, but the name has a non-ASCII byte or a JSON escape; cancho writes ASCII
                     only and refuses the rest. A narrowing, stated in the document.
  both-internal      both tools answer `internal`; each says it in its own words.
  offset-past-2^60   a register offset of 2^60 or more: cancho's integers are exact below 2^60 (hexval.cho), so it
                     refuses; Python sizes a range from it. A limit of the port.
  python-float-width-crash  `"bus_width": 32.0`: Python formats `4.0` with an integer format and raises (exit 3);
                     cancho reads the integer and writes a fragment, admitted only if it compiles.

Usage:

    python3 tests/differential/generate_dts.py /path/to/built/chw [--jobs N] [--fixtures-only | --handmade-only] [--compile-mutants]

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

sys.path.insert(0, str(ROOT / "oracle" / "legacy" / "tools" / "generate"))
import generate as pygen  # noqa: E402  (the oracle)

if __import__('shutil').which('dtc') is None:
    sys.exit('generate_dts.py needs dtc (device-tree-compiler): the known-difference classes are admitted only by compiling')
EXE = sys.argv[1]
TARGET = "devicetree"


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


TREE = "/dts-v1/;\n/ {\n    #address-cells = <1>;\n    #size-cells = <1>;\n    soc: soc {\n        #address-cells = <1>;\n        #size-cells = <1>;\n    };\n    intc: interrupt-controller {\n        interrupt-controller;\n        #interrupt-cells = <2>;\n    };\n};\n"


def compiles(fragment, tmp):
    """-> (ok, first line of dtc's complaint). The fragment is appended to a tree that has `soc` and `intc`."""
    d = pathlib.Path(tempfile.mkdtemp(dir=tmp))  # one directory per call: the pool runs several at once
    (d / "x.dts").write_text(TREE + fragment)
    p = subprocess.run(["dtc", "-I", "dts", "-O", "dtb", "-o", "/dev/null", str(d / "x.dts")],
                       capture_output=True, text=True, errors="replace")
    import shutil
    shutil.rmtree(d, ignore_errors=True)
    first = next((l for l in p.stderr.splitlines() if "rror" in l), p.stderr.strip()[:120])
    return p.returncode == 0, first[:160]


def checker_known(tmp, label, text):
    """Is this input one on which the two checkers differ in a known class?"""
    tags, problem = check_json.judge(tmp, label, text)
    return problem is None and any(t.startswith("known:") for t in tags)


# Hand-made inputs whose fragment cannot compile in the oracle's tree, and the generator (Python and cancho alike) writes it:
# a block called `soc` or `intc` redefines a label of the tree the fragment is appended to. Stated in docs/cancho-port.md 21.3.
SHARED_DEFECTS = {"gen:soc-block", "gen:intc-block"}


def judge(tmp, label, text, py, path, compile_it):
    """-> (tags, unexplained or None)"""
    ca = cancho_run(path)
    if ca[0] not in (0, 1, 2, 3):
        return [], f"{label}: cancho exited {ca[0]} (a trap or a signal): {ca[2].strip()[:120]}"
    if py[0] == "crash":
        return [f"python-crash:{py[2]}"], None if ca[0] in (0, 1) else f"{label}: python raised and cancho exited {ca[0]}"
    if py == ca:
        tags = ["identical", f"rc{ca[0]}"]
        if ca[0] == 0 and compile_it:
            ok, why = compiles(ca[1], tmp)
            tags.append("compiles" if ok else "shared-defect:does-not-compile")
            if not ok and label.startswith("gen:") and label not in SHARED_DEFECTS:
                # A hand-made input whose Python fragment does not compile must be refused by cancho (unspellable);
                # writing the same broken fragment is not an agreement to admit.
                return tags, f"{label}: cancho writes the fragment Python writes, and dtc rejects it ({why})"
        return tags, None
    if py[0] == 0 and ca[0] == 1 and "error[generator-unimplemented]: target devicetree:" in ca[2]:
        ok, why = compiles(py[1], tmp)
        if ok and "is past 2^60" in ca[2]:
            return ["known:offset-past-2^60"], None
        if ok:
            # cancho writes ASCII names only, so a name with a non-ASCII letter or a JSON escape is refused although
            # Python writes it.
            if re.search(r"[^\x00-\x7f]|\\", text) and re.search(r"is not a device-tree label|cannot be written inside", ca[2]):
                return ["known:non-ascii-name"], None
            return [], f"{label}: cancho refused ({ca[2].strip()[:100]}) but Python's fragment compiles"
        return ["known:unspellable"], None
    if py[0] == 3 and ca[0] == 3:
        # Both refuse as `internal` (an IR the checker should have caught); the messages are each tool's own.
        return ["known:both-internal"], None
    if py[0] == 0 and ca[0] == 1 and "is past 2^60" in ca[2]:
        # A register offset of 2^60 or more: cancho's integers are exact below 2^60 (hexval.cho). A limit of the port.
        return ["known:offset-past-2^60"], None
    if py[0] == 3 and ca[0] == 0 and "Unknown format code" in py[2]:
        # `"bus_width": 32.0`: the Python tool formats `4.0` with `X` and raises.
        ca_ok, _ = compiles(ca[1], tmp)
        if ca_ok:
            return ["known:python-float-width-crash"], None
    if checker_known(tmp, label, text):
        return ["known:checker"], None
    return [], f"{label}: rc python={py[0]} cancho={ca[0]}\n   python stderr: {py[2].strip()[:140]}\n   cancho stderr: {ca[2].strip()[:140]}"


# hand-made inputs a generator can get wrong (docs/cancho-port.md 20.5, item 3)
def doc(**over):
    d = {"version": "0.1.0", "block": {"name": "Blk", "base_address": "0x40000000", "bus_width": 32, "endianness": "little",
                                      "registers": [{"name": "CTRL", "offset": "0x0", "kind": "RW", "reset": "0x1",
                                                     "fields": [{"name": "EN", "lsb": 0, "msb": 0}]}]}}
    for k, v in over.items():
        d["block"][k] = v
    return d


def with_interrupts(names, block="Blk", **over):
    d = doc(name=block, **over)
    d["block"]["interrupts"] = [{"name": n, "number": 3 + i} for i, n in enumerate(names)]
    return d


def named(block=None, intr=None, version=None):
    d = doc() if intr is None else with_interrupts([intr])
    if block is not None:
        d["block"]["name"] = block
    if version is not None:
        d["version"] = version
    return d


GENERATOR_INPUTS = [
    ("plain", doc()),
    ("one-interrupt", with_interrupts(["done"])),
    ("two-interrupts", with_interrupts(["rx", "tx"])),
    ("many-interrupts", with_interrupts([f"irq{i}" for i in range(9)])),
    ("big-irq-number", {**with_interrupts(["a"]), "block": {**with_interrupts(["a"])["block"], "interrupts": [{"name": "a", "number": 1000000}]}}),
    ("width-8", doc(bus_width=8)),
    ("width-16", doc(bus_width=16)),
    ("base-zero", doc(base_address="0x0")),
    ("base-max-32", doc(base_address="0xffffffff")),
    ("base-past-32", doc(base_address="0x100000000")),
    ("base-past-2^60", doc(base_address="0x1ffffffffffffffffff")),
    ("base-underscore", doc(base_address="0x4000_0000")),
    ("base-upper-x", doc(base_address="0x4000ABCD")),
    ("no-registers", doc(registers=[])),
    ("far-register", {"version": "0.1.0", "block": {"name": "Far", "base_address": "0x10", "bus_width": 16, "endianness": "little", "registers": [
        {"name": "Z", "offset": "0x1000", "kind": "WO", "fields": [{"name": "hi", "lsb": 12, "msb": 15}]},
        {"name": "A", "offset": "0x0", "kind": "RO"}]}}),
    ("register-past-2^60", {"version": "0.1.0", "block": {"name": "Far", "base_address": "0x10", "bus_width": 32, "endianness": "little", "registers": [
        {"name": "Z", "offset": "0x1000000000000000000", "kind": "WO"}]}}),
    ("version-0", named(version="0.9.0")),
    ("version-2", named(version="2.0.0")),
    ("version-10", named(version="10.20.30")),
    ("abbreviations", named(block="UartCTRLx")),
    ("abbreviation-2", named(block="HTTPServer2Name")),
    ("digit-capital", named(block="Uart2Block")),
    ("all-caps", named(block="UART")),
    ("underscore", named(block="Uart_Regs")),
    ("lower-with-capital-run", named(block="aBCd")),
    ("block-keyword", named(block="int")),
    ("digit-first-block", named(block="9Blk")),
    ("dash-block", named(block="A-B")),
    ("space-block", named(block="x y")),
    ("empty-block", named(block="")),
    ("non-ascii-block", named(block="Écrit")),
    ("star-slash-block", named(block="A*/B")),
    ("comment-end-in-interrupt", named(intr="a*/b")),
    ("comment-start-in-interrupt", named(intr="a/*b")),
    ("backslash-interrupt", named(intr="a\\b")),
    ("dash-interrupt", named(intr="tx-done")),
    ("soc-block", named(block="soc")),
    ("intc-block", named(block="intc")),
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
    compile_mutants = "--compile-mutants" in sys.argv
    bad = []
    tally = collections.Counter()
    with tempfile.TemporaryDirectory() as tmp:
        # 1. fixtures
        for f in ([] if "--handmade-only" in sys.argv else check_json.fixture_files()):
            rel = str(f.relative_to(ROOT))
            text = f.read_text()
            py = python_run(rel)
            tags, problem = judge(tmp, rel, text, py, rel, True)
            tally["fixtures"] += 1
            tally.update(f"fixture:{t}" for t in tags)
            if problem:
                bad.append(problem)
        print(f"fixtures: {tally['fixtures']} files; identical to generate.py on {tally['fixture:identical']}"
              f" ({tally['fixture:rc0']} generate a header, {tally['fixture:rc1']} are refused, {tally['fixture:rc2']} exit 2),"
              f" {sum(v for k, v in tally.items() if k.startswith('fixture:known:'))} known differences")
        print(f"  headers that compile with dtc: {tally['fixture:compiles']}"
              f" of {tally['fixture:rc0']}; do not: {tally['fixture:shared-defect:does-not-compile']}")
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
                want_compile = compile_mutants or label.startswith("gen:")
                futs.append(pool.submit(judge, str(cdir), label, text, pys[n], path, want_compile))
            for fu in futs:
                tags, problem = fu.result()
                tally["inputs"] += 1
                tally.update(tags)
                if problem:
                    bad.append(problem)
    print(f"inputs: {tally['inputs']} distinct ({tally['duplicate-input-skipped']} repeats skipped)")
    print(f"  stdout, stderr and exit status identical to generate.py: {tally['identical']}"
          f" (header written on {tally['rc0']}, refused on {tally['rc1']})")
    print(f"  known differences: checker {tally['known:checker']}, unspellable name {tally['known:unspellable']},"
          f" non-ASCII name {tally['known:non-ascii-name']}, float width crash {tally['known:python-float-width-crash']},"
          f" both internal {tally['known:both-internal']}, offset past 2^60 {tally['known:offset-past-2^60']}")
    crashes = sum(v for k, v in tally.items() if k.startswith("python-crash:"))
    print(f"  generate.py raised, cancho answered with exit 0 or 1 and no trap: {crashes}")
    for k in sorted(tally):
        if k.startswith("python-crash:") or k.startswith("shared-defect:") or k == "compiles":
            print(f"  {k}: {tally[k]}")
    print(f"{len(bad)} unexplained differences")
    for b in bad[:400]:
        print("UNEXPLAINED", b)
    sys.exit(1 if bad else 0)


main()
