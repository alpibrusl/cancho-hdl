**Repository:** alpibrusl/cancho-hdl
**Title:** A generated register block has no input for a register the device writes

## Problem

`chw generate --target systemverilog` writes a register block whose only outputs are the stored values of the registers
(`reg_<name>_out`). There is no input port for a register that the device, not the CPU, changes (`RO` status, `W1C` flags, counters,
a FIFO level). `docs/sv-behavioral.md` already states the consequence for the simulation roundtrip: device-side operations have no port
on the module, so a register the device wrote is "tainted" and its reads are not compared.

On the Tang Nano 20K this showed up four times in one day. In each design the information that a real peripheral would put in a status
register had to be carried outside the contract, by hand-written glue:

* `boards/tang-nano-20k/rtl/deadman.v`: the trip flag. The host reads it through a new `T` command added to the hand-written UART
  bridge, because reading a `STATUS` register of the generated block returns only what the CPU stored (measured on the board: a read of
  an `RO` register of `uart.chw` returns 0 and cannot be anything else).
* The image filter's row counter and the RAM self-test's state: shown on LEDs, not readable through any contract.

So the contract describes the CPU's view of the block and the design does something else beside it. That is the drift the project exists
to remove.

## Proposal (to discuss, not decided)

For each register the contract marks device-written (`volatile`, `RO`, `W1C`, or a new explicit `driven_by: device`), the generated module
gets an input `reg_<name>_in` (and, for `W1C`/`RC`, a pulse output when the CPU clears bits), and the register's read value is the input
(for `RO`) or the stored value with the device's set pulses OR-ed in (`W1C`). The reference model already has `D`, `Df` operations for
exactly this; the generator would match what the model does.

## Open questions

* Is the stored value or the input what a read returns when both exist (a counter the CPU can also load)?
* Does the C header need to change (it should not: it describes the CPU's view)?
* The behavioral roundtrip would stop tainting registers; its device ops `D`/`Df` become driveable in the bench.

## Acceptance

* A contract with an `RO` status register and a `W1C` flag generates a module with the inputs, and `iverilog` reads it.
* The behavioral roundtrip drives the model's `D`/`Df` ops into the module and compares the following reads (today skipped as `tainted`).
* The deadman design on the board reads its trip flag through a contract register, and the `T` command can be removed from the bridge.

Evidence: branch `hardware-test-tang-nano-20k`, `docs/fpga-experiments.md` (E4 and the limits paragraph).
