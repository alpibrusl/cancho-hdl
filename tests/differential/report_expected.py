"""Test-only generator of tests/unit/test_report.cho (docs/cancho-port.md, 35.6): every expected text in that file is what
`tools/report/report.py` writes (its `main()` in this process, the roundtrip lanes replaced by the stubs of report_cmp.py)
for the scenario, never typed by hand. Run it to regenerate the file after a change of a scenario; the unit tests are
then compared with the oracle again:

    python3 tests/differential/report_expected.py /path/to/built/chw > tests/unit/test_report.cho

Oracle code only: it decides nothing about the product."""
import contextlib
import copy
import json
import os
import pathlib
import sys
import tempfile

sys.argv = [sys.argv[0], sys.argv[1] if len(sys.argv) > 1 else "chw"]
import report_cmp as rc  # noqa: E402

R = rc.R

BASE = ('{"version":"0.1.0","block":{"name":"B","base_address":"0x40","bus_width":32,"endianness":"little","registers":['
        '{"name":"R","offset":"0x00","kind":"RW","reset":"0x0","fields":[{"name":"F","lsb":0,"msb":3,"enum":{"A":0,"B":1}},{"name":"G","lsb":8,"msb":9}]},'
        '{"name":"S","offset":"0x04","kind":"RO"}],"interrupts":[{"name":"I","number":1,"source":{"register":"R","field":"F"},'
        '"clear":{"register":"R","field":"G","kind":"W1C"}}]},"dma_buffers":[{"name":"D","fields":[{"name":"X","offset":"0x0","owner":"CPU"},{"name":"Y","offset":"0x4","owner":"DEVICE"}]}]}')
OVERLAP = BASE.replace('"name":"G","lsb":8,"msb":9', '"name":"G","lsb":2,"msb":5')
NO_DMA = ('{"version":"0.1.0","block":{"name":"B","base_address":"0x40","bus_width":32,"endianness":"little","registers":'
          '[{"name":"R","offset":"0x00","kind":"RW"}]}}')
NO_REGS = '{"version":"0.1.0","block":{"name":"B","base_address":"0x40","bus_width":32,"endianness":"little"}}'
NO_BLOCK = '{"version":"0.1.0"}'
BAD_VERSION = BASE.replace('"version":"0.1.0"', '"version":"9.9.9"')
TEXT = ("register-block T @ 0x4000, width 32, little-endian {\n    register CTRL @ 0x00 : RW, reset 0x0 {\n"
        "        field ENABLE : bits [0..0]\n    }\n}\n")
TEXT_WARN = ("register-block T @ 0x4000, width 32, little-endian {\n    register CTRL @ 0x00 : WO, reset 0x1 {\n"
             "        field ENABLE : bits [0..0]\n    }\n}\n")
PARSE_ERROR = "register-block P @ 0x2000, width 32, little-endian {\n    register CTRL @ 0x00 RW {\n    }\n}\n"
LEADING_BLANKS = " " * 70 + TEXT
BLANKS_64 = " " * 64 + TEXT
BLANKS_63 = " " * 63 + TEXT
MIXED_BLANKS = "\t\r\n \t" + TEXT

# (name, contract, py flags, combo, cancho mode, lanes, output flags)
SCENARIOS = [
    ("clean_no_roundtrips", BASE, ["--no-roundtrips"], "F", 2, None),
    ("clean_default_is_skipped_with_a_reason", BASE, [], "F", 0, None),
    ("clean_lane_passed_and_failed", BASE, [], "A", 1, "A"),
    ("clean_lanes_both_passed", NO_DMA, [], "B", 1, "B"),
    ("clean_lanes_both_skipped_with_a_tool", NO_DMA, [], "C", 1, "C"),
    ("clean_lane_failed_then_passed_with_no_reason", NO_REGS, [], "D", 1, "D"),
    ("clean_lanes_skipped_with_trailing_blanks", NO_DMA, [], "E", 1, "E"),
    ("refused_contract_skips_both_roundtrips", OVERLAP, [], "A", 1, "A"),
    ("refused_contract_no_roundtrips", OVERLAP, ["--no-roundtrips"], "F", 2, None),
    ("a_parse_error_reports_only_the_parse_refusal", PARSE_ERROR, [], "A", 1, "A"),
    ("a_document_with_no_block_ran_only_the_version_group", NO_BLOCK, ["--no-roundtrips"], "F", 2, None),
    ("a_block_without_lists_ran_no_register_group", NO_REGS, ["--no-roundtrips"], "F", 2, None),
    ("registers_only_ran_the_register_group", NO_DMA, ["--no-roundtrips"], "F", 2, None),
    ("a_version_refusal_fails_the_runtime_check", BAD_VERSION, ["--no-roundtrips"], "F", 2, None),
    ("a_text_contract_ran_the_parse_pass", TEXT, ["--no-roundtrips"], "F", 2, None),
    ("a_warning_is_not_a_failure", TEXT_WARN, ["--no-roundtrips"], "F", 2, None),
    ("a_file_that_starts_with_blanks_is_not_textual", LEADING_BLANKS, ["--no-roundtrips"], "F", 2, None),
    ("a_first_character_at_the_65th_byte_is_not_seen", BLANKS_64, ["--no-roundtrips"], "F", 2, None),
    ("a_first_character_at_the_64th_byte_is_seen", BLANKS_63, ["--no-roundtrips"], "F", 2, None),
    ("a_tab_a_carriage_return_and_a_newline_are_blanks", MIXED_BLANKS, ["--no-roundtrips"], "F", 2, None),
]


