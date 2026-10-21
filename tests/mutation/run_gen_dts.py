"""Test-only harness for the mutation checks of the device-tree generator (docs/cancho-port.md, 20.5 item 6, 21.4).

A differential that cannot fail proves nothing. For each break below this copies src/ to a temporary
directory, changes ONE expression of gen_dts.cho in the copy (the old text must occur exactly once), builds
`chw` from the copy and runs the two quick tiers of tests/differential/generate_dts.py against it:

  fixtures   --fixtures-only: the 50 fixtures through both command lines, bytes compared
  handmade   --handmade-only: the hand-made inputs (names a label cannot spell, bases, interrupts, versions)

and `cancho test` of tests/unit/test_gen_dts.cho. A break is KILLED when any of the three fails. The table
printed at the end is the evidence: each decision of the generator has a break, and the tier that caught it.

Usage: python3 tests/mutation/run_gen_dts.py [--only NAME,NAME] [--jobs N]   (needs $CANCHO, default ../cancho/target/release/cancho, and dtc)
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
MODULES = """lex ir parse json_out json_in diag pyrepr pattern schema front load diagnostic hexval check_util check_block
check_regs check_intr check_dma check dg_json dg_text dg_report gen_c gen_dts gen_sv diff_util diff diff_fmt
impact""".split()
PROGRAM = ["main"] + MODULES + ["io", "conform"]

# (name, old, new, what it breaks)
M = [
    ("zero-registers", "    if nregs == 0 {", "    if nregs < 0 {", "a block with no register is not refused"),
    ("base-limit", "base.v > 4294967295", "base.v > 4294967296", "a base one past 32 bits fits an address cell"),
    ("size-width", "max_offset + b.width / 8", "max_offset + b.width / 4", "the last register is two words wide"),
    ("size-max", "        if hv.v > max_offset {", "        if hv.v < max_offset {", "the range is sized from the first register, not the highest"),
    ("upper-hex", "return buffer.push(heap, o, byte_of('A' + d - 10));", "return buffer.push(heap, o, byte_of('a' + d - 10));", "hex digits in lower case"),
    ("hex-prefix", "buffer.append(heap, out, \"0x\")", "buffer.append(heap, out, \"0X\")", "the hex prefix is upper case"),
    ("unit-address", "o = put_upper_hex(heap, gc.put(heap, o, \"@\"), base.v);", "o = put_upper_hex(heap, gc.put(heap, o, \"@\"), base.v + 1);", "the unit address is not the base"),
    ("snake-pass1", "        if i > a && bytes.is_upper(c) && bytes.is_upper(int_of(src[i - 1])) && i + 1 < e && bytes.is_lower(int_of(src[i + 1])) {", "        if false {", "the end of a capital run is not a word boundary"),
    ("snake-pass2-digit", "(bytes.is_lower(int_of(t[j - 1])) || bytes.is_digit(int_of(t[j - 1])))", "(bytes.is_lower(int_of(t[j - 1])))", "a capital after a digit is not a word boundary"),
    ("snake-lower", "o = buffer.push(heap, o, byte_of(bytes.to_lower(c)));", "o = buffer.push(heap, o, byte_of(c));", "the name keeps its capitals"),
    ("dashed", "                o = buffer.push(heap, o, byte_of('-'));", "                o = buffer.push(heap, o, byte_of('_'));", "the compatible string keeps underscores"),
    ("version-major", "    while i < e && int_of(src[i]) != '.' {", "    while i < e {", "the compatible string carries the whole version"),
    ("version-default", "        o = gc.put(heap, o, \"0\");", "        o = gc.put(heap, o, \"1\");", "the implied version is 1"),
    ("interrupt-align", "\"             \"", "\"            \"", "continuation lines are one column left"),
    ("interrupt-flags", "\" 4>\"", "\" 1>\"", "the flag cell changes"),
    ("interrupt-comment", "\", IRQ \"", "\", irq \"", "the comment spells IRQ in lower case"),
    ("interrupt-parent", "interrupt-parent = <&intc>;", "interrupt-parent = <&gic>;", "another interrupt parent"),
    ("bus-width", "    o = gc.put_int(heap, o, b.width);", "    o = gc.put_int(heap, o, b.width / 8);", "bus-width in bytes"),
    ("banner", "&soc {\\n    \");", "&sox {\\n    \");", "the fragment opens another node"),
    ("label", "gc.is_identifier(src, b.name_s, b.name_e) ||", "gc.is_identifier(src, b.name_s, b.name_e) && false ||", "a block name that is not a label is written"),
    ("plain-ascii", "if c >= 128 || c == '\\\\' || c < 32 {", "if c < 32 {", "a non-ASCII byte or an escape is written"),
    ("comment-end", "if int_of(src[i]) == '*' && int_of(src[i + 1]) == '/' {", "if false {", "a name may end the comment"),
    ("interrupt-name", "!no_comment_end(src, n.name_s, n.name_e) || !is_plain(src, n.name_s, n.name_e)", "false", "an interrupt name is not checked"),
    ("version-plain", "b.ver_s >= 0 && !is_plain(src, b.ver_s, b.ver_e)", "false", "a version with an escape is written"),
    ("path-comment", "!no_comment_end(path, 0, len(path))", "false", "a source path may end the comment"),
    ("width-internal", "if b.width < 0 {", "if false {", "a negative width is sized"),
    ("offset-internal", "if !offset_value(src, r.off_s, r.off_e).ok {", "if false {", "an unreadable register offset is not noticed"),
    ("offset-big", "        if hv.big {", "        if false {", "a register offset past 2^60 is used saturated"),
    ("base-internal", "if !hexval.parse(src[b.base_s..b.base_e]).ok {", "if false {", "an unreadable base is not noticed"),
    ("hex-big-case", "byte_of(bytes.to_upper(int_of(t[i])))", "t[i]", "a big base is quoted in lower case"),
    ("interrupt-number", "if vec.get(ir.intrs, i).number < 0 {", "if false {", "an interrupt with no number is written"),
]


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, **kw)


def one(m):
    name, old, new, what = m
    with tempfile.TemporaryDirectory() as tmp:
        src = pathlib.Path(tmp) / "src"
        shutil.copytree(ROOT / "src", src)
        text = (src / "gen_dts.cho").read_text()
        if text.count(old) != 1:
            return name, what, f"BAD BREAK: the old text occurs {text.count(old)} times"
        (src / "gen_dts.cho").write_text(text.replace(old, new))
        exe = pathlib.Path(tmp) / "chw"
        r = sh([CANCHO, "build", *[str(src / f"{x}.cho") for x in PROGRAM], "--std", "-o", str(exe)])
        if r.returncode != 0:
            return name, what, "BUILD FAILED: " + (r.stdout + r.stderr).strip()[:200]
        tiers = []
        if sh([sys.executable, "tests/differential/generate_dts.py", str(exe), "--fixtures-only"]).returncode != 0:
            tiers.append("fixtures")
        if sh([sys.executable, "tests/differential/generate_dts.py", str(exe), "--handmade-only"]).returncode != 0:
            tiers.append("handmade")
        lib = [str(src / f"{x}.cho") for x in MODULES]
        t = sh([CANCHO, "test", "tests/unit/test_gen_dts.cho", *lib, "--std"])
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
