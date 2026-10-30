# The Sipeed Tang Nano 20K (Gowin GW2AR-18): what exists, what was measured, what was not

Written 2026-10-29. Everything under `boards/tang-nano-20k/`. **Nothing here has run on a board**: no board was attached to the
session that wrote it, and the place-and-route and bitstream steps could not be run there (see "Not done").

## What exists

| File | What it is |
|---|---|
| `boards/tang-nano-20k/leds.chw` | The contract: `LEDS` (RW, bits 5:0 are the six on-board LEDs) and `SCRATCH` (RW, 32 bits), base `0x40000000`. Written in the contract format; `chw check` accepts it. |
| `rtl/uart_axil_bridge.v`, `uart_rx.v`, `uart_tx.v`, `top.v` | **Hand-written board glue**, not generated and not part of the product: an 8N1 UART at 27 MHz / 234 clocks per bit (115200 baud, 0.15 % off), a byte protocol that turns a read or a write into one AXI4-Lite transaction on the module `chw generate --target systemverilog` writes, and the top level (power-on reset, LEDs active low). |
| `tang_nano_20k.cst` | Pin constraints (kept free of comments in case a constraint parser rejects them; not tested). **The pin numbers (clock 4, UART 69 and 70, LEDs 15 to 20) are from memory of Sipeed's published schematic and examples, not checked against it**; check each before flashing. |
| `tb/top_tb.v` | A bench playing the host on the serial line, at the real bit rate. |
| `check.sh` | The gate lane (8n): generate, simulate with iverilog, synthesise with Yosys. |
| `build.sh` | The whole open-source flow, step by step; a step whose tool is missing is reported and the script exits 2. |

The byte protocol (big-endian): host sends `W a3 a2 a1 a0 d3 d2 d1 d0` and gets one byte back, or sends `R a3 a2 a1 a0` and gets
`resp d3 d2 d1 d0`. `resp` is the AXI response: `00` OKAY, `02` SLVERR (no register at the address, a write to a read-only
register, a read of a write-only one). Any other command byte is ignored. Block commands (`B`, `I`, `E`, `D`: many words in one frame) are described at the top of `rtl/uart_axil_bridge.v` and measured in `docs/fpga-experiments.md`.

## Measured (this session, Icarus Verilog 12 and Yosys 0.33 from Ubuntu 24.04)

* The bench passes 11 of 11 checks through the whole path, UART bit by bit: a write to `LEDS` answers OKAY and sets the LED pins
  (value `0b000101` pulls pins 0 and 2 low); the read-back gives 5; `SCRATCH` reads back `0xdeadbeef` and leaves the LEDs alone; a
  read at an address with no register and a write below the base each answer SLVERR and change nothing; all six LEDs on and off.
  This is a simulation of the RTL at its clock and baud rate, with the bench's own idea of a UART; it is not a measurement of the
  board's USB-serial chip.
* `yosys synth_gowin -top top` finishes with no warning and no error: 1,281 cells (365 `DFFRE`, 114 `ALU`, 239 `LUT1`, 140 `LUT4`,
  92 `LUT2`, 23 `LUT3`, 158 `MUX2_LUT5`, 72 `MUX2_LUT6`, 34 `MUX2_LUT7`, 1 `MUX2_LUT8`, 2 `IBUF`, 7 `OBUF`). That is a count of mapped
  cells, not a fit: the part's capacity was not checked by a place-and-route tool.
* The first behavioral simulation of the register block (docs/sv-behavioral.md) found that no register was reachable at a non-zero
  base; the module the board design uses is the fixed one, and this design's base is `0x40000000`, so it is the case that failed.

## Not done, and why

* **Place and route, bitstream, flashing, and everything that follows from them**: the timing at 27 MHz, whether the design fits and
  routes, whether the pins are right, whether the LEDs light. The Ubuntu 24.04 package `nextpnr-gowin` (0.6) rejects the board's
  device (`ERROR: Invalid device GW2AR-LV18QN88C8/I7`, measured); the flow needs `nextpnr-himbaechel` with the Gowin micro-architecture
  and `apycula` (`gowin_pack`), which are not in the distribution. Building nextpnr from source in the session that wrote this was
  refused by the session's permission classifier (it is code fetched from the internet, and nothing had authorised running it), so it
  was not tried; the fetched source is not used.
* Nothing about the board's USB-serial chip: which device node it appears as, its baud-rate limits, whether it forwards the UART
  pins as assumed.

## To run it on a machine with the board

1. Install the open-source flow: Yosys, nextpnr built with `-DARCH=himbaechel -DHIMBAECHEL_UARCH=gowin
   -DHIMBAECHEL_GOWIN_DEVICES=GW2A-18C`, `pip install apycula`, and openFPGALoader (the YosysHQ OSS CAD Suite ships all of them).
2. Build `chw` (`CANCHO=<compiler of .cancho-rev> sh scripts/build.sh chw`), then from the repository root
   `CHW=./chw sh boards/tang-nano-20k/build.sh --flash` (`build.sh [OUTDIR] [--flash]`; the board attached, `top.fs` loaded to SRAM).
   Read the nextpnr report: the achieved clock must be at least 27 MHz.
3. Check each pin of `tang_nano_20k.cst` against the schematic first.
4. From a shell, once the board's serial port appears (the on-board BL616 usually shows two; the second is the UART; unverified here):
   ```sh
   stty -F /dev/ttyACM1 115200 raw -echo
   printf 'W\x40\x00\x00\x00\x00\x00\x00\x05' > /dev/ttyACM1      # LEDS = 0b000101
   printf 'R\x40\x00\x00\x00' > /dev/ttyACM1; head -c 5 /dev/ttyACM1 | od -An -tx1   # 00 00 00 00 05
   ```
   LEDs 0 and 2 should light. If nothing answers, the pin numbers or the port are the first suspects.

## What would make this a claim

A line in `docs/guarantees.md` for the board only when someone has run steps 1 to 4 and written down what the LEDs did and what
nextpnr reported, with the tool versions. Until then the guarantee is the simulation and the synthesis above, no more.
