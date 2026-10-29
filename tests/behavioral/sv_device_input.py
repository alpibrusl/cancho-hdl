"""A device-written register is read from its input (docs/issues: cancho-hdl#21).

For every register the contract marks `RO` and `volatile`, the generated module has an input `reg_<name>_in`, and a bus read of the
register returns whatever the input holds. This drives each such input with a distinct value, reads each register over the bus under
`tests/behavioral/sv_device_tb.sv`, and checks the read equals the value driven; it also checks that a write to the register is
refused (SLVERR) and does not change what a read returns, and that a register that is not device-written has no `_in` port.

Run: python3 tests/behavioral/sv_device_input.py /path/to/chw     (needs iverilog and vvp; without them it says so and exits 2)
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
CONTRACTS = ["examples/uart-contract/uart.chw", "boards/tang-nano-20k/deadman.chw", "boards/tang-nano-20k/lab/lab.chw", "boards/tang-nano-20k/stats/stats.chw"]


def main() -> int:
    chw = sys.argv[1]
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        print("sv_device_input: iverilog is not on PATH; the check did not run")
        return 2
    total = bad = 0
    for cpath in CONTRACTS:
        gen = subprocess.run([chw, "generate", str(ROOT / cpath), "--target", "systemverilog"], capture_output=True, text=True, cwd=ROOT)
        if gen.returncode != 0:
            print(f"FAIL {cpath}: chw generate exited {gen.returncode}")
            bad += 1
            continue
        ir = json.loads((ROOT / cpath).read_text())
        block = ir["block"]
        base = int(block["base_address"], 16)
        regs = block["registers"]
        dev = [r for r in regs if r["kind"] == "RO" and r.get("volatile")]
        ins = re.findall(r"input  wire \[DATA_WIDTH-1:0\]\s+reg_(\w+)_in", gen.stdout)
        want = [r["name"].lower() for r in dev]
        total += 1
        if sorted(ins) != sorted(want):
            print(f"MISMATCH {cpath}: input ports {sorted(ins)}, device-written registers {sorted(want)}")
            bad += 1
            continue
        if not dev:
            continue
        mod = re.search(r"^module (\w+) #\(", gen.stdout, re.M).group(1)
        outs = re.findall(r"output wire \[DATA_WIDTH-1:0\]\s+(reg_\w+_out)", gen.stdout)
        values = {r["name"].lower(): 0xA5A50000 + 0x11 * (k + 1) for k, r in enumerate(dev)}
        with tempfile.TemporaryDirectory() as td:
            td = pathlib.Path(td)
            (td / "m.sv").write_text(gen.stdout)
            conns = ["clk", "rst_n"] + [f"s_axi_{p}" for p in (
                "awaddr awvalid awready wdata wstrb wvalid wready bresp bvalid bready araddr arvalid arready rdata rresp rvalid rready".split())]
            ports = [f".{c}({c.removeprefix('s_axi_')})" if c.startswith("s_axi_") else f".{c}({c})" for c in conns]
            ports += [f".reg_{n}_in(32'h{v:08x})" for n, v in values.items()] + [f".{o}({o}_w)" for o in outs]
            (td / "sv_wiring.svh").write_text("\n".join(f"  wire [31:0] {o}_w;" for o in outs) + f"\n  {mod} dut (\n    " + ",\n    ".join(ports) + "\n  );\n")
            subprocess.run(["iverilog", "-g2012", "-o", str(td / "t.vvp"), "-I", str(td), str(ROOT / "tests/behavioral/sv_device_tb.sv"), str(td / "m.sv")],
                           check=True, capture_output=True, cwd=td)
            cmds, expect = [], []
            for r in dev:
                a = base + int(r["offset"], 16)
                v = values[r["name"].lower()]
                cmds += [f"R {a:08x}", f"W {a:08x} ffffffff", f"R {a:08x}"]
                expect += [f"OK 0x{v:08x}", "ERR slverr", f"OK 0x{v:08x}"]
            (td / "c.txt").write_text("\n".join(cmds) + "\n")
            run = subprocess.run(["vvp", "-N", str(td / "t.vvp"), f"+CMDS={td / 'c.txt'}", "+MODE=strict"], capture_output=True, text=True, cwd=td)
            got = [l for l in run.stdout.splitlines() if l.startswith(("OK", "ERR"))]
            for c, e, g in zip(cmds, expect, got):
                total += 1
                if e != g:
                    bad += 1
                    print(f"MISMATCH {cpath}: {c!r}: wanted {e}, module {g}")
            if len(got) != len(cmds):
                bad += 1
                print(f"MISMATCH {cpath}: bench printed {len(got)} lines for {len(cmds)} commands")
    print(f"sv_device_input: compared {total}, different {bad}")
    return 0 if bad == 0 and total else 1


if __name__ == "__main__":
    sys.exit(main())