def cho(s):
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif ord(ch) < 32:
            raise SystemExit(f"control character {ord(ch)} in a literal")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def oracle(contract, flags, combo, extra=()):
    # The unit tests load against the empty schema, which refuses nothing: the oracle's schema pass refuses nothing either
    # (the pass still runs, so `schema-invalid` is among the codes that ran).
    R.checker_mod._validate_schema = lambda ir, path: []
    with tempfile.TemporaryDirectory() as td:
        old = os.getcwd()
        os.chdir(td)
        try:
            pathlib.Path("c.chw").write_text(contract, encoding="utf-8")
            return rc.py_run("c.chw", [*flags, *extra], combo)
        finally:
            os.chdir(old)


def lanes_text(combo):
    return json.dumps(list(rc.COMBOS[combo]("c.chw")))


def main():
    names = []
    out = []
    w = out.append
    w('''// test_report.cho -- `chw report` (src/report*.cho), one scenario at a time (docs/cancho-port.md, 35.6).
//
// Every expected text below is what `tools/report/report.py` writes for the same contract, taken from the tool by
// tests/differential/report_expected.py, which also writes this file; none is typed. The contract is loaded against the
// empty schema `{}` (a test borrows only the heap), so the schema pass has nothing to refuse and the scenarios are the
// ones the checker's rules decide.
//
//     cancho test tests/unit/test_report.cho tests/unit/support.cho src/*.cho --std
//     (all of src/ except main.cho and conform.cho)

import std.buffer;
import std.bytes;
import std.json;
import std.test;
import chw.diff_fmt;
import chw.load;
import chw.report;
import chw.report_check;
import tsup;

fn tape_of[&h, &t](heap: &!h Heap, text: &t [byte]) -> [heap] (Box[[int]], int) {
    let tape = box_slice(heap, json.tape_len(text), 0);
    var nodes = 0;
    borrow mut tape as &!w in {
        nodes = json.parse(text, contents(w));
    }
    return (tape, nodes);
}

// The report `build` writes for `contract` (mode 0 no lanes, 1 lanes, 2 none) and `lanes`.
fn built[&h, &c, &l](heap: &!h Heap, contract: &c [byte], mode: int, lanes: &l [byte]) -> [heap] buffer.Buffer {
    let sch = tsup.schema_of(heap, "{}");
    var out = buffer.empty(heap, 16);
    borrow sch as &sr in {
        let loaded = load.load(heap, contract, sr);
        borrow loaded as &lr in {
            let (lt, ln) = tape_of(heap, lanes);
            borrow lt as &ltr in {
                buffer.drop(heap, out);
                out = report.build(heap, lr, "c.chw", contract, mode, lanes, contents(ltr));
            }
            unbox_slice(heap, lt);
        }
        load.drop(heap, loaded);
    }
    load.drop_schema(heap, sch);
    return out;
}

fn same[&h, &c, &l, &w](heap: &!h Heap, contract: &c [byte], mode: int, lanes: &l [byte], want: &w [byte]) -> [heap] int {
    let out = built(heap, contract, mode, lanes);
    var ok = false;
    borrow out as &or in {
        ok = bytes.equal(buffer.bytes(or), want);
    }
    buffer.drop(heap, out);
    return test.assert(ok);
}

// `format_text`, `--pretty` and `--strict` of the report `text`.
fn as_text[&h, &d](heap: &!h Heap, doc: &d [byte]) -> [heap] buffer.Buffer {
    var out = buffer.empty(heap, 16);
    let (tape, nodes) = tape_of(heap, doc);
    borrow tape as &tr in {
        buffer.drop(heap, out);
        out = report.text(heap, buffer.empty(heap, 512), doc, contents(tr));
    }
    unbox_slice(heap, tape);
    return out;
}

fn pretty_of[&h, &d](heap: &!h Heap, doc: &d [byte]) -> [heap] buffer.Buffer {
    var out = buffer.empty(heap, 16);
    let (tape, nodes) = tape_of(heap, doc);
    borrow tape as &tr in {
        buffer.drop(heap, out);
        out = diff_fmt.pretty(heap, buffer.empty(heap, 512), doc, contents(tr), 0, 0);
    }
    unbox_slice(heap, tape);
    return out;
}

fn refusals_of[&h, &d](heap: &!h Heap, doc: &d [byte]) -> [heap] buffer.Buffer {
    var out = buffer.empty(heap, 16);
    let (tape, nodes) = tape_of(heap, doc);
    if nodes < 0 {
        buffer.drop(heap, out);
        out = buffer.append(heap, buffer.empty(heap, 16), "not json");
    } else {
        borrow tape as &tr in {
            buffer.drop(heap, out);
            out = report_check.validate(heap, buffer.empty(heap, 128), doc, contents(tr));
        }
    }
    unbox_slice(heap, tape);
    return out;
}

fn refused_as[&h, &d, &w](heap: &!h Heap, doc: &d [byte], want: &w [byte]) -> [heap] int {
    let out = refusals_of(heap, doc);
    var ok = false;
    borrow out as &or in {
        ok = bytes.equal(buffer.bytes(or), want);
    }
    buffer.drop(heap, out);
    return test.assert(ok);
}
''')
    texts = {}
    for name, contract, flags, combo, mode, lanes in SCENARIOS:
        rcode, doc, err = oracle(contract, flags, combo)
        assert rcode in (0, 1) and err == "", (name, rcode, err)
        doc = doc[:-1]  # `main` writes a newline after the document; `build` does not
        texts[name] = doc
        lt = lanes_text(lanes) if lanes else "[]"
        w(f"fn test_{name}[&h](heap: &!h Heap) -> [heap] int {{\n    return same(heap, {cho(contract)}, {mode}, {cho(lt)}, {cho(doc)});\n}}\n")
    # JSON that is not JSON: the wording of the syntax message is the loaders' known difference (13.5), so the fragments
    # that matter are checked, not the whole text.
    w("fn has[&h, &c, &l, &f](heap: &!h Heap, contract: &c [byte], fragment: &f [byte]) -> [heap] bool {\n    let out = built(heap, contract, 2, \"[]\");\n    var found = false;\n    borrow out as &or in {\n        found = bytes.find(buffer.bytes(or), fragment) >= 0;\n    }\n    buffer.drop(heap, out);\n    return found;\n}\n")
    rcode, doc, err = oracle("{", ["--no-roundtrips"], "F")
    py = json.loads(doc)
    frag = ('"checks_run": ["schema-invalid"], "checks_passed": 0, "checks_failed": 1')
    assert frag in doc
    w(f"fn test_json_that_is_not_json_is_a_schema_refusal_that_fired[&h](heap: &!h Heap) -> [heap] int {{\n    return test.assert(has(heap, \"{{\", {cho(frag)}) && has(heap, \"{{\", {cho('"static_checks_not_run": ' + json.dumps(py['unknown']['static_checks_not_run']))}) && has(heap, \"{{\", {cho('"checks_performed": [], "checks_passed": 0')}));\n}}\n")
    # the other renderings of one report with a trust boundary and a failed lane
    name, contract, flags, combo, mode, lanes = SCENARIOS[2]
    for label, extra in (("text", ["--output", "text"]), ("pretty", ["--pretty"])):
        rcode, doc, err = oracle(contract, flags, combo, extra)
        if label == "pretty":
            doc = doc[:-1]
        w(f"fn test_{name}_as_{label}[&h](heap: &!h Heap) -> [heap] int {{\n    let doc = {cho(texts[name])};\n    let out = {'as_text' if label == 'text' else 'pretty_of'}(heap, doc);\n"
          f"    var ok = false;\n    borrow out as &or in {{\n        ok = bytes.equal(buffer.bytes(or), {cho(doc)});\n    }}\n    buffer.drop(heap, out);\n    return test.assert(ok);\n}}\n")
    # text of the others: a skipped lane lists its target, a refusal, a parse error
    for name, contract, flags, combo, mode, lanes in (SCENARIOS[7], SCENARIOS[9], SCENARIOS[4], SCENARIOS[0]):
        rcode, doc, err = oracle(contract, flags, combo, ["--output", "text"])
        w(f"fn test_{name}_as_text[&h](heap: &!h Heap) -> [heap] int {{\n    let doc = {cho(texts[name])};\n    let out = as_text(heap, doc);\n"
          f"    var ok = false;\n    borrow out as &or in {{\n        ok = bytes.equal(buffer.bytes(or), {cho(doc)});\n    }}\n    buffer.drop(heap, out);\n    return test.assert(ok);\n}}\n")
    # --strict: the exit status of each scenario, from report.py
    strict_cases = []
    for name, contract, flags, combo, mode, lanes in SCENARIOS:
        rcode, doc, err = oracle(contract, flags, combo, ["--strict"])
        strict_cases.append((name, rcode))
    w("fn strict_holds[&h, &d](heap: &!h Heap, doc: &d [byte]) -> [heap] bool {\n    var ok = false;\n    let (tape, nodes) = tape_of(heap, doc);\n    borrow tape as &tr in {\n        ok = report.strict_ok(doc, contents(tr));\n    }\n    unbox_slice(heap, tape);\n    return ok;\n}\n")
    for name, status in strict_cases:
        w(f"fn test_strict_{name}[&h](heap: &!h Heap) -> [heap] int {{\n    return test.assert(strict_holds(heap, {cho(texts[name])}) == {'true' if status == 0 else 'false'});\n}}\n")
    # lanes_check
    lanes_cases = [
        ("an_array_of_two_good_lanes", json.dumps(list(rc.COMBOS["A"]("c.chw"))), 0),
        ("an_empty_array", "[]", 0),
        ("one_lane_alone", json.dumps([rc.COMBOS["B"]("c.chw")[1]]), 0),
        ("a_skipped_lane_needs_no_tool", '[{"target":"c-header","outcome":"skipped","reason":"r"}]', 0),
        ("an_object", '{"target":"c-header"}', 1),
        ("an_entry_that_is_not_an_object", '["c-header"]', 2),
        ("a_target_that_is_neither", '[{"target":"vhdl","outcome":"skipped","reason":"r"}]', 3),
        ("a_target_that_is_missing", '[{"outcome":"skipped","reason":"r"}]', 3),
        ("c_header_twice", '[{"target":"c-header","outcome":"skipped","reason":"r"},{"target":"c-header","outcome":"skipped","reason":"r"}]', 4),
        ("systemverilog_twice", '[{"target":"systemverilog","outcome":"skipped","reason":"r"},{"target":"systemverilog","outcome":"skipped","reason":"r"}]', 4),
        ("an_outcome_that_is_not_one", '[{"target":"c-header","outcome":"ok","tool":"t","reason":"r"}]', 5),
        ("an_outcome_that_is_missing", '[{"target":"c-header","tool":"t","reason":"r"}]', 5),
        ("a_reason_that_is_missing", '[{"target":"c-header","outcome":"skipped"}]', 6),
        ("a_reason_that_is_not_a_string", '[{"target":"c-header","outcome":"skipped","reason":1}]', 6),
        ("a_tool_that_is_not_a_string", '[{"target":"c-header","outcome":"skipped","tool":1,"reason":"r"}]', 7),
        ("a_passed_lane_with_no_tool", '[{"target":"c-header","outcome":"passed","reason":"r"}]', 8),
        ("a_failed_lane_with_no_tool", '[{"target":"systemverilog","outcome":"failed","reason":"r"}]', 8),
        ("a_lane_with_a_null_tool", '[{"target":"systemverilog","outcome":"failed","tool":null,"reason":"r"}]', 7),
    ]
    w("fn lanes_code[&h, &d](heap: &!h Heap, doc: &d [byte]) -> [heap] int {\n    var code = 0 - 1;\n    let (tape, nodes) = tape_of(heap, doc);\n    borrow tape as &tr in {\n        code = report.lanes_check(doc, contents(tr));\n    }\n    unbox_slice(heap, tape);\n    return code;\n}\n")
    for name, text, code in lanes_cases:
        w(f"fn test_lanes_{name}[&h](heap: &!h Heap) -> [heap] int {{\n    return test.assert_eq(lanes_code(heap, {cho(text)}), {code});\n}}\n")
    w("fn test_every_lanes_reason_is_worded_and_distinct() -> [] int {\n"
      "    var i = 1;\n    var ok = true;\n    while i <= 8 {\n        var j = i + 1;\n        while j <= 8 {\n            if bytes.equal(report.lanes_reason(i), report.lanes_reason(j)) {\n                ok = false;\n            }\n            j = j + 1;\n        }\n        if len(report.lanes_reason(i)) == 0 {\n            ok = false;\n        }\n        i = i + 1;\n    }\n    return test.assert(ok);\n}\n")
    # validate_report: corrupted copies of the report of the failed-lane scenario
    good = json.loads(texts["clean_lane_passed_and_failed"])

    def edit(fn):
        d = copy.deepcopy(good)
        fn(d)
        return d

    def set_in(path, value):
        def f(d):
            for p in path[:-1]:
                d = d[p]
            d[path[-1]] = value
        return f

    def delete(path):
        def f(d):
            for p in path[:-1]:
                d = d[p]
            del d[path[-1]]
        return f

    cases = [
        ("the_real_report", lambda d: None),
        ("not_an_object", None),
        ("wrong_schema_name", set_in(["schema"], "other")),
        ("no_schema_field", delete(["schema"])),
        ("non_guarantees_missing", delete(["non_guarantees"])),
        ("trust_boundaries_null", set_in(["trust_boundaries"], None)),
        ("static_checks_run_missing", delete(["static_checks_run"])),
        ("tested_roundtrips_run_missing", delete(["tested_roundtrips_run"])),
        ("unknown_items_missing", delete(["unknown_items"])),
        ("an_empty_list_is_not_missing", set_in(["unknown_items"], [])),
        ("everything_missing", lambda d: [d.pop(k) for k in list(d)]),
        ("a_non_guarantee_paraphrased", set_in(["non_guarantees", 1], "No timing closure.")),
        ("a_non_guarantee_dropped", lambda d: d["non_guarantees"].pop(8)),
        ("two_non_guarantees_dropped", lambda d: (d["non_guarantees"].pop(0), d["non_guarantees"].pop(0))),
        ("non_guarantees_is_a_string", set_in(["non_guarantees"], "all of them")),
        ("a_trust_boundary_relabelled", set_in(["trust", "boundaries", 0, "tier"], "Static")),
        ("a_trust_boundary_without_a_tier", delete(["trust", "boundaries", 0, "tier"])),
        ("a_trust_boundary_without_a_tool", lambda d: (d["trust"]["boundaries"][0].pop("tool"), d["trust"]["boundaries"][0].__setitem__("tier", "Unknown"))),
        ("a_trust_boundary_that_is_not_an_object", lambda d: d["trust"]["boundaries"].append(5)),
        ("the_trust_section_is_a_list", set_in(["trust"], [])),
        ("a_code_outside_the_catalog", lambda d: d["static"]["checks_run"].append("made-up")),
        ("two_codes_outside_the_catalog", lambda d: d["static"]["checks_run"].extend(["made-up", "it's"])),
        ("a_number_in_checks_run", lambda d: d["static"]["checks_run"].append(5)),
        ("a_null_in_checks_run", lambda d: d["static"]["checks_run"].append(None)),
        ("a_passed_count_too_high", lambda d: d["static"].__setitem__("checks_passed", d["static"]["checks_passed"] + 1)),
        ("a_failed_count_too_high", set_in(["static", "checks_failed"], 3)),
        ("a_count_that_is_a_bool", set_in(["static", "checks_failed"], True)),
        ("a_count_that_is_a_string", set_in(["static", "checks_failed"], "0")),
        ("a_count_that_is_null", set_in(["static", "checks_passed"], None)),
        ("a_negative_count", set_in(["static", "checks_failed"], -1)),
        ("counts_absent_with_a_list", lambda d: (d["static"].pop("checks_passed"), d["static"].pop("checks_failed"))),
        ("checks_run_absent", delete(["static", "checks_run"])),
        ("the_static_section_is_absent", delete(["static"])),
        ("the_static_section_is_a_string", set_in(["static"], "x")),
        ("an_error_for_a_code_not_run", lambda d: d["static"]["diagnostics"].append({"code": "dma-overlap", "severity": "Error"})),
        ("errors_for_two_codes_not_run_are_sorted", lambda d: d["static"]["diagnostics"].extend([{"code": "zz", "severity": "Error"}, {"code": "aa", "severity": "Error"}, {"code": "zz", "severity": "Error"}])),
        ("an_error_for_a_code_that_ran", lambda d: d["static"]["diagnostics"].append({"code": "field-overlap", "severity": "Error"})),
        ("a_warning_for_a_code_not_run_is_fine", lambda d: d["static"]["diagnostics"].append({"code": "dma-overlap", "severity": "Warning"})),
        ("an_error_with_no_code", lambda d: d["static"]["diagnostics"].append({"severity": "Error"})),
        ("an_error_with_a_null_code_that_checks_run_holds", lambda d: (d["static"]["diagnostics"].append({"code": None, "severity": "Error"}), d["static"]["checks_run"].append(None))),
        ("an_error_with_an_int_code", lambda d: d["static"]["diagnostics"].append({"code": 7, "severity": "Error"})),
        ("an_error_with_an_int_code_that_checks_run_holds", lambda d: (d["static"]["diagnostics"].append({"code": 7, "severity": "Error"}), d["static"]["checks_run"].append(7))),
        ("a_diagnostic_that_is_not_an_object", lambda d: d["static"]["diagnostics"].append("Error")),
        ("diagnostics_is_not_a_list", set_in(["static", "diagnostics"], {"code": "x"})),
        ("a_code_with_non_ascii", lambda d: d["static"]["diagnostics"].append({"code": "café \"x\"", "severity": "Error"})),
        ("tested_counts_too_high", set_in(["tested", "roundtrips_passed"], 2)),
        ("tested_counts_too_low", set_in(["tested", "roundtrips_failed"], 0)),
        ("tested_counts_absent", lambda d: (d["tested"].pop("roundtrips_passed"), d["tested"].pop("roundtrips_failed"))),
        ("tested_roundtrips_run_absent", delete(["tested", "roundtrips_run"])),
        ("tested_section_is_a_list", set_in(["tested"], [])),
        ("a_skipped_roundtrip_counted_as_run", lambda d: (d["tested"]["details"].__setitem__(0, dict(d["tested"]["details"][0], outcome="skipped")))),
        ("two_skipped_roundtrips_counted_as_run", lambda d: [x.__setitem__("outcome", "skipped") for x in d["tested"]["details"]]),
        ("a_skipped_roundtrip_with_no_target", lambda d: d["tested"]["details"].append({"outcome": "skipped"})),
        ("a_skipped_roundtrip_with_an_int_target", lambda d: (d["tested"]["details"].append({"outcome": "skipped", "target": 5}), d["tested"]["roundtrips_run"].append("5::x"), d["tested"]["roundtrips_failed"].__add__(0))),
        ("a_skipped_roundtrip_with_a_null_target", lambda d: (d["tested"]["details"].append({"outcome": "skipped", "target": None}), d["tested"]["roundtrips_run"].append("None::x"))),
        ("a_claimed_name_with_a_quote", lambda d: (d["tested"]["details"].append({"outcome": "skipped", "target": "it's"}), d["tested"]["roundtrips_run"].append("it's::\"x\""))),
        ("details_is_not_a_list", set_in(["tested", "details"], 5)),
        ("a_detail_that_is_not_an_object", lambda d: d["tested"]["details"].append("skipped")),
        ("details_absent", delete(["tested", "details"])),
        ("roundtrips_run_holds_a_number", lambda d: d["tested"]["roundtrips_run"].append(3)),
    ]
    for name, fn in cases:
        if fn is None:
            text = "[1, 2]"
            py, crash = rc.py_validate(json.loads(text))
        else:
            d = edit(fn)
            text = json.dumps(d)
            py, crash = rc.py_validate(d)
        if crash:
            continue  # Python raises (35.4, 4): no oracle text to hold the port to
        w(f"fn test_validate_{name}[&h](heap: &!h Heap) -> [heap] int {{\n    return refused_as(heap, {cho(text)}, {cho(py)});\n}}\n")
    sys.stdout.write("\n".join(out))


main()
