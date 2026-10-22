"""Roundtrip test: generated SystemVerilog is structurally well-formed.

Verifies that the generated `systemverilog` output for every
valid example has the expected shape: module declaration, the
right number of register output ports, the right number of
write-decode and read-decode branches, the right reset values,
the right access-kind handling, and a stable endmodule.

The parent proposal §5.3 names the roundtrip test
`tests/roundtrip/systemverilog_parses.rs` and lists "parses
under Yosys and slang" as the gate. Neither tool is available
in the default Linux environment; this test is the
characterisation check that runs without them.

When slang, yosys, or iverilog is on `$PATH`, the test
additionally tries a real parse. The real parse is a stronger
guarantee than the structural check, and a passing real parse
supersedes the structural one.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oracle" / "legacy" / "tools" / "generate"))
sys.path.insert(0, str(ROOT / "oracle" / "legacy" / "tools" / "parse"))

from generate import _load_generator  # noqa: E402
from parser import load_contract  # noqa: E402


EXAMPLES = ROOT / "examples"
MANIFEST = json.loads((EXAMPLES / "MANIFEST.json").read_text())


# ---------------------------------------------------------------------------
# Structural checks
# ---------------------------------------------------------------------------


def _check_module_declaration(src: str, expected_module: str) -> list[str]:
    notes: list[str] = []
    if f"module {expected_module} #(" not in src:
        notes.append(f"missing `module {expected_module} #(` declaration")
    if not re.search(rf"module {re.escape(expected_module)}\s*#\(", src):
        notes.append(f"module declaration does not match expected name {expected_module}")
    if "endmodule" not in src:
        notes.append("missing `endmodule`")
    if src.count("(") != src.count(")"):
        notes.append("unbalanced parens: "
                     + str(src.count("(")) + " open vs "
                     + str(src.count(")")) + " close")
    if src.count("{") != src.count("}"):
        notes.append("unbalanced braces: "
                     + str(src.count("{")) + " open vs "
                     + str(src.count("}")) + " close")
    return notes


def _check_register_output_ports(src: str, registers: list[dict]) -> list[str]:
    notes: list[str] = []
    for reg in registers:
        name = reg["name"]
        if f"reg_{name.lower()}_out" not in src:
            notes.append(f"missing output port reg_{name.lower()}_out for register {name}")
    return notes


def _check_address_localparams(src: str, registers: list[dict]) -> list[str]:
    notes: list[str] = []
    for reg in registers:
        name = reg["name"]
        offset = int(reg["offset"], 16)
        pattern = rf"ADDR_{name}\s*=\s*ADDR_WIDTH'h{offset:08x}"
        if not re.search(pattern, src):
            notes.append(f"missing or wrong ADDR_{name} localparam (expected 0x{offset:08x})")
    return notes


def _check_reset_values(src: str, registers: list[dict]) -> list[str]:
    notes: list[str] = []
    for reg in registers:
        rn = reg["name"].lower()
        if "reset" in reg:
            reset_val = int(reg["reset"], 16)
            expected = f"r_{rn} <= DATA_WIDTH'h{reset_val:08x}"
            if expected not in src:
                notes.append(f"missing reset assignment `{expected}` for register {reg['name']}")
        else:
            expected = f"r_{rn} <= DATA_WIDTH'h0"
            if expected not in src:
                notes.append(f"missing zero-reset assignment `{expected}` for register {reg['name']}")
    return notes


def _check_access_kind_handling(src: str, registers: list[dict]) -> list[str]:
    notes: list[str] = []
    for reg in registers:
        kind = reg["kind"]
        rn = reg["name"].lower()
        if kind == "W1C":
            if f"r_{rn} <= r_{rn} & ~s_axi_wdata" not in src:
                notes.append(f"W1C register {reg['name']} missing `r_{rn} & ~s_axi_wdata` write logic")
        elif kind == "W0C":
            if f"r_{rn} <= r_{rn} & s_axi_wdata" not in src:
                notes.append(f"W0C register {reg['name']} missing `r_{rn} & s_axi_wdata` write logic")
        elif kind == "W1S":
            if f"r_{rn} <= r_{rn} | s_axi_wdata" not in src:
                notes.append(f"W1S register {reg['name']} missing `r_{rn} | s_axi_wdata` write logic")
        elif kind == "W0S":
            if f"r_{rn} <= r_{rn} & ~s_axi_wdata" not in src:
                notes.append(f"W0S register {reg['name']} missing `r_{rn} & ~s_axi_wdata` write logic")
        elif kind == "RC":
            if f"r_{rn} <= DATA_WIDTH'h0" not in src:
                notes.append(f"RC register {reg['name']} missing clear-on-write logic")
    return notes


def _check_stable_ids(src: str, ir: dict) -> list[str]:
    notes: list[str] = []
    block_name = ir["block"]["name"]
    if f"// chw:{block_name}" not in src:
        notes.append(f"missing block stable ID `// chw:{block_name}`")
    for reg in ir["block"].get("registers", []):
        id_str = f"// chw:{block_name}.register.{reg['name']}"
        if id_str not in src:
            notes.append(f"missing register stable ID `{id_str}`")
    return notes


def _check_enum_localparams(src: str, ir: dict) -> list[str]:
    notes: list[str] = []
    block_name = ir["block"]["name"]
    for reg in ir["block"].get("registers", []):
        for fld in reg.get("fields", []):
            if "enum" in fld and isinstance(fld["enum"], dict):
                for label, _val in fld["enum"].items():
                    expected = f"{reg['name']}_{fld['name']}_{label.upper()}"
                    if expected not in src:
                        notes.append(f"missing enum localparam `{expected}`")
    return notes


def _check_write_decode_branches(src: str, registers: list[dict]) -> list[str]:
    notes: list[str] = []
    for reg in registers:
        kind = reg["kind"]
        if kind == "RO":
            # RO writes are silently dropped (no explicit decode branch).
            continue
        pattern = f"s_axi_awaddr == ADDR_{reg['name']}"
        if pattern not in src:
            notes.append(f"missing write-decode branch for register {reg['name']}")
    return notes


def _check_read_decode_branches(src: str, registers: list[dict]) -> list[str]:
    notes: list[str] = []
    for reg in registers:
        pattern = f"s_axi_araddr == ADDR_{reg['name']}"
        if pattern not in src:
            notes.append(f"missing read-decode branch for register {reg['name']}")
    return notes


# ---------------------------------------------------------------------------
# Real-parse check (if any tool is on $PATH)
# ---------------------------------------------------------------------------


def _try_real_parse(sv_path: pathlib.Path) -> tuple[bool, str]:
    """If iverilog, slang, or yosys is on $PATH, run it and report
    whether the file parses. Returns (parsed_ok, info)."""
    if shutil.which("iverilog"):
        proc = subprocess.run(
            ["iverilog", "-t", "null", str(sv_path)],
            capture_output=True, text=True,
        )
        return proc.returncode == 0, f"iverilog: {proc.returncode}"
    if shutil.which("slang"):
        proc = subprocess.run(
            ["slang", "--parse-only", str(sv_path)],
            capture_output=True, text=True,
        )
        return proc.returncode == 0, f"slang: {proc.returncode}"
    if shutil.which("yosys"):
        proc = subprocess.run(
            ["yosys", "-p", f"read_verilog {sv_path}"],
            capture_output=True, text=True,
        )
        return proc.returncode == 0, f"yosys: {proc.returncode}"
    return True, "no real parser on $PATH; structural check only"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    gen = _load_generator("systemverilog")
    if gen is None:
        print("FAIL  systemverilog generator not registered")
        return 1

    # Real-parse capability check
    real_parser_msg = None
    if shutil.which("iverilog") or shutil.which("slang") or shutil.which("yosys"):
        real_parser_msg = "real parser available"
    else:
        real_parser_msg = "no iverilog/slang/yosys on $PATH; structural check only"

    print(f"== systemverilog roundtrip ({real_parser_msg}) ==")
    failures: list[str] = []

    for rel in MANIFEST["valid"]:
        chw = ROOT / rel
        ir, load_diags = load_contract(str(chw))
        if ir is None:
            failures.append(f"  FAIL  {chw.stem}: contract did not load: "
                            f"{load_diags[0].message}")
            continue
        expected_module = _to_lower_snake(ir["block"]["name"]) + "_axi"

        out = ROOT / f"gen-out/{chw.stem}_systemverilog.sv"
        out.parent.mkdir(parents=True, exist_ok=True)

        # Generate
        src = gen(ir, source_path=str(chw))
        out.write_text(src)

        # Determinism
        src2 = gen(ir, source_path=str(chw))
        if src != src2:
            failures.append(f"  FAIL  {chw.stem}: not deterministic")
            continue

        # Structural checks
        registers = ir["block"].get("registers", [])
        notes: list[str] = []
        notes.extend(_check_module_declaration(src, expected_module))
        notes.extend(_check_register_output_ports(src, registers))
        notes.extend(_check_address_localparams(src, registers))
        notes.extend(_check_reset_values(src, registers))
        notes.extend(_check_access_kind_handling(src, registers))
        notes.extend(_check_stable_ids(src, ir))
        notes.extend(_check_enum_localparams(src, ir))
        notes.extend(_check_write_decode_branches(src, registers))
        notes.extend(_check_read_decode_branches(src, registers))

        if notes:
            failures.append(f"  FAIL  {chw.stem}: structural issues:")
            for n in notes:
                failures.append(f"          {n}")
            continue

        # Real-parse (if a tool is available)
        parsed_ok, parse_info = _try_real_parse(out)
        if not parsed_ok:
            failures.append(f"  FAIL  {chw.stem}: {parse_info}")
            continue

        status = "structural" if "structural" in real_parser_msg else "real-parse"
        print(f"  PASS  {chw.stem}: {status} check OK ({parse_info})")

    # Cleanup
    gen_out = ROOT / "gen-out"
    if gen_out.exists():
        shutil.rmtree(gen_out)

    print()
    if failures:
        print(f"== {len(failures)} failure(s) ==")
        for f in failures:
            print(f)
        return 1
    print("== systemverilog roundtrip: all valid examples pass ==")
    return 0


def _to_lower_snake(name: str) -> str:
    if not name:
        return name
    out: list[str] = []
    for i, ch in enumerate(name):
        if ch.isupper():
            prev_lower = i > 0 and name[i - 1].islower()
            end_of_abbrev = (
                i > 0 and i + 1 < len(name)
                and name[i - 1].isupper()
                and name[i + 1].islower()
            )
            if i > 0 and (prev_lower or end_of_abbrev):
                out.append("_")
        out.append(ch.lower())
    return "".join(out)


if __name__ == "__main__":
    sys.exit(main())