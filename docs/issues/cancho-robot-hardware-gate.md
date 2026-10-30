**Repository:** alpibrusl/cancho-robot
**Title:** Can the hardware enforce what the compiler proves? A deadman and limit gate in an FPGA between the controller and the bus

## The gap

The question of this repository is whether the compiler can prove the safety core is the only thing able to move the arms. The proof
stops at the controller's code: it says nothing about the machine the code runs on, the USB-serial adapter, or another process on the Pi
(the README's first defect list). A device that owns the only wire to the servo bus can keep a rule even when the software does not.

## What exists (measured, cancho-hdl branch `hardware-test-tang-nano-20k`; nothing has touched a servo)

* A Tang Nano 20K (Gowin GW2AR-18) driven entirely from cancho through the `Tty` capability (`cancho authority`: `tty_open("/dev")`,
  `tty_read`, `tty_write`, `poll`, no foreign call), compiler `471b8e93` built by cancho.
* A **hardware deadman**, described by a checked contract (`deadman.chw`: `CTRL.ENABLE`, `TIMEOUT_MS`, `KICK.SEQ`) and a small
  hand-written block: armed, a change of `KICK.SEQ` restarts a millisecond counter; at `TIMEOUT_MS` a trip latches and `torque_ok`
  drops; only `ENABLE=0` clears it; `TIMEOUT_MS=0` never trips. Tested from cancho: 24 kicks 50 ms apart kept it alive; with a 200 ms
  timeout the trip was first seen 197 to 210 ms after the last kick (8 runs; the host's view through USB serial, good to a few ms); a
  kick after the trip changed nothing; re-arming worked. 700 LUT4, 152 MHz, no synthesis warning. The "output" was an LED.

## Proposal, in order, each step stated before it is run

1. **Bus recorder** (no servo needed first): timestamped capture of every byte of both directions at the FPGA clock, tested with a
   loopback at 1 Mbaud. It gives a ground truth for the 0.33 ms median servo latency that was measured in software, and for what the
   controller really sent.
2. **Read-only on a real servo** (ping, read position), through the FPGA as a passthrough, compared with the Python reference on the
   same bus. Needs an operator and the adapter; nothing is written.
3. **Limit gate**: goal-position writes outside per-joint `LIMIT_MIN`/`LIMIT_MAX` (in the contract) never reach the bus; the deadman
   drops torque if the controller stops kicking. Only after 1 and 2, with an operator at the e-stop, as the epic requires.

## What this changes in the claim, and what it does not

If it works, "only the safety core can move the arm" gets a second, independent enforcement: the contract's limits are checked in
hardware, and `chw diff`/`impact` say what a limit change invalidates. It does **not** make the FPGA design verified: the glue is
hand-written and its guarantee is its tests. The contract flow covers the register block only.

## Open questions

* The Feetech bus is half-duplex at 1 Mbaud on one wire: direction control in the FPGA, with the adapter's timing, is unmeasured.
* Where does the FPGA sit: between the Pi and the adapter (USB), or replace the adapter (needs a level-shifted TTL pin pair on a board
  with the right pins)? The Tang Nano 20K's USB-serial runs at 115200 here; the bus needs 1 Mbaud on a GPIO pin, not that port.
* Failure mode when the FPGA is unprogrammed or crashes: the bus must go safe, not open.

## Acceptance

Step 1 passes in loopback with recorded timestamps compared against a signal generator; step 2 matches the reference on the same
reads; step 3 refuses an out-of-limit write on the bus (seen in the recorder) and the deadman drops torque within the declared time.
