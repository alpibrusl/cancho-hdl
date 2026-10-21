"""Test-only harness for the mutation checks of `chw report` (docs/cancho-port.md, 35.6).

A differential that cannot fail proves nothing. For each break below this copies src/ to a temporary directory, changes ONE
expression in the named file of the copy (the old text must occur exactly once), builds `chw` from the copy and runs the
two quick tiers:

  unit       `cancho test` of tests/unit/test_report.cho (120 tests: whole reports, taken from report.py)
  fixtures   tests/differential/report_cmp.py --fixtures-only --real-lanes: `chw report` against tools/report/report.py on
             every fixture (the six lane stubs, the real clang/iverilog results, every output flag), and
             `validate_report` against `chw report --validate` on 8,000 corrupted copies of five reports;
             run only for a break the unit tests did not kill

A break is KILLED when either fails. The table printed at the end is the evidence: each decision has a break, and the tier
that caught it. A break that changes no output is listed in EQUIVALENT with its reason and is not counted as a survivor.

Usage: python3 tests/mutation/run_report.py [--only NAME,NAME] [--jobs N]   (needs $CANCHO, default ../cancho/target/release/cancho)
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
diff_util diff diff_fmt impact report_data report report_check""".split()
PROGRAM = ["main"] + MODULES + ["io", "conform"]

