# The SystemVerilog behavioral roundtrip: first measurement

Status: measured with Icarus Verilog; the open item in `docs/roadmap.md` is **not** closed by this. This note records
what the first simulation of the generated module showed, so that the roadmap and `docs/guarantees.md` can be
corrected where they say more than this.

## What was run

`tests/behavioral/sv_behavior.py` generates the module with the product (`chw generate FILE --target systemverilog`),
simulates it under `tests/behavioral/sv_device_tb.sv` (`iverilog -g2012`, `vvp`), and compares the bus-level trace with
the reference model (`oracle/legacy/tools/sim/reference_model.py`) over the corpus `tests/behavioral/scenarios.json`.
Compiler pin: `.cancho-rev` 7e4088b. Python is the oracle only: it never decides anything the product emits.

Of the corpus's 11 scenarios (64 ops), 25 are bus operations on registers that can be compared (`R`, `Rf`, `W`, `Wf`,
`RESET`). The other ops have no port on the generated module (device-side writes, DMA, interrupts: 32 ops) or are
refused by the model while the module has no refusal (4 ops), or read a register the device wrote (2 ops). 25 is a
small number, and a module whose reads never answer already agrees on 13 of them (the writes, which are
acknowledged whatever they do). Equal counts below are read with that in mind.

## Results

| Master | `BASE_ADDR` | Compared | Equal |
|---|---|---|---|
| holds `*valid` until the response (`--mode hold`) | as generated (`0x40000000`) | 25 | 13 (every read times out) |
| holds `*valid` until the response | zeroed in the generated text (`--diagnose-zero-base`; investigation only) | 25 | 25 |
| follows AXI4-Lite (`--mode strict`) | zeroed | 25 | 2 |

### Defect 1: no register is reachable when the block base is not 0

Measured on `examples/uart-contract/uart.chw` (`base_address 0x40000000`). The module compares
`s_axi_awaddr == ADDR_<REG>` where `ADDR_<REG>` is the register's *offset* (`'h00000000`), and also requires
`s_axi_awaddr >= BASE_ADDR` (`0x40000000`) before any register decode (`aw_match_*`, `ar_match_*`). No address satisfies
both: an offset fails the second test, an absolute address fails the first. Writes are acknowledged and change nothing;
reads never answer. Same in `oracle/legacy/gen/systemverilog/systemverilog.py` (lines 132, 203, 260), so the cancho
port reproduces it faithfully (`src/gen_sv.cho`, `put_write_cond`, `put_read_branch`). The structural roundtrip
(`tests/roundtrip/systemverilog_parses.py`) cannot see this, because it checks shape, not behavior.

### Defect 2: the response is combinational on the request

`s_axi_bvalid = awvalid && wvalid` and `s_axi_rvalid = rdata_valid` (a function of `arvalid` and the address)
(`gen_sv.cho` `sv_handshake`). A master that follows AXI4-Lite drops `*valid` after the handshake and waits for the
response; the response is then gone. Measured: 2 of 25 equal with such a master even with defect 1 removed. By the
AXI4-Lite rule as I recall it (a slave asserts BVALID/RVALID only after the request handshake), this is also a protocol
deviation; that reading is from the spec text, not measured here. Consequence for a board: a vendor AXI interconnect or
a soft-core bridge that registers its requests will not get responses.

### From reading the generator, not measured

* `WSTRB` is an input and is ignored; every write is a full-word write.
* An address in the block that is not a register is acknowledged `OKAY`; there is no `SLVERR`.
* The reset (`sv_reset_hdr`) and the write logic are two `always @(posedge clk)` blocks that assign the same `r_*`
  registers. Synthesis tools commonly refuse or warn on that; no synthesis tool was available here to say which.
* Kind `RC` is a write-clears register in the module, and the module never clears it on a read (`gen_sv.cho`
  `put_read_branch`); the reference model clears on read. The corpus has no `RC` register, so this is unexercised.
* `RO` write and `WO` read are silent in the module, refusals in the model (documented as a Trust-tier choice in the
  generated comment).

## Not claimed

Timing, synthesis and place-and-route are not covered: Yosys, nextpnr and Verilator were not available in this
session. Nothing here has run on a board.
