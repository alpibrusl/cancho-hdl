"""Golden tests for the evidence report (oracle/legacy/tools/report/report.py).

Covers the §6 contract end to end:

1. A valid contract gets a complete report: every mandatory field
   present, the §2 non-guarantees restated **verbatim** and pinned —
   the test parses the markdown table from docs/guarantees.md and
   requires set equality with the report's catalog, so a cream-off
   row in either place fails.
2. Every claim is arithmetically derivable: passed+failed ==
   len(checks_run); a fired Error diagnostic is never outside
   checks_run; skipped roundtrips are counted nowhere as passed.
3. Evidence-provenance rule: codes for groups that did not run (the
   DMA family over a uart contract with no dma_buffers) appear in
   unknown.static_checks_not_run, never in checks_run.
4. Refusal lane: a refused contract still yields a complete report —
   the refusal is the static evidence, the roundtrips are reported
   `outcome: "skipped"` with the refusal as the reason, and --strict
   exits 1. A parse-error document reports only the parse refusal.
5. The self-validation refusals (§6.2): intentionally corrupted
   report copies are rejected with report-schema-truncated (missing
   mandatory sections, paraphrased non-guarantees) or
   evidence-over-claim (miscounted tally, code outside the catalog,
   skipped roundtrip counted as run, Trust boundary relabelled).
6. Determinism: two runs over the same contract produce byte-identical
   JSON (modulo the compiler-version string, which is fixed on this
   machine but could differ across environments — the test diffs the
   raw documents directly, which is exactly the same-machine claim).

Run from anywhere:
    python3 tests/report/report_golden.py
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oracle" / "legacy" / "tools" / "report"))

from report import (  # noqa: E402
    NON_GUARANTEES, build_report, validate_report, format_text,
)

FAILURES: list[str] = []


def expect(cond: bool, label: str, detail: str = "") -> None:
    if cond:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}")
        if detail:
            print(detail)
        FAILURES.append(label)


def _docs_non_guarantees() -> list[str]:
    """Parse the first column of the §2 table of docs/guarantees.md."""
    text = (ROOT / "docs" / "guarantees.md").read_text()
    section = re.search(r"## 2\. .*?(?=\n## 3\.)", text, re.S).group(0)
    rows = []
    for line in section.splitlines():
        m = re.match(r"^\| (.+?) \|", line.strip())
        if m and m.group(1).strip() != "Non-guarantee":
            rows.append(m.group(1).strip())
    return rows


def main() -> int:
    print("== report golden ==")

    print()
    print("## catalog pinning ##")
    docs_rows = _docs_non_guarantees()
    expect(set(docs_rows) == set(NON_GUARANTEES) and len(docs_rows) == len(NON_GUARANTEES),
           "report's non-guarantee catalog == docs/guarantees.md §2 table (set + count)",
           f"docs={docs_rows}\nreport={list(NON_GUARANTEES)}")

    print()
    print("## valid contract (uart JSON) ##")
    doc = build_report("examples/uart-contract/uart.chw")
    for key in ("non_guarantees", "trust_boundaries", "static_checks_run",
                "tested_roundtrips_run", "unknown_items"):
        expect(key in doc, f"mandatory field present: {key}")
    expect(validate_report(doc) == [], "self-validation accepts the real report",
           json.dumps(validate_report(doc)))
    st = doc["static"]
    expect(st["checks_passed"] + st["checks_failed"] == len(st["checks_run"]) == len(doc["static_checks_run"]),
           "static counts sum to len(checks_run)",
           f"{st['checks_passed']}+{st['checks_failed']} vs {len(st['checks_run'])}")
    fired_errors = {d["code"] for d in st["diagnostics"] if d["severity"] == "Error"}
    expect(not (fired_errors - set(st["checks_run"])),
           "every fired Error is inside checks_run", json.dumps(sorted(fired_errors)))
    expect("dma-overlap" not in st["checks_run"]
           and "dma-overlap" in doc["unknown"]["static_checks_not_run"],
           "DMA rules over a contract without buffers: not run, and reported as not run",
           json.dumps(doc["unknown"]["static_checks_not_run"]))
    expect("field-overlap" in st["checks_run"],
           "field-overlap ran (it evaluated and found nothing)")
    expect(all(ng in doc["non_guarantees"] for ng in NON_GUARANTEES),
           "§2 rows restated verbatim (all 9)")
    expect(doc["trust"]["count"] == len(doc["trust"]["boundaries"])
           and all(b["tier"] == "Trust" for b in doc["trust"]["boundaries"]),
           "trust boundaries counted and all Trust")
    details = {d["target"]: d for d in doc["tested"]["details"]}
    expect(details["c-header"]["outcome"] == "passed" and "clang" in details["c-header"]["tool"],
           "c-header roundtrip ran and passed under clang",
           json.dumps(details["c-header"]))
    expect(details["systemverilog"]["outcome"] == "skipped"
           and "no SystemVerilog parser" in details["systemverilog"]["reason"],
           "systemverilog roundtrip reported skipped (no tool on $PATH)",
           json.dumps(details["systemverilog"]))
    expect(doc["tested"]["roundtrips_passed"] + doc["tested"]["roundtrips_failed"]
           == len(doc["tested"]["roundtrips_run"]) == 1,
           "tested counts count only the roundtrip that ran")
    expect(len(doc["unknown_items"]) > 0 and all(u["tier"] == "Unknown" for u in doc["unknown_items"]),
           "unknown items present and Unknown-tiered")

    print()
    print("## determinism ##")
    doc2 = build_report("examples/uart-contract/uart.chw")
    expect(json.dumps(doc) == json.dumps(doc2),
           "two runs over the same contract → byte-identical JSON")
    expect(format_text(doc) == format_text(doc2), "text form deterministic")

    print()
    print("## refusal contract still gets a complete report ##")
    refused = build_report("examples/refusal/field-overlap.chw")
    expect(validate_report(refused) == [], "refused contract → complete, valid report",
           json.dumps(validate_report(refused)))
    rst = refused["static"]
    expect(rst["checks_failed"] >= 1 and "field-overlap" in rst["checks_run"],
           "refusal is the static evidence (field-overlap failed)",
           json.dumps(rst["checks_failed"]))
    skipped = {d["target"]: d for d in refused["tested"]["details"]}
    expect(all(skipped[t]["outcome"] == "skipped" for t in ("c-header", "systemverilog")),
           "roundtrips skipped over a refused contract (never 'attempted')")
    proc = subprocess.run(
        [sys.executable, "oracle/legacy/tools/report/report.py", "examples/refusal/field-overlap.chw", "--strict"],
        capture_output=True, text=True, cwd=str(ROOT))
    expect(proc.returncode == 1, "--strict exits 1 on a refused contract", str(proc.returncode))

    print()
    print("## parse-error document ##")
    parsedown = build_report("examples/refusal/parse-error.chw")
    expect(validate_report(parsedown) == [], "parse-error contract → complete, valid report",
           json.dumps(validate_report(parsedown)))
    expect(any(d["code"] == "parse-error" for d in parsedown["static"]["diagnostics"]),
           "parse-error is the static evidence")
    expect(all(d["outcome"] == "skipped" for d in parsedown["tested"]["details"]),
           "no roundtrips on an unparseable contract")

    print()
    print("## corrupted reports are refused ##")
    base = build_report("examples/uart-contract/uart.chw")
    import copy

    def refused_by(mutate, expected_code, label):
        d = copy.deepcopy(base)
        doc_, code = d, expected_code
        mutate(doc_)
        got = validate_report(doc_)
        expect(any(c == code for c, _ in got), label, json.dumps(got))

    refused_by(lambda d: d.pop("non_guarantees"), "report-schema-truncated",
               "missing non_guarantees → truncated")
    refused_by(lambda d: d["non_guarantees"].pop(0), "report-schema-truncated",
               "dropped §2 row → truncated (no omission)")
    refused_by(lambda d: d.pop("unknown_items"), "report-schema-truncated",
               "missing unknown_items → truncated")
    refused_by(lambda d: d["static"].__setitem__("checks_passed", d["static"]["checks_passed"] + 3),
               "evidence-over-claim", "inflated passed count → over-claim")
    refused_by(lambda d: d["static"]["checks_run"].append("timing-closure-too-fast"),
               "evidence-over-claim", "check claimed outside the catalog → over-claim")
    refused_by(lambda d: d["trust"]["boundaries"][0].__setitem__("tier", "Tested"),
               "evidence-over-claim", "trust boundary relabelled → over-claim")
    refused_by(lambda d: d["tested"]["roundtrips_run"].append("systemverilog::iverilog"),
               "evidence-over-claim", "skipped roundtrip counted as run → over-claim")
    refused_by(lambda d: d["tested"]["roundtrips_run"].pop(),
               "evidence-over-claim", "tested run-list shortened under the counts → count mismatch")

    print()
    if FAILURES:
        print(f"== report golden: {len(FAILURES)} failure(s) ==")
        return 1
    print("== report golden: all pass ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
