# Contract schema

> **Status: Phase 1.** The schema below is the normative input to
> every tool in this repo. There are two source forms for it: the
> **textual `.chw` syntax** (§10, frozen as of Phase 1) and the
> **JSON wire format** this document describes. The parser
> (`tools/parse/`) turns the textual form into the JSON form;
> every downstream tool reads the JSON form directly. Both forms
> are accepted by every tool that loads a `.chw` file.

---

## 1. Position

A contract file (`.chw`) describes **one register block** and
zero or more DMA buffers associated with it. The schema lives
in this directory as both a human-readable README (this file)
and a machine-checkable JSON Schema
([`cancho-hdl-contract.schema.json`](cancho-hdl-contract.schema.json)).

The Phase 0 schema is **deliberately minimal**: it expresses the
five constructs the parent proposal §5.1 names and nothing
else. Anything richer (multi-block systems, structured
constraint expressions, multi-bus blocks) is gated on the
open questions in [`docs/contract-design.md`](../../docs/contract-design.md) §5.

---

## 2. Top-level shape

```jsonc
{
  "$schema": "https://alpibrusl/cancho-hdl/spec/contract-schema/cancho-hdl-contract.schema.json",
  "version": "0.1.0",
  "block": { /* RegisterBlock, §3 */ },
  "dma_buffers": [ /* DmaBuffer, §5 */ ]
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `$schema` | string | recommended | The URI of this schema. Phase 1 validates with a local copy. |
| `version` | string | required | Contract-schema version. Must parse as `MAJOR.MINOR.PATCH`. |
| `block` | object | required | One register block per file. See §3. |
| `dma_buffers` | array | optional | Zero or more DMA buffer layouts. See §5. |

A file with more than one `block` is refused with
`schema-invalid` (Phase 1) until Phase 2 introduces a
`system_map` aggregate.

---

## 3. Register block

```jsonc
{
  "name": "UartRegs",
  "base_address": "0x40000000",
  "bus_width": 32,
  "endianness": "little",
  "registers": [ /* Register, §4 */ ],
  "interrupts":  [ /* Interrupt, §4.3 */ ]
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | required | Identifier; used in stable IDs |
| `base_address` | string | required | Hex literal; validated by checker |
| `bus_width` | integer | required | One of `8`, `16`, `32` |
| `endianness` | enum | required | `little` or `big` |
| `registers` | array | required | One or more registers |
| `interrupts` | array | optional | Zero or more interrupts |

---

## 4. Register

```jsonc
{
  "name": "CTRL",
  "offset": "0x00",
  "kind": "RW",
  "reset": "0x00000000",
  "volatile": false,
  "polling": false,
  "fields": [ /* Field, §4.2 */ ]
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | required | |
| `offset` | string | required | Hex literal, relative to `block.base_address` |
| `kind` | enum | required | One of: `RO`, `WO`, `RW`, `RC`, `W1C`, `W0C`, `W1S`, `W0S` |
| `reset` | string | optional | Hex literal; must fit in `bus_width`. Absent means "undefined at reset". |
| `volatile` | bool | optional | Default `false`. Marks the register as `volatile` in the C binding. |
| `polling` | bool | optional | Default `false`. Hints at the C binding's polling helper. |
| `fields` | array | optional | Zero or more fields. A register with no fields is still a register (used for reserved space and FIFO windows). |

### 4.1 Access kinds

The `kind` enum is the vocabulary the Phase 0 schema accepts.
It is **closed**: any other string is `register-kind-unknown`.
Phase 1's open question list ([contract-design.md](../../docs/contract-design.md) §5
question 1) tracks which variants survive to `0.2.0`.

| `kind` | Read | Write | Effect on write |
|---|---|---|---|
| `RO`  | yes | no  | n/a |
| `WO`  | no  | yes | n/a |
| `RW`  | yes | yes | none |
| `RC`  | yes | no  | n/a (read clears the field; encoded per question 2) |
| `W1C` | no  | yes | writing `1` clears the corresponding bit |
| `W0C` | no  | yes | writing `0` clears the corresponding bit |
| `W1S` | no  | yes | writing `1` sets the corresponding bit |
| `W0S` | no  | yes | writing `0` sets the corresponding bit |

### 4.2 Field

```jsonc
{
  "name": "BAUD_DIV",
  "lsb": 8,
  "msb": 15,
  "enum": { "None": 0, "Even": 1, "Odd": 2 },
  "constraint": "nonzero when ENABLE == 1"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | required | |
| `lsb` | integer | required | Least-significant bit; `0 <= lsb < bus_width` |
| `msb` | integer | required | Most-significant bit; `lsb <= msb < bus_width` |
| `enum` | object | optional | Map of name → integer value. Each value must fit in `(msb - lsb + 1)` bits. |
| `constraint` | string | optional | Free-text constraint. The Phase 0 checker does not parse this; Phase 1 either downgrades it to documentation or commits to an expression language. |

### 4.3 Interrupt

```jsonc
{
  "name": "rx_ready",
  "number": 5,
  "source": { "register": "STATUS", "field": "RX_READY" },
  "enable": { "register": "IER",    "field": "RX_EN" },
  "status": { "register": "ISR",    "field": "RX" },
  "clear":  { "register": "ICR",    "field": "RX", "kind": "W1C" }
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | required | |
| `number` | integer | optional | Hardware interrupt number. The checker does not enforce uniqueness across blocks (multi-block impact is a Phase 2 concern); it enforces non-negative integers. |
| `source` | object | optional | `{ register, field }`. The field's bit read on `RO` / `RW` triggers the interrupt source. |
| `enable` | object | optional | `{ register, field }`. Writing `1` to the field enables the interrupt. |
| `status` | object | optional | `{ register, field }`. The field indicates the interrupt is currently active. |
| `clear`  | object | optional | `{ register, field, kind }`. `kind` is one of `W1C`, `W0C`, `RC`. Absent `kind` means the field is the same kind as the control. |

Every `{ register, field }` reference is resolved by the
checker. Unresolved references are refused with
`interrupt-*-unresolved`.

---

## 5. DMA buffer

```jsonc
{
  "name": "TxDescriptor",
  "fields": [
    { "name": "next_ptr",  "offset": "0x00", "owner": "CPU",    "align": 8 },
    { "name": "data_ptr",  "offset": "0x08", "owner": "CPU",    "align": 4, "coherent": false },
    { "name": "length",    "offset": "0x10", "owner": "CPU",    "constraint": "length <= 4096" },
    { "name": "done_flag", "offset": "0x14", "owner": "DEVICE", "written_as": 1 }
  ]
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | required | |
| `fields` | array | required | One or more fields. Each is a DmaField (§5.1). |

### 5.1 DMA field

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | required | |
| `offset` | string | required | Byte offset from the buffer's start. Hex literal. |
| `owner` | enum | required | `CPU` or `DEVICE`. `DEVICE`-owned fields have no write accessor in the generated binding. |
| `align` | integer | optional | Power of two in `[1, 4096]`. `offset % align == 0` must hold. |
| `coherent` | bool | optional | Default `false`. `true` means the field requires cache-coherent access. |
| `constraint` | string | optional | Same status as register-field `constraint`. |
| `written_as` | integer | optional | For `DEVICE`-owned fields: the value the device writes. Documented, not enforced. |

---

## 6. Canonical JSON form

The wire format the checker, generators, diff, and impact read
is the **canonical JSON** form, not the source `.chw` text.

Rules:

1. **No comments.** JSON has no syntax for them. The `.chw`
   source may have comments; the canonical form does not.
2. **Stable key order.** Keys are emitted in the order they
   appear in the schema definition. Consumers can rely on
   `git diff` of the IR being meaningful.
3. **Integer literals.** `base_address`, `offset`, `reset`,
   `lsb`, `msb`, `align`, and `number` are hex strings in the
   source; they are emitted as hex strings in the canonical
   form too, **except** `lsb`, `msb`, `align`, and `number`,
   which are decimal integers. This split keeps the addresses
   visually grouped while making bit/byte math simple.
4. **No `null` fields.** Optional fields absent in the source
   are absent in the canonical form. They are not serialized
   as `null`.
5. **No duplicate keys.** The serializer rejects them with
   `schema-invalid` rather than silently picking one.

A tool that does not respect any of these rules is refused at
the wire level with `ir-version-unsupported` or
`schema-invalid`, depending on which rule was broken.

---

## 7. Stable identifiers

Every entity carries an ID of the form:

| Entity | ID |
|---|---|
| Block | `chw:<block.name>` |
| Register | `chw:<block.name>.register.<register.name>` |
| Field | `chw:<block.name>.register.<register.name>.field.<field.name>` |
| Interrupt | `chw:<block.name>.interrupt.<interrupt.name>` |
| DMA buffer | `chw:<block.name>.dma.<buffer.name>` |
| DMA field | `chw:<block.name>.dma.<buffer.name>.field.<field.name>` |

These IDs are the **only** stable handle for diagnostics,
diffs, and impact analysis. They never change when fields are
reordered or renumbered — `git blame` on a generated file
points to the entity whose ID appears in the diagnostic.

---

## 8. Versioning

| Schema | Version | Bump policy |
|---|---|---|
| `cancho-hdl-contract` | `0.1.0` (Phase 0) | Major = breaking field rename or removal; minor = additive field; patch = documentation clarification |

A `0.2.0` is the earliest point the open questions in
[`docs/contract-design.md`](../../docs/contract-design.md) §5
can change. Until then, the schema is frozen.

---

## 9. What Phase 1 must add

- The JSON Schema file
  [`cancho-hdl-contract.schema.json`](cancho-hdl-contract.schema.json)
  matching this README byte for byte on every example in
  `examples/`.
- [x] A parser from `.chw` text (§10) to canonical JSON
  (`tools/parse/`), with roundtrip tests for every valid example
  and refusal tests for syntax errors (`tests/parser/parser_roundtrip.py`).
- A serializer from JSON to canonical JSON (idempotence is a
  tested guarantee).

Phase 1 does **not** add a schema field that is not in this
README. Phase 1 does **not** change a field's semantics
without a major version bump.

---

## 10. The textual syntax (frozen at Phase 1)

The parent proposal §5.2 sketched a textual form and explicitly
refused to freeze it until "the checker and generators have
validated the model on two real peripherals." Those peripherals
(`uart-contract`, `simple-dma`) are landed, so this section
**freezes** the syntax. Grammar deviations become `parse-error`
diagnostics with real line/column spans
(`spec/diagnostics/README.md` §3.1). The two references are the
normative cross-check: `examples/textual/uart.chw` parses to the
JSON IR of `examples/uart-contract/uart.chw`, and
`examples/textual/dma.chw` to `examples/simple-dma/dma.chw`'s —
asserted by `tests/parser/parser_roundtrip.py`.

```text
file        := item* EOF
item        := block | dma_buffer
block       := "register-block" IDENT "@" HEX "," "width" DEC ","
               endianness "{" (register | interrupt)* "}"
register    := "register" IDENT "@" HEX ":" KIND attr* "{" field* "}"
attr        := "reset" HEX | "volatile" | "polling"          (comma-separated)
field       := "field" IDENT ":" "bits" "[" DEC [ ".." DEC ] "]"
               [ "enum" "{" enum_entry* "}" ] [ "constraint" text ]
enum_entry  := IDENT "=" DEC                                  (comma-separated)
interrupt   := "interrupt" IDENT "from" IDENT "." IDENT "{" linkage* "}"
linkage     := ("source" | "enable" | "status") "@" IDENT "." IDENT
             | "clear" [ ":" ("W1C" | "W0C" | "RC") ] "@" IDENT "." IDENT
             | "number" DEC
dma_buffer  := "dma-buffer" IDENT "{" dma_field* "}"
dma_field   := "field" IDENT ":" "@" HEX dma_attr* {
               every field must carry "owned by"
             }
dma_attr    := "owned" "by" ("CPU" | "DEVICE") | "aligned" DEC
             | "coherent" ("true" | "false") | "written" "as" DEC
             | "constraint" text
endianness  := "little-endian" | "big-endian"
KIND        := RO | WO | RW | RC | W1C | W0C | W1S | W0S
```

Rules the grammar cannot say, enforced by the parser:

1. **Hex literals** may use `_` separators (`0x4000_0000`).
   The parser normalizes by stripping underscores and
   lowercasing; digit widths are preserved literally, so an
   author writing `0x00` gets `0x00` in the IR, not `0x0`.
2. **Comments** are `//` to end of line. The word `constraint`
   inside a comment is inert.
3. **`constraint` text** is everything on the line after the
   keyword, up to a `//` comment. Lexically it is one string
   token, so it may contain characters (`<=`, `==`) that are not
   grammar tokens.
4. **Reserved words** are the keywords above plus `constraint`.
   A register named `reset` is fine; a field named `constraint`
   is not.
5. **The `number` linkage** is optional (`"number"` in the JSON
   is optional) and may appear anywhere in the interrupt body.
6. **DMA ownership** is mandatory in the text form: `owned by
   CPU` or `owned by DEVICE` on every field. The schema requires
   it too; the parser refuses at `parse-error` before the
   `dma-owner-unknown` checker rule can apply.
7. **Separators.** Enum entries and register/dma attribute lists
   are comma-separated; a trailing comma inside an `enum { … }`
   body is accepted, so the C style is legal there. Between
   interrupt linkage items a `,` or `;` is optional (the sketch's
   plain-newline style is the frozen style).