"""Test-only harness for the mutation checks of the CMSIS-SVD generator (docs/cancho-port.md, 23.5).

A differential that cannot fail proves nothing. For each break below this copies src/ to a temporary
directory, changes ONE expression of gen_svd.cho in the copy (the old text must occur exactly once), builds
`chw` from the copy and runs the two quick tiers of tests/differential/generate_svd.py against it:

  fixtures   --fixtures-only: the 50 fixtures through both command lines, bytes compared
  handmade   --handmade-only: the hand-made inputs (every access kind, resets, enums, names that need escaping or carry `--`, bases, a source path)

and `cancho test` of tests/unit/test_gen_svd.cho. A break is KILLED when any of the three fails. The table
printed at the end is the evidence: each decision of the generator has a break, and the tier that caught it.

Usage: python3 tests/mutation/run_gen_dts.py [--only NAME,NAME] [--jobs N]   (needs $CANCHO, default ../cancho/target/release/cancho, and xmllint)
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
check_regs check_intr check_dma check dg_json dg_text dg_report gen_c gen_dts gen_svd gen_sv diff_util diff
diff_fmt impact""".split()
PROGRAM = ["main"] + MODULES + ["io", "conform"]

# (name, old, new, what it breaks)
M = [
    ("xml-amp", 'o = gc.put(heap, o, "&amp;");', 'o = gc.put(heap, o, "&");', "an ampersand in a name is not escaped"),
    ("xml-lt", 'o = gc.put(heap, o, "&lt;");', 'o = gc.put(heap, o, "<");', "a less-than in a name is not escaped"),
    ("xml-gt", 'o = gc.put(heap, o, "&gt;");', 'o = gc.put(heap, o, ">");', "a greater-than in a name is not escaped"),
    ("hex-upper", "byte_of(bytes.to_upper(int_of(t[i])))", "t[i]", "hex digits in lower case"),
    ("hex-prefix", 'var o = gc.put(heap, out, "0x");', 'var o = gc.put(heap, out, "0X");', "the hex prefix is upper case"),
    ("reset-pad", "o = put_hex(heap, o, src, r.reset_s, r.reset_e, b.width / 4);", "o = put_hex(heap, o, src, r.reset_s, r.reset_e, 0);", "a reset value is not padded to the bus width"),
    ("offset-pad", "o = put_hex(heap, o, src, r.off_s, r.off_e, 0);", "o = put_hex(heap, o, src, r.off_s, r.off_e, 8);", "an offset is padded"),
    ("base-pad", "o = put_hex(heap, o, src, b.base_s, b.base_e, 0);", "o = put_hex(heap, o, src, b.base_s, b.base_e, 8);", "the base is padded"),
    ("offset-order", "o = put_register(heap, o, src, ir, vec.get(ir.regs, contents(permr)[j]));", "o = put_register(heap, o, src, ir, vec.get(ir.regs, j));", "registers are written in declaration order"),
    ("kind-ro", 'return (true, "read-only", "", "");', 'return (true, "read-write", "", "");', "RO maps to read-write"),
    ("kind-wo", 'return (true, "write-only", "", "");', 'return (true, "read-only", "", "");', "WO maps to read-only"),
    ("kind-rc", 'return (true, "read-write", "", "clear");', 'return (true, "read-write", "", "");', "RC has no read action"),
    ("kind-w0c", '"zeroToClear"', '"oneToClear"', "W0C maps to oneToClear"),
    ("kind-w0s", '"zeroToSet"', '"oneToSet"', "W0S maps to oneToSet"),
    ("kind-w1c", '(true, "read-write", "oneToClear", "")', '(true, "read-write", "zeroToClear", "")', "W1C maps to zeroToClear"),
    ("kind-w1s", '(true, "read-write", "oneToSet", "")', '(true, "read-write", "zeroToSet", "")', "W1S maps to zeroToSet"),
    ("kind-unknown", "    return (false, \"\", \"\", \"\");\n}", "    return (true, \"read-write\", \"\", \"\");\n}", "an unknown kind is written as read-write"),
    ("reset-undefined", "          <resetValue>0x0</resetValue>\\n", "          <resetValue>0x1</resetValue>\\n", "an undefined reset is not zero"),
    ("reset-comment", "reset undefined in the contract", "reset not in the contract", "the undefined-reset comment changes"),
    ("mwv-order", 'if len(mwv) > 0 {', 'if len(mwv) > 100 {', "modifiedWriteValues is never written"),
    ("ra-order", 'if len(ra) > 0 {', 'if len(ra) > 100 {', "readAction is never written"),
    ("fields-element", "    if r.n > 0 {\n        o = gc.put(heap, o, \"          <fields>", "    if r.n > 100 {\n        o = gc.put(heap, o, \"          <fields>", "fields are never written"),
    ("field-access", 'o = gc.put(heap, o, "</msb>\\n            <access>");\n            o = gc.put(heap, o, access);', 'o = gc.put(heap, o, "</msb>\\n            <access>");\n            o = gc.put(heap, o, "read-write");', "a field's access is always read-write"),
    ("field-bits", 'o = gc.put_int(heap, o, f.lsb);', 'o = gc.put_int(heap, o, f.msb);', "the lsb is the msb"),
    ("enum-value", "o = gc.put_int(heap, o, en.value);", "o = gc.put_int(heap, o, en.value + 1);", "an enum value is off by one"),
    ("enum-element", "    if f.has_enum {\n                o = gc.put(heap", "    if false {\n                o = gc.put(heap", "enumerated values are never written"),
    ("zero-registers", "    if nregs == 0 {", "    if nregs < 0 {", "a block with no register is not refused"),
    ("version-default", 'o = gc.put(heap, o, "0.1.0");', 'o = gc.put(heap, o, "0.1.1");', "the implied version is 0.1.1"),
    ("unit-bits", "<addressUnitBits>8<", "<addressUnitBits>32<", "address units of 32 bits"),
    ("width-element", 'o = gc.put(heap, o, "</width>\\n  <peripherals>', 'o = gc.put(heap, o, "</width>\\n  <peripheralz>', "the peripherals element is misspelled"),
    ("size-element", "o = gc.put_int(heap, o, b.width);\n                o = gc.put(heap, o, \"</size>", "o = gc.put_int(heap, o, b.width / 8);\n                o = gc.put(heap, o, \"</size>", "the size is in bytes"),
    ("irq-comment", '", IRQ "', '", irq "', "the comment spells IRQ in lower case"),
    ("irq-intro", "interrupts are board-level in CMSIS-SVD", "interrupts are device-level in CMSIS-SVD", "the interrupts comment changes"),
    ("dma-intro", "DMA buffers are not part of the peripheral register map", "DMA buffers are part of the peripheral register map", "the DMA comment changes"),
    ("dma-comment-id", 'gc.put_span(heap, gc.put(heap, o, ".dma."), src, x.name_s, x.name_e)', 'gc.put_span(heap, gc.put(heap, o, ".buffer."), src, x.name_s, x.name_e)', "the DMA stable ID names a buffer"),
    ("dash-detect", "if int_of(src[i]) == '-' && int_of(src[i + 1]) == '-' {", "if int_of(src[i]) == '-' && int_of(src[i + 1]) == '.' {", "a double dash is not noticed"),
    ("dash-block", "    let first = comment_message(heap, src, b.name_s, b.name_e);", "    let first = buffer.empty(heap, 1);", "the block name is not checked for a double dash"),
    ("dash-path", "    let pm = comment_message(heap, path, 0, len(path));", "    let pm = buffer.empty(heap, 1);", "the source path is not checked for a double dash"),
    ("dash-interrupt", 'joined_message(heap, src, b.name_s, b.name_e, ".interrupt.", n.name_s, n.name_e)', "buffer.empty(heap, 1)", "an interrupt name is not checked for a double dash"),
    ("dash-interrupt-id", '".interrupt.", n.name_s, n.name_e)', '".interrupts.", n.name_s, n.name_e)', "the message quotes another stable ID"),
    ("dash-dma", 'joined_message(heap, src, b.name_s, b.name_e, ".dma.", d.name_s, d.name_e)', "buffer.empty(heap, 1)", "a DMA name is not checked for a double dash"),
    ("dash-register", "        let m = comment_message(heap, src, r.name_s, r.name_e);", "        let m = buffer.empty(heap, 1);", "a register name is not checked for a double dash"),
    ("dash-field", "            let fm = comment_message(heap, src, f.name_s, f.name_e);", "            let fm = buffer.empty(heap, 1);", "a field name is not checked for a double dash"),
    ("dash-enum", "                    let em = comment_message(heap, src, en.name_s, en.name_e);", "                    let em = buffer.empty(heap, 1);", "an enum label is not checked for a double dash"),
    ("kind-message", " has no CMSIS-SVD mapping", " has no mapping", "the unknown-kind message changes"),
    ("irq-number", "        if n.number < 0 {\n            return (gc.internal_text(heap, \"an interrupt has no number\")", "        if n.number < -5 {\n            return (gc.internal_text(heap, \"an interrupt has no number\")", "an interrupt with no number is written"),
    ("plain-block", "    if !is_plain(src, b.name_s, b.name_e) {", "    if false {", "a block name with an escape is written"),
    ("plain-version", "if b.ver_s >= 0 && !is_plain(src, b.ver_s, b.ver_e) {", "if false {", "a version with an escape is written"),
    ("plain-interrupt", "        if !is_plain(src, n.name_s, n.name_e) {", "        if false {", "an interrupt name with an escape is written"),
    ("plain-dma", "        if !is_plain(src, d.name_s, d.name_e) {", "        if false {", "a DMA name with an escape is written"),
    ("plain-register", "        if !is_plain(src, r.name_s, r.name_e) {", "        if false {", "a register name with an escape is written"),
    ("plain-field", "        if !is_plain(src, f.name_s, f.name_e) {", "        if false {", "a field name with an escape is written"),
    ("plain-enum", "        if !is_plain(src, e.name_s, e.name_e) {", "        if false {", "an enum label with an escape is written"),
    ("plain-path", "if !is_plain(path, 0, len(path)) || !no_markup(path, 0, len(path)) {", "if !no_markup(path, 0, len(path)) {", "a source path with a non-ASCII byte is written"),
    ("markup-path", "if !is_plain(path, 0, len(path)) || !no_markup(path, 0, len(path)) {", "if !is_plain(path, 0, len(path)) {", "a source path with markup is written unescaped"),
    ("markup-amp", "if c == '&' || c == '<' {\n            return false;", "if c == '<' {\n            return false;", "a path with an ampersand is written"),
    ("width-internal", "    if b.width < 0 {", "    if false {", "a negative width is sized"),
    ("base-internal", "    if !hexval.parse(src[b.base_s..b.base_e]).ok {", "    if false {", "an unreadable base is not noticed"),
    ("offset-internal", "        if !off.ok {", "        if false {", "an unreadable register offset is not noticed"),
    ("reset-internal", "        if r.reset_s >= 0 && !hexval.parse(src[r.reset_s..r.reset_e]).ok {", "        if false {", "an unreadable reset is not noticed"),
    ("fields-internal", "        if r.first < 0 || r.n < 0 || r.first + r.n > nfields {", "        if false {", "a register naming fields that are not there is written"),
    ("enums-internal", "        if f.has_enum && (f.enum_first < 0 || f.enum_n < 0 || f.enum_first + f.enum_n > nenums) {", "        if false {", "a field naming enum entries that are not there is written"),
    ("offset-big", "        if offset_value(src, r.off_s, r.off_e).big {", "        if false {", "a register offset past 2^60 is used saturated"),
    ("spans-block", "    if !span_ok(src, b.name_s, b.name_e) || !span_ok(src, b.base_s, b.base_e) || b.ver_s >= 0 && !span_ok(src, b.ver_s, b.ver_e) {", "    if false {", "a block span outside the text is sliced"),
    ("spans-register", "        if !span_ok(src, r.name_s, r.name_e) || !span_ok(src, r.off_s, r.off_e) || !span_ok(src, r.kind_s, r.kind_e) || r.reset_s >= 0 && !span_ok(src, r.reset_s, r.reset_e) {", "        if false {", "a register span outside the text is sliced"),
]


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, **kw)


def one(m):
    name, old, new, what = m
    with tempfile.TemporaryDirectory() as tmp:
        src = pathlib.Path(tmp) / "src"
        shutil.copytree(ROOT / "src", src)
        text = (src / "gen_svd.cho").read_text()
        if text.count(old) != 1:
            return name, what, f"BAD BREAK: the old text occurs {text.count(old)} times"
        (src / "gen_svd.cho").write_text(text.replace(old, new))
        exe = pathlib.Path(tmp) / "chw"
        r = sh([CANCHO, "build", *[str(src / f"{x}.cho") for x in PROGRAM], "--std", "-o", str(exe)])
        if r.returncode != 0:
            return name, what, "BUILD FAILED: " + (r.stdout + r.stderr).strip()[:200]
        tiers = []
        if sh([sys.executable, "tests/differential/generate_svd.py", str(exe), "--fixtures-only"]).returncode != 0:
            tiers.append("fixtures")
        if sh([sys.executable, "tests/differential/generate_svd.py", str(exe), "--handmade-only"]).returncode != 0:
            tiers.append("handmade")
        lib = [str(src / f"{x}.cho") for x in MODULES]
        t = sh([CANCHO, "test", "tests/unit/test_gen_svd.cho", *lib, "--std"])
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
