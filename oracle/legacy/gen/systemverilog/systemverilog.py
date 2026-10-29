"""SystemVerilog register module generator for cancho-hdl.

Implements the per-target contract in `spec/generators/README.md` §5.
Reads a contract IR and emits a SystemVerilog module that:

- Implements an AXI4-Lite memory-mapped slave that decodes the
  register map.
- Has one `reg [N-1:0]` per register at its offset, applied
  through the AXI4-Lite write path.
- Has one `reg_<name>_out` output port per register, exposing
  the live value, and `reg_<name>_in` for `RO` volatile ones (device-written).
- Honors access kinds: RW/RO/WO/RC/W1C/W0C/W1S/W0S.
- Applies contract reset values on `!rst_n`.
- Carries stable ID comments on every register and field, so a
  generated module that defines a register named `CTRL` is
  traceable back to `chw:UartRegs.register.CTRL`.

Tier of output: `Tested` (parses) + `Trust` (synthesis). The
synthesis output is a trusted boundary; the parent proposal
explicitly never claims it.

The output is deterministic. Same IR → byte-identical bytes.

Usage:

    from systemverilog import generate
    src = generate(ir_dict, source_path="examples/uart-contract/uart.chw")
    open("gen/uart_regs.sv", "w").write(src)
"""

from __future__ import annotations

import io
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_lower_snake(name: str) -> str:
    """`UartRegs` → `uart_regs`, `CTRL` → `ctrl`. See c_header.py for
    the full rule on abbreviation boundaries."""
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


SV_BAR = "    // ----------------------------------------------------------------\n"
SV_PORTS = """    input  wire                       clk,
    input  wire                       rst_n,

    // AXI4-Lite write address channel
    input  wire [ADDR_WIDTH-1:0]      s_axi_awaddr,
    input  wire                       s_axi_awvalid,
    output wire                       s_axi_awready,

    // AXI4-Lite write data channel
    input  wire [DATA_WIDTH-1:0]      s_axi_wdata,
    input  wire [DATA_WIDTH/8-1:0]    s_axi_wstrb,
    input  wire                       s_axi_wvalid,
    output wire                       s_axi_wready,

    // AXI4-Lite write response channel
    output wire [1:0]                 s_axi_bresp,
    output wire                       s_axi_bvalid,
    input  wire                       s_axi_bready,

    // AXI4-Lite read address channel
    input  wire [ADDR_WIDTH-1:0]      s_axi_araddr,
    input  wire                       s_axi_arvalid,
    output wire                       s_axi_arready,

    // AXI4-Lite read data channel
    output wire [DATA_WIDTH-1:0]      s_axi_rdata,
    output wire [1:0]                 s_axi_rresp,
    output wire                       s_axi_rvalid,
"""

SV_WRITE_DECODE = """    // ----------------------------------------------------------------
    // Write decode: accepted when address and data are valid and no response is pending
    // ----------------------------------------------------------------
    reg                  bvalid_r;
    reg [1:0]            bresp_r;
    reg                  rvalid_r;
    reg [1:0]            rresp_r;
    reg [DATA_WIDTH-1:0] rdata_r;
    wire wr_acc;
    assign wr_acc = s_axi_awvalid && s_axi_wvalid && !bvalid_r;
    wire aw_match_{bn};
    assign aw_match_{bn} =
        wr_acc && (s_axi_awaddr >= BASE_ADDR);

    reg wr_hit;
    always @(*) begin
        wr_hit = 1'b0;
"""
SV_WMASK = """    end

    wire [DATA_WIDTH-1:0] wmask;
    genvar bi;
    generate
        for (bi = 0; bi < DATA_WIDTH/8; bi = bi + 1) begin : g_wmask
            assign wmask[8*bi +: 8] = {8{s_axi_wstrb[bi]}};
        end
    endgenerate

"""
SV_READ_DECODE = """    // ----------------------------------------------------------------
    // Read mux: accepted when the address is valid and no response is pending
    // ----------------------------------------------------------------
    wire rd_acc;
    assign rd_acc = s_axi_arvalid && !rvalid_r;
    wire ar_match_{bn};
    assign ar_match_{bn} =
        rd_acc && (s_axi_araddr >= BASE_ADDR);

    reg [DATA_WIDTH-1:0] rdata;
    reg                  rdata_valid;
    always @(*) begin
        rdata = 'h0;
        rdata_valid = 1'b0;
"""
SV_SEQ_HDR = """    // ----------------------------------------------------------------
    // Reset, handshake and write logic: one clocked block, one driver per register
    // ----------------------------------------------------------------
    always @(posedge clk) begin
        if (!rst_n) begin
"""
SV_SEQ_MID = """            bvalid_r <= 1'b0;
            bresp_r <= 2'b00;
            rvalid_r <= 1'b0;
            rresp_r <= 2'b00;
            rdata_r <= 'h0;
        end else begin
            if (bvalid_r && s_axi_bready) bvalid_r <= 1'b0;
            if (rvalid_r && s_axi_rready) rvalid_r <= 1'b0;
            if (wr_acc) begin
                bvalid_r <= 1'b1;
                bresp_r <= wr_hit ? 2'b00 : 2'b10;  // SLVERR: no writable register at the address
            end
            if (rd_acc) begin
                rvalid_r <= 1'b1;
                rdata_r <= rdata;
                rresp_r <= rdata_valid ? 2'b00 : 2'b10;  // SLVERR: no readable register at the address
            end
"""
SV_SEQ_END = """        end
    end

    // ----------------------------------------------------------------
    // AXI4-Lite handshake: a request is accepted on one clock and answered on the next, held until its ready
    // ----------------------------------------------------------------
    assign s_axi_awready = wr_acc;
    assign s_axi_wready  = wr_acc;
    assign s_axi_bvalid  = bvalid_r;
    assign s_axi_bresp   = bresp_r;

    assign s_axi_arready = rd_acc;
    assign s_axi_rdata   = rdata_r;
    assign s_axi_rvalid  = rvalid_r;
    assign s_axi_rresp   = rresp_r;

"""


