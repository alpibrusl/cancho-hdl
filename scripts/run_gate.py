"""Run the full Phase 0+1 gate.

Seven checks, in order:

1. Schema validates the valid examples in both source forms and
   reports the schema-level refusals (`scripts/verify_examples.py`).
2. The static checker passes every example and refuses every refusal
   case per the sidecar (`tools/check/conformance.py`).
3. The reference-model simulator passes every scenario
   (`tools/sim/run_scenarios.py`).
4. The c-header roundtrip compiles and runs
   (`tests/roundtrip/c_header_compiles.py`).
5. The systemverilog roundtrip passes structural checking, plus a
   real parse when iverilog/slang/yosys is on `$PATH`
   (`tests/roundtrip/systemverilog_parses.py`).
6. The textual parser roundtrip proves text and JSON forms are the
   same contract (`tests/parser/parser_roundtrip.py`).
7. The diagnostic text formatter golden test pins rendered output
   (`tests/text_format/golden.py`).
8. The diff / impact golden suite pins the semantic-diff document
   and the seeded Phase 2 change (`tests/diff/diff_golden.py`).
9. The evidence-report golden suite pins the §6 document, the
   verbatim non-guarantee restatement, and the evidence-over-claim
   refusals (`tests/report/report_golden.py`).
10. The devicetree roundtrip pins the DTSI fragment shape
    (`tests/roundtrip/devicetree_generates.py`).
11. The cancho-binding roundtrip pins the accessor palette, the
    DEVICE-no-setter rule, and the shared size refusal
    (`tests/roundtrip/cancho_binding_validates.py`).
12. The svd roundtrip pins the CMSIS-SVD document (XSD-validated
    when lxml is available), the §6.1 access mapping, and the
    §6.2/§6.3 reset / interrupt / DMA comment rule
    (`tests/roundtrip/svd_validates.py`).

All twelve must pass for this script to exit 0. Any failure
exits 1.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(label: str, args: list[str]) -> int:
    print(f"\n== {label} ==")
    rc = subprocess.call(args, cwd=str(ROOT))
    if rc != 0:
        print(f"  FAIL  {label} exited {rc}")
    return rc


def main() -> int:
    rc = 0
    rc |= run("schema validation", [sys.executable, "scripts/verify_examples.py"])
    rc |= run("static checker conformance", [sys.executable, "tools/check/conformance.py"])
    rc |= run("reference model + scenarios", [sys.executable, "tools/sim/run_scenarios.py"])
    rc |= run("c-header roundtrip (clang + gcc + smoke)", [sys.executable, "tests/roundtrip/c_header_compiles.py"])
    rc |= run("systemverilog roundtrip (structural + iverilog/slang/yosys if available)", [sys.executable, "tests/roundtrip/systemverilog_parses.py"])
    rc |= run("textual parser roundtrip", [sys.executable, "tests/parser/parser_roundtrip.py"])
    rc |= run("diagnostic text formatter golden", [sys.executable, "tests/text_format/golden.py"])
    rc |= run("diff / impact golden (seeded Phase 2 criterion)", [sys.executable, "tests/diff/diff_golden.py"])
    rc |= run("evidence report golden (§6, non-guarantees, over-claim refusals)", [sys.executable, "tests/report/report_golden.py"])
    rc |= run("devicetree roundtrip (§4 structural + dtc when available)", [sys.executable, "tests/roundtrip/devicetree_generates.py"])
    rc |= run("cancho-binding roundtrip (§3 palette + DEVICE no-setter)", [sys.executable, "tests/roundtrip/cancho_binding_validates.py"])
    rc |= run("svd roundtrip (§6 XSD + access mapping + comment lane)", [sys.executable, "tests/roundtrip/svd_validates.py"])
    print()
    if rc:
        print("== GATE FAILED ==")
        return 1
    print("== GATE PASSED ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())