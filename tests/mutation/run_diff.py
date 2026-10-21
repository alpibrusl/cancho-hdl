"""Test-only harness for the mutation checks of `chw diff` and `chw impact` (docs/cancho-port.md, 33.6).

A differential that cannot fail proves nothing. For each break below this copies src/ to a temporary directory,
changes ONE expression in the named file of the copy (the old text must occur exactly once), builds `chw` from the copy
and runs the two quick tiers:

  fixtures   tests/differential/diff_cmp.py --fixtures-only: the 804 runs of whole-file pairs, `chw diff` and `chw impact`
             against tools/diff/diff.py, bytes and exit status
  unit       `cancho test` of tests/unit/test_diff.cho

A break is KILLED when either fails. The table printed at the end is the evidence: each decision has a break, and the
tier that caught it. A break that changes no output is listed in EQUIVALENT with its reason and is not counted as a
survivor.

Usage: python3 tests/mutation/run_diff.py [--only NAME,NAME] [--jobs N]   (needs $CANCHO, default ../cancho/target/release/cancho)
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
check_block check_regs check_intr check_dma check dg_json dg_text dg_report gen_c gen_dts gen_svd gen_binding gen_sv
diff_util diff diff_fmt impact""".split()
PROGRAM = ["main"] + MODULES + ["io", "conform"]

