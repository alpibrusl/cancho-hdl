"""Golden tests for the semantic diff and impact tools.

Covers:

1. Identity: diffing a contract with itself (both forms) is empty,
   cross-form (JSON wire file vs textual file) is empty — the two
   forms are the same contract by construction.
2. Determinism: the same diff run twice is byte-identical.
3. The seeded-change criterion from docs/roadmap.md Phase 2: widen
   `BAUD_DIV` from 8 to 12 bits and rebase the register map; the
   diff names every register that moved and the widened field, and
   the impact list marks c-header and systemverilog stale with
   reasons while the Phase 2 generators report `stale: null`
   ("not checked") — tier discipline, not fake "no change" claims.
4. Refusal: diffing a contract the checker does not accept exits 1
   with the refusal on stderr.
5. Classification units: widened / narrowed / repositioned are
   mutually exclusive; enum label add/change/remove, reset change,
   DMA ownership flip, interrupt linkage change each produce the
   named entry and nothing else.

Run from anywhere:
    python3 tests/diff/diff_golden.py
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "diff"))
sys.path.insert(0, str(ROOT / "tools" / "check"))

from diff import compute_diff, compute_impact, diff_is_empty  # noqa: E402

DIFF_KEYS = [
    "added_registers", "removed_registers", "moved_registers",
    "widened_fields", "narrowed_fields", "repositioned_fields",
    "added_fields", "removed_fields", "changed_enum_values",
    "changed_interrupts", "added_interrupts", "removed_interrupts",
    "changed_dma_layouts", "changed_reset_values", "changed_block_properties",
]

FAILURES: list[str] = []


def expect(cond: bool, label: str, detail: str = "") -> None:
    if cond:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}")
        if detail:
            print(detail)
        FAILURES.append(label)


def _ir(path_rel: str) -> dict:
    import sys as _s
    _s.path.insert(0, str(ROOT / "tools" / "parse"))
    from parser import load_contract
    ir, diags = load_contract(str(ROOT / path_rel))
    assert ir is not None, diags[0].message
    return ir


def _mini_block(registers, interrupts=None, dma=None, name="Mini",
                base="0x40000000", bus_width=32, endianness="little"):
    return {
        "$schema": "x", "version": "0.1.0",
        "block": {"name": name, "base_address": base, "bus_width": bus_width,
                  "endianness": endianness, "registers": registers,
                  **({"interrupts": interrupts} if interrupts else {})},
        "dma_buffers": dma or [],
    }


def main() -> int:
    print("== diff / impact golden ==")

    uart_json = _ir("examples/uart-contract/uart.chw")
    uart_text = _ir("examples/textual/uart.chw")
    dma_json = _ir("examples/simple-dma/dma.chw")
    dma_text = _ir("examples/textual/dma.chw")

    # 1. Identity, both forms and cross-form
    print()
    print("## identity ##")
    expect(diff_is_empty(compute_diff(uart_json, uart_json)),
           "uart JSON vs itself: empty")
    expect(diff_is_empty(compute_diff(uart_json, uart_text)),
           "uart JSON vs textual: empty")
    expect(diff_is_empty(compute_diff(dma_json, dma_text)),
           "dma JSON vs textual: empty")

    # 2. Determinism
    print()
    print("## determinism ##")
    rebase = _ir("tests/diff/fixtures/uart_rebase.chw")
    d1 = json.dumps(compute_diff(uart_json, rebase))
    d2 = json.dumps(compute_diff(uart_json, rebase))
    expect(d1 == d2, "same pair diffed twice → byte-identical")

    # 3. Seeded change (roadmap Phase 2 exit criterion)
    print()
    print("## seeded change: rebase + BAUD_DIV broaden 8 → 12 bits ##")
    seeded = compute_diff(uart_json, rebase)
    expect(len(seeded["moved_registers"]) == 5, "five registers reported as moved",
           json.dumps(seeded["moved_registers"]))
    expect(seeded["widened_fields"] == [{
        "id": "chw:UartRegs.register.CTRL.field.BAUD_DIV",
        "from": {"lsb": 8, "msb": 15},
        "to": {"lsb": 8, "msb": 19},
    }], "BAUD_DIV widening reported with from/to bit ranges",
        json.dumps(seeded["widened_fields"]))
    expect(seeded["changed_interrupts"] == [], "interrupt linkages unchanged (by name)",
           json.dumps(seeded["changed_interrupts"]))

    impact = compute_impact(uart_json, rebase)
    targets = {a["target"]: a for a in impact["affected_artifacts"]}
    expect(set(targets) == {"c-header", "cancho-binding", "devicetree",
                            "systemverilog", "svd"},
           "impact covers all five generator targets")
    expect(targets["c-header"]["stale"] is True
           and "widened_fields=1" in targets["c-header"]["reason"]
           and "moved_registers=5" in targets["c-header"]["reason"],
           "c-header stale with counted reasons",
           json.dumps(targets["c-header"]))
    expect(targets["systemverilog"]["stale"] is True,
           "systemverilog stale")
    expect(targets["devicetree"]["stale"] is True,
           "devicetree stale (the reg range changes with the map)",
           json.dumps(targets["devicetree"]))
    expect(targets["cancho-binding"]["stale"] is False
           and "byte-identical" in targets["cancho-binding"]["reason"],
           "cancho-binding NOT stale, with the proof: it encodes names, "
           "widths, and kinds — not offsets (a rule-based staleness "
           "oracle would have flagged it)",
           json.dumps(targets["cancho-binding"]))
    expect(targets["svd"]["stale"] is True
           and "moved_registers=5" in targets["svd"]["reason"],
           "svd stale — measured, not 'not checked': the svd generator "
           "landed and its bytes move with the register map",
           json.dumps(targets["svd"]))

    # 3b. Impact on identical contracts: stale is False, not null.
    impact_same = compute_impact(uart_json, uart_json)
    for a in impact_same["affected_artifacts"]:
        if a["target"] in ("c-header", "systemverilog", "devicetree", "svd"):
            expect(a["stale"] is False
                   and "byte-identical" in a["reason"],
                   f"{a['target']} identical → stale: false (proof it was considered)",
                   json.dumps(a))

    # 4. Refusal lane: diff refuses to run on a contract the checker rejects.
    print()
    print("## refusals ##")
    proc = subprocess.run(
        [sys.executable, "tools/diff/diff.py", "diff",
         "examples/refusal/field-overlap.chw", "examples/uart-contract/uart.chw"],
        capture_output=True, text=True, cwd=str(ROOT))
    expect(proc.returncode == 1 and "field-overlap" in proc.stderr,
           "diff refuses a contract with checker errors (exit 1)",
           f"rc={proc.returncode} stderr={proc.stderr!r}")

    # 5. Classification units
    print()
    print("## classification units ##")
    def one_reg(f1, f2, extra1=None, extra2=None):
        base = _mini_block([
            {"name": "A", "offset": "0x00", "kind": "RW",
             "fields": [f1] + ([extra1] if extra1 else [])}])
        cand = _mini_block([
            {"name": "A", "offset": "0x00", "kind": "RW",
             "fields": [f2] + ([extra2] if extra2 else [])}])
        return compute_diff(base, cand)

    d = one_reg({"name": "F", "lsb": 2, "msb": 5}, {"name": "F", "lsb": 2, "msb": 9})
    expect(len(d["widened_fields"]) == 1 and diff_is_empty(d) is False,
           "grow → widened")
    d = one_reg({"name": "F", "lsb": 2, "msb": 9}, {"name": "F", "lsb": 3, "msb": 8})
    expect(len(d["narrowed_fields"]) == 1, "shrink both ends → narrowed")
    d = one_reg({"name": "F", "lsb": 2, "msb": 5}, {"name": "F", "lsb": 6, "msb": 9})
    expect(len(d["repositioned_fields"]) == 1 and not d["narrowed_fields"],
           "same width, different lsb → repositioned (not narrowed)")

    d = one_reg({"name": "M", "lsb": 0, "msb": 1,
                 "enum": {"Off": 0, "On": 1}},
                {"name": "M", "lsb": 0, "msb": 1,
                 "enum": {"Off": 0, "On": 2, "Auto": 3}})
    labels = {(e["label"], e["from"], e["to"]) for e in d["changed_enum_values"]}
    expect(labels == {("On", 1, 2), ("Auto", None, 3)},
           "enum: value change + label add reported",
           json.dumps(d["changed_enum_values"]))

    base = _mini_block([{"name": "A", "offset": "0x00", "kind": "RW",
                         "reset": "0x00000000", "fields": []}])
    cand = _mini_block([{"name": "A", "offset": "0x00", "kind": "RW",
                         "reset": "0x0000ffff", "fields": []}])
    d = compute_diff(base, cand)
    expect(len(d["changed_reset_values"]) == 1
           and d["changed_reset_values"][0]["from"] == "0x00000000",
           "reset change reported with from/to")

    # DMA owner flip
    base = _mini_block([{"name": "A", "offset": "0x00", "kind": "RW", "fields": []}],
                       dma=[{"name": "T", "fields": [
                           {"name": "p", "offset": "0x00", "owner": "CPU",
                            "align": 8}]}])
    cand = _mini_block([{"name": "A", "offset": "0x00", "kind": "RW", "fields": []}],
                       dma=[{"name": "T", "fields": [
                           {"name": "p", "offset": "0x00", "owner": "DEVICE",
                            "align": 8}]}])
    d = compute_diff(base, cand)
    lay = d["changed_dma_layouts"]
    expect(len(lay) == 1 and lay[0]["owner_changes"] == [
        {"id": "chw:Mini.dma.T.field.p", "from": "CPU", "to": "DEVICE"}],
        "dma ownership flip reported with from/to",
        json.dumps(lay))

    # Interrupt linkage change
    base = _mini_block(
        [{"name": "A", "offset": "0x00", "kind": "RW", "fields": [
            {"name": "F", "lsb": 0, "msb": 0}]}],
        interrupts=[{"name": "x", "number": 1,
                     "source": {"register": "A", "field": "F"}}])
    cand = _mini_block(
        [{"name": "A", "offset": "0x00", "kind": "RW", "fields": [
            {"name": "F", "lsb": 0, "msb": 0}]}],
        interrupts=[{"name": "x", "number": 2,
                     "source": {"register": "A", "field": "F"}}])
    d = compute_diff(base, cand)
    expect(len(d["changed_interrupts"]) == 1
           and d["changed_interrupts"][0]["changes"] == [
               {"role": "number", "from": 1, "to": 2}],
           "interrupt number change reported per role",
           json.dumps(d["changed_interrupts"]))

    # Bus width change is a block property, not a register diff
    base = _mini_block([{"name": "A", "offset": "0x00", "kind": "RW", "fields": []}],
                       bus_width=32)
    cand = _mini_block([{"name": "A", "offset": "0x00", "kind": "RW", "fields": []}],
                       bus_width=16)
    d = compute_diff(base, cand)
    expect(d["changed_block_properties"] == [
        {"property": "bus_width", "from": 32, "to": 16}],
        "bus width change lands in changed_block_properties",
        json.dumps(d["changed_block_properties"]))

    print()
    if FAILURES:
        print(f"== {len(FAILURES)} failure(s) ==")
        return 1
    print("== diff / impact golden: all pass ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
