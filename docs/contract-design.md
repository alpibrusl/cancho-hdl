# Contract design

The Hardware Contract is the input to every tool in this repo.
It is the **only** place the software/hardware boundary is
declared. Everything else — C headers, Cancho bindings, device
trees, SystemVerilog register modules, SVD — is generated.

This page documents **what the contract expresses** and **what
shape it takes**. The schema itself is normative and lives at
[`../spec/contract-schema/README.md`](../spec/contract-schema/README.md).

---

## 1. Scope of the contract model

The contract expresses, and only expresses, the five things the
parent proposal §5.1 calls out:

1. **Register blocks** — a memory-mapped region with a base
   address, bus width, and endianness.
2. **Registers** — fixed offsets inside a block, with an access
   type, reset value, and optional volatile / polling semantics.
3. **Fields** — bit ranges inside a register, with an optional
   enumeration and a documented constraint.
4. **Interrupts** — sources, numbering, and the linkage to the
   enable / status / clear registers that control them.
5. **DMA buffer layouts** — field offsets, alignment, ownership,
   and cache-coherency expectations.

A sixth concern runs through all of the above:

6. **Stable identifiers** — every register, field, interrupt
   source, and DMA buffer carries a deterministic ID used by
   diagnostics, diffs, and agent queries.

Things the contract **does not** express in Phase 0 / Phase 1:

- HDL behavior (FSMs, datapaths, clock/reset topology).
- Bus protocol specifics beyond the address/data bus of the
  block (e.g. AXI4-Lite handshake is in the generated
  SystemVerilog, not in the contract).
- Multi-block address maps (every `.chw` file describes one
  block; the address map is composed at the diff / impact
  layer).
- Timing, area, or power.

---

## 2. Shape (Phase 0)

The Phase 0 contract is **JSON**, validated by a JSON Schema.
This is a deliberate Phase 0 choice:

- It stays out of "yet-another-parser" territory. Phase 1
  implements a parser for `.chw` text and a serializer to JSON.
  If the text format needs to change, only the parser changes;
  every downstream tool reads JSON.
- It is machine-readable by definition. Agents can build it
  directly when scaffolding examples.
- It is diff-stable. The JSON form has a canonical ordering
  (`spec/contract-schema/README.md` §6) so `git diff` on a
  generated IR is meaningful.

The `.chw` text format shown in the parent proposal §5.2 is a
**sketch, not implemented syntax**. The sketch and the schema
are deliberately separate documents; Phase 1 closes the gap.

### 2.1 Skeleton

```jsonc
{
  "$schema": "cancho-hdl-contract.schema.json",
  "version": "0.1.0",
  "block": {
    "name": "UartRegs",
    "base_address": "0x40000000",
    "bus_width": 32,
    "endianness": "little",
    "registers": [
      {
        "name": "CTRL",
        "offset": "0x00",
        "kind": "RW",
        "reset": "0x00000000",
        "fields": [
          { "name": "ENABLE",   "lsb": 0,  "msb": 0 },
          { "name": "PARITY",   "lsb": 1,  "msb": 2,
            "enum": { "None": 0, "Even": 1, "Odd": 2 } },
          { "name": "BAUD_DIV", "lsb": 8,  "msb": 15,
            "constraint": "nonzero when ENABLE == 1" }
        ]
      },
      {
        "name": "STATUS",
        "offset": "0x04",
        "kind": "RO",
        "volatile": true,
        "fields": [
          { "name": "TX_BUSY",  "lsb": 0, "msb": 0 },
          { "name": "RX_READY", "lsb": 1, "msb": 1 }
        ]
      }
    ],
    "interrupts": [
      {
        "name": "rx_ready",
        "source": { "register": "STATUS", "field": "RX_READY" },
        "enable":  { "register": "IER",    "field": "RX_EN" },
        "status":  { "register": "ISR",    "field": "RX" },
        "clear":   { "register": "ICR",    "field": "RX", "kind": "W1C" }
      }
    ]
  },
  "dma_buffers": [
    {
      "name": "TxDescriptor",
      "fields": [
        { "name": "next_ptr",  "offset": "0x00", "owner": "CPU",    "align": 8 },
        { "name": "data_ptr",  "offset": "0x08", "owner": "CPU",    "align": 4, "coherent": false },
        { "name": "length",    "offset": "0x10", "owner": "CPU",    "constraint": "length <= 4096" },
        { "name": "done_flag", "offset": "0x14", "owner": "DEVICE", "written_as": 1 }
      ]
    }
  ]
}
```

