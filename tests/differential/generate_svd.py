"""Test-only oracle driver for stage 5 (docs/cancho-port.md, 23.5): compare the cancho CMSIS-SVD generator
(`chw generate FILE --target svd`) with the Python tool (`oracle/legacy/tools/generate/generate.py --target svd FILE`).

The same three parts as generate_dts.py (which this file copies the shape of; that file runs on import, so it cannot
be imported):

  1. Fixtures: every valid example, refusal fixture, tests/stage1 and tests/stage2 file through both command lines;
     exit status, standard output and standard error compared byte for byte. Each document either tool produces is
     checked with `xmllint --noout` (well-formed) and `xmllint --schema spec/generators/CMSIS-SVD.xsd` (valid).
  2. Mutants: the mutants of tests/differential/check_json.py (imported, not copied).
  3. Hand-made inputs only a generator can get wrong: every access kind, resets, enums, interrupts, DMA buffers,
     names that need XML escaping or carry `--`, bases past 2^60, a source path with markup.

Known classes, each with its reason:

  checker-known      the two checkers differ on this input in a class check_json.py already explains.
  python-crash       the Python tool raised; cancho must still answer with exit 0 or 1 and never a trap.
  unspellable        cancho refuses a path with markup (Python writes it unescaped into <description>). Admitted only
                     if Python's document is not well-formed.
  non-ascii-name     the Python document is well-formed, but a name has a non-ASCII byte or a JSON escape; cancho writes
                     ASCII only and refuses the rest. A narrowing, stated in the document.
  both-internal      both tools answer `internal`; each says it in its own words.
  offset-past-2^60   a register offset of 2^60 or more: cancho's integers are exact below 2^60 (hexval.cho).
  python-float-width-crash  `"bus_width": 32.0`: Python formats `8.0` with an integer format and raises.
  float-irq-number   `"number": 4.0`: an integer to the schema; Python writes `IRQ 4.0` in a comment, cancho `IRQ 4`.
                     Admitted only if that is the whole difference.

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

if __import__('shutil').which('xmllint') is None:
    sys.exit('generate_svd.py needs xmllint (libxml2-utils): the known-difference classes are admitted only by checking the XML')
EXE = sys.argv[1]
TARGET = "svd"
XSD = str(ROOT / "spec" / "generators" / "CMSIS-SVD.xsd")


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


import shutil


def well_formed(document, tmp):
    """-> (ok, first line of xmllint's complaint)."""
    d = pathlib.Path(tempfile.mkdtemp(dir=tmp))  # one directory per call: the pool runs several at once
    (d / "x.svd").write_text(document, encoding="utf-8")
    p = subprocess.run(["xmllint", "--noout", str(d / "x.svd")], capture_output=True, text=True, errors="replace")
    shutil.rmtree(d, ignore_errors=True)
    first = next((l for l in p.stderr.splitlines() if "rror" in l), p.stderr.strip()[:120])
    return p.returncode == 0, first[:160]


def schema_valid(document, tmp):
    d = pathlib.Path(tempfile.mkdtemp(dir=tmp))
    (d / "x.svd").write_text(document, encoding="utf-8")
    p = subprocess.run(["xmllint", "--noout", "--schema", XSD, str(d / "x.svd")], capture_output=True, text=True, errors="replace")
    shutil.rmtree(d, ignore_errors=True)
    return p.returncode == 0


def checker_known(tmp, label, text):
    """Is this input one on which the two checkers differ in a known class?"""
    tags, problem = check_json.judge(tmp, label, text)
    return problem is None and any(t.startswith("known:") for t in tags)


def judge(tmp, label, text, py, path, check_xml):
    """-> (tags, unexplained or None)"""
    ca = cancho_run(path)
    if ca[0] not in (0, 1, 2, 3):
        return [], f"{label}: cancho exited {ca[0]} (a trap or a signal): {ca[2].strip()[:120]}"
    if py[0] == "crash":
        return [f"python-crash:{py[2]}"], None if ca[0] in (0, 1) else f"{label}: python raised and cancho exited {ca[0]}"
    if py == ca:
        tags = ["identical", f"rc{ca[0]}"]
        if ca[0] == 0 and check_xml:
            ok, why = well_formed(ca[1], tmp)
            tags.append("well-formed" if ok else "shared-defect:not-well-formed")
            if ok:
                tags.append("schema-valid" if schema_valid(ca[1], tmp) else "schema-invalid")
            if not ok:
                # Both tools write the same document, and it is not XML: only a hand-made input is expected to be clean.
                return tags, f"{label}: cancho writes the document Python writes, and xmllint rejects it ({why})"
        return tags, None
    if py[0] == 0 and ca[0] == 1 and "error[generator-unimplemented]: target svd:" in ca[2]:
        ok, why = well_formed(py[1], tmp)
        if ok and "is past 2^60" in ca[2]:
            return ["known:offset-past-2^60"], None
        if ok:
            # cancho writes ASCII names only, so a name with a non-ASCII letter or a JSON escape is refused although
            # Python writes it.
            if re.search(r"[^\x00-\x7f]|\\", text) or "non-ASCII" in ca[2]:
                return ["known:non-ascii-name"], None
            return [], f"{label}: cancho refused ({ca[2].strip()[:100]}) but Python's document is well-formed"
        return ["known:unspellable"], None
    if py[0] == 3 and ca[0] == 3:
        # Both refuse as `internal` (an IR the checker should have caught); the messages are each tool's own.
        return ["known:both-internal"], None
    if py[0] == 0 and ca[0] == 1 and "is past 2^60" in ca[2]:
        return ["known:offset-past-2^60"], None
    if py[0] == 3 and ca[0] == 0 and "Unknown format code" in py[2]:
        # `"bus_width": 32.0`: the Python tool formats `8.0` with `X` and raises.
        ok, _ = well_formed(ca[1], tmp)
        if ok:
            return ["known:python-float-width-crash"], None
    if py[0] == 0 and ca[0] == 0 and re.search(r", IRQ \d+\.0 -->", py[1]):
        # `"number": 4.0` is an integer to the schema; Python prints the float it read (`IRQ 4.0`), cancho the integer.
        # Admitted only if that is the whole difference.
        if re.sub(r", IRQ (\d+)\.0 -->", r", IRQ \1 -->", py[1]) == ca[1] and py[2] == ca[2]:
            return ["known:float-irq-number"], None
    if checker_known(tmp, label, text):
        return ["known:checker"], None
    return [], f"{label}: rc python={py[0]} cancho={ca[0]}\n   python stderr: {py[2].strip()[:140]}\n   cancho stderr: {ca[2].strip()[:140]}"


# hand-made inputs a generator can get wrong (docs/cancho-port.md 23.5, item 3)
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


def with_reg(**reg):
    d = doc()
    r = {"name": "R", "offset": "0x4", "kind": "RW"}
    r.update(reg)
    d["block"]["registers"].append(r)
    return d


def with_dma(names):
    d = doc()
    d["dma_buffers"] = [{"name": n, "fields": [{"name": "f", "offset": "0x0", "owner": "CPU"}]} for n in names]
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
    ("big-irq-number", {**with_interrupts(["a"]), "block": {**with_interrupts(["a"])["block"], "interrupts": [{"name": "a", "number": 1000000}]}}),
    ("float-irq-number", {**with_interrupts(["a"]), "block": {**with_interrupts(["a"])["block"], "interrupts": [{"name": "a", "number": 4.0}]}}),
    ("one-dma", with_dma(["Tx"])),
    ("two-dma", with_dma(["Tx", "Rx"])),
    ("width-8", doc(bus_width=8)),
    ("width-16", doc(bus_width=16)),
    ("base-zero", doc(base_address="0x0")),
    ("base-max-32", doc(base_address="0xffffffff")),
    ("base-past-32", doc(base_address="0x100000000")),
    ("base-past-2^60", doc(base_address="0x1ffffffffffffffffff")),
    ("base-underscore", doc(base_address="0x4000_0000")),
    ("base-upper-x", doc(base_address="0x4000ABCD")),
    ("no-registers", doc(registers=[])),
    ("kind-RO", with_reg(kind="RO")),
    ("kind-WO", with_reg(kind="WO")),
    ("kind-RW", with_reg(kind="RW")),
    ("kind-RC", with_reg(kind="RC")),
    ("kind-W0C", with_reg(kind="W0C")),
    ("kind-W0S", with_reg(kind="W0S")),
    ("kind-W1C", with_reg(kind="W1C")),
    ("kind-W1S", with_reg(kind="W1S")),
    ("kind-unknown", with_reg(kind="XX")),
    ("reset-none", with_reg()),
    ("reset-zero", with_reg(reset="0x0")),
    ("reset-wide", with_reg(reset="0xdeadbeef")),
    ("reset-past-width", with_reg(reset="0x1ffffffff")),
    ("reset-underscore", with_reg(reset="0xab_cd")),
    ("reset-width-8", {**doc(bus_width=8), "block": {**doc(bus_width=8)["block"], "registers": [{"name": "R", "offset": "0x0", "kind": "RW", "reset": "0x5"}]}}),
    ("reset-big", with_reg(reset="0x1ffffffffffffffffff")),
    ("enum", with_reg(fields=[{"name": "MODE", "lsb": 0, "msb": 1, "enum": {"A": 0, "B": 1, "C": 3}}])),
    ("enum-escaped-label", with_reg(fields=[{"name": "MODE", "lsb": 0, "msb": 1, "enum": {"a&b": 0, "<c>": 1}}])),
    ("enum-dash-label", with_reg(fields=[{"name": "MODE", "lsb": 0, "msb": 1, "enum": {"a--b": 0}}])),
    ("enum-negative", with_reg(fields=[{"name": "MODE", "lsb": 0, "msb": 1, "enum": {"A": -1}}])),
    ("enum-empty", with_reg(fields=[{"name": "MODE", "lsb": 0, "msb": 1, "enum": {}}])),
    ("fields-several", with_reg(fields=[{"name": "A", "lsb": 0, "msb": 3}, {"name": "B", "lsb": 4, "msb": 7}, {"name": "C", "lsb": 31, "msb": 31}])),
    ("fields-none", with_reg(fields=[])),
    ("equal-offsets", {**doc(), "block": {**doc()["block"], "registers": [{"name": "B", "offset": "0x4", "kind": "RW"}, {"name": "A", "offset": "0x4", "kind": "RO"}]}}),
    ("reversed-offsets", {**doc(), "block": {**doc()["block"], "registers": [{"name": "B", "offset": "0x8", "kind": "RW"}, {"name": "A", "offset": "0x0", "kind": "RO"}, {"name": "C", "offset": "0x4", "kind": "RC"}]}}),
    ("far-register", {"version": "0.1.0", "block": {"name": "Far", "base_address": "0x10", "bus_width": 16, "endianness": "little", "registers": [
        {"name": "Z", "offset": "0x1000", "kind": "WO", "fields": [{"name": "hi", "lsb": 12, "msb": 15}]},
        {"name": "A", "offset": "0x0", "kind": "RO"}]}}),
    ("register-past-2^60", {"version": "0.1.0", "block": {"name": "Far", "base_address": "0x10", "bus_width": 32, "endianness": "little", "registers": [
        {"name": "Z", "offset": "0x1000000000000000000", "kind": "WO"}]}}),
    ("version-1", named(version="1.2.3")),
    ("version-escaped", named(version="1<2&3>")),
    ("version-dash", named(version="1--2")),
    ("block-escaped", named(block="A&B<C>D")),
    ("block-dash", named(block="A--B")),
    ("block-single-dash", named(block="A-B")),
    ("block-trailing-dash", named(block="A-")),
    ("block-quote", named(block="A\"B'C")),
    ("block-space", named(block="x y")),
    ("block-empty", named(block="")),
    ("block-non-ascii", named(block="Écrit")),
    ("block-star-slash", named(block="A*/B")),
    ("block-comment-end", named(block="A-->B")),
    ("interrupt-dash", named(intr="tx--done")),
    ("interrupt-single-dash", named(intr="tx-done")),
    ("interrupt-escaped", named(intr="a&b")),
    ("interrupt-backslash", named(intr="a\\b")),
    ("dma-dash", with_dma(["T--x"])),
    ("dma-escaped", with_dma(["T&x"])),
    ("register-dash", with_reg(name="R--x")),
    ("register-escaped", with_reg(name="R<x>")),
    ("register-non-ascii", with_reg(name="Régistre")),
    ("field-dash", with_reg(fields=[{"name": "F--x", "lsb": 0, "msb": 0}])),
    ("field-escaped", with_reg(fields=[{"name": "F&x", "lsb": 0, "msb": 0}])),
    ("dash-order-block-first", {**with_interrupts(["i--"], block="B--"), }),
    ("dash-order-interrupt-then-register", {**with_interrupts(["i--"]), "block": {**with_interrupts(["i--"])["block"], "registers": [{"name": "R--", "offset": "0x0", "kind": "RW"}]}}),
    ("dash-order-register-then-field", with_reg(name="R--", fields=[{"name": "F--", "lsb": 0, "msb": 0}])),
    ("dash-order-field-then-enum", with_reg(fields=[{"name": "F--", "lsb": 0, "msb": 1, "enum": {"E--": 0}}])),
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
              f" ({tally['fixture:rc0']} generate a document, {tally['fixture:rc1']} are refused, {tally['fixture:rc2']} exit 2),"
              f" {sum(v for k, v in tally.items() if k.startswith('fixture:known:'))} known differences")
        print(f"  documents well-formed for xmllint: {tally['fixture:well-formed']}"
              f" of {tally['fixture:rc0']}; schema-valid: {tally['fixture:schema-valid']}; do not validate: {tally['fixture:schema-invalid']}")
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
    # A source path is a third input of the generator (the banner and the description carry it unescaped).
    import json as _json
    with tempfile.TemporaryDirectory() as tmp2:
        for name in ("a&b.chw", "a<b.chw", "a>b.chw", "a--b.chw", "a b.chw", "\u00e9.chw"):
            path = str(pathlib.Path(tmp2) / name)
            text = _json.dumps(GENERATOR_INPUTS[0][1])
            pathlib.Path(path).write_text(text, encoding="utf-8")
            tags, problem = judge(tmp2, f"path:{name}", text, python_run(path), path, True)
            tally["inputs"] += 1
            tally.update(tags)
            if problem:
                bad.append(problem)
    print(f"inputs: {tally['inputs']} distinct ({tally['duplicate-input-skipped']} repeats skipped)")
    print(f"  stdout, stderr and exit status identical to generate.py: {tally['identical']}"
          f" (document written on {tally['rc0']}, refused on {tally['rc1']})")
    print(f"  known differences: checker {tally['known:checker']}, unspellable name {tally['known:unspellable']},"
          f" non-ASCII name {tally['known:non-ascii-name']}, float width crash {tally['known:python-float-width-crash']},"
          f" both internal {tally['known:both-internal']}, offset past 2^60 {tally['known:offset-past-2^60']},"
          f" float IRQ number {tally['known:float-irq-number']}")
    crashes = sum(v for k, v in tally.items() if k.startswith("python-crash:"))
    print(f"  generate.py raised, cancho answered with exit 0 or 1 and no trap: {crashes}")
    for k in sorted(tally):
        if k.startswith("python-crash:") or k.startswith("shared-defect:") or k in ("well-formed", "schema-valid", "schema-invalid"):
            print(f"  {k}: {tally[k]}")
    print(f"{len(bad)} unexplained differences")
    for b in bad[:400]:
        print("UNEXPLAINED", b)
    sys.exit(1 if bad else 0)


main()
