# The SystemVerilog behavioral roundtrip

Status: **delivered for the bus operations**, measured with Icarus Verilog (`iverilog -g2012`); the open item of
`docs/roadmap.md` is narrowed, not closed (see "Not claimed"). Written 2026-10-29; the first measurement (earlier the same
day) is kept below as "What it found", with its numbers corrected where the harness grew.

## What is run

`tests/behavioral/sv_behavior.py` generates the module with the product (`chw generate FILE --target systemverilog`), simulates
it under `tests/behavioral/sv_device_tb.sv`, and compares the bus-level trace with the reference model
(`oracle/legacy/tools/sim/reference_model.py`) over `tests/behavioral/scenarios.json`. Python is the oracle only: it never decides
anything the product emits. It runs in the gate (`scripts/gate_cancho.sh`, lane 8m) with two masters:

* `hold`: keeps `awvalid`/`wvalid`/`arvalid` up until the response arrives;
* `strict`: follows AXI4-Lite: a valid is held until its ready, then dropped, and a response counts only on a clock after the
  request was accepted.

Of the corpus's 11 scenarios (64 ops), 29 are compared: the bus operations `R`, `Rf`, `W`, `Wf`, `RESET`. 32 have no port on the
module (device-side writes, DMA, interrupts), 2 read a register the device wrote (the module cannot be given the device's value),
1 is a refusal the host makes before it touches the bus (a value that does not fit a field). An op the model refuses for the access
kind (a write to a read-only register, a read of a write-only one) is driven and the module must answer SLVERR. Eighteen directed
bus commands that the corpus does not make are added per run: a write and a read at an address with no register (inside the block, and
below its base) answer SLVERR and change nothing, and a write with byte strobes changes only the bytes strobed. 29 + 18 = 47 comparisons per
master. The module decodes the full bus address, base included.

The harness can fail: against the generator as it was before the fix it reports 19 of 47 equal with the holding master and 4 of 47
with the strict one.

## What it found, and what was done

Measured on the first run, with the generator as written until 2026-10-28 (`uart.chw`, `base_address 0x40000000`):

1. **No register was reachable when the block base was not 0.** The module compared `s_axi_awaddr == ADDR_<REG>` (the register's
   *offset*) and also required `s_axi_awaddr >= BASE_ADDR` before any register decode. No address satisfied both: writes were
   acknowledged and changed nothing, reads never answered. The Python generator had the same defect, so the cancho port had
   reproduced it faithfully. The structural roundtrip could not see it, because it checks shape, not behavior.
2. **The response was combinational on the request** (`bvalid = awvalid && wvalid`, `rvalid` a function of `arvalid`). A master that
   drops its valids after the handshake gets no response. Measured: 4 of 47 with the strict master. By the AXI4-Lite rule as I
   recall it (a slave asserts BVALID/RVALID only after the request handshake) this is also a protocol deviation; that reading is from
   the spec text, not measured here.
3. Found by reading, then fixed in the same change: `WSTRB` was ignored; there was no `SLVERR`; the reset and the write logic were two
   `always @(posedge clk)` blocks assigning the same registers (a second driver, which synthesis tools commonly refuse); a held write
   was applied on every clock it was held.

Fixed in one commit in both generators (`oracle/legacy/gen/systemverilog/systemverilog.py` and `src/gen_sv.cho`, the same bytes; the
Python line count is unchanged, so `oracle/legacy/CEILING` is too):

* a register is decoded at `BASE_ADDR + ADDR_<REG>`;
* a request is accepted on one clock (`awready = wready = awvalid && wvalid && !bvalid_r`, `arready = arvalid && !rvalid_r`) and
  answered on the next from registers, held until `bready`/`rready`;
* the reset, the handshake and every register's write are in one clocked block, so each register has one driver;
* `WSTRB` selects the bytes written (`wmask`); W1C, W0C, W1S and W0S act on the strobed bits only;
* an address with no writable register answers SLVERR to a write, one with no readable register answers SLVERR to a read; so does a
  write to a read-only register and a read of a write-only one (the module used to drop the first silently and answer OKAY to the
  second).

After: 47 of 47 equal with both masters, on `uart.chw` and `dma.chw`. The generator's differential against the Python tool is byte
for byte on the fixtures and on the 55,258 mutants (0 unexplained differences), and the mutation table of
`tests/mutation/run_gen_sv.py` has a break for each decision above.

## Not claimed

* Device side: a register the device writes (`D`, `Df`), DMA buffers and interrupts have no port on the module, so their behavior is
  not simulated; the reference model's `RC` clears on read, the module's does not, and no corpus scenario has an `RC` register.
* Timing, synthesis and place-and-route: Yosys, nextpnr and Verilator were not used. Nothing here has run on a board.
* AXI4-Lite conformance beyond the two masters above; the strict master is this repository's reading of the rule, not a protocol
  checker.
* Icarus accepts constructs other tools refuse; `generate`/`genvar`, `+:` part selects and `always @(*)` are plain Verilog-2005, but
  that is not a measurement of any other tool.