# (name, file, old, new, what it breaks)
M = [
    # -- diff_util: the dict Python keeps, and the comparisons
    ("first-position", "diff_util", "        if bytes.equal(name_of(src, tape, k), name) {\n            return false;", "        if bytes.equal(name_of(src, tape, k), name) {\n            return true;", "a repeated name is visited again"),
    ("last-value", "diff_util", "        if bytes.equal(name_of(src, tape, k), name) {\n            found = k;", "        if bytes.equal(name_of(src, tape, k), name) && found < 0 {\n            found = k;", "the first of two same-named elements is the one kept"),
    ("key-first", "diff_util", "        if bytes.equal(body(src, tape, j), key) {\n            return false;", "        if bytes.equal(body(src, tape, j), key) {\n            return true;", "a repeated key is visited again"),
    ("key-last", "diff_util", "        if bytes.equal(body(src, tape, j), key) {\n            found = j + 1;", "        if bytes.equal(body(src, tape, j), key) && found < 0 {\n            found = j + 1;", "the first of two same-keyed pairs is the one kept"),
    ("equal-absent", "diff_util", "    if a < 0 || b < 0 {\n        return a < 0 && b < 0;\n    }\n    let ka", "    if a < 0 || b < 0 {\n        return a < 0 || b < 0;\n    }\n    let ka", "an absent value equals a present one"),
    ("equal-kind", "diff_util", "    if ka != kb {\n        return false;\n    }", "    if false {\n        return false;\n    }", "values of two kinds are compared by their text"),
    ("equal-number", "diff_util", "        return bytes.equal(digits(s1, t1, a), digits(s2, t2, b));", "        return true;", "two different numbers are equal"),
    ("equal-string", "diff_util", "        return bytes.equal(body(s1, t1, a), body(s2, t2, b));", "        return true;", "two different strings are equal"),
    ("equal-array-count", "diff_util", "        if json.count(t1, a) != json.count(t2, b) {\n            return false;\n        }\n        var x = a + 1;\n        var y = b + 1;", "        if false {\n            return false;\n        }\n        var x = a + 1;\n        var y = b + 1;", "arrays of different length are compared by their common prefix"),
    ("equal-object-keys", "diff_util", "        return distinct == distinct_b;", "        return true;", "an object with a key more is equal"),
    ("hex-length", "diff_util", "    if len(x) != len(y) {\n        return false;\n    }\n    var i = 0;\n    while i < len(x) {\n        if lower_of", "    if false {\n        return false;\n    }\n    var i = 0;\n    while i < len(x) && i < len(y) {\n        if lower_of", "a hex number that is a prefix of another is equal to it"),
    ("hex-case", "diff_util", "        if lower_of(int_of(x[i])) != lower_of(int_of(y[i])) {", "        if x[i] != y[i] {", "hex digits are compared in case"),
    ("hex-zeros", "diff_util", "    while i < len(h) && h[i] == byte_of('0') {", "    while false {", "leading zeros count"),
    ("hex-prefix", "diff_util", "    if len(h) >= 2 && h[0] == byte_of('0') && (h[1] == byte_of('x') || h[1] == byte_of('X')) {\n        i = 2;\n    }", "    if false {\n        i = 2;\n    }", "the 0x prefix counts"),
    ("hex-lower", "diff_util", "    if c >= 'A' && c <= 'Z' {\n        return c + 32;", "    if c >= 'A' && c <= 'E' {\n        return c + 32;", "F is not lower-cased"),
    ("hex-nodes-absent", "diff_util", "    if a < 0 || b < 0 {\n        return a < 0 && b < 0;\n    }\n    return hex_equal(", "    if a < 0 || b < 0 {\n        return true;\n    }\n    return hex_equal(", "an absent hex value equals any"),
    ("separator", "diff_util", "    if k > 0 {\n        return buffer.append(heap, out, \", \");", "    if k > 1 {\n        return buffer.append(heap, out, \", \");", "the second element has no separator"),
    ("value-null", "diff_util", "    if k < 0 || k == 0 {\n        return buffer.append(heap, out, \"null\");", "    if k == 0 {\n        return buffer.append(heap, out, \"nul\");", "an absent value is written wrong"),
    ("value-true", "diff_util", "        return buffer.append(heap, out, \"true\");", "        return buffer.append(heap, out, \"True\");", "true is capitalised"),
    ("value-false", "diff_util", "        return buffer.append(heap, out, \"false\");", "        return buffer.append(heap, out, \"False\");", "false is capitalised"),
    ("value-key-sep", "diff_util", "        o = buffer.append(heap, o, \": \");\n        o = value(heap, o, src, tape, j + 1);", "        o = buffer.append(heap, o, \":\");\n        o = value(heap, o, src, tape, j + 1);", "a pair has no space after the colon"),
    ("value-object-skip", "diff_util", "        j = json.skip(tape, j + 1);\n        left = left - 1;\n        n = n + 1;\n    }\n    return buffer.push(heap, o, byte_of('}'));", "        j = json.skip(tape, j) + 1;\n        left = left - 1;\n        n = n + 1;\n    }\n    return buffer.push(heap, o, byte_of('}'));", "the walk of an object's pairs is off"),
    ("field-id-suffix", "diff_util", "    o = buffer.append(heap, o, \".field.\");", "    o = buffer.append(heap, o, \".fld.\");", "a field id is spelled differently"),
    ("id-prefix", "diff_util", "    var o = buffer.append(heap, out, \"\\\"chw:\");\n    o = buffer.append(heap, o, block);\n    o = buffer.push(heap, o, byte_of('.'));\n    o = buffer.append(heap, o, kind);\n    o = buffer.push(heap, o, byte_of('.'));\n    o = buffer.append(heap, o, name);\n    return", "    var o = buffer.append(heap, out, \"\\\"hw:\");\n    o = buffer.append(heap, o, block);\n    o = buffer.push(heap, o, byte_of('.'));\n    o = buffer.append(heap, o, kind);\n    o = buffer.push(heap, o, byte_of('.'));\n    o = buffer.append(heap, o, name);\n    return", "an id has another prefix"),
    ("plain-escape", "diff_util", "if c < 32 || c >= 127 || c == '\\\\' {", "if c < 32 || c >= 127 {", "a backslash in a name is copied"),
    ("plain-nonascii", "diff_util", "if c < 32 || c >= 127 || c == '\\\\' {", "if c < 32 || c == '\\\\' {", "a non-ASCII byte in a name is copied"),
    ("plain-control", "diff_util", "if c < 32 || c >= 127 || c == '\\\\' {", "if c >= 127 || c == '\\\\' {", "a control byte in a name is copied"),
    ("plain-float", "diff_util", "                    if !(c == '-' && k == tape[3 * i + 1]) {\n                        return false;\n                    }", "                    if false {\n                        return false;\n                    }", "a float is copied"),
    ("plain-negzero", "diff_util", "            if bytes.equal(digits(src, tape, i), \"-0\") {\n                return false;\n            }", "", "-0 is copied"),
    # -- diff: the lists
    ("registers-added-block", "diff", "            if !same || du.last_named(s2, t2, other, name) < 0 {\n                o = register_entry", "            if du.last_named(s2, t2, other, name) < 0 {\n                o = register_entry", "registers of another block are matched by name"),
    ("registers-offset-key", "diff", "    o = du.lit(heap, o, \", \\\"offset\\\": \");\n    o = du.value(heap, o, src, tape, json.get(src, tape, reg, \"offset\"));", "    o = du.lit(heap, o, \", \\\"offset\\\": \");\n    o = du.value(heap, o, src, tape, json.get(src, tape, reg, \"kind\"));", "an added register shows its kind as its offset"),
    ("moved-same", "diff", "    if !same {\n        return o;\n    }\n    let carr = registers_of(cs, ct);\n    let barr = registers_of(bs, bt);\n    var j = carr + 1;\n    var left = json.count(ct, carr);\n    var n = 0;\n    while left > 0 {\n        if du.is_first(cs, ct, carr, j) {\n            let name = du.name_of(cs, ct, j);\n            let creg", "    let carr = registers_of(cs, ct);\n    let barr = registers_of(bs, bt);\n    var j = carr + 1;\n    var left = json.count(ct, carr);\n    var n = 0;\n    while left > 0 {\n        if du.is_first(cs, ct, carr, j) {\n            let name = du.name_of(cs, ct, j);\n            let creg", "registers of another block are compared"),
    ("moved-hex", "diff", "                    if !du.hex_equal_nodes(bs, bt, bo, cs, ct, co) {", "                    if !du.equal(bs, bt, bo, cs, ct, co) {", "an offset in another spelling is a move"),
    ("reset-hex", "diff", "                    if !du.hex_equal_nodes(bs, bt, br, cs, ct, cr) {", "                    if !du.equal(bs, bt, br, cs, ct, cr) {", "a reset in another spelling is a change"),
    ("reset-absent", "diff", "                    let br = json.get(bs, bt, breg, \"reset\");", "                    let br = json.get(cs, ct, creg, \"reset\");", "a missing base reset is read as the candidate's"),
    ("classify-widen", "diff", "    if c_lsb <= b_lsb && c_msb >= b_msb {\n        return 0;", "    if c_lsb < b_lsb && c_msb >= b_msb {\n        return 0;", "a field widened on one side only is repositioned"),
    ("classify-narrow", "diff", "    if c_lsb >= b_lsb && c_msb <= b_msb {\n        return 1;", "    if c_lsb > b_lsb && c_msb <= b_msb {\n        return 1;", "a field narrowed on one side only is repositioned"),
    ("classify-order", "diff", "    if c_lsb <= b_lsb && c_msb >= b_msb {\n        return 0;\n    }\n    if c_lsb >= b_lsb && c_msb <= b_msb {\n        return 1;\n    }\n    return 2;", "    if c_lsb >= b_lsb && c_msb <= b_msb {\n        return 1;\n    }\n    if c_lsb <= b_lsb && c_msb >= b_msb {\n        return 0;\n    }\n    return 2;", "narrowed is tested before widened"),
    ("field-range-lsb", "diff", "!bytes.equal(du.digits(bs, bt, json.get(bs, bt, bf, \"lsb\")), du.digits(cs, ct, json.get(cs, ct, cf, \"lsb\"))) ||", "false ||", "a changed lsb alone is not a change"),
    ("field-range-msb", "diff", "|| !bytes.equal(du.digits(bs, bt, json.get(bs, bt, bf, \"msb\")), du.digits(cs, ct, json.get(cs, ct, cf, \"msb\")))", "|| false", "a changed msb alone is not a change"),
    ("field-added-mode", "diff", "                            if mode == 3 {", "                            if mode == 4 {", "added fields are listed as removed"),
    ("field-enum-mode", "diff", "                            if mode == 5 {", "                            if mode == 3 {", "enum changes are listed with added fields"),
    ("field-removed-mode", "diff", "                if mode == 4 {\n                    var x = bfs + 1;", "                if mode == 3 {\n                    var x = bfs + 1;", "removed fields are listed as added"),
    ("field-removed-base", "diff", "                            if du.last_named(cs, ct, cfs, fname) < 0 {", "                            if du.last_named(cs, ct, cfs, fname) < 1 {", "a removed field at position 0 of the candidate is missed"),
    ("enum-value", "diff", "            if bv < 0 || !bytes.equal(du.digits(bs, bt, bv), du.digits(cs, ct, cv)) {", "            if bv < 0 {", "a changed enum value is not noticed"),
    ("enum-removed", "diff", "            if du.last_key(cs, ct, ce, label) < 0 {", "            if false {", "a dropped enum label is not noticed"),
    ("enum-from-to", "diff", "bs, bt, du.last_key(bs, bt, be, label), cs, ct, 0 - 1);", "bs, bt, 0 - 1, cs, ct, du.last_key(bs, bt, be, label));", "a dropped label is written as added"),
    ("interrupt-roles", "diff", "    while r < 5 {", "    while r < 4 {", "the clear role is not compared"),
    ("interrupt-role-name", "diff", "    if i == 2 {\n        return \"enable\";", "    if i == 2 {\n        return \"status\";", "the enable role is named status"),
    ("interrupt-empty", "diff", "                if m > 0 {", "                if m > -1 {", "an interrupt with no change is listed"),
    ("interrupt-added-same", "diff", "            if !same || du.last_named(s2, t2, other, name) < 0 {\n                o = du.id(heap, du.lit(heap, du.sep(heap, o, n), \"{\\\"id\\\": \"), block_name(s1, t1), \"interrupt\", name);", "            if du.last_named(s2, t2, other, name) < 0 {\n                o = du.id(heap, du.lit(heap, du.sep(heap, o, n), \"{\\\"id\\\": \"), block_name(s1, t1), \"interrupt\", name);", "interrupts of another block are matched by name"),
    ("dma-new-fields", "diff", "                o = field_ids(heap, o, block_name(cs, ct), name, cs, ct, cd);", "                o = du.lit(heap, o, \"[]\");", "a new buffer lists no added fields"),
    ("dma-new-owner", "diff", "\", \\\"removed_field_ids\\\": [], \\\"moved_fields\\\": [], \\\"owner_changes\\\": []}\"", "\", \\\"removed_field_ids\\\": [], \\\"moved_fields\\\": []}\"", "a new buffer has no owner_changes"),
    ("dma-removed-fields", "diff", "                o = field_ids(heap, o, block_name(bs, bt), name, bs, bt, bd);", "                o = du.lit(heap, o, \"[]\");", "a removed buffer lists no removed fields"),
    ("dma-removed-owner", "diff", "\", \\\"moved_fields\\\": []}\");\n                n = n + 1;", "\", \\\"moved_fields\\\": [], \\\"owner_changes\\\": []}\");\n                n = n + 1;", "a removed buffer has owner_changes"),
    ("dma-offset-key", "diff", "                var key = \"offset\";", "                var key = \"owner\";", "dma moves compare owners"),
    ("dma-owner-key", "diff", "                if what == 1 {\n                    key = \"owner\";", "                if what == 1 {\n                    key = \"offset\";", "owner changes compare offsets"),
    ("dma-coherent-key", "diff", "                if what == 2 {\n                    key = \"coherent\";", "                if what == 2 {\n                    key = \"owner\";", "coherence changes compare owners"),
    ("dma-owner-omit", "diff", "        if no > 0 {\n            borrow owners", "        if no > -1 {\n            borrow owners", "owner_changes is written when empty"),
    ("dma-coherent-omit", "diff", "        if nc > 0 {\n            borrow cohs", "        if nc > -1 {\n            borrow cohs", "coherence_changes is written when empty"),
    ("dma-added-count", "diff", "        if len(buffer.bytes(ar)) > 2 {", "        if len(buffer.bytes(ar)) > 40 {", "a buffer with one added field is unchanged"),
    ("dma-removed-count", "diff", "        if len(buffer.bytes(rr)) > 2 {", "        if len(buffer.bytes(rr)) > 40 {", "a buffer with one removed field is unchanged"),
    ("dma-moved-same", "diff", "    var changed = nm + no + nc > 0;", "    var changed = no + nc > 0;", "a moved dma field alone is not a change"),
    ("dma-changed-owner", "diff", "    var changed = nm + no + nc > 0;", "    var changed = nm + nc > 0;", "an owner change alone is not a change"),
    ("dma-changed-coherent", "diff", "    var changed = nm + no + nc > 0;", "    var changed = nm + no > 0;", "a coherence change alone is not a change"),
    ("property-hex", "diff", "        if i == 1 {\n            equal = du.hex_equal_nodes", "        if i == 7 {\n            equal = du.hex_equal_nodes", "a base address in another spelling is a change"),
    ("property-name", "diff", "    if i == 0 {\n        return \"name\";", "    if i == 0 {\n        return \"names\";", "a property is misnamed"),
    ("property-count", "diff", "    while i < 4 {\n        let a = json.get(bs, bt, block_of(bs, bt), property_name(i));", "    while i < 3 {\n        let a = json.get(bs, bt, block_of(bs, bt), property_name(i));", "the endianness is not compared"),
    ("same-block", "diff", "    let same = bytes.equal(block_name(bs, bt), block_name(cs, ct));", "    let same = true;", "two blocks of different names are matched"),
    ("order-lists", "diff", "    o = close_list(heap, registers_only_in(heap, open_list(heap, o, \"added_registers\"), cs, ct, bs, bt, same));\n    o = close_list(heap, registers_only_in(heap, open_list(heap, o, \"removed_registers\"), bs, bt, cs, ct, same));", "    o = close_list(heap, registers_only_in(heap, open_list(heap, o, \"removed_registers\"), bs, bt, cs, ct, same));\n    o = close_list(heap, registers_only_in(heap, open_list(heap, o, \"added_registers\"), cs, ct, bs, bt, same));", "two lists swap places"),
    ("base-id", "diff", "\".register\\\", \\\"candidate_id\\\": \\\"chw:\"", "\".registers\\\", \\\"candidate_id\\\": \\\"chw:\"", "the base id is spelled differently"),
    ("schema-name", "diff", "\\\"schema\\\": \\\"cancho-hdl-diff\\\"", "\\\"schema\\\": \\\"cancho-hdl-diffs\\\"", "the schema is named differently"),
    # -- impact
    ("impact-reason-block", "impact", "        o = buffer.append(heap, o, \"block properties changed\");", "        o = buffer.append(heap, o, \"block property changed\");", "the block reason is spelled differently"),
    ("impact-reason-join", "impact", "                o = buffer.append(heap, o, \"; \");", "                o = buffer.append(heap, o, \", \");", "reasons are joined with a comma"),
    ("impact-reason-lists", "impact", "    while i < 14 {", "    while i < 13 {", "the reset lists are not counted"),
    ("impact-reason-first", "impact", "        n = 1;\n    }\n    var i = 0;", "        n = 0;\n    }\n    var i = 0;", "the first reason after the block line has no separator"),
    ("impact-reason-name", "impact", "        return \"widened_fields\";", "        return \"widened\";", "a list is misnamed in a reason"),
    ("impact-stale-text", "impact", "            o = du.lit(heap, o, \", \\\"stale\\\": true, \\\"reason\\\": \\\"\");", "            o = du.lit(heap, o, \", \\\"stale\\\": true, \\\"why\\\": \\\"\");", "the reason key is renamed"),
    ("impact-same-text", "impact", "no change (byte-identical output for both contracts)", "no change", "the fresh reason is shortened"),
    ("impact-targets", "impact", "    if i == 2 {\n        return \"devicetree\";", "    if i == 2 {\n        return \"dts\";", "a target is misnamed"),
    ("impact-compare", "impact", "                same = bytes.equal(buffer.bytes(br), buffer.bytes(cr));", "                same = len(buffer.bytes(br)) == len(buffer.bytes(cr));", "artifacts of one length are the same"),
    ("impact-fallback", "impact", "                    o = du.lit(heap, o, \"artifact bytes differ\");", "                    o = du.lit(heap, o, \"changed\");", "a stale artifact with no listed change has another reason"),
    # -- diff_fmt
    ("fmt-indent", "diff_fmt", "        o = buffer.append(heap, o, \"  \");", "        o = buffer.append(heap, o, \" \");", "a level is one space"),
    ("fmt-empty-array", "diff_fmt", "            return buffer.append(heap, o, \"[]\");", "            return buffer.append(heap, o, \"[ ]\");", "an empty list is spaced"),
    ("fmt-empty-object", "diff_fmt", "        return buffer.append(heap, o, \"{}\");", "        return buffer.append(heap, o, \"{ }\");", "an empty object is spaced"),
    ("fmt-comma", "diff_fmt", "            o = buffer.append(heap, o, \",\\n\");", "            o = buffer.append(heap, o, \", \\n\");", "a comma is followed by a space"),
    ("fmt-key-sep", "diff_fmt", "            o = buffer.append(heap, o, \": \");", "            o = buffer.append(heap, o, \":\");", "a key has no space after the colon"),
    ("fmt-close", "diff_fmt", "    o = indent(heap, buffer.push(heap, o, byte_of('\\n')), level);", "    o = indent(heap, buffer.push(heap, o, byte_of('\\n')), level + 1);", "a container closes one level deep"),
]

