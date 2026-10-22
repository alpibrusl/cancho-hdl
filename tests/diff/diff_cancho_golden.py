"""Golden claims of the semantic diff and impact (spec/diagnostics/README.md, 7), held against the cancho binary.

These are the claims of the Python tool's golden that name a contract of this repository, unchanged in what they require:

1. Identity: a contract diffed against itself, and a JSON wire file against its text form, is an empty diff.
2. Determinism: the same pair diffed twice is byte-identical.
3. The seeded change of docs/roadmap.md, Phase 2 (`tests/diff/fixtures/uart_rebase.chw`: BAUD_DIV widened from 8 to 12 bits,
   the register map rebased): five registers moved, the widening named with its bit ranges, interrupts unchanged, and the
   impact list stale for c-header, devicetree, systemverilog and svd with counted reasons, not stale for cancho-binding (with
   the proof: its bytes are identical).
4. Impact on identical contracts says `stale: false` with a proof, never `null`.
5. Diffing a contract the checker refuses exits 1 with the refusal on standard error.

The classification units of the Python golden (widened, narrowed, repositioned, enums, resets, DMA, interrupts, bus width) are
held by tests/unit/test_diff.cho. Oracle code: it decides nothing about the product.

    python3 tests/diff/diff_cancho_golden.py /path/to/built/chw
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
os.chdir(ROOT)
EXE = sys.argv[1]
FAILURES: list[str] = []

UART = "examples/uart-contract/uart.chw"
UART_TEXT = "examples/textual/uart.chw"
DMA = "examples/simple-dma/dma.chw"
DMA_TEXT = "examples/textual/dma.chw"
REBASE = "tests/diff/fixtures/uart_rebase.chw"

DIFF_KEYS = [
    "added_registers", "removed_registers", "moved_registers", "widened_fields", "narrowed_fields", "repositioned_fields",
    "added_fields", "removed_fields", "changed_enum_values", "changed_interrupts", "added_interrupts", "removed_interrupts",
    "changed_dma_layouts", "changed_reset_values", "changed_block_properties",
]


def expect(cond: bool, label: str, detail: str = "") -> None:
    if cond:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}")
        if detail:
            print(detail)
        FAILURES.append(label)


def chw(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([EXE, *args], capture_output=True, text=True)


def document(verb: str, a: str, b: str) -> dict:
    p = chw(verb, a, b)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def empty(d: dict) -> bool:
    return all(not d[k] for k in DIFF_KEYS)


def main() -> int:
    print("== chw diff / impact golden ==")

    print()
    print("## identity ##")
    expect(empty(document("diff", UART, UART)), "uart JSON vs itself: empty")
    expect(empty(document("diff", UART, UART_TEXT)), "uart JSON vs textual: empty")
    expect(empty(document("diff", DMA, DMA_TEXT)), "dma JSON vs textual: empty")

    print()
    print("## determinism ##")
    expect(chw("diff", UART, REBASE).stdout == chw("diff", UART, REBASE).stdout, "same pair diffed twice: byte-identical")

    print()
    print("## seeded change: rebase + BAUD_DIV broaden 8 to 12 bits ##")
    seeded = document("diff", UART, REBASE)
    expect(len(seeded["moved_registers"]) == 5, "five registers reported as moved", json.dumps(seeded["moved_registers"]))
    expect(seeded["widened_fields"] == [{
        "id": "chw:UartRegs.register.CTRL.field.BAUD_DIV", "from": {"lsb": 8, "msb": 15}, "to": {"lsb": 8, "msb": 19},
    }], "BAUD_DIV widening reported with from/to bit ranges", json.dumps(seeded["widened_fields"]))
    expect(seeded["changed_interrupts"] == [], "interrupt linkages unchanged (by name)")

    impact = document("impact", UART, REBASE)
    targets = {a["target"]: a for a in impact["affected_artifacts"]}
    expect(set(targets) == {"c-header", "cancho-binding", "devicetree", "systemverilog", "svd"},
           "impact covers all five generator targets")
    expect(targets["c-header"]["stale"] is True and "widened_fields=1" in targets["c-header"]["reason"]
           and "moved_registers=5" in targets["c-header"]["reason"], "c-header stale with counted reasons",
           json.dumps(targets["c-header"]))
    expect(targets["systemverilog"]["stale"] is True, "systemverilog stale")
    expect(targets["devicetree"]["stale"] is True, "devicetree stale (the reg range changes with the map)",
           json.dumps(targets["devicetree"]))
    expect(targets["cancho-binding"]["stale"] is False and "byte-identical" in targets["cancho-binding"]["reason"],
           "cancho-binding NOT stale, with the proof: it encodes names, widths and kinds, not offsets",
           json.dumps(targets["cancho-binding"]))
    expect(targets["svd"]["stale"] is True and "moved_registers=5" in targets["svd"]["reason"],
           "svd stale, measured and not 'not checked'", json.dumps(targets["svd"]))

    same = document("impact", UART, UART)
    for a in same["affected_artifacts"]:
        expect(a["stale"] is False and "byte-identical" in a["reason"],
               f"{a['target']} identical: stale false (proof it was considered)", json.dumps(a))

    print()
    print("## refusals ##")
    p = chw("diff", "examples/refusal/field-overlap.chw", UART)
    expect(p.returncode == 1 and "field-overlap" in p.stderr, "diff refuses a contract with checker errors (exit 1)",
           f"rc={p.returncode} stderr={p.stderr!r}")

    print()
    if FAILURES:
        print(f"== {len(FAILURES)} failure(s) ==")
        return 1
    print("== chw diff / impact golden: all pass ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
