"""The evidence report (oracle/legacy/tools/report/) — `cancho-hdl report`.

`cancho-hdl report <contract.chw>` produces `spec/diagnostics/README.md`
§6: a JSON document scored per tier, in which every claim is derived
from something that actually ran during this invocation — the schema
pass, the static checker, the c-header compile roundtrip, the
SystemVerilog parse when a tool is on `$PATH`.

Rules the document lives by (§6.1/§6.2, docs/guarantees.md §3):

- `static_checks_run` lists the rule codes **actually invoked**. The
  checker instruments its rule groups (`checker.check(..., ran=set())`);
  the report maps groups to catalog codes. A group that did not run
  (no DMA buffers, no interrupts, jsonschema absent, parse never
  reached) appears in `unknown.static_checks_not_run` — never in
  `checks_run`.
- `tested_roundtrips_run` is analogous for generator roundtrips; a
  skipped roundtrip is listed with `outcome: "skipped"`, never
  smuggled into the passed count.
- `trust_boundaries` names every external tool the report leans on
  (the compiler, the SV parser), each labeled `Trust` — never
  relabelled.
- `non_guarantees` literally restates every row of
  docs/guarantees.md §2 (no summary, no paraphrase, no omission).
  The catalog is pinned to the doc by the golden suite, which parses
  the markdown table and compares sets.
- `unknown_items` is free-form; the item may exist (unavailable
  behavioral roundtrip, unenforced constraint semantics). Empty is
  valid; absent is not.

The report **validates itself** before emitting: function
`validate_report` re-checks the document against §6.2 and refuses
with `report-schema-truncated` (missing mandatory sections) or
`evidence-over-claim` (counts that cannot add up, a Trust boundary
labelled otherwise, a roundtrip counted as passed because it was
skipped, a code claimed outside the catalog). The golden suite feeds
it intentionally corrupted copies — the refusals are the conformance
suite's `evidence-over-claim` test.

Staleness note: an invalid contract still gets a complete report —
the refusal is the `static.failed` evidence, and the roundtrip tier
is reported as *not attempted* (`outcome: "skipped"` with the refusal
as the reason). A report over a contract the checker refused never
claims the generators ran.

Usage:

    python3 oracle/legacy/tools/report/report.py <contract.chw>            # JSON
    python3 oracle/legacy/tools/report/report.py <contract.chw> --pretty   # indented JSON
    python3 oracle/legacy/tools/report/report.py <contract.chw> --output text
    python3 oracle/legacy/tools/report/report.py <contract.chw> --strict   # exit 1 if any tier not "passed"

Strict means: static tier passed (zero Error diagnostics), tested
tier passed (every attempted roundtrip passed — a skipped roundtrip
is *not* "passed"), runtime tier passed. A strict failure still
prints the full JSON first.

Exit codes: 0 = report emitted (complete, all tiers passed when
--strict); 1 = --strict and a tier not passed; 2 = usage.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
from typing import Any

_ROOT = pathlib.Path(__file__).resolve().parents[4]
for p in (_ROOT / "oracle" / "legacy" / "tools" / "parse", _ROOT / "oracle" / "legacy" / "tools" / "check"):  # noqa: E501
    sys.path.insert(0, str(p))

from parser import load_contract  # noqa: E402
import checker as checker_mod  # noqa: E402
from diagnostic import Diagnostic  # noqa: E402

_REPORT_SCHEMA_VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# The §2 catalog: every row restated verbatim. Pinned against
# docs/guarantees.md by tests/report/report_golden.py, which parses the
# markdown table and compares sets — a drift in either direction fails.
# ---------------------------------------------------------------------------

NON_GUARANTEES: tuple[str, ...] = (
    "Functional correctness of generated RTL beyond the register map itself.",
    "Timing closure.",
    "Area, power, fanout.",
    "Functional correctness of third-party IP.",
    "Driver logic that uses a generated binding.",
    "That every real datasheet quirk has a structured encoding.",
    "That a passing `cancho-hdl check` proves the system works.",
    "That `cancho-hdl diff` flags semantic regressions a human would catch.",
    "That generated output for one vendor toolchain works under another.",
)

# Rule groups (as instrumented in checker.check) → the catalog codes
# whose governing evaluation runs with the group (spec §3). Field rules
# are evaluated inside the register pass ("registers"); the interrupt
# unresolved family is the role-rewritten set.
GROUP_CODES: dict[str, tuple[str, ...]] = {
    "schema-version": ("schema-version-unsupported",),
    "block": (
        "block-name-missing", "block-base-address-missing",
        "block-bus-width-invalid", "block-endianness-unknown",
    ),
    "registers": (
        "register-name-missing", "register-offset-missing",
        "register-offset-non-aligned", "register-offset-overflow",
        "register-offset-duplicate", "register-kind-unknown",
        "reset-overflow", "reset-wo-nonzero",
        "field-name-missing", "field-bounds-missing",
        "field-bounds-inverted", "field-bounds-overflow",
        "field-overlap", "field-enum-overflow",
        "field-constraint-ignored",
    ),
    "interrupts": (
        "interrupt-name-missing", "interrupt-duplicate-name",
        "interrupt-source-unresolved", "interrupt-enable-unresolved",
        "interrupt-status-unresolved", "interrupt-clear-unresolved",
        "interrupt-clear-kind-invalid",
    ),
    "dma": (
        "dma-name-missing", "dma-field-name-missing", "dma-overlap",
        "dma-align-illegal", "dma-align-unsatisfied", "dma-owner-unknown",
    ),
}

# The Schema pass ("schema-invalid") runs separately from the rule
# groups, so it is tracked by its own key.
SCHEMA_PASS_CODES: tuple[str, ...] = ("schema-invalid",)

# The parse pass ("parse-error") runs on every textual input.
PARSE_PASS_CODES: tuple[str, ...] = ("parse-error",)

# Every checker-reachable code in the catalog (the validator refuses
# checks_run entries outside this set — the golden suite derives the
# same set from spec/diagnostics/README.md §3 and compares).
CATALOG_CODES: frozenset[str] = frozenset(
    code
    for group in (*GROUP_CODES.values(), SCHEMA_PASS_CODES, PARSE_PASS_CODES)
    for code in group
) | {"internal", "ir-version-unsupported"}

# Tiers per code family, for splitting checks_run / checks_performed.
RUNTIME_CODES: frozenset[str] = frozenset({"schema-version-unsupported"})

_REPORT_SCHEMA_KEYS = (
    "non_guarantees", "trust_boundaries",
    "static_checks_run", "tested_roundtrips_run", "unknown_items",
)


def _sniff_textual(path: str) -> bool:
    """Same rule the parser uses (spec/contract-schema README §10):
    first non-whitespace character '{' means the JSON wire form."""
    with open(path, "r", encoding="utf-8") as fh:
        for ch in fh.read(64):
            if not ch.isspace():
                return ch != "{"
        return False


def _schema_pass_available() -> bool:
    return importlib.util.find_spec("jsonschema") is not None


# ---------------------------------------------------------------------------
# Roundtrips
# ---------------------------------------------------------------------------


def _cc_candidates() -> list[tuple[str, str]]:
    """(tool name, path) for the C compilers present, in preference
    order. Their identity and version become the Trust boundary —
    whatever compiler validates the header is trusted, never
    relabelled as the report's own evidence."""
    out = []
    for name in ("clang", "gcc", "cc"):
        exe = shutil.which(name)
        if exe:
            out.append((name, exe))
    return out


