"""Golden tests for `chw report`, the cancho port of the evidence report (docs/cancho-port.md, 35): the claims of
the retired Python golden (tests/report/report_golden.py, deleted in stage 7), held against the cancho binary instead of report.py. Oracle code: it decides nothing.

The product runs no tool (1.2), so the Tested tier is read from lane results this script writes (a clang that passed, an
iverilog that is not on the $PATH), as an oracle run would.

    python3 tests/report/report_cancho_golden.py /path/to/built/chw
"""
import copy
import json
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
EXE = sys.argv[1]
FAILURES = []


def expect(cond, label, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        if detail:
            print(detail)
        FAILURES.append(label)


def chw(*args):
    p = subprocess.run([EXE, *args], capture_output=True, text=True, cwd=ROOT)
    return p.returncode, p.stdout, p.stderr


def docs_non_guarantees():
    text = (ROOT / "docs" / "guarantees.md").read_text()
    section = re.search(r"## 2\. .*?(?=\n## 3\.)", text, re.S).group(0)
    rows = []
    for line in section.splitlines():
        m = re.match(r"^\| (.+?) \|", line.strip())
        if m and m.group(1).strip() != "Non-guarantee":
            rows.append(m.group(1).strip())
    return rows


def lanes(tmp, path):
    f = pathlib.Path(tmp) / "lanes.json"
    f.write_text(json.dumps([
        {"target": "c-header", "input": path, "tool": "clang (test)", "outcome": "passed", "reason": "compiled clean"},
        {"target": "systemverilog", "input": path, "tool": "iverilog (not on $PATH)", "outcome": "skipped", "reason": "no SystemVerilog parser on $PATH; not checked"},
    ]))
    return str(f)


def report(tmp, path, *flags):
    rc, out, err = chw("report", path, *flags, "--lanes", lanes(tmp, path))
    return rc, out, err


def validate(doc, tmp):
    f = pathlib.Path(tmp) / "doc.json"
    f.write_text(json.dumps(doc))
    return chw("report", "--validate", str(f))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        print("## catalog pinning ##")
        rc, out, err = chw("report", "examples/uart-contract/uart.chw", "--no-roundtrips")
        doc = json.loads(out)
        rows = docs_non_guarantees()
        expect(rows == doc["non_guarantees"], "the report's non-guarantees == docs/guarantees.md section 2, in order", f"docs={rows}\nreport={doc['non_guarantees']}")
        expect(len(rows) == 9, "nine rows")

        print("## valid contract (uart) ##")
        rc, out, err = report(tmp, "examples/uart-contract/uart.chw")
        doc = json.loads(out)
        expect(rc == 0 and err == "", "the report is written, nothing on standard error")
        for key in ("non_guarantees", "trust_boundaries", "static_checks_run", "tested_roundtrips_run", "unknown_items"):
            expect(key in doc, f"mandatory field present: {key}")
        st = doc["static"]
        expect(st["checks_passed"] + st["checks_failed"] == len(st["checks_run"]) == len(doc["static_checks_run"]), "static counts sum to len(checks_run)")
        fired_errors = {d["code"] for d in st["diagnostics"] if d["severity"] == "Error"}
        expect(not (fired_errors - set(st["checks_run"])), "every fired Error is inside checks_run")
        expect("dma-overlap" not in st["checks_run"] and "dma-overlap" in doc["unknown"]["static_checks_not_run"], "DMA rules over a contract without buffers: not run, and reported as not run")
        expect("field-overlap" in st["checks_run"], "field-overlap ran")
        expect(doc["trust"]["count"] == len(doc["trust"]["boundaries"]) == 1 and all(b["tier"] == "Trust" for b in doc["trust"]["boundaries"]), "the one trust boundary counted and labelled Trust")
        details = {d["target"]: d for d in doc["tested"]["details"]}
        expect(details["c-header"]["outcome"] == "passed" and details["systemverilog"]["outcome"] == "skipped", "the lanes are the details")
        expect(doc["tested"]["roundtrips_run"] == ["c-header::clang"] and doc["tested"]["roundtrips_passed"] == 1 and doc["tested"]["roundtrips_failed"] == 0, "tested counts count only the roundtrip that ran")
        expect(any("systemverilog roundtrip not run" in u["description"] for u in doc["unknown_items"]), "the skipped roundtrip is an unknown item")
        expect(len(doc["unknown_items"]) > 0 and all(u["tier"] == "Unknown" for u in doc["unknown_items"]), "unknown items present and Unknown-tiered")
        rc_strict = report(tmp, "examples/uart-contract/uart.chw", "--strict")[0]
        expect(rc_strict == 1, "--strict exits 1 while a roundtrip is skipped", str(rc_strict))

        print("## the default is honest ##")
        rc, out, err = chw("report", "examples/uart-contract/uart.chw")
        doc = json.loads(out)
        expect(all(d["outcome"] == "skipped" for d in doc["tested"]["details"]) and doc["tested"]["roundtrips_run"] == [] and doc["trust"]["boundaries"] == [], "with no lanes nothing is claimed to have run")
        expect(chw("report", "examples/uart-contract/uart.chw", "--strict")[0] == 1, "--strict exits 1 with no lanes")

        print("## determinism ##")
        a = report(tmp, "examples/uart-contract/uart.chw")
        b = report(tmp, "examples/uart-contract/uart.chw")
        expect(a == b, "two runs over the same contract: byte-identical")
        expect(report(tmp, "examples/uart-contract/uart.chw", "--output", "text") == report(tmp, "examples/uart-contract/uart.chw", "--output", "text"), "text form deterministic")

        print("## a refused contract still gets a complete report ##")
        rc, out, err = report(tmp, "examples/refusal/field-overlap.chw")
        refused = json.loads(out)
        expect(rc == 0 and err == "", "complete report, exit 0")
        expect(refused["static"]["checks_failed"] >= 1 and "field-overlap" in refused["static"]["checks_run"], "the refusal is the static evidence")
        expect(all(d["outcome"] == "skipped" for d in refused["tested"]["details"]) and refused["tested"]["roundtrips_run"] == [], "roundtrips skipped over a refused contract: the lanes are not read")
        expect(report(tmp, "examples/refusal/field-overlap.chw", "--strict")[0] == 1, "--strict exits 1 on a refused contract")

        print("## a parse-error document ##")
        rc, out, err = report(tmp, "examples/refusal/parse-error.chw")
        parse = json.loads(out)
        expect(rc == 0 and [d["code"] for d in parse["static"]["diagnostics"]] == ["parse-error"], "parse-error is the static evidence")
        expect(parse["static"]["checks_run"] == ["parse-error"], "only the parse pass ran")
        expect(all(d["outcome"] == "skipped" for d in parse["tested"]["details"]), "no roundtrips on an unparseable contract")

        print("## a lanes file that is not acceptable is refused ##")
        bad = pathlib.Path(tmp) / "bad.json"
        for text, why in (("{", "not JSON"), ("{}", "not an array"), ('[{"target":"c-header","outcome":"passed","reason":"r"}]', "a passed lane with no tool")):
            bad.write_text(text)
            rc, out, err = chw("report", "examples/uart-contract/uart.chw", "--lanes", str(bad))
            expect(rc == 1 and out == "" and err.startswith("error[lanes-invalid]: "), f"lanes-invalid: {why}", err)
        rc, out, err = chw("report", "examples/uart-contract/uart.chw", "--lanes", str(pathlib.Path(tmp) / "absent.json"))
        expect(rc == 1 and err.startswith("error[lanes-invalid]: "), "lanes-invalid: a file that cannot be read", err)

        print("## corrupted reports are refused ##")
        rc, out, err = report(tmp, "examples/uart-contract/uart.chw")
        base = json.loads(out)
        expect(validate(base, tmp)[0] == 0, "the real report is accepted")

        def refused_by(mutate, code, label):
            d = copy.deepcopy(base)
            mutate(d)
            rc, out, err = validate(d, tmp)
            expect(rc == 1 and f"internal[{code}]: " in err, label, err)

        refused_by(lambda d: d.pop("non_guarantees"), "report-schema-truncated", "missing non_guarantees -> truncated")
        refused_by(lambda d: d["non_guarantees"].pop(0), "report-schema-truncated", "dropped section 2 row -> truncated")
        refused_by(lambda d: d.pop("unknown_items"), "report-schema-truncated", "missing unknown_items -> truncated")
        refused_by(lambda d: d["static"].__setitem__("checks_passed", d["static"]["checks_passed"] + 3), "evidence-over-claim", "inflated passed count -> over-claim")
        refused_by(lambda d: d["static"]["checks_run"].append("timing-closure-too-fast"), "evidence-over-claim", "check claimed outside the catalog -> over-claim")
        refused_by(lambda d: d["trust"]["boundaries"][0].__setitem__("tier", "Tested"), "evidence-over-claim", "trust boundary relabelled -> over-claim")
        refused_by(lambda d: d["tested"]["roundtrips_run"].append("systemverilog::iverilog"), "evidence-over-claim", "skipped roundtrip counted as run -> over-claim")
        refused_by(lambda d: d["tested"]["roundtrips_run"].pop(), "evidence-over-claim", "tested run-list shortened under the counts -> count mismatch")
        rc, out, err = chw("report", "--validate", str(pathlib.Path(tmp) / "absent.json"))
        expect(rc == 2, "--validate of a file that cannot be read exits 2")
        notjson = pathlib.Path(tmp) / "notjson.txt"
        notjson.write_text("x")
        rc, out, err = chw("report", "--validate", str(notjson))
        expect(rc == 1 and err.startswith("error[report-unreadable]: "), "--validate of a file that is not JSON: report-unreadable", err)

    if FAILURES:
        print(f"== report golden (cancho): {len(FAILURES)} failure(s) ==")
        return 1
    print("== report golden (cancho): all pass ==")
    return 0


sys.exit(main())
