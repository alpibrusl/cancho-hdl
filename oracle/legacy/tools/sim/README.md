# oracle/legacy/tools/sim/

> **Status: Phase 0.** A reference-model simulator that consumes
> the contract IR (see [`../../spec/contract-schema/README.md`](../../spec/contract-schema/README.md))
> and behaves as a memory-mapped peripheral would. It enforces
> the contract's access semantics at runtime (tier `Runtime`)
> and serves as the oracle against which Phase 1 generators
> are roundtrip-tested.

---

## What this is

The reference model is a **behavioural oracle**, not a hardware
description. Given the same `.chw` and the same bus operation
sequence, the model produces the same register, interrupt, and
DMA state a correctly-designed peripheral would. Anything else
is refused with a diagnostic code from
[`../../spec/diagnostics/README.md`](../../spec/diagnostics/README.md).

The model is **Python** at Phase 0 so it is easy to read and
modify. Phase 1 may add a Rust implementation under the same
crate layout for the roundtrip suite; the contract is the
Python API here, not the language.

---

## What this is not

- **Not RTL.** No clock, no reset sequencing, no combinational
  paths. The model is one step ahead of the bus at all times;
  it does not model propagation delay or metastability.
- **Not a substitute for vendor simulation.** Tier `Trust` for
  vendor toolchains remains — see
  [`../../docs/guarantees.md`](../../docs/guarantees.md).
- **Not a verifier of generated RTL beyond the contract.** It
  validates that a generated C header / SystemVerilog module
  produces the same register state under the same operations.
  It does not validate timing, area, or power.

---

## Tier of every model behaviour

| Behaviour | Tier | Why |
|---|---|---|
| Field bit-range decoding | Static | enforced by schema |
| Access kind enforcement (`RO` rejects write, `WO` rejects read) | Runtime | enforced by the model; reported as `runtime-access-kind-violation` |
| `W1C` / `W0C` / `W1S` / `W0S` clear/set semantics | Runtime | enforced by the model |
| `RC` read-to-clear | Runtime | enforced by the model |
| DMA `DEVICE`-owned field write | Runtime | enforced by the model; reported as `runtime-dma-owner-violation` |
| DMA `CPU`-owned field read | Runtime | enforced by the model |
| Interrupt source/status/enable/clear linkage | Runtime | enforced by the model |
| Reset value application | Runtime | applied at `model.reset()` |
| Vendor synthesis / timing | Trust | out of scope |

---

## The API

```python
from reference_model import ReferenceModel, AccessError

model = ReferenceModel.from_chw_file("examples/uart-contract/uart.chw")

# Register access
value = model.read("CTRL")                       # full register
bit = model.read_field("CTRL", "ENABLE")        # one field
model.write("CTRL", 0x00000001)
model.write_field("CTRL", "BAUD_DIV", 0x80)

# Access kind
try:
    model.read("ICR")                           # ICR is WO
except AccessError as e:
    assert e.code == "runtime-access-kind-violation"

# Interrupts
model.write_field("STATUS", "RX_READY", 1)
assert model.interrupt_pending("rx_ready")
model.interrupt_clear("rx_ready")
assert not model.interrupt_pending("rx_ready")

# DMA
model.dma_write("TxDescriptor", "next_ptr", 0x1000)         # CPU-owned, OK
try:
    model.dma_write("TxDescriptor", "done_flag", 1)         # DEVICE-owned
except AccessError as e:
    assert e.code == "runtime-dma-owner-violation"

# Reset
model.reset()
```

---

## Phase 0 acceptance runs

The scenarios under `scenarios/` are the Phase 0 acceptance
that the model is correct against the contract:

| Scenario | Drives | Confirms |
|---|---|---|
| `scenarios/uart_basic.py` | `examples/uart-contract/uart.chw` | R/W semantics, enum field, interrupt lifecycle, reset |
| `scenarios/dma_basic.py` | `examples/simple-dma/dma.chw` | `W1C` clear, DMA ownership, alignment |

Each scenario exits `0` on success and `1` on the first
unexpected refusal or state mismatch.

The refusal suite at `oracle/legacy/tools/sim/test_refusal_runtime.py`
constructs the refusal `.chw` files, attempts the operation the
case the refutes, and asserts the right `AccessError.code` is
emitted. This is the **runtime twin** of every schema-level
refusal in `examples/refusal/`.

---

## Phase 1 next steps

- `tests/roundtrip/c_header_compiles.rs` — generate C header,
  link it with the reference model via a thin shim, drive the
  same scenarios, assert identical state.
- `tests/roundtrip/systemverilog_parses.rs` — generate SV,
  parse with slang, assert module port shape matches the
  contract (no functional comparison yet — that needs Verilator
  and is a Phase 2 concern).
- `tests/roundtrip/reference_model_in_rust.rs` — port the
  reference model to Rust so the roundtrip suite is single-
  language and runs in CI without Python.