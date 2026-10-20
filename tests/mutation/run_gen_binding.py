"""Test-only harness for the mutation checks of the cancho-binding generator (docs/cancho-port.md, 26.5).

A differential that cannot fail proves nothing. For each break below this copies src/ to a temporary
directory, changes ONE expression of gen_binding.cho in the copy (the old text must occur exactly once), builds
`chw` from the copy and runs the two quick tiers of tests/differential/generate_binding.py against it:

  fixtures   --fixtures-only: the 50 fixtures through both command lines, bytes compared
  handmade   --handmade-only: the hand-made inputs (every access kind, resets, enums, names that need escaping or carry `--`, bases, a source path)

and `cancho test` of tests/unit/test_gen_binding.cho. A break is KILLED when any of the three fails. The table
printed at the end is the evidence: each decision of the generator has a break, and the tier that caught it.

Usage: python3 tests/mutation/run_gen_dts.py [--only NAME,NAME] [--jobs N]   (needs $CANCHO, default ../cancho/target/release/cancho, )
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
check_block check_regs check_intr check_dma check dg_json dg_text dg_report gen_c gen_dts gen_svd gen_binding""".split()
PROGRAM = ["main"] + MODULES + ["io", "conform"]

# (name, old, new, what it breaks)
M = [
    ("pascal-upper", "o = buffer.push(heap, o, byte_of(bytes.to_upper(c)));", "o = buffer.push(heap, o, byte_of(c));", "a type name keeps its first letter lower case"),
    ("pascal-underscore", "        if c == '_' {\n                start = true;", "        if c == '_' {\n                start = false;", "a part after an underscore is not capitalised"),
    ("kind-rc", 'if bytes.equal(k, "RO") || bytes.equal(k, "RC") {', 'if bytes.equal(k, "RO") {', "RC has no getter"),
    ("kind-w1s", 'if bytes.equal(k, "WO") || bytes.equal(k, "W1S") || bytes.equal(k, "W0S") {', 'if bytes.equal(k, "WO") || bytes.equal(k, "W0S") {', "W1S has no setter"),
    ("kind-w0s", 'if bytes.equal(k, "WO") || bytes.equal(k, "W1S") || bytes.equal(k, "W0S") {', 'if bytes.equal(k, "WO") || bytes.equal(k, "W1S") {', "W0S has no setter"),
    ("kind-rw", 'if bytes.equal(k, "RW") {\n        return (true, true, false, true);', 'if bytes.equal(k, "RW") {\n        return (true, true, false, false);', "RW has no setter"),
    ("kind-w1c", 'if bytes.equal(k, "W1C") || bytes.equal(k, "W0C") {', 'if bytes.equal(k, "W1C") {', "W0C has no clear"),
    ("kind-wo", 'if bytes.equal(k, "WO") || bytes.equal(k, "W1S") || bytes.equal(k, "W0S") {\n        return (true, false, false, true);', 'if bytes.equal(k, "WO") || bytes.equal(k, "W1S") || bytes.equal(k, "W0S") {\n        return (true, true, false, true);', "WO has a getter"),
    ("kind-unknown", "    return (false, false, false, false);\n}", "    return (true, true, false, false);\n}", "an unknown kind is read-only"),
    ("kind-message", "has no cancho accessor mapping", "has no mapping", "the unknown-kind message changes"),
    ("enum-empty", "    return f.has_enum && f.enum_n > 0;", "    return f.has_enum;", "an empty enum declares a type"),
    ("labels-count", "    if a.enum_n != b.enum_n {\n        return false;", "    if false {\n        return false;", "label lists of different length are the same list"),
    ("labels-bytes", "        if !bytes.equal(src[x.name_s..x.name_e], src[y.name_s..y.name_e]) {", "        if false {", "label lists with different labels are the same list"),
    ("collision-message", "two enum fields named ", "two enum fields called ", "the collision message changes"),
    ("collision-type", "refusing to collide the type ", "refusing the type ", "the collision message drops the type"),
    ("collision-skip", "                        if !same_labels(src, ir, vec.get(ir.fields, prev), f) {", "                        if false {", "two enum fields with one name and different labels are accepted"),
    ("width-one-bool", '    if f.msb - f.lsb + 1 == 1 {\n        return gc.put(heap, out, "bool");', '    if f.msb - f.lsb + 1 == 2 {\n        return gc.put(heap, out, "bool");', "a one-bit field is u32"),
    ("bare-getter", "let bare = !is_enum(f) && f.msb - f.lsb + 1 == 1;", "let bare = f.msb - f.lsb + 1 == 1;", "an enum field of one bit has a bare getter"),
    ("get-suffix", "            if !bare {", "            if bare {", "the getter suffix is inverted"),
    ("clear-suffix", '            o = gc.put(heap, o, "_clear();\\n");\n        }\n        if can_set {', '            o = gc.put(heap, o, "_clr();\\n");\n        }\n        if can_set {', "the clear accessor is misspelled"),
    ("set-arg", 'gc.put(heap, o, "_set(v: ")', 'gc.put(heap, o, "_set(x: ")', "the setter argument is misnamed"),
    ("field-comment", '    // chw:"), src, b.name_s, b.name_e);\n        o = gc.put_span(heap, gc.put(heap, o, ".register."', '    // id:"), src, b.name_s, b.name_e);\n        o = gc.put_span(heap, gc.put(heap, o, ".register."', "the stable-ID comment changes"),
    ("intr-arm", "    if model.has_key(x.order, 2) {", "    if model.has_key(x.order, 3) {", "arm follows the status linkage"),
    ("intr-status", "    if model.has_key(x.order, 3) {", "    if model.has_key(x.order, 2) {", "status follows the enable linkage"),
    ("intr-clear", "    if model.has_key(x.order, 4) {", "    if model.has_key(x.order, 3) {", "clear follows the status linkage"),
    ("intr-blank", '    if vec.size(ir.intrs) > 0 {\n        o = gc.put(heap, o, "\\n");', '    if vec.size(ir.intrs) > 100 {\n        o = gc.put(heap, o, "\\n");', "no blank line before the interrupts"),
    ("intr-capability", '"\\n    capability "', '"\\n    cap "', "the capability keyword changes"),
    ("intr-pascal-block", "    o = put_pascal(heap, gc.put(heap, o, \"\\n    capability \"), src, b.name_s, b.name_e);", "    o = put_snaked(heap, gc.put(heap, o, \"\\n    capability \"), src, b.name_s, b.name_e);", "the capability carries the block in snake case"),
    ("dma-device", 'bytes.equal(src[d.owner_s..d.owner_e], "DEVICE")', 'bytes.equal(src[d.owner_s..d.owner_e], "CPU")', "the CPU-owned field has no setter"),
    ("dma-no-owner", "        if d.owner_s >= 0 && bytes.equal(", "        if d.owner_s >= 0 || bytes.equal(", "a field without an owner has no setter"),
    ("dma-comment", "no setter: DEVICE-owned (the field is the device's to write)", "no setter: device-owned", "the no-setter comment changes"),
    ("dma-getter", '"() -> u32;\\n");\n        if d.owner_s', '"() -> u64;\\n");\n        if d.owner_s', "a DMA getter is u64"),
    ("dma-setter", '"_set(v: u32);\\n"', '"_set(v: u64);\\n"', "a DMA setter takes u64"),
    ("dma-buffer-keyword", '"\\n    buffer "', '"\\n    buf "', "the buffer keyword changes"),
    ("dma-close", 'return gc.put(heap, o, "    }\\n");', 'return gc.put(heap, o, "}\\n");', "the buffer closes at the wrong indent"),
    ("hex-min", "gs.put_hex(heap, gc.put(heap, o, \" @ \"), src, b.base_s, b.base_e, 0)", "gs.put_hex(heap, gc.put(heap, o, \" @ \"), src, b.base_s, b.base_e, 8)", "the base is padded"),
    ("width-prefix", '" : u"', '" : i"', "the width type is signed"),
    ("module-name", "o = put_snaked(heap, o, src, b.name_s, b.name_e);\n    o = gc.put(heap, o, \" {\\n    foreign block \");", "o = gc.put_span(heap, o, src, b.name_s, b.name_e);\n    o = gc.put(heap, o, \" {\\n    foreign block \");", "the module is named with the block's own spelling"),
    ("banner", '". Do not edit.\\n\\nmodule "', '". Do not edit.\\nmodule "', "no blank line after the banner"),
    ("enum-dedupe", "                    if !seen {", "                    if true {", "an enum is declared once per field"),
    ("enum-sep", 'o = gc.put(heap, o, ", ");\n                            }\n                            let en', 'o = gc.put(heap, o, ",");\n                            }\n                            let en', "enum labels are joined without a space"),
    ("enum-open", 'o = gc.put(heap, o, " { ");', 'o = gc.put(heap, o, " {");', "the enum opens without a space"),
    ("enum-close", 'o = gc.put(heap, o, " }\\n");', 'o = gc.put(heap, o, "}\\n");', "the enum closes without a space"),
    ("enum-keyword", '"\\nenum "', '"\\nenumeration "', "the enum keyword changes"),
    ("width-internal", "|| b.width < 0 {", "|| false {", "a negative width is written"),
    ("base-internal", "    if !hexval.parse(src[b.base_s..b.base_e]).ok {\n        return false;", "    if false {\n        return false;", "an unreadable base is not noticed"),
    ("fields-internal", "|| r.first < 0 || r.n < 0 || r.first + r.n > nfields {", "|| false {", "a register naming fields that are not there is written"),
    ("enums-internal", "        if f.has_enum && (f.enum_first < 0 || f.enum_n < 0 || f.enum_first + f.enum_n > nenums) {", "        if false {", "a field naming enum entries that are not there is written"),
    ("dma-fields-internal", "|| d.first < 0 || d.n < 0 || d.first + d.n > ndf {", "|| false {", "a buffer naming fields that are not there is written"),
    ("spans-block", "    if !span_ok(src, b.name_s, b.name_e) || !span_ok(src, b.base_s, b.base_e) || b.width < 0 {", "    if b.width < 0 {", "a block span outside the text is sliced"),
    ("spans-register", "if !span_ok(src, r.name_s, r.name_e) || !span_ok(src, r.kind_s, r.kind_e) || r.first < 0", "if r.first < 0", "a register span outside the text is sliced"),
    ("plain-block", "    if !gd.is_plain(src, b.name_s, b.name_e) {", "    if false {", "a block name with an escape is written"),
    ("plain-register", "        if !gd.is_plain(src, r.name_s, r.name_e) {", "        if false {", "a register name with an escape is written"),
    ("plain-field", "        if !gd.is_plain(src, f.name_s, f.name_e) {", "        if false {", "a field name with an escape is written"),
    ("plain-enum", "        if !gd.is_plain(src, e.name_s, e.name_e) {", "        if false {", "an enum label with an escape is written"),
    ("plain-interrupt", "        if !gd.is_plain(src, n.name_s, n.name_e) {", "        if false {", "an interrupt name with an escape is written"),
    ("plain-buffer", "        if !gd.is_plain(src, d.name_s, d.name_e) {\n            return gc.refusal(heap, src, d.name_s, d.name_e, \"the DMA buffer name\"", "        if false {\n            return gc.refusal(heap, src, d.name_s, d.name_e, \"the DMA buffer name\"", "a buffer name with an escape is written"),
    ("plain-dma-field", "        if !gd.is_plain(src, d.name_s, d.name_e) {\n            return gc.refusal(heap, src, d.name_s, d.name_e, \"the DMA field name\"", "        if false {\n            return gc.refusal(heap, src, d.name_s, d.name_e, \"the DMA field name\"", "a DMA field name with an escape is written"),
    ("plain-path", "    if !gd.is_plain(path, 0, len(path)) {", "    if false {", "a source path with a non-ASCII byte is written"),
]


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, **kw)


def one(m):
    name, old, new, what = m
    with tempfile.TemporaryDirectory() as tmp:
        src = pathlib.Path(tmp) / "src"
        shutil.copytree(ROOT / "src", src)
        text = (src / "gen_binding.cho").read_text()
        if text.count(old) != 1:
            return name, what, f"BAD BREAK: the old text occurs {text.count(old)} times"
        (src / "gen_binding.cho").write_text(text.replace(old, new))
        exe = pathlib.Path(tmp) / "chw"
        r = sh([CANCHO, "build", *[str(src / f"{x}.cho") for x in PROGRAM], "--std", "-o", str(exe)])
        if r.returncode != 0:
            return name, what, "BUILD FAILED: " + (r.stdout + r.stderr).strip()[:200]
        tiers = []
        if sh([sys.executable, "tests/differential/generate_binding.py", str(exe), "--fixtures-only"]).returncode != 0:
            tiers.append("fixtures")
        if sh([sys.executable, "tests/differential/generate_binding.py", str(exe), "--handmade-only"]).returncode != 0:
            tiers.append("handmade")
        lib = [str(src / f"{x}.cho") for x in MODULES]
        t = sh([CANCHO, "test", "tests/unit/test_gen_binding.cho", *lib, "--std"])
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
