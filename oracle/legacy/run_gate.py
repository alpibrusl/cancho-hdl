"""The oracle's own gate: the self-checks of the legacy reference implementation (oracle/legacy).

This is not the gate of the product (scripts/gate.sh is: it runs scripts/gate_cancho.sh, which holds `chw` to this
implementation byte for byte and to the claims of its goldens, and then this script). These six checks run the legacy
generators and the reference simulator against themselves, as they always did:

1. The reference-model simulator passes every scenario and its run-time refusals
   (`oracle/legacy/tools/sim/run_scenarios.py`).
2. The c-header roundtrip compiles and runs
   (`tests/roundtrip/c_header_compiles.py`).
3. The systemverilog roundtrip passes structural checking, plus a
   real parse when iverilog/slang/yosys is on `$PATH`
   (`tests/roundtrip/systemverilog_parses.py`).
4. The devicetree roundtrip pins the DTSI fragment shape
   (`tests/roundtrip/devicetree_generates.py`).
5. The cancho-binding roundtrip pins the accessor palette, the
   DEVICE-no-setter rule, and the shared size refusal
   (`tests/roundtrip/cancho_binding_validates.py`).
6. The svd roundtrip pins the CMSIS-SVD document (XSD-validated
   when lxml is available), the 6.1 access mapping, and the
   6.2/6.3 reset / interrupt / DMA comment rule
   (`tests/roundtrip/svd_validates.py`).

The other claims of the former thirteen-check gate moved to the product's gate, held against the binary: schema validation
of the examples (step 9, against jsonschema), the checker's conformance (steps 7 and 8b, `chw conform`), the textual
parser's roundtrip (`tests/parser/parser_cancho_roundtrip.py`), the text form of a diagnostic
(`tests/text_format/golden_cancho.py`), the diff and impact goldens (`tests/diff/diff_cancho_golden.py`), the evidence report
golden (`tests/report/report_cancho_golden.py`) and the C behavioral roundtrip (`tests/behavioral/c_behavior.py`).

All six must pass for this script to exit 0. Any failure exits 1.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(label: str, args: list[str]) -> int:
    print(f"\n== {label} ==")
    rc = subprocess.call(args, cwd=str(ROOT))
    if rc != 0:
        print(f"  FAIL  {label} exited {rc}")
    return rc


def main() -> int:
    rc = 0
    rc |= run("reference model + scenarios", [sys.executable, "oracle/legacy/tools/sim/run_scenarios.py"])
    rc |= run("c-header roundtrip (clang + gcc + smoke)", [sys.executable, "tests/roundtrip/c_header_compiles.py"])
    rc |= run("systemverilog roundtrip (structural + iverilog/slang/yosys if available)", [sys.executable, "tests/roundtrip/systemverilog_parses.py"])
    rc |= run("devicetree roundtrip (structural + dtc when available)", [sys.executable, "tests/roundtrip/devicetree_generates.py"])
    rc |= run("cancho-binding roundtrip (palette + DEVICE no-setter)", [sys.executable, "tests/roundtrip/cancho_binding_validates.py"])
    rc |= run("svd roundtrip (XSD + access mapping + comment lane)", [sys.executable, "tests/roundtrip/svd_validates.py"])
    print()
    if rc:
        print("== GATE FAILED ==")
        return 1
    print("== GATE PASSED ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())