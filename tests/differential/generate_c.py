"""Test-only oracle driver for stage 3 (docs/cancho-port.md, 17.5): compare the cancho C header
generator (`chw generate FILE --target c-header`) with the Python tool
(`tools/generate/generate.py --target c-header FILE`).

Three parts.

  1. Fixtures. Every valid example, refusal fixture, tests/stage1 and tests/stage2 file is run
     through both command lines; exit status, standard output and standard error are compared
     byte for byte. Each header either tool produces for a fixture is compiled with
     `cc -std=c11 -Wall -Wextra -Werror -fsyntax-only` (the contract of spec/generators 2.1).
  2. Mutants. The same mutants as tests/differential/check_json.py (imported, not copied), run
     through both command lines. The Python side runs in this process, serially; the cancho side
     in a pool. A difference must fall in a class below; anything else is UNEXPLAINED and fails.
  3. Hand-made inputs that only a generator can get wrong: names a C header cannot spell.

Known classes, each with its reason:

  checker-known      the two checkers differ on this input in a class check_json.py already
                     explains (docs/cancho-port.md 13.5), so the refusal text differs.
  python-crash       the Python tool raised (checker.py assumes a schema-valid shape); cancho must
                     still answer, with exit 0 or 1 and never a trap.
  unspellable        cancho refuses a name the header cannot spell (generator-unimplemented) and
                     the Python tool wrote a header anyway. Admitted only if that header really
                     does not compile; if it compiles, cancho refused too much and the run fails.
  non-ascii-name     the one case where the Python header does compile: a name with a non-ASCII
                     letter or a JSON escape. cancho writes ASCII names only (17.4) and refuses
                     the rest; gcc and clang accept UTF-8 identifiers, MSVC and older compilers
                     do not. A narrowing, stated in the document, not a claim of equal output.
  python-float-width-crash  `"bus_width": 32.0`: the Python tool raises on `32.0 // 4` in an integer format
                     (exit 3, error[internal]); cancho reads the integer and writes a header, admitted
                     only if that header compiles.
  both-internal      both tools answer `internal` (an IR the checker should have caught, e.g. a field
                     outside a float bus width the checker reads as 32); each says it in its own words.
  offset-past-2^60   a DMA offset of 2^60 or more: cancho's integers are exact below 2^60 (hexval.cho), so it
                     refuses; Python writes an array that many bytes long. A limit of the port.
  python-float-width a width written as `3.2e1` is a valid integer to the schema; the Python tool
                     writes `32.0` into C (`uint32_t x : 31.0;`), which does not compile. Admitted
                     only if the cancho header compiles and the two are equal once `N.0` is read as `N`
                     (a width used only in a macro still compiles as `8.0`).

Usage:

    python3 tests/differential/generate_c.py /path/to/built/chw [--jobs N] [--fixtures-only | --handmade-only] [--compile-mutants]

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

if __import__('shutil').which('cc') is None:
    sys.exit('generate_c.py needs a C compiler (cc): two known-difference classes are admitted only by compiling')
EXE = sys.argv[1]
TARGET = "c-header"


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


def compiles(header, tmp):
    """-> (ok, first line of the compiler's complaint)"""
    d = pathlib.Path(tempfile.mkdtemp(dir=tmp))  # one directory per call: the pool runs several at once
    (d / "x.h").write_text(header)
    (d / "x.c").write_text('#include "x.h"\nint main(void) { return 0; }\n')
    p = subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-fsyntax-only", str(d / "x.c")],
                       capture_output=True, text=True, errors="replace")
    import shutil
    shutil.rmtree(d, ignore_errors=True)
    first = next((l for l in p.stderr.splitlines() if "error" in l), p.stderr.strip()[:120])
    return p.returncode == 0, first[:160]


def checker_known(tmp, label, text):
    """Is this input one on which the two checkers differ in a known class?"""
    tags, problem = check_json.judge(tmp, label, text)
    return problem is None and any(t.startswith("known:") for t in tags)


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
        return tags, None
    if py[0] == 0 and ca[0] == 1 and "error[generator-unimplemented]: target c-header:" in ca[2]:
        ok, why = compiles(py[1], tmp)
        if ok and "is past 2^60" in ca[2]:
            return ["known:offset-past-2^60"], None
        if ok:
            # gcc and clang accept UTF-8 in identifiers; cancho writes ASCII names only (17.4), so a
            # name with a non-ASCII letter or a JSON escape is refused although Python writes it.
            if re.search(r"[^\x00-\x7f]|\\", text) and re.search(r"is not (a C identifier|usable as a C member)|cannot be written inside a C comment", ca[2]):
                return ["known:non-ascii-name"], None
            return [], f"{label}: cancho refused ({ca[2].strip()[:100]}) but Python's header compiles"
        return ["known:unspellable"], None
    if py[0] == 3 and ca[0] == 3:
        # Both refuse as `internal` (an IR the checker should have caught); the messages are each tool's own.
        return ["known:both-internal"], None
    if py[0] == 0 and ca[0] == 1 and "is past 2^60" in ca[2]:
        # A DMA offset of 2^60 or more: cancho's integers are exact below 2^60 (hexval.cho). Python writes an
        # array of that many bytes, which a 64-bit compiler accepts. A limit of the port, stated in 17.4.
        return ["known:offset-past-2^60"], None
    if py[0] == 3 and ca[0] == 0 and "Precision not allowed in integer format specifier" in py[2]:
        # `"bus_width": 32.0`: the Python tool formats `32.0 // 4` with an integer format and raises.
        ca_ok, _ = compiles(ca[1], tmp)
        if ca_ok:
            return ["known:python-float-width-crash"], None
    if py[0] == 0 and ca[0] == 0:
        # `"bus_width": 3.2e1` is a valid integer to the schema; Python prints it as `32.0` in C.
        fixed = re.sub(r"(?<![\w.])(\d+)\.0\b", r"\1", py[1])
        py_ok, _ = compiles(py[1], tmp)
        ca_ok, _ = compiles(ca[1], tmp)
        if ca_ok and fixed == ca[1]:
            return ["known:python-float-width"], None
    if checker_known(tmp, label, text):
        return ["known:checker"], None
    return [], f"{label}: rc python={py[0]} cancho={ca[0]}\n   python stderr: {py[2].strip()[:140]}\n   cancho stderr: {ca[2].strip()[:140]}"


