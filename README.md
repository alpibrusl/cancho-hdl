# cancho-hdl

**A typed hardware contract layer for the software/hardware boundary,
with the same refusal discipline Cancho applies to systems.**

Most embedded and accelerator codebases keep the register map, the C
header, the device tree, the SystemVerilog block and the driver each
in a separate file maintained by hand, with no tool that says
"these have drifted". cancho-hdl declares the boundary once, in a
single `.chw` file, and generates C headers, Cancho bindings, device
tree fragments, SystemVerilog register modules, and CMSIS-SVD XML from
it. Every change is checked, refused, or accepted with a structured
diagnostic an agent can read.

```
[CHECK]        uart.chw                              <- one source of truth
  register CTRL @ 0x00 : RW, reset 0x00000000       <- declares the boundary
    field ENABLE   : bits [0]
    field PARITY   : bits [1..2] enum { None, Even, Odd }
    field BAUD_DIV : bits [8..15]

[GENERATE]     --target c-header     -> gen/uart.h
[CHECK]        uart.chw              -> 0 refusals
[REPORT]       5 static checks run, 5 passed, 0 failed; vendor toolchain is a Trust boundary
```

- **One source of truth, generated everywhere.** C header, Cancho
  binding, device tree, SystemVerilog register RTL, CMSIS-SVD. The
  generators are deterministic: same IR in, byte-identical artifacts
  out. `git diff` on a generated file is meaningful.
- **Static checker, today.** A violation emits a `Diagnostic` with
  a stable `code` (kebab-case), a tier (`Static` / `Tested` /
  `Runtime` / `Trust` / `Unknown`), a span, a subject, a
  remediation hint. The catalog is in
  [`spec/diagnostics/README.md`](spec/diagnostics/README.md) §3 and
  the shape is locked at the first refusal against a real input.
  Every rule has at least one refusal fixture in
  `examples/refusal/`; the conformance suite asserts each.
- **Reference-model simulator.** A Python interpreter for the
  contract that drives both sides of the bus (CPU and device) with
  real access-kind enforcement — `RO` rejects CPU write, `WO`
  rejects CPU read, `W1C` clears, `RC` reads-then-clears, DMA
  `DEVICE`-owned fields refuse CPU writes. It is the **oracle**
  the roundtrip tests will compare the generated C header and
  SystemVerilog against. The schema's claims are falsifiable today.
- **Semantic diff and impact.** `cancho-hdl diff` and
  `cancho-hdl impact` tell an agent exactly which artifacts a
  hardware-side change invalidates, field by field. "Widen
  `BAUD_DIV` and update the driver correctly" has a structured
  answer, not a guess.
- **An evidence report that refuses to over-claim.**
  `cancho-hdl report` emits the §6 document: per-tier counts
  derived from what actually ran (rule groups that could not run
  are listed as not-run, skipped roundtrips are never counted as
  passed), a verbatim restatement of every row of
  `docs/guarantees.md` §2, and a validator that refuses the
  report itself with `evidence-over-claim` when an emitter
  claims more than it checked.
- **Tier taxonomy reused from Cancho Core.** *Statically checked /
  tested / runtime enforced / trusted boundary / unknown*. The
  toolchain never claims more than it has evidence for: timing
  closure, vendor toolchain output, and third-party IP are always
  `Trust`, never relabelled.

[Proposal](../Cancho-HW-Design-and-MVP-Roadmap.md) ·
[Contract design](docs/contract-design.md) ·
[Diagnostics](spec/diagnostics/README.md) ·
[Generators](spec/generators/README.md) ·
[Guarantees](docs/guarantees.md) ·
[Roadmap](docs/roadmap.md)

## Status

**Phase 1 of 4, code complete.** Schema, diagnostic format
(JSON + the human-readable form derived from it), guarantees
table, generator contracts, two reference peripherals in both
source forms (`uart-contract` + `textual/`, `simple-dma` +
`textual/`), 12 refusal cases (11 checker-side + `parse-error`,
each pinned by sidecars), the reference simulator (22/22
scenarios), the static checker (every refusal matched, zero
errors on the valid examples), the frozen textual `.chw` parser
(text twins parse to the identical IR as their JSON wire form),
the c-header generator (compiles clean under clang + gcc, smoke
binary returns the expected value), and the systemverilog
generator (structural check passes; real parse runs when
iverilog, slang, or yosys is on `$PATH`) are landed. Phase 2 is
code complete: `cancho-hdl diff` and `cancho-hdl impact` are
landed — the semantic-diff document and the per-target staleness
list, decided by byte-comparing generator output, with the
roadmap's seeded-change criterion now measured across all five
targets — the `devicetree`, `cancho-binding` and `svd`
generators are landed (a deterministic DTSI fragment, typed
`.cancho` accessor declarations, and XSD-validated CMSIS-SVD
XML with SVD-native `modifiedWriteValues`/`readAction`
semantics, all structurally checked and refusing instead of
degrading — the shared `size` refusal keeps the C and binding
artifacts from disagreeing silently), and `cancho-hdl report`
is landed: the §6 evidence document whose
`non_guarantees` restates every row of `docs/guarantees.md` §2
verbatim, whose counts are derived from what actually ran, and
which refuses itself with `evidence-over-claim` when a copy
claims more than it checked.

