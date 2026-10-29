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

* **BRAM test** (measured). `rtl/mem_test.v` is an 8192-byte RAM with a built-in self-test (five patterns) behind the UART;
  `host/memtest.cho` runs it from cancho: the board's self-test reports 0 differing bytes in all five patterns; the host reads 64
  addresses back after the self-test fill (0 different, so the fill really wrote); the host writes 2048 pseudo-random bytes at
  distinct addresses and reads them all back (0 different). 4 block RAMs, 425 LUT4, 148 MHz. Yosys prints 6 warnings from its
  block-RAM mapping (unused write-data bits set to undefined); the build still completes and the test passes, but the warning gate of
  `check.sh` would refuse this design as it stands. The self-test judges itself; only the host steps are independent evidence.
* **The laptop webcam through the filter** (measured). ffmpeg grabs the LGE FHD camera (`/dev/video0`), scales to 96x72 greyscale,
  and `host/camfilter.cho` (cancho; reads frames on standard input, streams them through the board, writes frames on standard
  output) does the rest. 4 real frames x 5 modes = 27,648 pixels per mode, compared byte for byte with an independent Python
  implementation of the same definition: **0 different in every mode**. The camera is not a cancho capability (the `Tty` design says
  a camera `ioctl` is an open question), so ffmpeg is the helper here, as the robot's camera stack would be.
  Speed, not tuned: 2.6 s per 96x72 frame, because `camfilter` writes 16 bytes per poll; the serial line itself would allow about
  0.6 s per frame. No camera frame is kept in the repository.

* **Line rate of the camera path** (measured). `camfilter` now keeps at most 48 bytes in flight, using the board's one answer per byte
  as credit: 0.87 s per 96x72 frame (was 2.6 s), output byte-identical to the verified one. The limit is the USB serial adapter: with
  96 or more bytes in flight it silently loses data (`tests/hardware/adapter_window.py`: 64 and below clean, 96 and 128 lose most of a
  3000-byte stream). The image design also got a 256-byte result FIFO, because the host sends back to back and the transmitter
  restarts a few clocks late after each byte (a 1600-byte back-to-back stream in simulation: 0 lost). A live pipe, ffmpeg at 1 frame/s
  into `camfilter` into a reader: 6 frames out at the camera's rate (first at 3.6 s, camera start-up included).
* **E4, the deadman** (measured, on the board). `deadman.chw` (CTRL.ENABLE, TIMEOUT_MS, KICK.SEQ; `chw check` clean) and the
  hand-written `rtl/deadman.v` behind it: armed, a change of KICK.SEQ restarts a millisecond counter; when it reaches TIMEOUT_MS the
  trip latches and `torque_ok` drops (LED 0 lit while ok, LED 1 while tripped); only ENABLE=0 clears it; TIMEOUT_MS=0 never trips.
  `host/deadman.cho` checks from cancho, against the board's own clock: disarmed at start; armed reads ok; 24 kicks 50 ms apart,
  24 of 24 polls ok; after the last kick the trip is first seen **197 to 210 ms** later (8 runs, 200 ms timeout; the clock starts a few
  ms before the host sees the acknowledgement, so a value just under 200 is expected); a kick after the trip changes nothing;
  ENABLE 0 then 1 re-arms; a 500 ms silence with TIMEOUT_MS=0 stays ok. 700 LUT4, 152 MHz, no Yosys warning.
  Update (cancho-hdl#21): the trip is now read through a contract register, `STATUS` (RO, volatile, 0x0C), because the generator gives
  device-written registers an input (`reg_status_in`); the `T` command of the first version is gone from the bridge, and the board test
  passes the same way (trip seen 204 ms after the last kick, 3 runs). Limits, stated: the "output" is an LED, nothing has been connected
  to a servo or a scope; the timing figure is the host's view through a USB serial link, good to a few milliseconds, not a
  measurement of the hardware's accuracy.

* **The lab design: analyzer, sequencer, histogram** (measured, on the board; `lab/lab.chw`, `rtl/lab.v`, `host/labio.cho`,
  `host/lab_test.cho`; 3515 LUT4, 8 block RAMs, 98 MHz; `check.sh` simulates it, 12 checks). Registers read from the instruments
  go through the new device-written inputs (cancho-hdl#21).
  1. Histogram (4096 bins x 16 bits): 2000 pseudo-random shots over 16 outcomes, every bin equal to the host's own count, total 2000.
     The same engine counted `qsim sample` output for two circuits (GHZ 3 qubits, 1000 shots; 5 qubits in uniform superposition, 4000
     shots): all bins equal to qsim's counts. **This found a real bug**: the first version never cleared bin 0 (the clear loop's write
     enable lagged its address by one clock), 981 counts left over after a clear; the simulation had not caught it because bin 0 was
     never non-zero before a clear. The simulation now checks it and fails on the old RTL.
  2. Sequencer watched by the analyzer on the same 27 MHz clock: four events programmed 135,000, 27,000 and 13,500,000 ticks apart;
     recorded spacing differs from programmed by **0 ticks** (all three). Same clock, so this shows the two instruments agree, not
     that either is right against an outside reference.
  3. Analyzer on the UART line: 87 edges recorded; the one-bit interval is **234.30 ticks** (115200 baud would be 234.375, so the
     adapter runs about 0.03 % fast); six bytes the host sent 50 ms apart (host sleep of 50 ms) are stamped 1,351,772 to 1,358,363
     ticks apart, that is 50.07 to 50.31 ms by the FPGA's clock.

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
| E4 | `deadman.chw`: `TIMEOUT_MS`, `KICK`, an output; test in simulation, then on the board: kick stops, output drops within the declared time | E2 | **done**, LED as the output, no scope (see results) |
| E5 | Feetech passthrough with a recorder: a second UART at 1 Mbaud between a servo adapter and the bridge; first with a loopback, then a real servo, read-only (ping) | servo + adapter, an operator present | |
| E6 | The limit gate in front of goal-position writes; only after E5 has run read-only | E4, E5, the e-stop | |

Rules carried over from the robot repo: read before write, an operator at the e-stop for anything that moves.

## What this does not claim

Nothing here has moved a servo. The designs are in SRAM, so a power cycle erases them. The UART bridge is hand-written and not
part of the product. Reset on the board is emulated by writing reset values back. A guarantee for the board needs a line in
`docs/guarantees.md`, written only after the experiment behind it has run.