def _tool_version(exe: str) -> str:
    try:
        first = subprocess.run([exe, "--version"], capture_output=True,
                               text=True, timeout=15).stdout.splitlines()
        return first[0].strip() if first else "unknown version"
    except Exception:
        return "unknown version"


def _run_c_header_roundtrip(ir: dict[str, Any], contract_path: str,
                            tmp: tempfile.TemporaryDirectory) -> dict:
    sys.path.insert(0, str(_ROOT / "oracle" / "legacy" / "gen" / "c-header"))
    from c_header import generate as gen_c_header
    detail: dict[str, Any] = {
        "target": "c-header", "input": contract_path,
    }
    ccs = _cc_candidates()
    if not ccs:
        detail.update(tool="clang/gcc/cc", outcome="skipped",
                      reason="no C compiler on $PATH")
        return detail
    name, exe = ccs[0]
    detail["tool"] = f"{name} ({_tool_version(exe)})"
    try:
        header = gen_c_header(ir, source_path=contract_path)
    except Exception as exc:  # noqa: BLE001
        detail.update(outcome="failed", reason=f"generator raised: {exc}")
        return detail
    h_path = pathlib.Path(tmp.name) / "report_roundtrip.h"
    h_path.write_text(header)
    proc = subprocess.run(
        [exe, "-Wall", "-Wextra", "-Werror", "-std=c11",
         "-c", "-x", "c", str(h_path), "-o", str(h_path.with_suffix(".o"))],
        capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        detail.update(outcome="failed", reason=proc.stderr.strip()[-400:])
        return detail
    detail.update(outcome="passed", reason="compiled clean (-Wall -Wextra -Werror -std=c11)")
    return detail


def _run_systemverilog_roundtrip(ir: dict[str, Any], contract_path: str,
                                 tmp: tempfile.TemporaryDirectory) -> dict:
    sys.path.insert(0, str(_ROOT / "oracle" / "legacy" / "gen" / "systemverilog"))
    from systemverilog import generate as gen_sv

    detail: dict[str, Any] = {
        "target": "systemverilog", "input": contract_path,
    }
    iverilog = shutil.which("iverilog")
    if not iverilog:
        detail.update(
            tool="iverilog (not on $PATH)", outcome="skipped",
            reason="no SystemVerilog parser on $PATH; not checked",
        )
        return detail
    detail["tool"] = f"iverilog ({_tool_version(iverilog)})"
    try:
        source = gen_sv(ir, source_path=contract_path)
    except Exception as exc:  # noqa: BLE001
        detail.update(outcome="failed", reason=f"generator raised: {exc}")
        return detail
    sv_path = pathlib.Path(tmp.name) / "report_roundtrip.sv"
    sv_path.write_text(source)
    proc = subprocess.run([iverilog, "-g2012", "-tnull", str(sv_path)],
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        detail.update(outcome="failed", reason=proc.stderr.strip()[-400:])
        return detail
    detail.update(outcome="passed", reason="iverilog -g2012 parse clean")
    return detail


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


def build_report(contract_path: str, run_roundtrips: bool = True) -> dict[str, Any]:
    """Run the full pipeline for `contract_path` and return the §6
    report. Every claim in the result is derived from this run."""
    static_ran: set[str] = set()      # rule-group names
    ran_codes: list[str] = []         # catalog codes whose group ran, §3 order
    not_run_codes: list[str] = []
    diagnostics: list[Diagnostic] = []

    textual = _sniff_textual(contract_path)
    ir, load_diags = load_contract(contract_path)
    diagnostics.extend(load_diags)
    if textual:
        static_ran.add("parse")
        # The parse pass ran on a textual input.
        ran_codes.extend(PARSE_PASS_CODES)
    elif ir is not None or load_diags:
        static_ran.add("json-wire-load")

    if ir is not None and _schema_pass_available():
        schema_diags = checker_mod._validate_schema(ir, contract_path)
        diagnostics.extend(schema_diags)
        static_ran.add("schema")
        ran_codes.extend(SCHEMA_PASS_CODES)

    if ir is not None:
        ran_groups: set[str] = set()
        check_diags = checker_mod.check(ir, source_path=contract_path, ran=ran_groups)
        diagnostics.extend(check_diags)
        static_ran |= ran_groups

    # Map groups to codes; groups that did not run go to not_run.
    for field, codes in GROUP_CODES.items():
        (ran_codes if field in static_ran else not_run_codes).extend(codes)

    # Codes fired by this run must appear in checks_run even if the
    # group accounting somehow missed the path (defence-in-depth:
    # an emitted diagnostic can never be listed as not-run).
    fired_codes = {d.code for d in diagnostics}
    for code in sorted(fired_codes):
        if code not in ran_codes and code in CATALOG_CODES:
            ran_codes.append(code)
            not_run_codes = [c for c in not_run_codes if c != code]

    static_passed = sum(
        1 for code in ran_codes
        if code not in RUNTIME_CODES
        and not any(d.code == code and d.severity == "Error" for d in diagnostics))
    static_failed = sum(
        1 for code in ran_codes
        if code not in RUNTIME_CODES
        and any(d.code == code and d.severity == "Error" for d in diagnostics))
    runtime_codes = [c for c in ran_codes if c in RUNTIME_CODES]
    runtime_passed = sum(
        1 for code in runtime_codes
        if not any(d.code == code and d.severity == "Error" for d in diagnostics))
    runtime_failed = len(runtime_codes) - runtime_passed

    static_diagnostics = [
        d.to_dict() for d in diagnostics if d.tier == "Static"
    ]

    trust: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    roundtrip_details: list[dict[str, Any]] = []
    roundtrips_run: list[str] = []

    # Roundtrips run only over a clean contract: a refused IR never
    # feeds the generators, and that refusal is itself the honest
    # tested-tier evidence.
    refused = ir is None or any(d.severity == "Error" for d in diagnostics)

    if run_roundtrips and not refused:
        with tempfile.TemporaryDirectory(prefix="cancho-report-") as td:
            tmp = type("T", (), {"name": td})  # duck the TemporaryDirectory
            details = [
                _run_c_header_roundtrip(ir, contract_path, tmp),
                _run_systemverilog_roundtrip(ir, contract_path, tmp),
            ]
        for detail in details:
            outcome = detail["outcome"]
            if outcome != "skipped":
                roundtrips_run.append(f"{detail['target']}::{detail['tool'].split(' ')[0]}")
            if outcome == "passed":
                trust.append({
                    "tool": detail["tool"], "tier": "Trust",
                    "why": "the roundtrip's verdict is this tool's output; not re-verified here",
                })
            elif outcome == "failed":
                pass
            else:
                unknown.append({
                    "description": (
                        f"{detail['target']} roundtrip not run: {detail.get('reason', '')}".strip()),
                    "tier": "Unknown",
                })
            roundtrip_details.append(detail)
    elif run_roundtrips:
        for target in ("c-header", "systemverilog"):
            roundtrip_details.append({
                "target": target, "input": contract_path,
                "outcome": "skipped",
                "reason": ("contract was refused; generators do not run on an "
                           "invalid IR") if ir is not None else
                          ("contract did not parse; generators not run"),
            })
            unknown.append({
                "description": (
                    f"{target} roundtrip not run: "
                    + ("contract was refused (generators do not run on an invalid IR)."
                       if ir is not None else
                       "contract did not parse (generators not run).")),
                "tier": "Unknown",
            })

    trusted_tools = len([t for t in trust if t["tier"] == "Trust"])
    if _schema_pass_available() is False:
        unknown.append({
            "description": "JSON Schema pass did not run (jsonschema not installed); "
                           "schema-invalid may be undetected in this run.",
            "tier": "Unknown",
        })
    if not run_roundtrips:
        unknown.append({
            "description": "roundtrips disabled for this run (--no-roundtrips).",
            "tier": "Unknown",
        })
    unknown.append({
        "description": ("behavioral roundtrip (drive the generated C accessors and "
                        "the SystemVerilog module through the reference-model "
                        "scenarios) is not implemented; the Tested tier covers "
                        "structure only."),
        "tier": "Unknown",
    })

    document: dict[str, Any] = {
        "schema": "cancho-hdl-report",
        "version": _REPORT_SCHEMA_VERSION,
        "input": contract_path,
        "static": {
            "checks_run": [c for c in ran_codes if c not in RUNTIME_CODES],
            "checks_passed": static_passed,
            "checks_failed": static_failed,
            "diagnostics": static_diagnostics,
        },
        "tested": {
            "roundtrips_run": roundtrips_run,
            "roundtrips_passed": sum(1 for d in roundtrip_details if d["outcome"] == "passed"),
            "roundtrips_failed": sum(1 for d in roundtrip_details if d["outcome"] == "failed"),
            "details": roundtrip_details,
        },
        "runtime": {
            "checks_performed": runtime_codes,
            "checks_passed": runtime_passed,
            "checks_failed": runtime_failed,
            "details": [],
        },
        "trust": {
            "boundaries": trust,
            "count": trusted_tools,
        },
        "unknown": {
            "items": unknown,
            "static_checks_not_run": not_run_codes,
        },
        # Mandatory top-level restatements, docs/guarantees.md §3.
        "static_checks_run": [c for c in ran_codes if c not in RUNTIME_CODES],
        "tested_roundtrips_run": list(roundtrips_run),
        "trust_boundaries": [t["tool"] for t in trust],
        "unknown_items": list(unknown),
        "non_guarantees": list(NON_GUARANTEES),
    }
    return document


# ---------------------------------------------------------------------------
# Self-validation: the refusals against the report itself (§6.2)
# ---------------------------------------------------------------------------


def validate_report(
    doc: Any,
    catalog_codes: frozenset[str] = CATALOG_CODES,
) -> list[tuple[str, str]]:
    """Refusal passes over an (alleged) report. Returns a list of
    `(code, message)` — empty iff the report is acceptable.

    Two refusal codes only: `report-schema-truncated` (a mandatory
    section is missing/empty), `evidence-over-claim` (a claim the run
    could not have made). The conformance `evidence-over-claim` lane
    is this function fed corrupted reports (tests/report).
    """
    refusals: list[tuple[str, str]] = []
    if not isinstance(doc, dict):
        return [("report-schema-truncated", "report is not a JSON object")]

    if doc.get("schema") != "cancho-hdl-report":
        refusals.append(("report-schema-truncated", "schema field is not cancho-hdl-report"))
    # §6.1: an *absent* mandatory field is the truncation; an empty
    # list is legitimate (an empty optional lane stays valid — e.g.
    # no roundtrip ran, no tool to trust).
    for key in _REPORT_SCHEMA_KEYS:
        if key not in doc or doc[key] is None:
            refusals.append(("report-schema-truncated", f"mandatory field '{key}' missing"))

    # §2 restatement is verbatim, no paraphrase, no omission.
    stated = doc.get("non_guarantees")
    if isinstance(stated, list):
        for ng in NON_GUARANTEES:
            if ng not in stated:
                refusals.append((
                    "report-schema-truncated",
                    f"non_guarantees is not the verbatim §2 restatement (missing: {ng})",
                ))
    # Trust boundaries are always labeled Trust (§6.2).
    for b in doc.get("trust", {}).get("boundaries", []) if isinstance(doc.get("trust"), dict) else []:
        if b.get("tier") != "Trust":
            refusals.append((
                "evidence-over-claim",
                f"trust boundary {b.get('tool')!r} labeled {b.get('tier')!r}; trust boundaries are Trust",
            ))

    static = doc.get("static", {})
    if isinstance(static, dict):
        run_list = static.get("checks_run", [])
        outside = [c for c in run_list if c not in catalog_codes]
        if outside:
            refusals.append((
                "evidence-over-claim",
                f"static checks claimed outside the catalog: {outside}",
            ))
        counts = static.get("checks_passed", 0), static.get("checks_failed", 0)
        if isinstance(run_list, list) and isinstance(counts[0], int) and isinstance(counts[1], int):
            if sum(counts) != len(run_list):
                refusals.append((
                    "evidence-over-claim",
                    "static passed+failed counts must sum to len(checks_run); "
                    f"{counts[0]}+{counts[1]} != {len(run_list)}",
                ))
        diags = static.get("diagnostics")
        if isinstance(diags, list):
            fired_errors = set()
            for d in diags:
                if isinstance(d, dict) and d.get("severity") == "Error":
                    fired_errors.add(d.get("code"))
            if fired_errors - set(run_list):
                refusals.append((
                    "evidence-over-claim",
                    "static reports Errors for codes not in checks_run: "
                    f"{sorted(fired_errors - set(run_list))}",
                ))

    tested = doc.get("tested", {})
    if isinstance(tested, dict):
        run_list = tested.get("roundtrips_run", [])
        passed = tested.get("roundtrips_passed", 0)
        failed = tested.get("roundtrips_failed", 0)
        details = tested.get("details", [])
        if isinstance(run_list, list) and isinstance(passed, int) and isinstance(failed, int):
            if passed + failed != len(run_list):
                refusals.append((
                    "evidence-over-claim",
                    "tested passed+failed counts must sum to len(roundtrips_run)",
                ))
        for d in details if isinstance(details, list) else []:
            if isinstance(d, dict) and d.get("outcome") == "skipped":
                handle = f"{d.get('target')}::"
                claimed = [r for r in (run_list if isinstance(run_list, list) else []) if isinstance(r, str) and r.startswith(handle)]
                if claimed:
                    refusals.append((
                        "evidence-over-claim",
                        f"skipped roundtrip counted as run: {claimed}",
                    ))

    return refusals


# ---------------------------------------------------------------------------
# Text form + CLI
# ---------------------------------------------------------------------------


def format_text(doc: dict[str, Any]) -> str:
    st = doc["static"]
    te = doc["tested"]
    rt = doc["runtime"]
    tr = doc["trust"]
    un = doc["unknown"]
    tested_note = ""
    skipped = [d for d in te["details"] if d["outcome"] == "skipped"]
    if skipped:
        tested_note = " (skipped: " + ", ".join(d["target"] for d in skipped) + ")"
    lines = [
        f"== cancho-hdl report: {doc['input']} ==",
        f"static   : {len(st['checks_run'])} checks run, {st['checks_passed']} passed, "
        f"{st['checks_failed']} failed",
        f"tested   : {len(te['roundtrips_run'])} roundtrip(s) run, {te['roundtrips_passed']} passed, "
        f"{te['roundtrips_failed']} failed{tested_note}",
        f"runtime  : {len(rt['checks_performed'])} check(s) performed, {rt['checks_passed']} passed, "
        f"{rt['checks_failed']} failed",
        f"trust    : {tr['count']} boundary/boundaries — "
        + "; ".join(b.split(" (")[0] for b in doc["trust_boundaries"]),
        f"unknown  : {len(un['items'])} item(s); {len(un['static_checks_not_run'])} "
        "static check(s) not run — see the JSON for both lists",
        f"non_guarantees: {len(doc['non_guarantees'])} rows restated verbatim "
        "(docs/guarantees.md §2) — see the JSON",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="cancho-hdl report",
        description="Evidence report for a .chw contract (spec/diagnostics/README.md §6).",
    )
    ap.add_argument("file", help="the .chw contract to report on")
    ap.add_argument("--output", choices=["json", "text"], default="json")
    ap.add_argument("--pretty", action="store_true", help="indent the JSON")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when any tier is not 'passed' (skipped roundtrips count)")
    ap.add_argument("--no-roundtrips", action="store_true",
                    help="skip the generator roundtrips (reported as skipped, honestly)")
    args = ap.parse_args()

    doc = build_report(args.file, run_roundtrips=not args.no_roundtrips)

    self_refusals = validate_report(doc)
    if self_refusals:
        for code, reason in self_refusals:
            print(f"internal[{code}]: {reason}", file=sys.stderr)
        return 1

    if args.output == "text":
        sys.stdout.write(format_text(doc))
    else:
        sys.stdout.write(json.dumps(doc, indent=2 if args.pretty else None) + "\n")

    if args.strict:
        tiers_ok = (
            doc["static"]["checks_failed"] == 0
            and doc["tested"]["roundtrips_failed"] == 0
            and all(d["outcome"] == "passed" for d in doc["tested"]["details"])
            and doc["runtime"]["checks_failed"] == 0
        )
        return 0 if tiers_ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
