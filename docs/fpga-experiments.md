# What the FPGA is for, here: experiments on the Tang Nano 20K, in cancho first

Written 2026-10-29 on branch `hardware-test-tang-nano-20k`. What is measured is marked **measured**; everything else is a plan.

## What is on the table

* **The board** (measured): a Tang Nano 20K, Gowin GW2AR-18, attached over USB as a Sipeed "USB Debugger" (FT2232, `0403:6010`).
  Interface 0 is JTAG (`/dev/ttyUSB0`, programming only), interface 1 is the UART (`/dev/ttyUSB1`).
  The part has about 20k LUT4, 15.5k flip-flops, 46 block RAMs; the two designs here use under 2 % of it and close timing at
  about 175 to 185 MHz against the 27 MHz clock.
* **The flow** (measured): `chw generate --target systemverilog` writes the register block from a `.chw` contract; the
  hand-written UART/AXI4-Lite bridge in `rtl/` puts it behind a serial port; Yosys, nextpnr-himbaechel and `gowin_pack`
  (the OSS CAD Suite, `/home/alpibru/oss-cad`) build `top.fs`; `openFPGALoader -b tangnano20k` loads it to SRAM.
  Loading needs raw USB access (`sudo`, or a udev rule not yet written).
* **Both sides of the contract, on the real chip** (measured): `tests/hardware/board_replay.py` replays the behavioral
  corpus on the board and gets 25 of 25 equal to the reference model (resets emulated, reported).
* **The host side in native cancho** (measured): `boards/tang-nano-20k/host/probe.cho` opens `/dev/ttyUSB1` through the
  `Tty` capability, configures 115200 8N1, reads `CTRL` over the bridge and prints `00 00 00 00 00`.
  `cancho authority` says it performs `tty_open("/dev")`, `tty_read`, `tty_write`, `poll`, `io_write`, `heap` and
  "never touches ... foreign code". No `extern fn`, no Python.

## Results since the first write-up (2026-10-29, same day)

* **The compiler written in cancho** (measured). cancho at `471b8e93` has `scripts/build-standalone.sh`: the Rust `cancho` builds the
  command line written in cancho (stage 1), which builds itself (stage 2), which builds itself again (stage 3); stage 2 and stage 3
  are byte-identical (sha256 `ce39e42c...`). That binary (`--version`: `cancho 0.0.0 (rev 471b8e93...)`, 3.1 MB) then ran
  `host/probe.cho` against the board, and built `chw` from `scripts/build.sh` whose `generate` output is byte-identical to the older
  `chw` for the two contracts and two targets compared (`leds.chw` and `uart.chw`; SystemVerilog and C header). The repository's
  `.cancho-rev` still pins `7e4088b`; nothing here moved it.
* **An image filter on the board** (measured). `rtl/img_stream.v` is a streaming 3x3 filter (pass, invert, threshold, Sobel, box
  blur) behind the UART; `host/imgtest.cho` sends a 64x48 greyscale image in each mode, reads the answers while writing, and compares
  every byte with the same filter written in cancho: **5 modes x 3072 pixels, 0 different**. Whole run (compile included) 6.5 s. The
  design uses 809 LUT4, 238 flip-flops and 2 block RAMs and closes timing at 78 MHz against 27 MHz. The contact sheet
  (original, pass, invert, threshold, Sobel, blur) is `docs/img/tang-nano-20k-image-filter.png`. The Sobel and blur windows end at the
  current pixel, so those two outputs are the image shifted by one pixel down and right, and zero in the first two rows and columns;
  that is the stated definition, not a bug. This is a hand-written design, outside the `.chw` contract flow; the contract flow only
  covers register blocks.
  Not measured: any speed advantage. At 115200 baud the serial line is the limit (about 11.5 KB/s each way); a 64x48 image takes 0.27 s
  per direction, and the filter itself keeps up with the line.

## Where it meets cancho-robot

cancho-robot exists to answer one question: can the compiler prove the *only* thing able to move the arms is the safety core.
The compiler can prove it about the controller's code. It cannot prove it about the computer that code runs on, the USB-serial
adapter, or a second process on the Pi. An FPGA between the controller and the servo bus moves part of the claim into
hardware the contract describes:

1. **Hardware deadman and limit gate (best fit).** The FPGA owns the only wire to the Feetech bus. Registers, declared in a
   `.chw`: `TIMEOUT_MS`, `KICK`, `TORQUE_ENABLE`, per-joint `LIMIT_MIN`/`LIMIT_MAX`, `SPEED_MAX`. If the controller stops kicking,
   the gate drops torque. A goal-position write outside the limits never reaches the bus. The same contract gives cancho a
   binding (`gen_binding`) and the C header and device tree for free, and `chw diff`/`impact` say what a limit change invalidates.
2. **Bus recorder.** Timestamped capture of every packet in both directions at the FPGA's clock, a cycle-accurate ground truth for the
   0.33 ms median servo latency that lex-robot measured in software, and for what the controller really sent.
3. **Deterministic sync write / two-arm fan-out.** One command from the controller, both arms updated on the same clock edge.
4. **Offloaded checks** (kinematics bound, collision capsule test in fixed point) are possible but the weakest fit: the
   safety core is small, and the gate in (1) is what turns a software claim into a hardware one.

## Experiments, in order

| # | What | Needs | Status |
|---|---|---|---|
| E1 | cancho talks to the board through `Tty` | board | **done** (`host/probe.cho`) |
| E2 | A cancho CLI `fpga` (`r ADDR`, `w ADDR DATA`, `selftest`) and the corpus replay in cancho, so Python is gone from the loop | E1 | next |
| E3 | Round-trip latency and throughput of the bridge from cancho, 1000 transactions; find the baud limit (115200 up to 3 Mbaud on the FT2232) | E2 | |
| E4 | `deadman.chw`: `TIMEOUT_MS`, `KICK`, an output pin; test in simulation, then on the board with a scope or LED: kick stops, output drops within the declared time | E2 | |
| E5 | Feetech passthrough with a recorder: a second UART at 1 Mbaud between a servo adapter and the bridge; first with a loopback, then a real servo, read-only (ping) | servo + adapter, an operator present | |
| E6 | The limit gate in front of goal-position writes; only after E5 has run read-only | E4, E5, the e-stop | |

Rules carried over from the robot repo: read before write, an operator at the e-stop for anything that moves.

## What this does not claim

Nothing here has moved a servo. The designs are in SRAM, so a power cycle erases them. The UART bridge is hand-written and not
part of the product. Reset on the board is emulated by writing reset values back. A guarantee for the board needs a line in
`docs/guarantees.md`, written only after the experiment behind it has run.
