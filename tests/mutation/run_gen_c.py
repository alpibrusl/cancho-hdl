"""Test-only harness for the mutation checks of the C header generator (docs/cancho-port.md, 17.5 item 6, 18.4).

A differential that cannot fail proves nothing. For each break below this copies src/ to a temporary
directory, changes ONE expression of gen_c.cho in the copy (the old text must occur exactly once), builds
`chw` from the copy and runs the two quick tiers of tests/differential/generate_c.py against it:

  fixtures   --fixtures-only: the 50 fixtures through both command lines, bytes compared
  handmade   --handmade-only: the hand-made inputs (names a header cannot spell, widths, gaps)

and `cancho test` of tests/unit/test_gen_c.cho. A break is KILLED when any of the three fails. The table
printed at the end is the evidence: each decision of the generator has a break, and the tier that caught it.

Usage: python3 tests/mutation/run_gen_c.py [--only NAME,NAME] [--jobs N]   (needs $CANCHO, default ../cancho/target/release/cancho)
"""
import concurrent.futures
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
CANCHO = os.environ.get("CANCHO", str(ROOT.parent / "cancho/target/release/cancho"))
MODULES = """lex ir parse json_out json_in diag pyrepr pattern schema front load diagnostic hexval check_util
check_block check_regs check_intr check_dma check dg_json dg_text dg_report gen_c""".split()
PROGRAM = ["main"] + MODULES + ["io", "conform"]

# (name, old, new, what it breaks)
M = [
    ("register-order", "contents(kr)[contents(ar)[i]] <= contents(kr)[contents(ar)[j]]", "contents(kr)[contents(ar)[i]] >= contents(kr)[contents(ar)[j]]", "registers come out in descending offset order"),
    ("field-order", "contents(kw)[k] = f.lsb * 1024 + f.msb;", "contents(kw)[k] = 0 - f.lsb;", "fields in descending bit order"),
    ("reserved-gap", "            if f.lsb > pos {", "            if f.lsb >= pos {", "a zero-width reserved field is written"),
    ("reserved-tail", "    if pos < b.width {", "    if pos <= b.width {", "a zero-width tail is written"),
    ("field-width", "let width = f.msb - f.lsb + 1;", "let width = f.msb - f.lsb;", "a field one bit narrow"),
    ("guard-case", "\". Do not edit. */\\n#ifndef CANCHO_HDL_\");", "\". Do not edit. */\\n#ifndef CANCHO_X_\");", "the include guard is renamed"),
    ("stable-id", "    o = put_span(heap, put(heap, o, \".register.\"), src, r.name_s, r.name_e);", "    o = put_span(heap, put(heap, o, \".reg.\"), src, r.name_s, r.name_e);", "a stable ID changes"),
    ("kind-note", "if !bytes.equal(src[r.kind_s..r.kind_e], \"RW\") {", "if !bytes.equal(src[r.kind_s..r.kind_e], \"RO\") {", "the kind note is on the wrong registers"),
    ("reset-digits", "b.width / 4);", "8);", "reset values padded to eight digits"),
    ("base-digits", "src, b.base_s, b.base_e, 8);", "src, b.base_s, b.base_e, 4);", "the base address padded to four digits"),
    ("gap-bytes", "(rel - pos) * size);", "(rel - pos));", "a register gap counted in registers"),
    ("dma-next", "pos = offset + 4;", "pos = offset + 8;", "a DMA field is eight bytes"),
    ("abbreviation", "bytes.is_upper(int_of(src[i - 1])) && bytes.is_lower(int_of(src[i + 1]));", "false;", "the end of an abbreviation is not a word boundary"),
    ("keyword", "    return !keyword;", "    return true;", "a keyword is a legal member name"),
    ("identifier", "        if !(letter || i > a && bytes.is_digit(c)) {", "        if false {", "any byte is an identifier byte"),
    ("comment-text", "        if c == '/' && d == '*' || c == '*' && d == '/' {", "        if false {", "a comment delimiter may go in a comment"),
    ("bus-width-comment", "    if b.width != 8 && b.width != 16 && b.width != 32 {", "    if b.width != 8 && b.width != 16 {", "32 is not a bus width"),
    ("big-base", "    if hv.big {\n        o = hexval.canon_into(heap, o, src[a..e]);", "    if false {\n        o = hexval.canon_into(heap, o, src[a..e]);", "a base past 2^60 is written wrong"),
    ("internal-offset", "        if offset_value(src, r.off_s, r.off_e) < 0 {", "        if false {", "an unreadable register offset is not noticed"),
]


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, **kw)


def one(m):
    name, old, new, what = m
    with tempfile.TemporaryDirectory() as tmp:
        src = pathlib.Path(tmp) / "src"
        shutil.copytree(ROOT / "src", src)
        text = (src / "gen_c.cho").read_text()
        if text.count(old) != 1:
            return name, what, f"BAD BREAK: the old text occurs {text.count(old)} times"
        (src / "gen_c.cho").write_text(text.replace(old, new))
        exe = pathlib.Path(tmp) / "chw"
        r = sh([CANCHO, "build", *[str(src / f"{x}.cho") for x in PROGRAM], "--std", "-o", str(exe)])
        if r.returncode != 0:
            return name, what, "BUILD FAILED: " + (r.stdout + r.stderr).strip()[:200]
        tiers = []
        if sh([sys.executable, "tests/differential/generate_c.py", str(exe), "--fixtures-only"]).returncode != 0:
            tiers.append("fixtures")
        if sh([sys.executable, "tests/differential/generate_c.py", str(exe), "--handmade-only"]).returncode != 0:
            tiers.append("handmade")
        lib = [str(src / f"{x}.cho") for x in MODULES]
        t = sh([CANCHO, "test", "tests/unit/test_gen_c.cho", *lib, "--std"])
        if t.returncode != 0:
            tiers.append("unit")
        return name, what, "KILLED by " + "+".join(tiers) if tiers else "SURVIVED"


def main():
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    jobs = int(sys.argv[sys.argv.index("--jobs") + 1]) if "--jobs" in sys.argv else 3
    todo = [m for m in M if only is None or m[0] in only]
    with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
        results = list(pool.map(one, todo))
    survived = 0
    for name, what, verdict in results:
        print(f"{verdict:34} {name:18} {what}")
        if not verdict.startswith("KILLED"):
            survived += 1
    print(f"{len(results) - survived} of {len(results)} breaks killed")
    sys.exit(1 if survived else 0)


main()