Not yet claimed: the behavioral roundtrip (drive the same
scenarios through the C accessors and the SV module, compare to
the reference model — needs Verilator or cocotb, flagged to
Phase 2/3) and that the toolchain produces working hardware
(trust boundary, never).

## What it does today

```sh
$ python3 scripts/verify_examples.py
== valid examples (must parse + pass schema) ==
  PASS  examples/uart-contract/uart.chw
  PASS  examples/simple-dma/dma.chw
  PASS  examples/textual/uart.chw
  PASS  examples/textual/dma.chw
== refusal examples ==
  bus-width-invalid.chw           SCHEMA-FAIL (64 is not one of [8, 16, 32])  expects: block-bus-width-invalid, schema-invalid
  dma-bad-align.chw               SCHEMA-PASS                expects: dma-align-unsatisfied
  dma-overlap.chw                 SCHEMA-PASS                expects: dma-overlap
  dma-owner-unknown.chw           SCHEMA-FAIL ('GPU' is not one of ['CPU', 'DEVICE'])  expects: dma-owner-unknown, schema-invalid
  enum-overflow.chw               SCHEMA-PASS                expects: field-enum-overflow
  field-out-of-bounds.chw         SCHEMA-FAIL (63 is greater than the maximum of 31)  expects: field-bounds-overflow, schema-invalid
  field-overlap.chw               SCHEMA-PASS                expects: field-overlap
  interrupt-unresolved.chw        SCHEMA-PASS                expects: interrupt-clear-unresolved, ...
  kind-unknown.chw                SCHEMA-FAIL ('WTF' is not one of ['RO', 'WO', 'RW', 'RC', 'W1C', 'W0C', ')  expects: register-kind-unknown, schema-invalid
  parse-error.chw                 PARSE-FAIL (parse-error)   expects: parse-error
  register-overlap.chw            SCHEMA-PASS                expects: register-offset-duplicate
  reset-overflow.chw              SCHEMA-PASS                expects: reset-overflow

$ python3 tools/check/checker.py examples/uart-contract/uart.chw
warning[field-constraint-ignored]: field 'BAUD_DIV' declares constraint 'nonzero when ENABLE == 1'; the Phase 0 checker does not parse constraint semantics (see docs/contract-design.md §5 question 3).
   --> examples/uart-contract/uart.chw
   = note: constraints are documented but not enforced until 0.2.0
$ echo $?
0

$ python3 tools/check/checker.py examples/refusal/field-overlap.chw
error[field-overlap]: field 'PARITY' bits [2..4] overlap with ENABLE bits [0..3] in register 'CTRL'.
   --> examples/refusal/field-overlap.chw
   = related[field-overlap]: field 'ENABLE' occupies bits [0..3] in register 'CTRL'.
help: start PARITY at bits [4..6] (just after ENABLE, bits [0..3]), or shrink / move either field — the toolchain cannot say which side the hardware semantics live on
$ echo $?
1

$ python3 tools/sim/run_scenarios.py
== running 5 scenarios ==
  PASS  uart/rw_basic
  PASS  uart/enum_field
  PASS  uart/access_kinds
  PASS  uart/interrupt_lifecycle
  PASS  uart/wo_w1c_semantics
== 5 passed, 0 failed ==
== running 6 scenarios ==
  PASS  dma/w1c_clear
  PASS  dma/cpu_owned
  PASS  dma/device_owned
  PASS  dma/rx_descriptor
  PASS  dma/irq_tx_complete
  PASS  dma/reset
== 6 passed, 0 failed ==
== runtime twin of schema-level refusals ==
  PASS  bus-width-invalid: schema caught, runtime not applicable
  PASS  dma-bad-align: schema caught, runtime not applicable
  PASS  dma-overlap: schema caught, runtime not applicable
  PASS  dma-owner-unknown: schema caught, runtime not applicable
  PASS  enum-overflow: schema caught, runtime not applicable
  PASS  field-out-of-bounds: schema caught, runtime not applicable
  PASS  field-overlap: schema caught, runtime not applicable
  PASS  interrupt-unresolved: schema caught, runtime not applicable
  PASS  kind-unknown: schema caught, runtime not applicable
  PASS  register-overlap: schema caught, runtime not applicable
  PASS  reset-overflow: schema caught, runtime not applicable
== 11 passed, 0 failed ==

$ python3 scripts/run_gate.py
== schema validation ==
== static checker conformance ==
== reference model + scenarios ==
== c-header roundtrip (clang + gcc + smoke) ==
== systemverilog roundtrip (structural + iverilog/slang/yosys if available) ==
== textual parser roundtrip ==
== diagnostic text formatter golden ==
== diff / impact golden (seeded Phase 2 criterion) ==
== evidence report golden (§6, non-guarantees, over-claim refusals) ==
== devicetree roundtrip (§4 structural + dtc when available) ==
== cancho-binding roundtrip (§3 palette + DEVICE no-setter) ==
== svd roundtrip (§6 XSD + access mapping + comment lane) ==
== GATE PASSED ==
```