# (name, file, old, new, what it breaks)
M = [
    # -- report_data: the tables
    ("ng-count", "report_data", "pub fn ng_count() -> [] int {\n    return 9;", "pub fn ng_count() -> [] int {\n    return 8;", "the last non-guarantee is not restated"),
    ("ng-row", "report_data", "return \"Timing closure.\";", "return \"Timing closure\";", "a non-guarantee is paraphrased"),
    ("ng-last-row", "report_data", "return \"That generated output for one vendor toolchain works under another.\";", "return \"That generated output for one vendor toolchain works under another one.\";", "the last non-guarantee is paraphrased"),
    ("group-count", "report_data", "pub fn group_count() -> [] int {\n    return 5;", "pub fn group_count() -> [] int {\n    return 4;", "the dma group is never listed"),
    ("group-bit-block", "report_data", "    if g == 1 {\n        return 2;\n    }\n    if g == 2 {\n        return 4;", "    if g == 1 {\n        return 4;\n    }\n    if g == 2 {\n        return 2;", "the block and register groups swap bits"),
    ("group-bit-dma", "report_data", "    if g == 3 {\n        return 8;\n    }\n    return 16;", "    if g == 3 {\n        return 8;\n    }\n    return 8;", "the dma group has the interrupts' bit"),
    ("group-size-block", "report_data", "    if g == 1 {\n        return 4;\n    }\n    if g == 2 {\n        return 15;", "    if g == 1 {\n        return 3;\n    }\n    if g == 2 {\n        return 15;", "the last block code is missing"),
    ("group-size-registers", "report_data", "    if g == 2 {\n        return 15;\n    }\n    if g == 3 {\n        return 7;", "    if g == 2 {\n        return 14;\n    }\n    if g == 3 {\n        return 7;", "the last register code is missing"),
    ("group-size-interrupts", "report_data", "    if g == 3 {\n        return 7;\n    }\n    return 6;", "    if g == 3 {\n        return 6;\n    }\n    return 6;", "the last interrupt code is missing"),
    ("group-size-dma", "report_data", "    if g == 3 {\n        return 7;\n    }\n    return 6;", "    if g == 3 {\n        return 7;\n    }\n    return 5;", "the last dma code is missing"),
    ("code-registers", "report_data", "return \"reset-wo-nonzero\";", "return \"reset-wo-non-zero\";", "a register code is misspelt"),
    ("code-interrupt-order", "report_data", "    if i == 1 {\n        return \"interrupt-duplicate-name\";", "    if i == 1 {\n        return \"interrupt-source-unresolved\";", "an interrupt code is listed twice"),
    ("code-dma", "report_data", "return \"dma-align-unsatisfied\";", "return \"dma-align-unsatisfiable\";", "a dma code is misspelt"),
    ("code-block-last", "report_data", "    return \"block-endianness-unknown\";", "    return \"block-endianness-invalid\";", "the last block code is misspelt"),
    ("runtime-code", "report_data", "    return bytes.equal(code, \"schema-version-unsupported\");\n}\n\n// CATALOG_CODES", "    return bytes.equal(code, \"schema-version-invalid\");\n}\n\n// CATALOG_CODES", "the runtime code is not the runtime one"),
    ("catalog-parse", "report_data", "if bytes.equal(code, \"parse-error\") || bytes.equal(code, \"schema-invalid\")", "if bytes.equal(code, \"parse-errors\") || bytes.equal(code, \"schema-invalid\")", "parse-error is outside the catalog"),
    ("catalog-schema", "report_data", "bytes.equal(code, \"schema-invalid\") || bytes.equal(code, \"internal\")", "bytes.equal(code, \"schema-invalids\") || bytes.equal(code, \"internal\")", "schema-invalid is outside the catalog"),
    ("catalog-internal", "report_data", "bytes.equal(code, \"internal\") || bytes.equal(code, \"ir-version-unsupported\")", "bytes.equal(code, \"internals\") || bytes.equal(code, \"ir-version-unsupported\")", "internal is outside the catalog"),
    ("catalog-ir-version", "report_data", "bytes.equal(code, \"ir-version-unsupported\")", "bytes.equal(code, \"ir-version-unsupporte\")", "ir-version-unsupported is outside the catalog"),
    ("catalog-groups", "report_data", "    var g = 0;\n    while g < group_count() {\n        var i = 0;\n        while i < group_size(g) {\n            if bytes.equal(code, code_at(g, i)) {\n                return true;", "    var g = 0;\n    while g < group_count() {\n        var i = 0;\n        while i < group_size(g) {\n            if bytes.equal(code, code_at(g, i)) && g != 4 {\n                return true;", "dma codes are outside the catalog"),
    # -- report: the lists of names
    ("names-has", "report", "        if bytes.equal(list[at..e], name) {\n            return true;", "        if bytes.starts_with(list[at..e], name) {\n            return true;", "a name that begins with another is taken for it"),
    ("names-drop", "report", "        if !bytes.equal(list[at..e], name) {\n            out = name_add(heap, out, list[at..e]);", "        if bytes.equal(list[at..e], name) {\n            out = name_add(heap, out, list[at..e]);", "the dropped line is the only one kept"),
    ("names-json-runtime", "report", "        if !(skip_runtime && rd.is_runtime_text(list[at..e])) {\n            o = du.quote", "        if true {\n            o = du.quote", "the runtime code is listed among the static ones"),
    ("names-json-sep", "report", "            o = du.quote(heap, du.sep(heap, o, n), list[at..e]);", "            o = du.quote(heap, du.sep(heap, o, 0), list[at..e]);", "the names have no separator"),
    ("names-json-skip-all", "report", "        if !(skip_runtime && rd.is_runtime_text(list[at..e])) {\n            o = du.quote", "        if !(rd.is_runtime_text(list[at..e])) {\n            o = du.quote", "the runtime code is dropped from the not-run list as well"),
    # -- report: the checks
    ("static-tier", "report", "        dg.Tier::Static => {\n            return true;", "        dg.Tier::Runtime => {\n            return true;", "the Static diagnostics are not listed"),
    ("fails-error", "report", "if d.kids.nest == 0 && dg.is_error(d.rule) && bytes.equal(dg.rule_name(d.rule), code) {", "if d.kids.nest == 0 && bytes.equal(dg.rule_name(d.rule), code) {", "a warning fails its check"),
    ("fails-nest", "report", "if d.kids.nest == 0 && dg.is_error(d.rule) && bytes.equal(dg.rule_name(d.rule), code) {", "if dg.is_error(d.rule) && bytes.equal(dg.rule_name(d.rule), code) {", "a related entry fails a check"),
    ("fails-code", "report", "&& bytes.equal(dg.rule_name(d.rule), code) {", "&& true {", "any error fails every check"),
    ("fired-order", "report", "if bytes.compare(name, after) > 0 && (len(best) == 0 || bytes.compare(name, best) < 0) {", "if bytes.compare(name, after) > 0 && (len(best) == 0 || bytes.compare(name, best) > 0) {", "fired codes are appended largest first"),
    ("fired-strict", "report", "if bytes.compare(name, after) > 0 && (len(best) == 0", "if bytes.compare(name, after) >= 0 && (len(best) == 0", "a fired code is visited again for ever"),
    ("fired-nest", "report", "        let d = dg.get(ds, i);\n        if d.kids.nest == 0 {\n            let name = dg.rule_name(d.rule);", "        let d = dg.get(ds, i);\n        if true {\n            let name = dg.rule_name(d.rule);", "a code fired only in a related entry is listed"),
    ("fired-listed", "report", "        if !listed && rd.in_catalog(fired) {", "        if rd.in_catalog(fired) {", "a fired code already listed is listed twice"),
    ("fired-catalog", "report", "        if !listed && rd.in_catalog(fired) {", "        if !listed {", "a fired code outside the catalog is listed"),
    ("fired-not-run", "report", "            borrow not_run as &nr in {\n                buffer.drop(heap, kept);\n                kept = name_drop(heap, buffer.bytes(nr), fired);\n            }", "            borrow not_run as &nr in {\n                buffer.drop(heap, kept);\n                kept = name_drop(heap, buffer.bytes(nr), \"\");\n            }", "a fired code stays in the not-run list"),
    ("sniff-brace", "report", "            return c != '{';", "            return c == '{';", "a JSON file is textual"),
    ("sniff-window", "report", "    while i < len(src) && i < 64 {", "    while i < len(src) && i < 65 {", "the sniff looks one byte further"),
    ("sniff-window-short", "report", "    while i < len(src) && i < 64 {", "    while i < len(src) && i < 63 {", "the sniff looks one byte less"),
    ("sniff-blank-tab", "report", "        if !(c == ' ' || c == '\\t' || c == '\\n' || c == '\\r') {\n            return c != '{';", "        if !(c == ' ' || c == '\\n' || c == '\\r') {\n            return c != '{';", "a tab is not a blank"),
    ("sniff-blank-newline", "report", "        if !(c == ' ' || c == '\\t' || c == '\\n' || c == '\\r') {\n            return c != '{';", "        if !(c == ' ' || c == '\\t' || c == '\\r') {\n            return c != '{';", "a newline is not a blank"),
    ("sniff-blank-cr", "report", "        if !(c == ' ' || c == '\\t' || c == '\\n' || c == '\\r') {\n            return c != '{';", "        if !(c == ' ' || c == '\\t' || c == '\\n') {\n            return c != '{';", "a carriage return is not a blank"),
    ("sniff-all-blank", "report", "        i = i + 1;\n    }\n    return false;\n}\n\nfn count_json", "        i = i + 1;\n    }\n    return true;\n}\n\nfn count_json", "a file of blanks is textual"),
    ("parse-pass", "report", "    if textual(source) {\n        ran_names = name_add(heap, ran_names, rd.parse_pass_code());", "    if !textual(source) {\n        ran_names = name_add(heap, ran_names, rd.parse_pass_code());", "the parse pass ran on a JSON file"),
    ("schema-pass", "report", "    if has_ir {\n        ran_names = name_add(heap, ran_names, rd.schema_pass_code());", "    if !has_ir {\n        ran_names = name_add(heap, ran_names, rd.schema_pass_code());", "the schema pass ran with no IR"),
    ("group-ran", "report", "            if has_ir && mask / rd.group_bit(g) % 2 == 1 {", "            if mask / rd.group_bit(g) % 2 == 1 {", "a group ran with no IR"),
    ("group-ran-bit", "report", "            if has_ir && mask / rd.group_bit(g) % 2 == 1 {", "            if has_ir && mask / rd.group_bit(g) % 2 == 0 {", "the groups that did not run are listed as run"),
    ("passed-failed", "report", "            } else if fails(ds, code) {\n                failed = failed + 1;\n            } else {\n                passed = passed + 1;", "            } else if fails(ds, code) {\n                passed = passed + 1;\n            } else {\n                failed = failed + 1;", "passed and failed are swapped"),
    ("runtime-failed", "report", "                if fails(ds, code) {\n                    runtime_failed = runtime_failed + 1;", "                if !fails(ds, code) {\n                    runtime_failed = runtime_failed + 1;", "the runtime check fails when it passes"),
    ("runtime-listed", "report", "    if runtime_n > 0 {\n        o = buffer.append(heap, o, \"[\\\"schema-version-unsupported\\\"]\");", "    if runtime_n > 1 {\n        o = buffer.append(heap, o, \"[\\\"schema-version-unsupported\\\"]\");", "the runtime check is never performed"),
    ("runtime-passed", "report", "o = count_json(heap, o, \"checks_passed\", runtime_n - runtime_failed);", "o = count_json(heap, o, \"checks_passed\", runtime_n);", "a failed runtime check counts as passed"),
    ("runtime-failed-count", "report", "o = count_json(heap, o, \"checks_failed\", runtime_failed);", "o = count_json(heap, o, \"checks_failed\", 0);", "a failed runtime check is not counted"),
    ("static-passed-count", "report", "o = count_json(heap, o, \"checks_passed\", passed);", "o = count_json(heap, o, \"checks_passed\", passed + failed);", "a failed check counts as passed"),
    ("refused", "report", "    let refused = !has_ir || dg.count_errors(ds) > 0;", "    let refused = !has_ir;", "a refused contract is round-tripped"),
    ("refused-ir", "report", "    let refused = !has_ir || dg.count_errors(ds) > 0;", "    let refused = dg.count_errors(ds) > 0;", "a contract that did not parse is round-tripped"),
    ("mode-none", "report", "    if mode != 2 {\n        if refused {", "    if mode != 2 && false {\n        if refused {", "no roundtrip is ever reported"),
    ("mode-none-kept", "report", "    if mode != 2 {\n        if refused {", "    if mode != 5 {\n        if refused {", "--no-roundtrips still reports the roundtrips"),
    ("mode-note", "report", "    if mode == 2 {\n        un = buffer.append", "    if mode == 0 {\n        un = buffer.append", "--no-roundtrips is not reported as unknown"),
    ("detail-sep", "report", "    d = buffer.append(heap, du.sep(heap, d, nd), \"{\\\"target\\\": \");", "    d = buffer.append(heap, du.sep(heap, d, 0), \"{\\\"target\\\": \");", "the details have no separator"),
    ("detail-tool", "report", "    if has_tool {\n        d = buffer.append(heap, d, \", \\\"tool\\\": \");", "    if !has_tool {\n        d = buffer.append(heap, d, \", \\\"tool\\\": \");", "a tool is written when there is none"),
    ("detail-outcome-failed", "report", "        d = buffer.append(heap, d, \"\\\"failed\\\"\");", "        d = buffer.append(heap, d, \"\\\"fail\\\"\");", "failed is written otherwise"),
    ("detail-outcome-passed", "report", "        d = buffer.append(heap, d, \"\\\"passed\\\"\");", "        d = buffer.append(heap, d, \"\\\"pass\\\"\");", "passed is written otherwise"),
    ("run-skipped", "report", "    if outcome != 2 {\n        var handle", "    if outcome != 1 {\n        var handle", "a skipped roundtrip is counted as run and a failed one is not"),
    ("run-handle", "report", "        handle = buffer.append(heap, handle, bytes.field(tool, ' ', 1));", "        handle = buffer.append(heap, handle, tool);", "the whole tool name is the handle"),
    ("run-handle-sep", "report", "        handle = buffer.append(heap, handle, \"::\");", "        handle = buffer.append(heap, handle, \":\");", "the handle has one colon"),
    ("run-sep", "report", "            rn = json_out.quoted(heap, du.sep(heap, rn, nrn), buffer.bytes(hr), 0, len(buffer.bytes(hr)));", "            rn = json_out.quoted(heap, du.sep(heap, rn, 0), buffer.bytes(hr), 0, len(buffer.bytes(hr)));", "the roundtrips run have no separator"),
    ("trust-why", "report", "not re-verified here\\\"}\");", "re-verified here\\\"}\");", "the trust note is paraphrased"),
    ("trust-tier", "report", "\\\"tier\\\": \\\"Trust\\\", \\\"why\\\"", "\\\"tier\\\": \\\"Static\\\", \\\"why\\\"", "a trust boundary is labelled otherwise"),
    ("trust-sep", "report", "        tr = buffer.append(heap, du.sep(heap, tr, ntr), \"{\\\"tool\\\": \");", "        tr = buffer.append(heap, du.sep(heap, tr, 0), \"{\\\"tool\\\": \");", "the trust boundaries have no separator"),
    ("trust-tools-sep", "report", "        tl = json_out.quoted(heap, du.sep(heap, tl, ntr), tool, 0, len(tool));", "        tl = json_out.quoted(heap, du.sep(heap, tl, 0), tool, 0, len(tool));", "the trust tools have no separator"),
    ("trust-count", "report", "        ntr = ntr + 1;\n        npp = npp + 1;", "        npp = npp + 1;", "a trust boundary is not counted"),
    ("failed-count", "report", "    } else if outcome == 1 {\n        nff = nff + 1;", "    } else if outcome == 1 {\n        npp = npp + 1;", "a failed roundtrip counts as passed"),
    ("unknown-sep", "report", "        un = unknown_item(heap, du.sep(heap, un, nun), target, why);", "        un = unknown_item(heap, du.sep(heap, un, 0), target, why);", "the unknown items have no separator"),
    ("unknown-count", "report", "        un = unknown_item(heap, du.sep(heap, un, nun), target, why);\n        nun = nun + 1;", "        un = unknown_item(heap, du.sep(heap, un, nun), target, why);", "the second unknown item has no separator"),
    ("unknown-note-sep", "report", "    un = buffer.append(heap, du.sep(heap, un, nun), \"{\\\"description\\\": \\\"behavioral", "    un = buffer.append(heap, du.sep(heap, un, 0), \"{\\\"description\\\": \\\"behavioral", "the behavioral note has no separator"),
    ("unknown-strip", "report", "        while e > 0 && is_strip(int_of(buffer.bytes(dr)[e - 1])) {", "        while false && e > 0 && is_strip(int_of(buffer.bytes(dr)[e - 1])) {", "the description is not stripped"),
    ("strip-space", "report", "    return c == ' ' || c >= 9 && c <= 13 || c >= 28 && c <= 31;", "    return c >= 9 && c <= 13 || c >= 28 && c <= 31;", "a space is not stripped"),
    ("strip-low", "report", "    return c == ' ' || c >= 9 && c <= 13 || c >= 28 && c <= 31;", "    return c == ' ' || c >= 10 && c <= 13 || c >= 28 && c <= 31;", "a tab is not stripped"),
    ("strip-high", "report", "    return c == ' ' || c >= 9 && c <= 13 || c >= 28 && c <= 31;", "    return c == ' ' || c >= 9 && c <= 12 || c >= 28 && c <= 31;", "a carriage return is not stripped"),
    ("strip-fs", "report", "    return c == ' ' || c >= 9 && c <= 13 || c >= 28 && c <= 31;", "    return c == ' ' || c >= 9 && c <= 13;", "the separators 28 to 31 are not stripped"),
    ("lane-mode", "report", "    var at = 0 - 1;\n    if mode == 1 {\n        at = lane_of(src, tape, target);", "    var at = 0 - 1;\n    if mode != 1 {\n        at = lane_of(src, tape, target);", "the lanes are read in the default mode"),
    ("lane-outcome-passed", "report", "    if json.string_equals(src, tape, outcome, \"passed\") {\n        code = 0;", "    if json.string_equals(src, tape, outcome, \"failed\") {\n        code = 0;", "a passed lane is read as failed"),
    ("lane-outcome-failed", "report", "    } else if json.string_equals(src, tape, outcome, \"failed\") {\n        code = 1;", "    } else if json.string_equals(src, tape, outcome, \"passed\") {\n        code = 1;", "a failed lane is read as skipped"),
    ("lane-target", "report", "        if json.string_equals(src, tape, json.get(src, tape, j, \"target\"), target) {\n            return j;", "        if json.string_equals(src, tape, json.get(src, tape, j, \"outcome\"), target) {\n            return j;", "the lane of another target is taken"),
    ("lane-of-array", "report", "fn lane_of[&s, &t](src: &s [byte], tape: &t [int], target: &static [byte]) -> [] int {\n    if !json.is_array(tape, 0) {\n        return 0 - 1;\n    }", "fn lane_of[&s, &t](src: &s [byte], tape: &t [int], target: &static [byte]) -> [] int {", "a lanes document that is not an array is walked"),
    ("lanes-check-array", "report", "pub fn lanes_check[&s, &t](src: &s [byte], tape: &t [int]) -> [] int {\n    if !json.is_array(tape, 0) {\n        return 1;\n    }", "pub fn lanes_check[&s, &t](src: &s [byte], tape: &t [int]) -> [] int {\n    if false {\n        return 1;\n    }", "a lanes document that is not an array is accepted"),
    ("lanes-check-object", "report", "        if !json.is_object(tape, j) {\n            return 2;", "        if false {\n            return 2;", "an entry that is not an object is accepted"),
    ("lanes-check-target", "report", "        if !is_target(src, tape, target) {\n            return 3;", "        if false {\n            return 3;", "an unknown target is accepted"),
    ("lanes-check-target-sv", "report", "json.string_equals(src, tape, node, \"c-header\") || json.string_equals(src, tape, node, \"systemverilog\")", "json.string_equals(src, tape, node, \"c-header\")", "systemverilog is not a target"),
    ("lanes-check-twice-c", "report", "            if seen_c {\n                return 4;", "            if false {\n                return 4;", "c-header twice is accepted"),
    ("lanes-check-twice-s", "report", "            if seen_s {\n                return 4;", "            if false {\n                return 4;", "systemverilog twice is accepted"),
    ("lanes-check-seen-c", "report", "            seen_c = true;", "            seen_c = false;", "c-header twice is not noticed"),
    ("lanes-check-seen-s", "report", "            seen_s = true;", "            seen_s = false;", "systemverilog twice is not noticed"),
    ("lanes-check-outcome", "report", "        if !(ran || json.string_equals(src, tape, outcome, \"skipped\")) {\n            return 5;", "        if false {\n            return 5;", "an unknown outcome is accepted"),
    ("lanes-check-skipped", "report", "        if !(ran || json.string_equals(src, tape, outcome, \"skipped\")) {", "        if !ran {", "skipped is not an outcome"),
    ("lanes-check-failed", "report", "let ran = json.string_equals(src, tape, outcome, \"passed\") || json.string_equals(src, tape, outcome, \"failed\");", "let ran = json.string_equals(src, tape, outcome, \"passed\");", "failed is not a ran outcome"),
    ("lanes-check-reason", "report", "        if !json.is_string(tape, json.get(src, tape, j, \"reason\")) {\n            return 6;", "        if false {\n            return 6;", "a lane with no reason is accepted"),
    ("lanes-check-tool-type", "report", "        if json.kind(tape, tool) >= 0 && !json.is_string(tape, tool) {\n            return 7;", "        if false {\n            return 7;", "a tool that is not a string is accepted"),
    ("lanes-check-tool-absent", "report", "        if json.kind(tape, tool) >= 0 && !json.is_string(tape, tool) {", "        if !json.is_string(tape, tool) {", "a skipped lane with no tool is refused"),
    ("lanes-check-tool-needed", "report", "        if ran && !json.is_string(tape, tool) {\n            return 8;", "        if false {\n            return 8;", "a passed lane with no tool is accepted"),
    ("lanes-check-advance", "report", "        j = json.skip(tape, j);\n        left = left - 1;\n    }\n    return 0;\n}", "        left = left - 1;\n    }\n    return 0;\n}", "only the first lane is checked"),
    ("lanes-reason-1", "report", "return \"the lanes document is not a JSON array\";", "return \"a target is given twice\";", "two lanes refusals share a reason"),
    # -- report: the text, strict
    ("text-input", "report", "    var o = buffer.append(heap, out, \"== cancho-hdl report: \");", "    var o = buffer.append(heap, out, \"== cancho-hdl report \");", "the text heading is misspelt"),
    ("text-static", "report", "o = buffer.push_nat(heap, o, count_of(src, tape, \"static\", \"checks_run\"));", "o = buffer.push_nat(heap, o, count_of(src, tape, \"static\", \"diagnostics\"));", "the text counts the diagnostics as the checks run"),
    ("text-skipped", "report", "                o = buffer.append(heap, o, \" (skipped: \");", "                o = buffer.append(heap, o, \" (skip: \");", "the skipped note is misspelt"),
    ("text-skipped-sep", "report", "                o = buffer.append(heap, o, \", \");\n            }\n            first = false;", "                o = buffer.append(heap, o, \"; \");\n            }\n            first = false;", "the skipped targets are joined with a semicolon"),
    ("text-skipped-close", "report", "    if !first {\n        o = buffer.push(heap, o, byte_of(')'));", "    if first {\n        o = buffer.push(heap, o, byte_of(')'));", "the skipped note is not closed"),
    ("text-tools-sep", "report", "            if n > 0 {\n                o = buffer.append(heap, o, \"; \");", "            if n > 0 {\n                o = buffer.append(heap, o, \", \");", "the trusted tools are joined with a comma"),
    ("text-tools-cut", "report", "            var cut = bytes.find(buffer.bytes(tr), \" (\");", "            var cut = bytes.find(buffer.bytes(tr), \"(\");", "the version is cut at the bracket, with the blank kept"),
    ("text-tools-nocut", "report", "            if cut < 0 {\n                cut = len(buffer.bytes(tr));", "            if cut < 0 {\n                cut = 0;", "a tool name with no version is dropped"),
    ("text-unknown", "report", "o = buffer.push_nat(heap, o, count_of(src, tape, \"unknown\", \"items\"));", "o = buffer.push_nat(heap, o, count_of(src, tape, \"unknown\", \"static_checks_not_run\"));", "the text counts the not-run checks as the unknown items"),
    ("strict-static", "report", "    if !bytes.equal(du.digits(src, tape, json.get(src, tape, st, \"checks_failed\")), \"0\") {", "    if false {", "a failed static check does not fail --strict"),
    ("strict-tested", "report", "    if !bytes.equal(du.digits(src, tape, json.get(src, tape, te, \"roundtrips_failed\")), \"0\") {", "    if false {", "a failed roundtrip does not fail --strict"),
    ("strict-skipped", "report", "        if !json.string_equals(src, tape, json.get(src, tape, j, \"outcome\"), \"passed\") {", "        if json.string_equals(src, tape, json.get(src, tape, j, \"outcome\"), \"failed\") {", "a skipped roundtrip does not fail --strict"),
    ("strict-runtime", "report", "    return bytes.equal(du.digits(src, tape, json.get(src, tape, rt, \"checks_failed\")), \"0\");", "    return true;", "a failed runtime check does not fail --strict"),
    # -- report_check
    ("check-not-object", "report_check", "    if !json.is_object(tape, 0) {\n        return refuse(heap, out, \"report-schema-truncated\", \"report is not a JSON object\");", "    if false {\n        return refuse(heap, out, \"report-schema-truncated\", \"report is not a JSON object\");", "a report that is not an object is walked"),
    ("check-schema", "report_check", "!is_text(src, tape, json.get(src, tape, 0, \"schema\"), \"cancho-hdl-report\")", "false", "the schema name is not checked"),
    ("check-keys", "report_check", "    while k < 5 {", "    while k < 4 {", "the last mandatory field is not checked"),
    ("check-key-null", "report_check", "        if json.kind(tape, json.get(src, tape, 0, field_key(k))) <= 0 {", "        if json.kind(tape, json.get(src, tape, 0, field_key(k))) < 0 {", "a null mandatory field is accepted"),
    ("check-key-names", "report_check", "    if i == 2 {\n        return \"static_checks_run\";", "    if i == 2 {\n        return \"static_checks\";", "a mandatory field is misnamed"),
    ("check-ng", "report_check", "            if !list_has(heap, src, tape, stated, rd.ng_at(i)) {", "            if false {", "a paraphrased non-guarantee is accepted"),
    ("check-ng-all", "report_check", "        var i = 0;\n        while i < rd.ng_count() {", "        var i = 1;\n        while i < rd.ng_count() {", "the first non-guarantee is not checked"),
    ("check-trust-tier", "report_check", "                if !is_text(src, tape, tier, \"Trust\") {", "                if false {", "a boundary labelled otherwise is accepted"),
    ("check-trust-object", "report_check", "                if !json.is_object(tape, j) {\n                    tool = 0 - 1;", "                if false {\n                    tool = 0 - 1;", "a boundary that is not an object is read"),
    ("check-trust-list", "report_check", "        let boundaries = json.get(src, tape, trust, \"boundaries\");\n        if json.is_array(tape, boundaries) {", "        let boundaries = json.get(src, tape, trust, \"boundaries\");\n        if true {", "boundaries that are not a list are walked"),
    ("check-outside", "report_check", "            if !inside {\n                outside =", "            if false {\n                outside =", "a code outside the catalog is accepted"),
    ("check-outside-string", "report_check", "            if json.is_string(tape, j) {\n                let c = decoded(heap, src, tape, j);\n                borrow c as &cr in {\n                    inside", "            if true {\n                let c = decoded(heap, src, tape, j);\n                borrow c as &cr in {\n                    inside", "a number in checks_run is inside the catalog"),
    ("check-sum", "report_check", "        if pv + fv != list_count(tape, run) {\n            var m = buffer.append(heap, buffer.empty(heap, 96), \"static passed", "        if pv + fv > list_count(tape, run) {\n            var m = buffer.append(heap, buffer.empty(heap, 96), \"static passed", "a count that is too low is accepted"),
    ("check-sum-less", "report_check", "        if pv + fv != list_count(tape, run) {\n            var m = buffer.append(heap, buffer.empty(heap, 96), \"static passed", "        if pv + fv < list_count(tape, run) {\n            var m = buffer.append(heap, buffer.empty(heap, 96), \"static passed", "a count that is too high is accepted"),
    ("check-sum-default", "report_check", "    let run_ok = run_list || json.kind(tape, run) < 0;", "    let run_ok = run_list;", "an absent checks_run is not the empty list"),
    ("check-sum-msg", "report_check", "m = buffer.append(heap, m, \" != \");\n            m = buffer.push_nat(heap, m, list_count(tape, run));\n            o = refuse_buf(heap, o, \"evidence-over-claim\", m);\n        }\n    }\n    // An Error", "m = buffer.append(heap, m, \" != \");\n            m = buffer.push_nat(heap, m, pv);\n            o = refuse_buf(heap, o, \"evidence-over-claim\", m);\n        }\n    }\n    // An Error", "the length in the message is a count"),
    ("check-bool-count", "report_check", "    if json.kind(tape, node) == json.kind_true() {\n        return (true, 1, true);", "    if json.kind(tape, node) == json.kind_true() {\n        return (true, 0, true);", "True is zero"),
    ("check-bool-false", "report_check", "    if json.kind(tape, node) == json.kind_false() {\n        return (true, 0, true);", "    if json.kind(tape, node) == json.kind_false() {\n        return (true, 1, true);", "False is one"),
    ("check-bool-show", "report_check", "    if is_bool {\n        if n == 1 {\n            return buffer.append(heap, out, \"True\");", "    if is_bool {\n        if n == 0 {\n            return buffer.append(heap, out, \"True\");", "True is written False"),
    ("check-negative", "report_check", "    if n < 0 {\n        return buffer.push_nat(heap, buffer.push(heap, out, byte_of('-')), 0 - n);", "    if n < 0 {\n        return buffer.push_nat(heap, out, 0 - n);", "a negative count loses its sign"),
    ("check-count-default", "report_check", "    if json.kind(tape, node) < 0 {\n        return (true, 0, false);", "    if json.kind(tape, node) < 0 {\n        return (false, 0, false);", "an absent count is not zero"),
    ("check-count-int", "report_check", "    if json.is_int(tape, node) && json.fits_int(src, tape, node) {", "    if json.is_int(tape, node) {", "an integer that does not fit is read"),
    ("check-errors", "report_check", "            if json.is_object(tape, j) && is_text(src, tape, json.get(src, tape, j, \"severity\"), \"Error\") {", "            if json.is_object(tape, j) {", "a warning outside checks_run is refused"),
    ("check-errors-object", "report_check", "            if json.is_object(tape, j) && is_text(src, tape, json.get(src, tape, j, \"severity\"), \"Error\") {", "            if is_text(src, tape, json.get(src, tape, j, \"severity\"), \"Error\") {", "a diagnostic that is not an object is read"),
    ("check-errors-listed", "report_check", "                        var fresh = !list_has(heap, src, tape, run, buffer.bytes(cr));", "                        var fresh = true;", "an Error for a code that ran is refused"),
    ("check-errors-none", "report_check", "                } else if json.kind(tape, code) <= 0 {\n                    if !list_has_null(tape, run) {", "                } else if json.kind(tape, code) <= 0 {\n                    if true {", "a null code held by checks_run is refused"),
    ("check-errors-none-kind", "report_check", "                } else if json.kind(tape, code) <= 0 {", "                } else if json.kind(tape, code) < 0 {", "a null code is another type"),
    ("check-errors-int", "report_check", "                    if iok {\n                        present = list_has_int(src, tape, run, iv);", "                    if false {\n                        present = list_has_int(src, tape, run, iv);", "an integer code held by checks_run is refused"),
    ("check-errors-other-dedupe", "report_check", "                                if !lines_have_all(buffer.bytes(orr), buffer.bytes(rr)) {\n                                    present = false;\n                                } else {\n                                    present = true;\n                                }", "                                present = false;", "a code of another type is listed twice"),
    ("check-errors-sorted", "report_check", "            if (!started || bytes.compare(line, after) > 0) && (!found || bytes.compare(line, best) < 0) {", "            if (!started || bytes.compare(line, after) > 0) && (!found || bytes.compare(line, best) > 0) {", "the codes are listed largest first"),
    ("check-errors-none-first", "report_check", "    if first {\n        o = buffer.append(heap, o, \"None\");\n        n = 1;\n    }", "    if first {\n        o = buffer.append(heap, o, \"None\");\n        n = 0;\n    }", "None has no separator after it"),
    ("check-errors-others", "report_check", "        if n > 0 {\n            o = buffer.append(heap, o, \", \");\n        }\n        o = buffer.append(heap, o, others[at2..e]);", "        o = buffer.append(heap, o, others[at2..e]);", "the codes of other types have no separator"),
    ("check-tested-sum", "report_check", "&& pok && fok && pv + fv != list_count(tape, run) {", "&& pok && fok && pv + fv > list_count(tape, run) {", "tested counts that are too low are accepted"),
    ("check-tested-sum-less", "report_check", "&& pok && fok && pv + fv != list_count(tape, run) {", "&& pok && fok && pv + fv < list_count(tape, run) {", "tested counts that are too high are accepted"),
    ("check-tested-default", "report_check", "    if (json.is_array(tape, run) || json.kind(tape, run) < 0) && pok", "    if json.is_array(tape, run) && pok", "an absent roundtrips_run is not the empty list"),
    ("check-skipped", "report_check", "if json.is_object(tape, j) && is_text(src, tape, json.get(src, tape, j, \"outcome\"), \"skipped\") {", "if json.is_object(tape, j) && is_text(src, tape, json.get(src, tape, j, \"outcome\"), \"passed\") {", "a skipped roundtrip counted as run is accepted"),
    ("check-skipped-object", "report_check", "if json.is_object(tape, j) && is_text(src, tape, json.get(src, tape, j, \"outcome\"), \"skipped\") {", "if is_text(src, tape, json.get(src, tape, j, \"outcome\"), \"skipped\") {", "a detail that is not an object is read"),
    ("check-skipped-handle", "report_check", "                handle = buffer.append(heap, handle, \"::\");", "                handle = buffer.append(heap, handle, \":\");", "the handle has one colon"),
    ("check-skipped-prefix", "report_check", "                                    if bytes.starts_with(buffer.bytes(rr), buffer.bytes(hr)) {", "                                    if bytes.find(buffer.bytes(rr), buffer.bytes(hr)) >= 0 {", "a handle found inside a name is taken for its prefix"),
    ("check-skipped-count", "report_check", "                if n > 0 {\n                    o = refuse_buf(heap, o, \"evidence-over-claim\", m);", "                if true {\n                    o = refuse_buf(heap, o, \"evidence-over-claim\", m);", "a skipped roundtrip not counted as run is refused"),
    ("check-skipped-sep", "report_check", "                                        m = pyrepr.str_repr(heap, du_sep(heap, m, n), buffer.bytes(rr));", "                                        m = pyrepr.str_repr(heap, du_sep(heap, m, 0), buffer.bytes(rr));", "the claimed handles have no separator"),
    ("check-skipped-target", "report_check", "                var handle = str_of(heap, buffer.empty(heap, 64), src, tape, json.get(src, tape, j, \"target\"));", "                var handle = buffer.empty(heap, 64);", "the handle has no target"),
    ("check-str-of", "report_check", "    if json.is_string(tape, node) {\n        let text = decoded(heap, src, tape, node);", "    if false {\n        let text = decoded(heap, src, tape, node);", "a string target is written with its quotes"),
    ("check-repr-none", "report_check", "    if json.kind(tape, node) < 0 {\n        return buffer.append(heap, out, \"None\");", "    if json.kind(tape, node) < 0 {\n        return buffer.append(heap, out, \"null\");", "an absent value is written null"),
    ("check-list-has-string", "report_check", "        if json.is_string(tape, j) {\n            let e = decoded(heap, src, tape, j);", "        if true {\n            let e = decoded(heap, src, tape, j);", "a number is read as a string"),
    ("check-catalog", "report_check", "                    inside = rd.in_catalog(buffer.bytes(cr));", "                    inside = true;", "any string is inside the catalog"),
    ("check-int-has", "report_check", "        if ok && v == n {\n            return true;", "        if ok && v != n {\n            return true;", "an integer code is held by any other number"),
    ("check-lines-have-all", "report_check", "    return lines_have(lines, one[0..len(one) - 1]);", "    return lines_have(lines, one);", "a line is compared with its newline"),
]

