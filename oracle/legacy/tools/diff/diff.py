"""Semantic diff and impact analysis for cancho-hdl contracts.

`cancho-hdl diff` answers "what did this change mean?" — a JSON
document listing the semantic changes between two contract IRs
(register adds/removes/moves, field widen/narrow/reposition, enum
changes, interrupt linkage changes, DMA layout changes, reset
value changes). `cancho-hdl impact` answers the agent-facing
follow-up: which generated artifacts are now stale, and why.

The output shape is `spec/diagnostics/README.md` §7 / §7.1. The
document is a **value**: stable key order, no null fields for
absent content, IDs are the stable handles from
`spec/contract-schema/README.md` §7
(`chw:<block>.register.<name>.field.<field>`), and the same diff
of the same pair of contracts is byte-identical every run.

Both inputs are loaded through `oracle/legacy/tools/parse/parser.py`, so a
diff may mix source forms freely: a textual `.chw` against a
JSON wire file is the same contract, and diffs to zero.

The diff **refuses to run on invalid contracts**: each input is
passed through the static checker first. A refusal diagnostic on
either side aborts with that diagnostic and exit 1 — an agent
must not receive a semantic diff of a contract the checker does
not accept.

Stability notes:

- Registers are matched by name within the (single) block; fields
  by name within the register. Reordering a register or field
  produces **no** diff entry: order is not a semantic property of
  the map (the ID scheme's premise, spec/contract-schema §7).
- A field whose bit range changes is classified as exactly one
  of widened (same or lower lsb, same or higher msb), narrowed
  (the mirror), or repositioned (same width, different lsb).
- Byte-identity of the artifact generators is how impact decides
  staleness: for every implemented generator target, both
  contracts are generated (same neutral source label, so the
  banner cannot diverge) and compared byte for byte. A
  `stale: false` entry is the proof the target was considered,
  not overlooked (spec §7.1).

Usage:

    python3 oracle/legacy/tools/diff/diff.py diff   <base.chw> <candidate.chw>   # §7 document
    python3 oracle/legacy/tools/diff/diff.py impact <base.chw> <candidate.chw>   # §7.1 document
    python3 oracle/legacy/tools/diff/diff.py diff <base> <cand> --pretty        # indented JSON

Exit codes: 0 = ran; 1 = a contract was refused by the checker; 2 = usage.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

_ROOT = pathlib.Path(__file__).resolve().parents[4]
for p in (_ROOT / "oracle" / "legacy" / "tools" / "parse", _ROOT / "oracle" / "legacy" / "tools" / "check", _ROOT / "oracle" / "legacy" / "tools" / "generate"):
    sys.path.insert(0, str(p))

from parser import load_contract  # noqa: E402
from checker import check_file  # noqa: E402

# Implemented generator targets, for impact byte-comparison.
from generate import _load_generator  # noqa: E402

_DIFF_SCHEMA_VERSION = "0.1.0"
_NEUTRAL_LABEL = "<diff>"

# Targets whose generators have landed (impact byte-compares these).
_IMPLEMENTED_TARGETS = ("c-header", "systemverilog", "devicetree",
                        "cancho-binding", "svd")
# Targets in the parent proposal's generator set that are Phase 2.
_ALL_TARGETS = ("c-header", "cancho-binding", "devicetree", "systemverilog", "svd")


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------


def _rid(block: str, reg: str) -> str:
    return f"chw:{block}.register.{reg}"


def _fid(block: str, reg: str, fld: str) -> str:
    return f"chw:{block}.register.{reg}.field.{fld}"


def _did(block: str, buf: str) -> str:
    return f"chw:{block}.dma.{buf}"


def _dfid(block: str, buf: str, fld: str) -> str:
    return f"chw:{block}.dma.{buf}.field.{fld}"


def _iid(block: str, intr: str) -> str:
    return f"chw:{block}.interrupt.{intr}"


def _hex_off(v: Any) -> str:
    return str(v)


def _hex_eq(a: Any, b: Any) -> bool:
    """Case-insensitive hex comparison; a None is never equal to a value."""
    if a is None or b is None:
        return a is b
    try:
        return int(str(a), 16) == int(str(b), 16)
    except ValueError:
        return str(a).lower() == str(b).lower()


def _classify_field(base: dict, cand: dict) -> str:
    """widened | narrowed | repositioned — exactly one."""
    b_lsb, b_msb = int(base["lsb"]), int(base["msb"])
    c_lsb, c_msb = int(cand["lsb"]), int(cand["msb"])
    if c_lsb <= b_lsb and c_msb >= b_msb:
        return "widened"
    if c_lsb >= b_lsb and c_msb <= b_msb:
        return "narrowed"
    return "repositioned"


def compute_diff(base_ir: dict, cand_ir: dict) -> dict[str, Any]:
    """The §7 semantic-diff document."""
    base_b = base_ir["block"]
    cand_b = cand_ir["block"]
    same_block = base_b["name"] == cand_b["name"]
    block_name = cand_b["name"]

    doc: dict[str, Any] = {
        "schema": "cancho-hdl-diff",
        "version": _DIFF_SCHEMA_VERSION,
        "base_id": _rid(base_b["name"], "") .rstrip("."),
        "candidate_id": _rid(cand_b["name"], "").rstrip("."),
        "added_registers": [],
        "removed_registers": [],
        "moved_registers": [],
        "widened_fields": [],
        "narrowed_fields": [],
        "repositioned_fields": [],
        "added_fields": [],
        "removed_fields": [],
        "changed_enum_values": [],
        "changed_interrupts": [],
        "added_interrupts": [],
        "removed_interrupts": [],
        "changed_dma_layouts": [],
        "changed_reset_values": [],
        "changed_block_properties": [],
    }

    # Block-level properties (bus width, endianness, base address, name).
    for prop in ("name", "base_address", "bus_width", "endianness"):
        a, b = base_b.get(prop), cand_b.get(prop)
        equal = _hex_eq(a, b) if prop == "base_address" else a == b
        if not equal:
            doc["changed_block_properties"].append({
                "property": prop,
                "from": base_b.get(prop),
                "to": cand_b.get(prop),
            })

    base_regs = {r["name"]: r for r in base_b.get("registers", [])}
    cand_regs = {r["name"]: r for r in cand_b.get("registers", [])}

    for name, creg in cand_regs.items():
        if not same_block or name not in base_regs:
            doc["added_registers"].append({
                "id": _rid(block_name, name),
                "offset": creg["offset"],
                "kind": creg["kind"],
            })
    for name, breg in base_regs.items():
        if not same_block or name not in cand_regs:
            doc["removed_registers"].append({
                "id": _rid(base_b["name"], name),
                "offset": breg["offset"],
                "kind": breg["kind"],
            })

    for name in cand_regs:
        if not same_block or name not in base_regs:
            continue
        breg, creg = base_regs[name], cand_regs[name]
        id_ = _rid(block_name, name)

        if not _hex_eq(breg["offset"], creg["offset"]):
            doc["moved_registers"].append({
                "id": id_,
                "from_offset": _hex_off(breg["offset"]),
                "to_offset": _hex_off(creg["offset"]),
            })

        if not _hex_eq(breg.get("reset"), creg.get("reset")):
            doc["changed_reset_values"].append({
                "id": id_,
                "from": breg.get("reset"),
                "to": creg.get("reset"),
            })

        b_flds = {f["name"]: f for f in breg.get("fields", [])}
        c_flds = {f["name"]: f for f in creg.get("fields", [])}

        for fn, cf in c_flds.items():
            if fn not in b_flds:
                doc["added_fields"].append({
                    "id": _fid(block_name, name, fn),
                    "lsb": cf["lsb"],
                    "msb": cf["msb"],
                })
                continue
            bf = b_flds[fn]
            if (bf["lsb"], bf["msb"]) != (cf["lsb"], cf["msb"]):
                klass = _classify_field(bf, cf)
                doc[f"{klass}_fields"].append({
                    "id": _fid(block_name, name, fn),
                    "from": {"lsb": bf["lsb"], "msb": bf["msb"]},
                    "to": {"lsb": cf["lsb"], "msb": cf["msb"]},
                })
            # Enum changes (only meaningful for surviving fields).
            b_enum = bf.get("enum") or {}
            c_enum = cf.get("enum") or {}
            for label in c_enum:
                if label not in b_enum:
                    doc["changed_enum_values"].append({
                        "id": _fid(block_name, name, fn),
                        "label": label,
                        "from": None,
                        "to": c_enum[label],
                    })
                    continue
                if b_enum[label] != c_enum[label]:
                    doc["changed_enum_values"].append({
                        "id": _fid(block_name, name, fn),
                        "label": label,
                        "from": b_enum[label],
                        "to": c_enum[label],
                    })
            for label in b_enum:
                if label not in c_enum:
                    doc["changed_enum_values"].append({
                        "id": _fid(block_name, name, fn),
                        "label": label,
                        "from": b_enum[label],
                        "to": None,
                    })
        for fn, bf in b_flds.items():
            if fn not in c_flds:
                doc["removed_fields"].append({
                    "id": _fid(block_name, name, fn),
                    "lsb": bf["lsb"],
                    "msb": bf["msb"],
                })

    # Interrupts.
    b_int = {i["name"]: i for i in base_b.get("interrupts", [])}
    c_int = {i["name"]: i for i in cand_b.get("interrupts", [])}
    for name, ci in c_int.items():
        if not same_block or name not in b_int:
            doc["added_interrupts"].append({"id": _iid(block_name, name)})
            continue
        bi = b_int[name]
        changes: list[dict[str, Any]] = []
        for role in ("number", "source", "enable", "status", "clear"):
            if bi.get(role) != ci.get(role):
                changes.append({
                    "role": role,
                    "from": bi.get(role),
                    "to": ci.get(role),
                })
        if changes:
            doc["changed_interrupts"].append({
                "id": _iid(block_name, name),
                "changes": changes,
            })
    for name in b_int:
        if not same_block or name not in c_int:
            doc["removed_interrupts"].append({"id": _iid(base_b["name"], name)})

    # DMA buffers.
    b_dma = {d["name"]: d for d in base_ir.get("dma_buffers", [])}
    c_dma = {d["name"]: d for d in cand_ir.get("dma_buffers", [])}
    for name, cd in c_dma.items():
        if not same_block or name not in b_dma:
            # A new buffer's every field is an add, all at once.
            doc["changed_dma_layouts"].append({
                "id": _did(block_name, name),
                "added_field_ids": [_dfid(block_name, name, f["name"]) for f in cd.get("fields", [])],
                "removed_field_ids": [],
                "moved_fields": [],
                "owner_changes": [],
            })
            continue
        bd = b_dma[name]
        b_de = {f["name"]: f for f in bd.get("fields", [])}
        c_de = {f["name"]: f for f in cd.get("fields", [])}
        added = [_dfid(block_name, name, fn) for fn in c_de if fn not in b_de]
        removed = [_dfid(block_name, name, fn) for fn in b_de if fn not in c_de]
        moved = [
            {"id": _dfid(block_name, name, fn),
             "from_offset": b_de[fn]["offset"], "to_offset": c_de[fn]["offset"]}
            for fn in c_de
            if fn in b_de and b_de[fn]["offset"] != c_de[fn]["offset"]
        ]
        owners = [
            {"id": _dfid(block_name, name, fn),
             "from": b_de[fn]["owner"], "to": c_de[fn]["owner"]}
            for fn in c_de
            if fn in b_de and b_de[fn].get("owner") != c_de[fn].get("owner")
        ]
        coherents = [
            {"id": _dfid(block_name, name, fn),
             "from": b_de[fn].get("coherent"), "to": c_de[fn].get("coherent")}
            for fn in c_de
            if fn in b_de and b_de[fn].get("coherent") != c_de[fn].get("coherent")
        ]
        if any([added, removed, moved, owners, coherents]):
            lay: dict[str, Any] = {
                "id": _did(block_name, name),
                "added_field_ids": added,
                "removed_field_ids": removed,
                "moved_fields": moved,
            }
            if owners:
                lay["owner_changes"] = owners
            if coherents:
                lay["coherence_changes"] = coherents
            doc["changed_dma_layouts"].append(lay)
    for name in b_dma:
        if not same_block or name not in c_dma:
            doc["changed_dma_layouts"].append({
                "id": _did(base_b["name"], name),
                "added_field_ids": [],
                "removed_field_ids": [_dfid(base_b["name"], name, f["name"]) for f in b_dma[name].get("fields", [])],
                "moved_fields": [],
            })

    return doc


def diff_is_empty(doc: dict[str, Any]) -> bool:
    keys = [k for k in doc if k.startswith("added_") or k.startswith("removed_")
            or k.startswith("moved_") or k.startswith("widened_") or k.startswith("narrowed_")
            or k.startswith("repositioned_") or k.startswith("changed_")]
    return all(not doc[k] for k in keys)


# ---------------------------------------------------------------------------
# Impact
# ---------------------------------------------------------------------------


def _short_reason(doc: dict[str, Any]) -> str | None:
    """A compact, deterministic change summary for a stale artifact."""
    parts: list[str] = []
    if doc["changed_block_properties"]:
        parts.append("block properties changed")
    for key in ("added_registers", "removed_registers", "moved_registers",
                "widened_fields", "narrowed_fields", "repositioned_fields",
                "added_fields", "removed_fields",
                "changed_enum_values", "changed_interrupts", "added_interrupts",
                "removed_interrupts", "changed_dma_layouts", "changed_reset_values"):
        if doc[key]:
            parts.append(f"{key}={len(doc[key])}")
    return "; ".join(parts) if parts else None


def compute_impact(base_ir: dict, cand_ir: dict) -> dict[str, Any]:
    """The §7.1 impact document: the §7 diff plus, per generator
    target, whether the artifact is stale — decided by
    byte-comparing the generator's output for base vs candidate.

    Targets whose generators have not landed are reported with
    `stale: null` ("not checked"), per the tier discipline: an
    unimplemented generator can never produce a "no change" claim.
    """
    doc = compute_diff(base_ir, cand_ir)
    artifacts: list[dict[str, Any]] = []
    stale = not diff_is_empty(doc)

    for target in _ALL_TARGETS:
        if target not in _IMPLEMENTED_TARGETS:
            artifacts.append({
                "target": target,
                "stale": None,
                "reason": "generator-unimplemented (Phase 2); not checked",
            })
            continue
        gen = _load_generator(target)
        out_b = gen(base_ir, source_path=_NEUTRAL_LABEL)
        out_c = gen(cand_ir, source_path=_NEUTRAL_LABEL)
        if out_b == out_c:
            artifacts.append({
                "target": target,
                "stale": False,
                "reason": "no change (byte-identical output for both contracts)",
            })
        else:
            reason = _short_reason(doc) or "artifact bytes differ"
            artifacts.append({
                "target": target,
                "stale": True,
                "reason": reason,
            })

    return {
        "schema": "cancho-hdl-impact",
        "version": _DIFF_SCHEMA_VERSION,
        "diff": doc,
        "affected_artifacts": artifacts,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _load_or_refuse(path: str) -> tuple[dict | None, list]:
    ir, diags = load_contract(path)
    if ir is None:
        return None, diags
    errs = [d for d in check_file(path) if d.severity == "Error"]
    if errs:
        return None, errs
    return ir, []


def _emit(doc: dict, pretty: bool) -> int:
    text = json.dumps(doc, indent=2) if pretty else json.dumps(doc)
    sys.stdout.write(text + "\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="cancho-hdl diff",
        description="Semantic diff (and impact list) between two .chw contracts.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, help_ in (("diff", "the §7 semantic-diff document"),
                        ("impact", "the §7.1 document: diff plus affected artifacts")):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("base")
        sp.add_argument("candidate")
        sp.add_argument("--pretty", action="store_true", help="indent the JSON")

    args = ap.parse_args()

    base_ir, errs_b = _load_or_refuse(args.base)
    cand_ir, errs_c = _load_or_refuse(args.candidate)
    if base_ir is None or cand_ir is None:
        for e in (errs_b or []) + (errs_c or []):
            print(f"error[{e.code}]: {e.message}", file=sys.stderr)
        return 1

    if args.cmd == "diff":
        return _emit(compute_diff(base_ir, cand_ir), args.pretty)
    return _emit(compute_impact(base_ir, cand_ir), args.pretty)


if __name__ == "__main__":
    sys.exit(main())