# Breaks that change no output, each with the reason. They are reported, not counted as survivors.
EQUIVALENT = {
    "plain-control": "a control byte cannot be inside a JSON string, so `json.parse` refuses the file before the check for it is reached",
    "classify-order": "the tests for widened and narrowed both hold only when the two ranges are equal, and an equal range is not listed at all",
    "field-removed-base": "`last_named` answers a node index, and the root is node 0, so no element is at an index below 1: `< 0` and `< 1` are the same test",
}


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, **kw)


def one(m):
    name, fname, old, new, what = m
    with tempfile.TemporaryDirectory() as tmp:
        src = pathlib.Path(tmp) / "src"
        shutil.copytree(ROOT / "src", src)
        text = (src / f"{fname}.cho").read_text()
        if text.count(old) != 1:
            return name, what, f"BAD BREAK: the old text occurs {text.count(old)} times"
        (src / f"{fname}.cho").write_text(text.replace(old, new))
        exe = pathlib.Path(tmp) / "chw"
        r = sh([CANCHO, "build", *[str(src / f"{x}.cho") for x in PROGRAM], "--std", "-o", str(exe)])
        if r.returncode != 0:
            return name, what, "BUILD FAILED: " + (r.stdout + r.stderr).strip()[:200]
        tiers = []
        if sh([sys.executable, "tests/differential/diff_cmp.py", str(exe), "--fixtures-only"]).returncode != 0:
            tiers.append("fixtures")
        lib = [str(src / f"{x}.cho") for x in MODULES]
        t = sh([CANCHO, "test", "tests/unit/test_diff.cho", "tests/unit/support.cho", *lib, "--std"])
        if t.returncode != 0:
            tiers.append("unit")
        if tiers:
            return name, what, "KILLED by " + "+".join(tiers)
        return name, what, "EQUIVALENT" if name in EQUIVALENT else "SURVIVED"


def main():
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    jobs = int(sys.argv[sys.argv.index("--jobs") + 1]) if "--jobs" in sys.argv else 3
    todo = [m for m in M if only is None or m[0] in only]
    with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
        results = list(pool.map(one, todo))
    survived = 0
    equivalent = 0
    for name, what, verdict in results:
        print(f"{verdict:34} {name:22} {what}")
        if verdict == "EQUIVALENT":
            equivalent += 1
            print(f"  equivalent: {EQUIVALENT[name]}")
        elif not verdict.startswith("KILLED"):
            survived += 1
    print(f"{len(results) - survived - equivalent} of {len(results)} breaks killed, {equivalent} equivalent")
    sys.exit(1 if survived else 0)


main()
