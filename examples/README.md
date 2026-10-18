# examples/

> **Status: Phase 1.** Two valid examples in JSON wire form,
> the same two in frozen textual form (`textual/`), and twelve
> refusal cases (`refusal/<name>.chw` + `<name>.expect.json`)
> are landed. Five of the twelve refusals trip at the schema
> level, one at the parser, the rest at the checker.

---

## Valid examples

| Example | File | What it exercises |
|---|---|---|
| UART register block | `uart-contract/uart.chw` | `RW`, `RO`, `WO` registers, enum field, free-text constraint, single interrupt with all four linkages (source/enable/status/clear) |
| DMA controller + descriptors | `simple-dma/dma.chw` | `W1C` register, multiple interrupts, `CPU` and `DEVICE` DMA fields, alignment, coherent flag, multiple DMA buffers |
| UART register block, textual | `textual/uart.chw` | The frozen textual syntax for the UART contract above. `tests/parser/parser_roundtrip.py` asserts its parsed IR equals the JSON wire form. |
| DMA controller + descriptors, textual | `textual/dma.chw` | The frozen textual syntax for the DMA contract above. |

Both JSON examples are **schema-valid**; both textual examples
parse to the identical IR. `tools/check/conformance.py` also
asserts all four pass every rule in
`spec/diagnostics/README.md` §3.

---

## Refusal examples

Each refusal example is a `.chw` file paired with a sidecar
`<name>.expect.json` file. The sidecar lists the diagnostic(s)
the checker must emit, with the expected `code`, `subject`,
and a substring the `message` must contain.

The conformance suite asserts every entry in every sidecar.

| File | Expected rule(s) | Notes |
|---|---|---|
| `register-overlap.chw` | `register-offset-duplicate` | Two registers at `0x00` |
| `field-overlap.chw` | `field-overlap` | `ENABLE [0..3]` and `PARITY [2..4]` in the same register |
| `field-out-of-bounds.chw` | `field-bounds-overflow` | `msb 63` on a 32-bit bus |
| `enum-overflow.chw` | `field-enum-overflow` | 2-bit field with enum value `7` |
| `reset-overflow.chw` | `reset-overflow` | 33-bit reset on a 32-bit register |
| `interrupt-unresolved.chw` | `interrupt-source-unresolved`, `interrupt-enable-unresolved`, `interrupt-status-unresolved`, `interrupt-clear-unresolved` | All four linkages point to nonexistent register/field |
| `dma-overlap.chw` | `dma-overlap` | Two DMA fields whose byte ranges overlap |
| `dma-bad-align.chw` | `dma-align-unsatisfied` | DMA offset `0x05` with `align: 4` |
| `dma-owner-unknown.chw` | `dma-owner-unknown` | `owner: "GPU"` is not `CPU` or `DEVICE` |
| `kind-unknown.chw` | `register-kind-unknown` | `kind: "WTF"` |
| `bus-width-invalid.chw` | `block-bus-width-invalid` | `bus_width: 64` (only 8/16/32 allowed) |
| `parse-error.chw` | `parse-error` | Textual form. The register line is missing `:` before the access kind; the diagnostic carries a real line/column span (`spec/diagnostics/README.md` §3.1). |

The full count is **2 JSON valid + 2 textual valid + 12 refusal
= 16 examples**, which exceeds the parent proposal §9 Phase 0
target of "10–20 valid and invalid examples."

---

## Manifest

`examples/MANIFEST.json` is the machine-readable list of every
example, valid or refusal. Phase 1 reads it; nothing else
should.

```json
{
  "version": "1",
  "valid": [
    "examples/uart-contract/uart.chw",
    "examples/simple-dma/dma.chw"
  ],
  "refusal_dir": "examples/refusal/",
  "refusal_glob": "*.chw",
  "expect_glob": "*.expect.json"
}
```

---

## What Phase 1 must add

- The parser from `.chw` text to JSON wire format (Phase 0
  examples are already JSON; the parser is exercised on these
  in addition to text examples added in Phase 1).
- The checker that emits every diagnostic named in the
  sidecars.
- `tests/conformance/refusal.rs` that loads each sidecar and
  asserts the checker emitted the named diagnostic(s).
- `tests/conformance/valid.rs` that asserts each valid example
  emits zero diagnostics.