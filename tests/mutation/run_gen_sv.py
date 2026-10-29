"""Test-only harness for the mutation checks of the SystemVerilog generator (docs/cancho-port.md, 29.5).

A differential that cannot fail proves nothing. For each break below this copies src/ to a temporary
directory, changes ONE expression of gen_sv.cho in the copy (the old text must occur exactly once), builds
`chw` from the copy and runs the two quick tiers of tests/differential/generate_sv.py against it:

  fixtures   --fixtures-only: the 50 fixtures through both command lines, bytes compared
  handmade   --handmade-only: the hand-made inputs (every access kind, resets, enums, names that need escaping or carry `--`, bases, a source path)

and `cancho test` of tests/unit/test_gen_sv.cho. A break is KILLED when any of the three fails. The table
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
MODULES = """lex ir parse json_out json_in diag pyrepr pattern schema front load diagnostic hexval check_util check_block
check_regs check_intr check_dma check dg_json dg_text dg_report gen_c gen_dts gen_svd gen_binding gen_sv
diff_util diff diff_fmt impact report_data report report_check""".split()
PROGRAM = ["main"] + MODULES + ["io", "conform"]

# (name, old, new, what it breaks)
M = [
    ("snake-prev-lower", "            if prev_lower || end_of_run {", "            if end_of_run {", "a capital after a lower-case letter is not a word boundary"),
    ("snake-end-of-run", "            if prev_lower || end_of_run {", "            if prev_lower {", "the end of a capital run is not a word boundary"),
    ("snake-first", "        if bytes.is_upper(c) && i > a {", "        if bytes.is_upper(c) {", "the first letter gets an underscore"),
    ("snake-run-next", "bytes.is_upper(int_of(src[i - 1])) && bytes.is_lower(int_of(src[i + 1]));", "bytes.is_upper(int_of(src[i - 1]));", "every capital after a capital is a boundary"),
    ("snake-lower", "        o = buffer.push(heap, o, byte_of(bytes.to_lower(c)));\n        i = i + 1;", "        o = buffer.push(heap, o, byte_of(c));\n        i = i + 1;", "the snake form keeps capitals"),
    ("hex-pad", "        var pad = min - len(buffer.bytes(lr));", "        var pad = min - len(buffer.bytes(lr)) - 1;", "hex is padded one digit short"),
    ("module-suffix", '"_axi #(\\n"', '"_ax #(\\n"', "the module suffix changes"),
    ("param-data", '"   parameter DATA_WIDTH = "', '"    parameter DATA_WIDTH = "', "DATA_WIDTH is indented like ADDR_WIDTH"),
    ("base-comment-pad", "src, b.base_s, b.base_e, 8);\n        o = gc.put(heap, o, \"\\n    localparam", "src, b.base_s, b.base_e, 6);\n        o = gc.put(heap, o, \"\\n    localparam", "the base comment is padded to 6"),
    ("base-width", "        o = gc.put_int(heap, o, b.width);\n        o = put_hex_digits(heap, gc.put(heap, o, \"'h\")", "        o = gc.put_int(heap, o, b.width / 2);\n        o = put_hex_digits(heap, gc.put(heap, o, \"'h\")", "the base literal has half the width"),
    ("addr-pad", 'o = put_hex_digits(heap, gc.put(heap, o, " = \'h"), src, r.off_s, r.off_e, 8);', 'o = put_hex_digits(heap, gc.put(heap, o, " = \'h"), src, r.off_s, r.off_e, 4);', "an address is padded to 4 digits"),
    ("addr-name", 'o = gc.put_span(heap, gc.put(heap, o, "    localparam [ADDR_WIDTH-1:0] ADDR_"), src, r.name_s, r.name_e);', 'o = put_snake_register(heap, gc.put(heap, o, "    localparam [ADDR_WIDTH-1:0] ADDR_"), src, r);', "an address constant is named with the snake form"),
    ("enum-upper", "        o = buffer.push(heap, o, byte_of(bytes.to_upper(int_of(src[i]))));", "        o = buffer.push(heap, o, byte_of(int_of(src[i])));", "an enum label keeps its case"),
    ("enum-radix", "gc.put(heap, o, \"'d\")", "gc.put(heap, o, \"'h\")", "an enum value is written in hex"),
    ("enum-has", "                if f.has_enum {\n                    var x = 0;", "                if false {\n                    var x = 0;", "enum localparams are never written"),
    ("enum-name", 'o = gc.put_span(heap, gc.put(heap, o, "_"), src, f.name_s, f.name_e);', 'o = gc.put_span(heap, gc.put(heap, o, "__"), src, f.name_s, f.name_e);', "the enum constant name has two underscores"),
    ("storage-name", '"\\n    reg [DATA_WIDTH-1:0] r_"', '"\\n    reg [DATA_WIDTH-1:0] x_"', "the storage register is misnamed"),
    ("assign-out", '"_out = r_"', '"_out = x_"', "the behaviour port reads another register"),
    ("reset-pad", "o = put_hex_digits(heap, o, src, r.reset_s, r.reset_e, b.width / 4);", "o = put_hex_digits(heap, o, src, r.reset_s, r.reset_e, b.width / 8);", "a reset is padded to half the digits"),
    ("reset-undefined", '" <= \'h0;  // "', '" <= \'h1;  // "', "an undefined reset is not zero"),
    ("reset-undefined-comment", '" (reset undefined)\\n"', '" (reset not defined)\\n"', "the undefined-reset comment changes"),
    ("reset-defined", "            if r.reset_s >= 0 {\n                o = gc.put(heap, o, \" <= 'h\");", "            if r.reset_s >= 100000 {\n                o = gc.put(heap, o, \" <= 'h\");", "no register has a reset value"),
    ("last-port-comma", "            if j + 1 < nregs {\n                o = gc.put(heap, o, \",\");", "            if true {\n                o = gc.put(heap, o, \",\");", "the last register port keeps its comma, which a parser refuses (issue 14)"),
    ("rready-comma", "        if nregs > 0 {\n            o = gc.put(heap, o, \",\");", "        if true {\n            o = gc.put(heap, o, \",\");", "a block with no register keeps a comma after its last fixed port"),
    ("sized-literal", '" = \'h"), src, r.off_s', '" = ADDR_WIDTH\'h"), src, r.off_s', "an address constant is sized by a parameter name, which a parser refuses (issue 14)"),
    ("aw-match", "wr_acc && (s_axi_awaddr >= BASE_ADDR);", "wr_acc && (s_axi_awaddr > BASE_ADDR);", "the write match is strict"),
    ("ar-match", "rd_acc && (s_axi_araddr >= BASE_ADDR);", "rd_acc && (s_axi_araddr > BASE_ADDR);", "the read match is strict"),
    ("write-cond", "    o = gc.put(heap, o, \" && (s_axi_awaddr == BASE_ADDR + ADDR_\");", "    o = gc.put(heap, o, \" && (s_axi_araddr == BASE_ADDR + ADDR_\");", "a write is decoded on the read address"),
    ("write-valid", '") && s_axi_wvalid"', '") && s_axi_awvalid"', "a write waits for the address valid, not the data"),
    ("kind-ro-comment", "RO: writes are dropped and answer SLVERR.", "RO: writes are dropped.", "the RO comment changes"),
    ("kind-ro-noop", '";  // no-op\\n"', '";  // noop\\n"', "the RO no-op comment changes"),
    ("kind-rw", '    if bytes.equal(kind, "RW") || bytes.equal(kind, "WO") {', '    if bytes.equal(kind, "RW") {', "WO has no write line"),
    ("kind-w1c", '    if bytes.equal(kind, "W1C") || bytes.equal(kind, "W0S") {', '    if bytes.equal(kind, "W1C") {', "W0S has no write line"),
    ("kind-w1c-expr", "\" & ~(s_axi_wdata & wmask);\\n\"", "\" & (s_axi_wdata & wmask);\\n\"", "W1C and W0S keep the bits that were written"),
    ("kind-w0c-expr", "\" & (s_axi_wdata | ~wmask);\\n\"", "\" & ~(s_axi_wdata | ~wmask);\\n\"", "W0C clears the bits that were written"),
    ("kind-w1s-expr", "\" | (s_axi_wdata & wmask);\\n\"", "\" & (s_axi_wdata & wmask);\\n\"", "W1S ands instead of ors"),
    ("kind-rc-comment", "RC: read clears, write has no effect", "RC: read clears", "the RC comment changes"),
    ("kind-rc", '    if bytes.equal(kind, "RC") {', '    if bytes.equal(kind, "RCX") {', "RC has no write line"),
    ("kind-unknown-text", "; no write logic emitted.", "; no logic.", "the unknown-kind comment changes"),
    ("kind-comment", '" (kind="', '" (kind ="', "the kind comment changes"),
    ("read-wo", '    if bytes.equal(src[r.kind_s..r.kind_e], "WO") {', '    if bytes.equal(src[r.kind_s..r.kind_e], "RO") {', "a write-only register reads its value"),
    ("read-wo-comment", "reads return 0 and answer SLVERR (the spec notes this is a write-only register).", "reads return 0.", "the WO read comment changes"),
    ("read-valid", "            rdata_valid = 1'b1;\\n        end", "            rdata_valid = 1'b0;\\n        end", "a read is never valid"),
    ("sort-offset", "contents(kw)[k] = hexval.parse(src[r.off_s..r.off_e]).v;", "contents(kw)[k] = 0 - k;", "registers are ordered by reverse declaration"),
    ("offset-big", "        if hexval.parse(src[r.off_s..r.off_e]).big {", "        if false {", "a register offset past 2^60 is used saturated"),
    ("width-internal", "|| b.width < 0 {", "|| false {", "a negative width is written"),
    ("base-internal", "    if !hexval.parse(src[b.base_s..b.base_e]).ok {\n        return false;", "    if false {\n        return false;", "an unreadable base is not noticed"),
    ("offset-internal", "        if !hexval.parse(src[r.off_s..r.off_e]).ok ||", "        if false ||", "an unreadable offset is not noticed"),
    ("reset-internal", "|| r.reset_s >= 0 && !hexval.parse(src[r.reset_s..r.reset_e]).ok {", "|| false {", "an unreadable reset is not noticed"),
    ("fields-internal", "        if r.first < 0 || r.n < 0 || r.first + r.n > nfields {", "        if false {", "a register naming fields that are not there is written"),
    ("enums-internal", "        if f.has_enum && (f.enum_first < 0 || f.enum_n < 0 || f.enum_first + f.enum_n > nenums) {", "        if false {", "a field naming enum entries that are not there is written"),
    ("spans-block", "    if !span_ok(src, b.name_s, b.name_e) || !span_ok(src, b.base_s, b.base_e) || b.width < 0 {", "    if b.width < 0 {", "a block span outside the text is sliced"),
    ("plain-block", "    if !gd.is_plain(src, b.name_s, b.name_e) {", "    if false {", "a block name with an escape is written"),
    ("plain-register", "        if !gd.is_plain(src, r.name_s, r.name_e) {", "        if false {", "a register name with an escape is written"),
    ("plain-field", "        if !gd.is_plain(src, f.name_s, f.name_e) {", "        if false {", "a field name with an escape is written"),
    ("plain-enum", "        if !gd.is_plain(src, e.name_s, e.name_e) {", "        if false {", "an enum label with an escape is written"),
    ("plain-path", "    if !gd.is_plain(path, 0, len(path)) {", "    if false {", "a source path with a non-ASCII byte is written"),
    ("static-banner", "Synthesis output is a Trust boundary", "Synthesis output is a trust boundary", "the banner comment changes"),
    ("static-ports", "    // AXI4-Lite write address channel", "    // AXI4-Lite write-address channel", "a port comment changes"),
    ("static-storage", "    // Internal storage", "    // Internal registers", "the storage section title changes"),
    ("static-handshake", "assign s_axi_awready = wr_acc;", "assign s_axi_awready = rd_acc;", "awready follows the read accept"),
    ("static-read", "        rdata_valid = 1'b0;", "        rdata_valid = 1'b1;", "the read mux defaults to valid"),
    ("rw-strobes", "\" & ~wmask) | (s_axi_wdata & wmask);\\n\"", "\" & ~wmask) | s_axi_wdata;\\n\"", "a write ignores the byte strobes"),
    ("wr-hit-kind", "|| bytes.equal(kind, \"W0S\") || bytes.equal(kind, \"RC\");", "|| bytes.equal(kind, \"W0S\");", "a write to an RC register answers SLVERR"),
    ("wr-hit-decode", "gc.put(heap, o, \" && (s_axi_awaddr == BASE_ADDR + ADDR_\"), src, r.name_s", "gc.put(heap, o, \" && (s_axi_awaddr == ADDR_\"), src, r.name_s", "the hit of a write forgets the base"),
    ("read-decode-base", "\" && (s_axi_araddr == BASE_ADDR + ADDR_\"", "\" && (s_axi_araddr == ADDR_\"", "a read forgets the base"),
    ("bresp-slverr", "bresp_r <= wr_hit ? 2'b00 : 2'b10;", "bresp_r <= wr_hit ? 2'b00 : 2'b00;", "an unmapped write answers OKAY"),
    ("rresp-slverr", "rresp_r <= rdata_valid ? 2'b00 : 2'b10;", "rresp_r <= rdata_valid ? 2'b00 : 2'b00;", "an unmapped read answers OKAY"),
    ("write-accept", "assign wr_acc = s_axi_awvalid && s_axi_wvalid && !bvalid_r;", "assign wr_acc = s_axi_awvalid && s_axi_wvalid;", "a write is accepted while a response is pending"),
    ("read-accept", "assign rd_acc = s_axi_arvalid && !rvalid_r;", "assign rd_acc = s_axi_arvalid;", "a read is accepted while a response is pending"),
    ("static-bvalid", "assign s_axi_bvalid  = bvalid_r;", "assign s_axi_bvalid  = wr_acc;", "the write response is combinational on the request"),
    ("static-rvalid", "assign s_axi_rvalid  = rvalid_r;", "assign s_axi_rvalid  = rd_acc;", "the read response is combinational on the request"),
    ("static-bready", "if (bvalid_r && s_axi_bready) bvalid_r <= 1'b0;", "if (bvalid_r) bvalid_r <= 1'b0;", "a response is dropped without its ready"),
    ("seq-reset", "        if (!rst_n) begin\\n", "        if (rst_n) begin\\n", "the reset is inverted"),
    ("static-tail", "`default_nettype wire", "`default_nettype none", "the default net type is not restored"),
]


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, **kw)


def one(m):
    name, old, new, what = m
    with tempfile.TemporaryDirectory() as tmp:
        src = pathlib.Path(tmp) / "src"
        shutil.copytree(ROOT / "src", src)
        text = (src / "gen_sv.cho").read_text()
        if text.count(old) != 1:
            return name, what, f"BAD BREAK: the old text occurs {text.count(old)} times"
        (src / "gen_sv.cho").write_text(text.replace(old, new))
        exe = pathlib.Path(tmp) / "chw"
        r = sh([CANCHO, "build", *[str(src / f"{x}.cho") for x in PROGRAM], "--std", "-o", str(exe)])
        if r.returncode != 0:
            return name, what, "BUILD FAILED: " + (r.stdout + r.stderr).strip()[:200]
        tiers = []
        if sh([sys.executable, "tests/differential/generate_sv.py", str(exe), "--fixtures-only"]).returncode != 0:
            tiers.append("fixtures")
        if sh([sys.executable, "tests/differential/generate_sv.py", str(exe), "--handmade-only"]).returncode != 0:
            tiers.append("handmade")
        lib = [str(src / f"{x}.cho") for x in MODULES]
        t = sh([CANCHO, "test", "tests/unit/test_gen_sv.cho", *lib, "--std"])
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