# hand-made inputs a generator can get wrong (docs/cancho-port.md 17.5, item 3)
def doc(**over):
    d = {"version": "0.1.0", "block": {"name": "Blk", "base_address": "0x40000000", "bus_width": 32, "endianness": "little",
                                      "registers": [{"name": "CTRL", "offset": "0x0", "kind": "RW", "reset": "0x1",
                                                     "fields": [{"name": "EN", "lsb": 0, "msb": 0, "enum": {"Off": 0, "On": 1}}]}]}}
    for k, v in over.items():
        d["block"][k] = v
    return d


def named(reg=None, field=None, block=None, label=None, buf=None, dfield=None, owner=None):
    d = doc()
    if block is not None:
        d["block"]["name"] = block
    if reg is not None:
        d["block"]["registers"][0]["name"] = reg
    if field is not None:
        d["block"]["registers"][0]["fields"][0]["name"] = field
    if label is not None:
        d["block"]["registers"][0]["fields"][0]["enum"] = {label: 0}
    if buf is not None or dfield is not None or owner is not None:
        d["dma_buffers"] = [{"name": buf or "Buf", "fields": [{"name": dfield or "f", "offset": "0x0", "owner": owner or "CPU"}]}]
    return d


GENERATOR_INPUTS = [
    ("plain", doc()),
    ("keyword-register", named(reg="INT")),
    ("keyword-field", named(field="Register")),
    ("keyword-dma-field", named(dfield="while")),
    ("dash-register", named(reg="A-B")),
    ("space-field", named(field="x y")),
    ("digit-first-block", named(block="9Blk")),
    ("comment-end-in-label", named(label="a*/b")),
    ("comment-start-in-label", named(label="a/*b")),
    ("backslash-label", named(label="a\\b")),
    ("star-slash-register", named(reg="A*/B")),
    ("non-ascii-register", named(reg="Écrit")),
    ("empty-register", named(reg="")),
    ("keyword-block", named(block="int")),
    ("keyword-buffer", named(buf="for", dfield="g")),
    ("owner-cpu-device", named(buf="B", dfield="g", owner="DEVICE")),
    ("width-8", doc(bus_width=8)),
    ("width-16", doc(bus_width=16)),
    ("big-base", doc(base_address="0x1ffffffffffffffffff")),
    ("no-registers", doc(registers=[])),
    ("no-fields", {"version": "0.1.0", "block": {"name": "B", "base_address": "0x0", "bus_width": 32, "endianness": "little", "registers": [{"name": "R", "offset": "0x4", "kind": "RO"}]}}),
    ("gaps", {"version": "0.1.0", "block": {"name": "Gp", "base_address": "0x10", "bus_width": 32, "endianness": "little", "registers": [
        {"name": "Z", "offset": "0x20", "kind": "WO", "fields": [{"name": "hi", "lsb": 28, "msb": 31}, {"name": "lo", "lsb": 2, "msb": 5}]},
        {"name": "A", "offset": "0x0", "kind": "W1C", "reset": "0xff", "fields": [{"name": "x", "lsb": 0, "msb": 7}]}]}}),
    ("abbreviations", named(block="UartCTRLx", reg="HTTPServer2", field="getHTTPCode")),
]


def hostile_inputs():
    """Large contracts, in the order that is worst for a naive sort: the answer must be linear and equal to Python's."""
    def block(regs, dma=None, name="Big"):
        d = {"version": "0.1.0", "block": {"name": name, "base_address": "0x1000", "bus_width": 32, "endianness": "little", "registers": regs}}
        if dma:
            d["dma_buffers"] = dma
        return d
    regs = [{"name": f"R{i}", "offset": hex(i * 4), "kind": "RW", "fields": [{"name": "A", "lsb": 0, "msb": 7}, {"name": "B", "lsb": 8, "msb": 15}]} for i in range(20000)]
    dfields = [{"name": f"f{i}", "offset": hex(i * 4), "owner": "CPU"} for i in range(20000)]
    return [
        ("20000 registers, reversed", block(list(reversed(regs)))),
        ("20000 DMA fields, reversed", block([{"name": "R", "offset": "0x0", "kind": "RW"}], [{"name": "D", "fields": list(reversed(dfields))}], "B")),
        ("a 100000-byte block name", block([{"name": "R", "offset": "0x0", "kind": "RW"}], None, "B" * 100000)),
        ("32 one-bit fields, reversed", block([{"name": "R", "offset": "0x0", "kind": "RW", "fields": [{"name": f"F{i}", "lsb": i, "msb": i} for i in reversed(range(32))]}], None, "B")),
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
        print(f"  headers that compile with -std=c11 -Wall -Wextra -Werror: {tally['fixture:compiles']}"
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
          f" non-ASCII name {tally['known:non-ascii-name']}, float width {tally['known:python-float-width']} + {tally['known:python-float-width-crash']} crashes,"
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
