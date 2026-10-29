**Repository:** alpibrusl/cancho-quantum
**Title:** Two experiments on an FPGA: a shot sampler with a count histogram, and a timed pulse sequencer from `sched`

## Scope and honesty first

`qsim` on a CPU is far faster than any FPGA reachable here (a 27 MHz part behind a 115200 baud serial line); **this is not about
simulation speed**. It is about two things an FPGA does and a CPU does not: exact integer bookkeeping that can be compared bit for bit,
and deterministic timing. I have read this repository's README and file list only, not `src/measure.cho` or `src/state.cho`; the first
step below is reading how `sample` draws its numbers.

## What exists (cancho-hdl branch `hardware-test-tang-nano-20k`)

A Tang Nano 20K driven from cancho through the `Tty` capability, with the method already used for an image filter (5 modes x 3072 pixels,
0 different from a cancho reference), an 8192-byte RAM self-test (0 different) and a hardware deadman: a hardware design judged byte for
byte against the same computation written in cancho.

## Experiment 1: shot sampler and outcome histogram

A block-RAM histogram with 2^n bins (n up to about 12 fits easily) counts measurement outcomes. The simplest honest form: the host sends
the outcome stream `qsim` produced for a seed and the board returns the counts; the board's job is only the counting, exact and
comparable. The stronger form: the board draws the outcomes itself from a cumulative-probability table (fixed-point) with a seeded
generator, which needs `qsim`'s generator to be reproduced bit for bit, or the comparison to be statistical, not exact. Decide that
after reading `measure.cho`.

* Acceptance (simple form): counts equal `qsim`'s for the same shots. Acceptance (strong form): either byte-equal to `sample`, or a
  stated statistical test with its threshold, written down before running.
* It could be a further engine in the M3 gate (`check_determinism.py`), with the caveat that the gate's engines compute amplitudes
  and this one counts.

## Experiment 2: timed pulse sequencer

`sched` already gives each gate a start and a duration (`coher`, `wait`, `time1`, `time2`). A cancho tool would turn a schedule into a
stream of (time, pin, level) events; the board replays it from block RAM with a cycle-accurate counter (37 ns per tick at 27 MHz, finer
with the on-chip PLL, not measured) on its GPIO pins. A recorder on the board's own pins, or a logic analyser, measures the pin timing
against the schedule.

* Acceptance: for three circuits, every pin edge within one tick of the schedule, measured, with the measurement method stated.
* Limits: the board has no DAC or ADC; this is digital pulses only, a model of a control sequencer, not a qubit controller.

## Not proposed

A fixed-point state-vector engine: about 14 qubits fit in the block RAMs and it would be a useful accuracy study (fixed-point error is
around 1e-4 against the 1e-12 gate) but it is not faster than the CPU, so I would not claim a result from it.

## Depends on

alpibrusl/cancho-hdl: device-written registers in generated blocks (the histogram counts and the sequencer status are device-written).