# name -> reason
EQUIVALENT = {
    "names-has": "no catalog code is a prefix of another, and only catalog codes are looked up, so `starts_with` and `equal` answer alike",
    "fails-nest": "a related entry carries the rule of its parent (or a Warning's), so an Error among the related entries of a top-level diagnostic that is not itself one does not occur in the checker's output",
    "fired-order": "the fired codes that are not already listed are `schema-invalid` of a JSON syntax error alone: the order of two of them has no input",
    "fired-catalog": "`Rule` is a closed set and every rule name is in the catalog (a unit test walks all of them), so the test is always true for an emitted code",
    "group-ran": "`ran` is 0 when there is no IR, so the bit test is false anyway",
    "refused-ir": "no IR means the loader gave a diagnostic that is an Error, so `count_errors` is above 0 on that path too; the wording that differs between the two cases is chosen by `has_ir`, which this break leaves alone",
    "lane-of-array": "`lane_of` runs only on a lanes document `lanes_check` accepted, which is an array; `json.count` of anything else is 0 and the walk is empty",
    "strict-tested": "a failed roundtrip is not `passed`, so the loop over the details refuses it too (report.py has the same overlap)",
    "check-trust-object": "`json.get` on a node that is not an object answers absent, which is what the branch sets by hand",
    "check-outside-string": "`decoded` of a number is empty, and the empty string is outside the catalog, as the number is",
    "check-list-has-string": "`decoded` of a number is empty, and no restated row or claimed code is the empty string",
    "check-errors-none-first": "None met with a code of another type is a sort of mixed types, on which report.py raises: there is no oracle text, and None alone needs no separator",
    "fired-not-run": "a code that fired is never in `not_run` as `check` emits it only from a group that ran; the removal is Python's defence in depth (35.1) and has no input here that reaches it",
    "fired-nest": "a related entry carries the code of its parent or another top-level rule; the codes a related entry holds alone do not occur in the checker's output",
    "check-skipped-object": "`json.get` of a key on a node that is not an object answers absent, so a detail that is not an object has no `outcome` and never equals `skipped`",
    "check-errors-object": "`json.get` of `severity` on a node that is not an object answers absent, which is never `Error`",
    "check-trust-list": "an array is the only thing the walk treats as a list: `json.count` of a non-list is 0, so the loop body is not entered",
    "lanes-check-array": "`lane_of` is called only after `lanes_check` accepted the document, which is an array; with a non-array `json.count` is 0 and the walk is empty",
    "lanes-reason-1": "`lanes_reason` is only a message; it is tested to be distinct and non-empty for each code, and 1 is distinct from 4 in the original (the break makes them equal, which that test sees)",
}


def sh(cmd, timeout=1200, **kw):
    """A break may loop for ever: a run that does not end in `timeout` seconds has failed, as a test that fails does."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, timeout=timeout, **kw)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", "timed out")


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
        lib = [str(src / f"{x}.cho") for x in MODULES]
        t = sh([CANCHO, "test", "tests/unit/test_report.cho", "tests/unit/support.cho", *lib, "--std"])
        if t.returncode != 0:
            tiers.append("unit")
        else:
            # the slow tier runs only for a break the unit tests let through
            if sh([sys.executable, "tests/differential/report_cmp.py", str(exe), "--fixtures-only", "--real-lanes"]).returncode != 0:
                tiers.append("fixtures")
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
        print(f"{verdict:34} {name:26} {what}")
        if verdict == "EQUIVALENT":
            equivalent += 1
            print(f"  equivalent: {EQUIVALENT[name]}")
        elif not verdict.startswith("KILLED"):
            survived += 1
    print(f"{len(results) - survived - equivalent} of {len(results)} breaks killed, {equivalent} equivalent")
    sys.exit(1 if survived else 0)


main()
