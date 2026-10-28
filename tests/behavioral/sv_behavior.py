"""The SystemVerilog behavioral roundtrip: the generated AXI4-Lite module vs the reference model.

The same corpus as the C-side roundtrip (`tests/behavioral/scenarios.json`), the same reference model
(`oracle/legacy/tools/sim/reference_model.py`), the same trace shape. For each scenario the module under test is the
PRODUCT's (`chw generate FILE --target systemverilog`); it is simulated with Icarus Verilog (`iverilog -g2012`) under
the bench `tests/behavioral/sv_device_tb.sv`. Python here is a test oracle only: it reads the corpus, writes a bus
command file, reads the bench's trace back and compares. Nothing it does is a decision of the product.

What can and cannot be compared (the module is a register file on an AXI4-Lite slave, nothing more):

  * R, Rf, W, Wf, RESET are bus operations and are driven and compared.
  * D, Df (the device writes a register), DW, DX, DR (DMA), IP, PE, PS, PC (interrupts) have no port on the module.
    They are not driven. A register the device wrote is *tainted* until the next RESET: its reads are not compared,
    because the module has no way to be given the device's value.
  * An op the model refuses (`ERR <code>`) is not compared with a bus response: the module has no refusal. A write to a
    read-only register is still driven, and the register is read back by whatever the script does next.
  * Wf is a read-modify-write on the bus: the word is built from the model's value of the register before the op.

Run: python3 tests/behavioral/sv_behavior.py /path/to/chw [--addr absolute|offset] [--mode hold|strict] [-v]
Needs `iverilog` and `vvp` on PATH; without them it says so and exits 2 (it does not pass).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (ROOT / "oracle" / "legacy" / "tools" / "parse", ROOT / "oracle" / "legacy" / "tools" / "sim"):
    sys.path.insert(0, str(_p))

from parser import load_contract  # noqa: E402
from reference_model import ReferenceModel, _field_mask  # noqa: E402
from op_runner import run_first_op  # noqa: E402

BUS_OPS = {"R", "Rf", "W", "Wf", "RESET"}
KINDS_BY_ACTION = {"W1C", "W0C", "W1S", "W0S"}


def hex_of(text: str) -> int:
    return int(text, 16)


def plan(ir: dict, ops: list[str], addr_mode: str):
    """Walk `ops` through the reference model; yield (model_line, bus_cmds, expect) per op.

    bus_cmds: command lines for the bench. expect: how to judge the bench's last line: None (not compared), or the
    model's trace line."""
    model = ReferenceModel(ir)
    block = ir["block"]
    base = hex_of(block["base_address"])
    regs = {r["name"]: r for r in block["registers"]}
    tainted: set[str] = set()

    def addr(name: str) -> int:
        off = hex_of(regs[name]["offset"])
        return (base + off) if addr_mode == "absolute" else off

    for line in ops:
        op, args = line.split()[0], line.split()[1:]
        before = dict(model._reg_state)
        trace: list[str] = []
        run_first_op(op, args, model, trace)
        got = trace[0]
        if op in ("D", "Df"):
            tainted.add(args[0])
        if op == "RESET":
            tainted.clear()
        if op not in BUS_OPS:
            yield line, [], None, "no-port"
            continue
        if op == "RESET":
            yield line, ["RESET"], got, None
            continue
        reg = args[0]
        if op in ("R", "Rf"):
            if got.startswith("ERR"):
                yield line, [], None, "model-refused"
            elif reg in tainted:
                yield line, [], None, "tainted"
            else:
                if op == "Rf":
                    # the bench returns the word; the field is cut out of it the way the model cuts it
                    yield line, [f"R {addr(reg):08x}"], got, ("field", model._fields_by_register[reg][args[1]])
                else:
                    yield line, [f"R {addr(reg):08x}"], got, None
            continue
        # a write
        kind = regs[reg]["kind"]
        if op == "W":
            word = int(args[1], 0) & 0xFFFFFFFF
        else:
            fdef = model._fields_by_register[reg][args[1]]
            if got.startswith("ERR"):
                yield line, [], None, "model-refused"
                continue
            enc = int(args[2], 0) << fdef["lsb"]
            if kind in KINDS_BY_ACTION:
                word = enc
            else:
                cur = 0 if kind == "WO" else before[reg]
                word = (cur & ~_field_mask(fdef["lsb"], fdef["msb"]) | enc) & 0xFFFFFFFF
        # a refused write (read-only register) is driven and its response is not judged
        yield line, [f"W {addr(reg):08x} {word:08x}"], (None if got.startswith("ERR") else got), None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("chw")
    ap.add_argument("--addr", choices=["absolute", "offset"], default="absolute")
    ap.add_argument("--mode", choices=["hold", "strict"], default="hold")
    ap.add_argument("--diagnose-zero-base", action="store_true",
                    help="investigation only: set the generated BASE_ADDR to 0 so that the checks behind the base-address "
                         "defect can be seen; the result is not a statement about the product's output")
    ap.add_argument("-v", action="store_true")
    ns = ap.parse_args()
    for tool in ("iverilog", "vvp"):
        if shutil.which(tool) is None:
            print(f"sv_behavior: {tool} is not on PATH; the behavioral roundtrip did not run")
            return 2
    corpus = json.loads((ROOT / "tests" / "behavioral" / "scenarios.json").read_text())
    total = ok = bad = 0
    skipped: dict[str, int] = {}
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        built: dict[str, tuple[dict, pathlib.Path, str]] = {}
        for sc in corpus["scenarios"]:
            cpath = sc["contract"]
            if cpath not in built:
                sv = subprocess.run([ns.chw, "generate", str(ROOT / cpath), "--target", "systemverilog"],
                                    capture_output=True, text=True, cwd=ROOT)
                if sv.returncode != 0:
                    print(f"FAIL {sc['name']}: chw generate exited {sv.returncode}: {sv.stdout[:200]}{sv.stderr[:200]}")
                    bad += 1
                    continue
                ir, _ = load_contract(str(ROOT / cpath))
                tag = re.sub(r"\W", "_", cpath)
                text = sv.stdout
                if ns.diagnose_zero_base:
                    text = re.sub(r"(BASE_ADDR = \d+'h)[0-9a-fA-F]+", r"\g<1>00000000", text)
                (td / f"{tag}.sv").write_text(text)
                mod = re.search(r"^module (\w+) #\(", sv.stdout, re.M).group(1)
                outs = re.findall(r"output wire \[DATA_WIDTH-1:0\]\s+(reg_\w+_out)", sv.stdout)
                wiring = [f"  wire [31:0] {o}_w;" for o in outs]
                conns = ["clk", "rst_n"] + [f"s_axi_{p}" for p in (
                    "awaddr", "awvalid", "awready", "wdata", "wstrb", "wvalid", "wready", "bresp", "bvalid", "bready",
                    "araddr", "arvalid", "arready", "rdata", "rresp", "rvalid", "rready")]
                ports = ",\n    ".join([f".{c}({c.removeprefix('s_axi_')})" if c.startswith("s_axi_") else f".{c}({c})" for c in conns] + [f".{o}({o}_w)" for o in outs])
                svh = td / f"{tag}.svh"
                svh.write_text("\n".join(wiring) + f"\n  {mod} dut (\n    {ports}\n  );\n")
                built[cpath] = (ir, td / f"{tag}.sv", tag)
                # the bench includes sv_wiring.svh: give it the per-contract file under that name
                (td / "sv_wiring.svh").write_text(svh.read_text())
                comp = subprocess.run(
                    ["iverilog", "-g2012", "-o", str(td / f"{tag}.vvp"), "-I", str(td),
                     str(ROOT / "tests/behavioral/sv_device_tb.sv"), str(td / f"{tag}.sv")],
                    capture_output=True, text=True, cwd=td)
                if comp.returncode != 0:
                    print(f"FAIL {cpath}: iverilog: {comp.stderr[:400]}")
                    bad += 1
                    del built[cpath]
                    continue
            ir, _sv, tag = built[cpath]
            steps = list(plan(ir, sc["ops"], ns.addr))
            cmds = [c for _l, cs, _e, _s in steps for c in cs]
            cf = td / "cmds.txt"
            cf.write_text("\n".join(cmds) + "\n")
            run = subprocess.run(["vvp", "-N", str(td / f"{tag}.vvp"), f"+CMDS={cf}", f"+MODE={ns.mode}"],
                                 capture_output=True, text=True, cwd=td)
            lines = [l for l in run.stdout.splitlines() if l.startswith(("OK", "ERR"))]
            if len(lines) != len(cmds):
                print(f"FAIL {sc['name']}: bench printed {len(lines)} lines for {len(cmds)} commands")
                bad += 1
                continue
            it = iter(lines)
            for line, cs, expect, why in steps:
                if isinstance(why, tuple):
                    fdef = why[1]
                    word = next(it)
                    if word.startswith("OK 0x"):
                        word = "OK 0x%08x" % ((int(word[5:], 16) & _field_mask(fdef["lsb"], fdef["msb"])) >> fdef["lsb"])
                    total += 1
                    if word == expect:
                        ok += 1
                    else:
                        bad += 1
                        print(f"  MISMATCH {sc['name']}: {line!r}: model {expect}, module {word}")
                    continue
                if why:
                    skipped[why] = skipped.get(why, 0) + 1
                    continue
                got = [next(it) for _ in cs][-1] if cs else None
                if expect is None:
                    skipped["driven-unjudged"] = skipped.get("driven-unjudged", 0) + 1
                    continue
                total += 1
                if got == expect:
                    ok += 1
                else:
                    bad += 1
                    if ns.v or bad <= 12:
                        print(f"  MISMATCH {sc['name']}: {line!r}: model {expect}, module {got}")
    print(f"sv_behavior ({ns.addr} addresses, {ns.mode} master): compared {total}, equal {ok}, different {bad}; not compared: {skipped}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