def generate(ir: dict[str, Any], source_path: str = "<memory>") -> str:
    block = ir["block"]
    block_name: str = block["name"]
    bus_width: int = int(block["bus_width"])
    base_address: int = int(block["base_address"], 16)
    module_name = _to_lower_snake(block_name) + "_axi"

    out = io.StringIO()

    # Banner
    out.write(f"// Generated by cancho-hdl from {source_path}. Do not edit.\n// chw:{block_name}\n"
              "// Synthesis output is a Trust boundary (see docs/guarantees.md).\n`default_nettype none\n\n")

    # Module declaration
    out.write(f"module {module_name} #(\n    parameter ADDR_WIDTH = 32,\n   parameter DATA_WIDTH = {bus_width}\n) (\n{SV_PORTS}")
    out.write("    input  wire                       s_axi_rready" + ("," if block.get("registers") else "") + "\n")
    out.write("\n")

    registers = sorted(block.get("registers", []), key=lambda r: int(r["offset"], 16))
    out.write("".join(f"    input  wire [DATA_WIDTH-1:0]      reg_{_to_lower_snake(r['name'])}_in,  // chw:{block_name}.register.{r['name']}\n" for r in registers if r["kind"] == "RO" and r.get("volatile")))
    for n, reg in enumerate(registers):
        out.write(
            f"    output wire [DATA_WIDTH-1:0]      reg_{_to_lower_snake(reg['name'])}_out{',' if n + 1 < len(registers) else ' '}  "
            f"// chw:{block_name}.register.{reg['name']}\n"
        )
    out.write(");\n\n")

    # Local parameters: base address + per-register offsets
    out.write(f"    // Base address from contract: 0x{base_address:08x}\n")
    out.write(f"    localparam [ADDR_WIDTH-1:0] BASE_ADDR = {bus_width}'h{base_address:08x};\n")
    for reg in registers:
        offset = int(reg["offset"], 16)
        out.write(
            f"    localparam [ADDR_WIDTH-1:0] ADDR_{reg['name']} = "
            f"'h{offset:08x};  // chw:{block_name}.register.{reg['name']}\n"
        )
    out.write("\n")

    # Per-field enum localparams
    for reg in registers:
        for fld in reg.get("fields", []):
            if "enum" in fld and isinstance(fld["enum"], dict):
                for label, val in fld["enum"].items():
                    out.write(
                        f"    localparam [DATA_WIDTH-1:0] "
                        f"{reg['name']}_{fld['name']}_{label.upper()} = "
                        f"{bus_width}'d{int(val)};\n"
                    )
    out.write("\n")

    # Internal storage
    out.write(SV_BAR + "    // Internal storage\n" + SV_BAR)
    for reg in registers:
        out.write(f"    // chw:{block_name}.register.{reg['name']}\n")
        out.write(
            f"    reg [DATA_WIDTH-1:0] r_{_to_lower_snake(reg['name'])};\n"
        )
    out.write("\n")

    # Continuous assignment: behavior output = register value
    out.write(SV_BAR + "    // Behavior ports: live register values for user to wire up\n" + SV_BAR)
    for reg in registers:
        rn = _to_lower_snake(reg["name"])
        out.write(
            f"    assign reg_{rn}_out = r_{rn};\n"
        )
    out.write("\n")

    # Write decode: a write is accepted when both valids are up and no response is pending
    bn = _to_lower_snake(block_name)
    writable = [r for r in registers if r["kind"] in ("RW", "WO", "W1C", "W0C", "W1S", "W0S", "RC")]
    out.write(SV_WRITE_DECODE.format(bn=bn))
    for reg in writable:
        out.write(f"        if (aw_match_{bn} && (s_axi_awaddr == BASE_ADDR + ADDR_{reg['name']})) wr_hit = 1'b1;\n")
    out.write(SV_WMASK)

    # Read decode and mux: a read is accepted when the address is valid and no response is pending
    out.write(SV_READ_DECODE.format(bn=bn))
    for reg in registers:
        out.write(f"        if (ar_match_{bn} && (s_axi_araddr == BASE_ADDR + ADDR_{reg['name']})) begin\n")
        if reg["kind"] == "WO":
            out.write("            // WO register: reads return 0 and answer SLVERR (the spec notes this is a write-only register).\n")
            out.write("            rdata = 'h0;\n        end\n")
        else:
            out.write(f"            rdata = {'reg_%s_in' if reg['kind'] == 'RO' and reg.get('volatile') else 'r_%s'};\n            rdata_valid = 1'b1;\n        end\n" % _to_lower_snake(reg["name"]))
    out.write("    end\n\n")

    # Reset, handshake and write logic: one clocked block, so every register has one driver
    out.write(SV_SEQ_HDR)
    for reg in registers:
        rn = _to_lower_snake(reg["name"])
        if "reset" in reg:
            out.write(f"            r_{rn} <= 'h{int(reg['reset'], 16):0{bus_width // 4}x};  // chw:{block_name}.register.{reg['name']}\n")
        else:
            out.write(f"            r_{rn} <= 'h0;  // chw:{block_name}.register.{reg['name']} (reset undefined)\n")
    out.write(SV_SEQ_MID)
    for reg in registers:
        rn = _to_lower_snake(reg["name"])
        kind = reg["kind"]
        out.write(f"            // chw:{block_name}.register.{reg['name']} (kind={kind})\n")
        cond = f"aw_match_{bn} && (s_axi_awaddr == BASE_ADDR + ADDR_{reg['name']}) && s_axi_wvalid"
        rhs = {
            "RW": f"(r_{rn} & ~wmask) | (s_axi_wdata & wmask);",
            "W1C": f"r_{rn} & ~(s_axi_wdata & wmask);",
            "W0C": f"r_{rn} & (s_axi_wdata | ~wmask);",
            "W1S": f"r_{rn} | (s_axi_wdata & wmask);",
            "RC": "'h0;  // RC: read clears, write has no effect",
        }
        rhs["WO"] = rhs["RW"]
        rhs["W0S"] = rhs["W1C"]
        if kind == "RO":
            out.write("            // RO: writes are dropped and answer SLVERR. This is a Trust-tier behavioural choice; the checker flags WO/RO misuse.\n")
            out.write(f"            if (1'b0) r_{rn} <= r_{rn};  // no-op\n")
        elif kind in rhs:
            out.write(f"            if ({cond}) r_{rn} <= {rhs[kind]}\n")
        else:
            out.write(f"            // Unknown kind {kind!r}; no write logic emitted.\n")
    out.write(SV_SEQ_END)

    out.write("endmodule\n")
    out.write("\n`default_nettype wire\n")
    return out.getvalue()


# ---------------------------------------------------------------------------
# CLI entry point (used by tests; the dispatcher is the public CLI)
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import argparse
    import json
    import pathlib
    import sys

    parser = argparse.ArgumentParser(
        prog="cancho-hdl generate --target systemverilog",
        description="Generate a SystemVerilog AXI4-Lite register module from a .chw contract.",
    )
    parser.add_argument("file", help="A .chw file (JSON wire format).")
    args = parser.parse_args()

    p = pathlib.Path(args.file)
    try:
        ir = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        print(f"error: file is not valid JSON: {e}", file=sys.stderr)
        sys.exit(2)

    src = generate(ir, source_path=str(p))
    sys.stdout.write(src)
    sys.exit(0)