The split is intentional. The schema catches the structural
violations itself (bus width, access kind, field bounds, DMA
owner). The static checker backstops the rest at compile time —
every schema-level rule has a Static-tier analogue, and the
conformance suite is the proof. The reference model backstops
the same rules at runtime, with the same code/subject contract.
The roundtrip suite tests the generators' outputs structurally
today (the C header compiles, the SV module decodes); the next
step is the behavioral roundtrip, which will drive the same
scenarios through the generated C header and the SystemVerilog
module and assert that both agree with the simulator.

## What a change means

`cancho-hdl diff` states what a contract change *is* — in the
IDs an agent can grep generated code by, not line numbers.
`cancho-hdl impact` states what it *costs*: for each generator
target, the artifact is regenerated for both contracts and
compared byte for byte, so `stale: true` is measured and
`stale: false` is proof the generator ran — while a generator
that has not landed reports `stale: null` ("not checked"),
never a fake "no change".

```sh
$ python3 tools/diff/diff.py diff examples/uart-contract/uart.chw examples/textual/uart.chw --pretty
{
  "schema": "cancho-hdl-diff",
  "version": "0.1.0",
  "base_id": "chw:UartRegs.register",
  "candidate_id": "chw:UartRegs.register",
  "added_registers": [],
  "removed_registers": [],
  "moved_registers": [],
  "widened_fields": [],
  "narrowed_fields": [],
  "repositioned_fields": [],
  "added_fields": [],
  "removed_fields": [],
  "changed_enum_values": [],
  "changed_interrupts": [],
  "added_interrupts": [],
  "removed_interrupts": [],
  "changed_dma_layouts": [],
  "changed_reset_values": [],
  "changed_block_properties": []
}
```

The all-empty diff above is the JSON wire file against the
frozen textual syntax of the **same contract** — two source
forms, zero semantic difference.

The seeded change from the roadmap (widen `BAUD_DIV` to 12
bits, rebase the register map) produces an answer per artifact:

```sh
$ python3 tools/diff/diff.py impact examples/uart-contract/uart.chw tests/diff/fixtures/uart_rebase.chw --pretty \
  | python3 -c "import json,sys; d=json.load(sys.stdin)['affected_artifacts']
for a in d:
    print('%-16s stale=%-5s %s' % (a['target'], a['stale'], a['reason']))"
c-header         stale=True  moved_registers=5; widened_fields=1
cancho-binding   stale=False no change (byte-identical output for both contracts)
devicetree       stale=True  moved_registers=5; widened_fields=1
systemverilog    stale=True  moved_registers=5; widened_fields=1
svd              stale=True  moved_registers=5; widened_fields=1
```

All five `stale` rows are measured — the departure point for the
svd row (once `stale: null`, "generator-unimplemented") is the
Phase 2 exit criterion's completion: no target claims "not
checked". The two polar rows are the tier discipline at work:
`cancho-binding` is declared NOT stale *with proof* (byte-
identical output for both contracts — it encodes names, widths,
and kinds, not offsets, so a rebase does not touch its bytes;
a rule-based staleness oracle would have flagged it wrongly),
while `devicetree` is declared stale because its generator ran
on both contracts and the bytes differ. The bytes do not lie.

## What it checked, and what it admits