The JSON keys are stable across schema versions; additions are
non-breaking, renames are major-version bumps.

---

## 3. Stable identifiers

Every register, field, interrupt, and DMA buffer carries a
deterministic ID of the form:

```
chw:<block-name>.<kind>.<name>
```

Examples:

- `chw:UartRegs.register.CTRL`
- `chw:UartRegs.register.CTRL.field.ENABLE`
- `chw:UartRegs.interrupt.rx_ready`
- `chw:UartRegs.dma.TxDescriptor.field.next_ptr`

The ID is the **only** stable handle for diagnostics, diffs, and
agent queries. Names may collide (a future block may have its
own `CTRL`); IDs do not.

---

## 4. Tier of every construct

Each construct in the contract carries an implicit guarantee
tier, reused from cancho-ui's taxonomy
([`../spec/diagnostics/README.md`](../spec/diagnostics/README.md) §2):

| Construct | Tier | Why |
|---|---|---|
| Register offset, width, access type | `Static` | Enforced by checker |
| Field bit range, enum, constraint text | `Static` (text), `Tested` (semantic) | Enum values checked statically; constraint text is documentation until Phase 2 |
| Interrupt linkage to existing register/field | `Static` | Name resolution is a static check |
| DMA buffer ownership, alignment | `Static` | Enforced by checker and reflected in the binding |
| Reset value vs. access semantics | `Static` | Enforced by checker (e.g. WO registers with non-zero reset) |
| Generated C header syntax | `Tested` | Compiles under a real C compiler in roundtrip |
| Generated SystemVerilog syntax | `Trust` | Vendor toolchain is a trusted boundary; the evidence report states this |
| Generated SVD schema validity | `Tested` | Validated against the CMSIS-SVD XSD |
| Vendor synthesis, timing, area | `Trust` | Reported as such; never claimed verified |
| Driver logic that uses a generated binding | `Unknown` | Out of contract scope |

The evidence report must list every `Trust` boundary on every
run, and must not promote `Tested` to `Static` (a passing C
compile does not prove the binding is correct, only that it
is well-formed).

---

## 5. Open questions for Phase 1

These are the questions Phase 0 leaves open. Phase 1 must close
each before the schema version is bumped past `0.1.0`:

1. **W1C variants.** Datasheets distinguish `W1C` (write 1 to
   clear) from `W0C` and from `RC` (read-to-clear). The Phase 0
   schema accepts `kind: "W1C"`, `kind: "W0C"`, `kind: "RC"`,
   and the read/write side of each. Phase 1 must pick one
   vocabulary and refuse the others with `access-kind-unknown`.
2. **Side-effect reads.** A read of `RC` clears the field. The
   Phase 0 schema encodes this as a note in the `kind` string;
   Phase 1 should encode it as a structured `on_read` action.
3. **Constraint syntax.** Field-level constraints are free
   text in Phase 0 (`"nonzero when ENABLE == 1"`). Phase 1
   must either commit to a structured expression language or
   refuse all constraints at the static tier and downgrade
   them to documentation.
4. **Address map composition.** The diff/impact layer needs to
   compose blocks into a system-level map. Phase 0 puts one
   block per file. Phase 1 should either extend the schema
   with a `system_map` aggregate or refuse cross-block impact
   analysis.
5. **Multi-bus blocks.** A block with two physical interfaces
   (e.g. APB control + AXI data) is out of Phase 0 scope. Phase
   1 should refuse such blocks at parse time with
   `block-multi-bus`.

A `0.2.0` schema is the earliest point these can change.

---

## 6. Phase 0 exit criteria

Per the parent proposal §9 Phase 0:

- [x] Contract schema documented and versioned.
- [x] Guarantees / non-guarantees table drafted.
- [x] Diagnostic format drafted, tier taxonomy inherited from
      cancho-ui.
- [x] Generator targets decided (five of them).
- [x] Bus protocol decided (AXI4-Lite).
- [ ] Two real peripherals expressible without ambiguity —
      **drafted** in `examples/uart-contract/` and
      `examples/simple-dma/`; **confirmed** by Phase 1
      checker on those files.

Stop/rethink if: the schema cannot express real datasheet
semantics without inventing per-device special cases. The
open questions above are the watch list for that signal.