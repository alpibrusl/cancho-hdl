# cancho-hdl

**One file for the software/hardware boundary, checked and generated everywhere.**

A register map lives in the RTL, a spreadsheet and a datasheet; the C header,
the device tree and the driver repeat it by hand, and every copy drifts.
cancho-hdl declares the boundary once, in a `.chw` contract, refuses
contradictions with a structured diagnostic, and generates the copies: a C
header, Cancho bindings, a device-tree fragment, SystemVerilog register RTL and
CMSIS-SVD.

```
$ chwparse examples/refusal/parse-error.chw                  # the cancho parser
error[parse-error]: expected ':' after the register offset (before the access kind), found 'RW'.  parse-error.chw:2:26

$ checker.py examples/refusal/field-overlap.chw              # the reference checker
error[field-overlap]: field 'PARITY' bits [2..4] overlap with ENABLE bits [0..3] in register 'CTRL'.
help: start PARITY at bits [4..6], or shrink / move either field
exit 1
```

- **One source of truth.** Registers, fields, interrupts and DMA layouts are
  declared once. The generators are deterministic: same IR in, byte-identical
  artifacts out, so `git diff` on a generated file means something.
- **Refusals are data.** Every diagnostic has a stable kebab-case `code`, a
  tier (`Static`, `Tested`, `Runtime`, `Trust`, `Unknown`), a span and a
  remediation. Every rule has a refusal fixture in `examples/refusal/`.
- **Impact, not guesswork.** `diff` and `impact` say which generated artifacts
  a hardware-side change invalidates, field by field, by byte-comparing the
  generators' output.
- **A report that refuses to over-claim.** Counts come from what ran, a skipped
  roundtrip is never counted as passed, and vendor toolchains are listed as
  trust boundaries, never as verified.
- **Becoming pure cancho.** The tools were first written in Python. The product
  is being rewritten in cancho (`docs/cancho-port.md`), with Python kept only as
  a test oracle. The textual parser is the first piece: its JSON for
  `uart.chw` and `dma.chw` is byte-identical to the Python parser's.
- **Measured.** The Python reference passes 22 of 22 simulator scenarios, every
  one of 12 refusal fixtures is matched, and the generated C header runs the
  scenario corpus op-for-op against the reference model under gcc and clang.
  The cancho parser matched the Python parser on 2,765 of 2,767 mutated inputs
  (stdout, stderr and exit status); the two differences are known and listed
  in the port plan. Not claimed: a SystemVerilog behavioural roundtrip (needs
  Verilator or cocotb), timing, or working hardware. Those stay trust
  boundaries.

**[Project page](https://alpibrusl.github.io/cancho-hdl)** ·
[Contract design](docs/contract-design.md) ·
[Guarantees](docs/guarantees.md) ·
[Port to cancho](docs/cancho-port.md) ·
[Roadmap](docs/roadmap.md)

## Try it

The cancho parser, and its differential test against the Python one:

```sh
git clone https://github.com/alpibrusl/cancho-hdl.git && cd cancho-hdl
export CANCHO=<path-to-the-cancho-binary>
sh spike/run.sh          # 11 cancho tests, byte-identical JSON, 2,765/2,767 mutations
```

The reference implementation (Python, being replaced, run from the repository
root):

```sh
python3 scripts/run_gate.py                                    # schema, checker, simulator, generators, roundtrips
python3 tools/check/checker.py examples/uart-contract/uart.chw
python3 tools/generate/generate.py --target c-header examples/uart-contract/uart.chw > uart.h
python3 tools/diff/diff.py impact examples/uart-contract/uart.chw tests/diff/fixtures/uart_rebase.chw --pretty
python3 tools/report/report.py examples/uart-contract/uart.chw --output text
```

Targets: `c-header`, `systemverilog`, `devicetree`, `cancho-binding`, `svd`.

## What it is not

Not a hardware description language, not a synthesis or timing tool, and not a
driver. The contract declares the boundary; the behaviour behind it is whatever
the vendor IP wires up. See [`docs/guarantees.md`](docs/guarantees.md).

## More

[Diagnostics](spec/diagnostics/README.md) · [Generators](spec/generators/README.md) ·
[Contract schema](spec/contract-schema/README.md) · [Proposal](docs/proposal.md) ·
[Examples](examples/README.md)

EUPL-1.2.