```sh
$ python3 tools/report/report.py examples/uart-contract/uart.chw --output text
== cancho-hdl report: examples/uart-contract/uart.chw ==
static   : 27 checks run, 27 passed, 0 failed
tested   : 1 roundtrip(s) run, 1 passed, 0 failed (skipped: systemverilog)
runtime  : 1 check(s) performed, 1 passed, 0 failed
trust    : 1 boundary/boundaries — clang
unknown  : 2 item(s); 6 static check(s) not run — see the JSON for both lists
non_guarantees: 9 rows restated verbatim (docs/guarantees.md §2) — see the JSON
$ echo $?
0

$ python3 tools/report/report.py examples/refusal/field-overlap.chw > /dev/null --strict
$ echo $?
1
```

The counts are provenance, not decoration: the 6 not-run static
checks are the DMA rule family over a contract with no DMA
buffers (listed in `unknown.static_checks_not_run`, from the
checker's own instrumentation), and the skipped systemverilog
roundtrip is listed `outcome: "skipped"` — it counts nowhere as
passed, and under `--strict` it fails the tier.

## Why

The register map and the driver live in different files in
different languages maintained by different people. When a field
widens, the driver is wrong silently. When an interrupt linkage
breaks, the device tree is wrong silently. When a DMA buffer's
ownership flips, the binding is wrong silently. cancho-hdl makes
the silent failures loud and the loud failures structured.

The same shape Cancho Core applies to systems-level programming —
explicit contracts, machine-readable diagnostics, an evidence
report that states its non-guarantees — applied to the place
where AI agents already lose the most information today.

## What it is not

- **Not a hardware description language.** Stage B is conditional;
  the `hdl/` subtree is not created. The contract declares the
  boundary; the behavior behind it is whatever the user / vendor
  IP wires up.
- **Not a synthesis tool.** Timing, area, power, and vendor IP
  semantics are `Trust` boundaries, reported as such.
- **Not a driver.** The generators emit accessors; they do not
  encode behavior. A driver that uses a binding correctly is the
  user's job.
- **Not a new language.** The `.chw` files here are the JSON
  wire format; the frozen textual syntax
  (`spec/contract-schema/README.md` §10) parses to exactly that
  IR, and the parent proposal's rule held: it was frozen only
  after "the checker and generators have validated the model on
  two real peripherals." Generators read the IR, not the text.

## Try it

```sh
git clone https://github.com/alpibrusl/cancho-hdl
cd cancho-hdl

python3 scripts/run_gate.py                                            # schema + checker + simulator + c-header + systemverilog + parser roundtrip
python3 tools/check/checker.py examples/uart-contract/uart.chw
python3 tools/check/checker.py examples/textual/uart.chw               # the frozen textual syntax — same contract, same result
python3 tools/parse/parser.py examples/refusal/parse-error.chw         # parse error with a line:column span
python3 tools/check/checker.py examples/refusal/field-overlap.chw --output json
python3 tools/generate/generate.py --target c-header \
    examples/uart-contract/uart.chw > uart.h
clang -Wall -Wextra -Werror -std=c11 -c -x c uart.h -o uart.o
python3 tools/generate/generate.py --target systemverilog \
    examples/uart-contract/uart.chw > uart_regs.sv
python3 tools/generate/generate.py --target devicetree \
    examples/uart-contract/uart.chw > uart.dtsi              # DTSI fragment for the SoC board file
python3 tools/generate/generate.py --target cancho-binding \
    examples/uart-contract/uart.chw > uart.cancho            # typed driver-side accessors
python3 tools/generate/generate.py --target svd \
    examples/uart-contract/uart.chw > uart.svd               # CMSIS-SVD XML for ARM tooling
python3 tools/diff/diff.py diff examples/uart-contract/uart.chw examples/textual/uart.chw
python3 tools/diff/diff.py impact examples/uart-contract/uart.chw \
    tests/diff/fixtures/uart_rebase.chw --pretty          # seeded Phase 2 change: what breaks, what is stale
python3 tools/report/report.py examples/uart-contract/uart.chw --output text
python3 tools/sim/run_scenarios.py

$EDITOR docs/contract-design.md           # what the contract expresses
$EDITOR spec/diagnostics/README.md        # the diagnostic catalog
$EDITOR spec/generators/README.md         # per-target output contracts
```

## Docs

The repo's `docs/` is the narrative; the `spec/` is normative.
Start with [`docs/contract-design.md`](docs/contract-design.md) for
what the contract expresses, then
[`spec/contract-schema/README.md`](spec/contract-schema/README.md)
for the wire format, then
[`spec/diagnostics/README.md`](spec/diagnostics/README.md) for the
rule catalog, then
[`spec/generators/README.md`](spec/generators/README.md) for the
per-target contracts. [`docs/guarantees.md`](docs/guarantees.md)
states what is and is not claimed. [`docs/roadmap.md`](docs/roadmap.md)
is the Phase 0–4 schedule.

EUPL-1.2.