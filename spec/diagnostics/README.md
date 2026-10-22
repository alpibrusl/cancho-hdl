# Diagnostic format

> **Status: Phase 1.** This document locks the shape of every
> diagnostic, evidence report item, and semantic-diff item
> cancho-hdl emits. The first refusal the tool emits against a
> real input pins the schema; the schema does not drift between
> releases.

---

## 1. Position

Every refusal is **a structured value**, not a string. A
diagnostic has fields an agent reads; a human-readable
sentence is parallel.

The tier taxonomy (`Static` / `Tested` / `Runtime` / `Trust` /
`Unknown`) is **inherited verbatim** from cancho-ui
[`../../cancho-ui/spec/diagnostics/README.md`](../../cancho-ui/spec/diagnostics/README.md)
§2. Phase 0 does not add a tier. cancho-hdl extends the
`Subject` enumeration with hardware-specific kinds; everything
else is shared.

---

## 2. The diagnostic shape

```text
Diagnostic {
    code: String,                       // stable rule tag, kebab-case
    severity: Severity,                 // Error | Warning
    tier: Tier,                         // Static | Tested | Runtime | Trust | Unknown
    span: Option<Span>,
    subject: Subject,
    message: String,                    // short explanation an agent can read
    expected: Option<Value>,
    actual: Option<Value>,
    remediation: Option<Remediation>,
    related: Vec<Related>,
    notes: Vec<String>,
}

Severity = Error | Warning

Tier = Static | Tested | Runtime | Trust | Unknown

Subject =
    | RegisterBlock     { name: String }
    | Register          { block: String, name: String }
    | Field             { block: String, register: String, name: String }
    | Interrupt         { block: String, name: String }
    | InterruptLinkage  { block: String, interrupt: String, role: String }
    | DmaBuffer         { block: String, name: String }
    | DmaField          { block: String, buffer: String, name: String }
    | GeneratedArtifact { kind: String, target: String }
    | Generator         { target: String }
    | Ir                { path: String }

Value =
    | Number(Number)
    | String(String)
    | Identifier(String)                // register/field/interrupt/buffer name
    | RefusalCode(String)               // another diagnostic's `code`
    | Null

Remediation {
    description: String,
    suggestion: Option<PatchHint>,      // structured patch when the compiler can justify one
    confidence: Confidence,             // High | Medium | Low
}

Confidence = High | Medium | Low

Related {
    code: String,
    span: Option<Span>,
    message: String,
}

Span {
    file: String,
    start: Position,                    // 1-indexed line, 1-indexed column
    end: Position,
}
```

### 2.1 Required fields

Every diagnostic carries `code`, `severity`, `tier`, `subject`,
`message`. The rest are present only when the diagnostic is
about them — `span` is `None` for diagnostics that do not come
from a source-located check (e.g. an internal compiler error
or a refusal emitted by a generator at run time).

### 2.2 No optional `message`

`message` is always present and always a non-empty string. The
message is what an agent reads first; it is the entry point.

### 2.3 No LLM-generated explanations

The `remediation.suggestion` field, when present, is a
**structured patch hint** produced by the toolchain's own
analysis, not by an LLM. The agent may apply the hint; the
toolchain re-checks the result.

### 2.4 Subject kinds are closed

The list of `Subject` variants above is the **whole list** for
Phase 1. Adding a variant is a minor schema bump (additive).
A new rule must use an existing variant; introducing a new
variant requires a rule in the catalog and a refusal test.

---

## 3. The rule catalog (Phase 0 / Phase 1)

Each entry's `code` is the **stable rule tag** used by the
diagnostic, by the refusal fixture in `examples/refusal/`, and
by the evidence report. Phase 0 lists the codes the Phase 1
checker must implement. A code listed here without a refusal
fixture is refused at the catalog level with
`rule-has-no-refusal-fixture` — the catalog must be backed by
tests, not assertions.

### 3.1 Schema and IR

| `code` | `subject` | `severity` | `tier` | Meaning |
|---|---|---|---|---|
| `parse-error` | `Ir` | `Error` | `Static` | A textual `.chw` file (spec/contract-schema/README.md §10) does not parse. The span names the offending token; message names what was expected. Lane-specific: only files in the text form can produce it. |
| `schema-invalid` | `Ir` | `Error` | `Static` | A `.chw` file fails JSON Schema validation |
| `schema-version-unsupported` | `Ir` | `Error` | `Runtime` | The schema `$version` is outside the toolchain's supported range |
| `ir-version-unsupported` | `Ir` | `Error` | `Runtime` | An IR consumer does not recognize the schema version |
| `block-name-missing` | `RegisterBlock` | `Error` | `Static` | A block without a name |
| `block-base-address-missing` | `RegisterBlock` | `Error` | `Static` | A block without `base_address` |
| `block-bus-width-invalid` | `RegisterBlock` | `Error` | `Static` | A block with `bus_width` other than 8, 16, or 32 |
| `block-endianness-unknown` | `RegisterBlock` | `Error` | `Static` | A block with `endianness` other than `little` or `big` |
| `internal` | `core` | `Error` | `Unknown` | A toolchain internal error |

**Sub-tags of `schema-invalid` and `internal` (the cancho validator, stage 1 of
[`docs/cancho-port.md`](../../docs/cancho-port.md), section 9.4).** The code stays
the catalog's; the cancho tools add a `keyword` that says which check refused,
so a test can pin it. For `schema-invalid`: the JSON Schema keyword (`type`,
`enum`, `pattern`, `minimum`, `maximum`, `minLength`, `minItems`, `required`,
`additionalProperties`), and three refusals the Python `jsonschema` pass did not
make: `json-syntax` (the file begins with `{` and is not RFC 8259 JSON),
`duplicate-key` (an object repeats a key), `integer-range` (an integer past 18
digits). For `internal`: `unsupported-keyword` (the schema file uses a keyword
the validator does not implement, which it refuses rather than skips). The cancho
diagnostics also carry a JSON Pointer to the node and, for the JSON wire form, its
line and column; fixtures for each sub-tag are in `tests/stage1/`.

**The cancho checker's output (stage 2 of the port plan).** `chw check FILE
--output json` prints exactly the shape of section 4 (`Diagnostic.to_json()` of
`oracle/legacy/tools/check/diagnostic.py`), and the structural diagnostics in the words
`checker.py` gives them: `schema validation failed: ` and the `jsonschema` message,
the pointer as a list in the subject, `expected` the schema's name. Its sub-tags
and positions are not in that shape, so they appear only with `--located`: the
position of the node (a `span` that is not the whole file) and a `keyword` in the
`Ir` subject. A semantic rule always carries the whole-file span, as the Python
checker's do. The rule table of this section is restated as code in
`src/diagnostic.cho` and compared with these tables by
`tests/differential/catalog.py`.

### 3.2 Registers and fields

| `code` | `subject` | `severity` | `tier` | Meaning |
|---|---|---|---|---|
| `register-name-missing` | `Register` | `Error` | `Static` | A register without a name |
| `register-offset-missing` | `Register` | `Error` | `Static` | A register without `offset` |
| `register-offset-non-aligned` | `Register` | `Error` | `Static` | A register offset not a multiple of the block's bus width |
| `register-offset-overflow` | `Register` | `Error` | `Static` | A register offset that pushes the register past the block's address space |
| `register-offset-duplicate` | `Register` | `Error` | `Static` | Two registers in the same block at the same offset |
| `register-kind-unknown` | `Register` | `Error` | `Static` | A `kind` other than `RO`, `WO`, `RW`, `RC`, `W1C`, `W0C`, `W1S`, `W0S` |
| `reset-overflow` | `Register` | `Error` | `Static` | A `reset` value that does not fit in the register width |
| `reset-wo-nonzero` | `Register` | `Warning` | `Static` | A `WO` register with a non-zero reset (most are unused; a non-zero reset on WO is suspicious) |
| `field-name-missing` | `Field` | `Error` | `Static` | A field without a name |
| `field-bounds-missing` | `Field` | `Error` | `Static` | A field without `lsb` / `msb` |
| `field-bounds-inverted` | `Field` | `Error` | `Static` | `msb < lsb` |
| `field-bounds-overflow` | `Field` | `Error` | `Static` | `msb >= bus_width` |
| `field-overlap` | `Field` | `Error` | `Static` | Two fields in the same register with overlapping bit ranges |
| `field-enum-overflow` | `Field` | `Error` | `Static` | An enum value that does not fit in the field width |
| `field-constraint-ignored` | `Field` | `Warning` | `Static` | A `constraint` string was provided but the checker does not enforce constraint semantics yet — see [`docs/contract-design.md`](../../docs/contract-design.md) §5 question 3 |

### 3.3 Interrupts

| `code` | `subject` | `severity` | `tier` | Meaning |
|---|---|---|---|---|
| `interrupt-name-missing` | `Interrupt` | `Error` | `Static` | An interrupt without a name |
| `interrupt-source-unresolved` | `InterruptLinkage` | `Error` | `Static` | An interrupt `source` references a register or field that does not exist |
| `interrupt-enable-unresolved` | `InterruptLinkage` | `Error` | `Static` | An interrupt `enable` references a register or field that does not exist |
| `interrupt-status-unresolved` | `InterruptLinkage` | `Error` | `Static` | An interrupt `status` references a register or field that does not exist |
| `interrupt-clear-unresolved` | `InterruptLinkage` | `Error` | `Static` | An interrupt `clear` references a register or field that does not exist |
| `interrupt-clear-kind-invalid` | `InterruptLinkage` | `Error` | `Static` | An interrupt `clear.kind` other than `W1C`, `W0C`, `RC`, or absent |
| `interrupt-duplicate-name` | `Interrupt` | `Error` | `Static` | Two interrupts in the same block with the same name |

### 3.4 DMA buffers

| `code` | `subject` | `severity` | `tier` | Meaning |
|---|---|---|---|---|
| `dma-name-missing` | `DmaBuffer` | `Error` | `Static` | A DMA buffer without a name |
| `dma-field-name-missing` | `DmaField` | `Error` | `Static` | A DMA field without a name |
| `dma-overlap` | `DmaField` | `Error` | `Static` | Two DMA fields whose byte ranges overlap |
| `dma-align-illegal` | `DmaField` | `Error` | `Static` | A DMA field with an `align` value other than a power of two in `[1, 4096]` |
| `dma-align-unsatisfied` | `DmaField` | `Error` | `Static` | A DMA field offset not divisible by `align` |
| `dma-owner-unknown` | `DmaField` | `Error` | `Static` | A DMA field with `owner` other than `CPU` or `DEVICE` |
| `dma-written-by-binding` | `DmaField` | `Error` | `Static` | A `DEVICE`-owned field has a write accessor in the generated binding |

### 3.5 Generators and roundtrip

| `code` | `subject` | `severity` | `tier` | Meaning |
|---|---|---|---|---|
| `generator-target-unknown` | `Generator` | `Error` | `Static` | A `--target` other than `c-header`, `cancho-binding`, `devicetree`, `systemverilog`, `svd` |
| `generator-unimplemented` | `Generator` | `Error` | `Unknown` | A target requested for which no generator has landed yet |
| `roundtrip-failed` | `GeneratedArtifact` | `Error` | `Tested` | A generated artifact does not roundtrip (re-parse / re-validate) |
| `evidence-over-claim` | `Ir` | `Error` | `Tested` | A report or generator claims a guarantee the toolchain does not enforce — mirrors cancho-ui |

### 3.6 Catalog discipline

A diagnostic is `Error` in Phase 0 / Phase 1. A warning exists
only when it is mechanically necessary to surface a real risk
(see `reset-wo-nonzero`, `field-constraint-ignored`). Adding a
warning requires a refusal fixture that demonstrates why
silence is unsafe in that case; otherwise the new diagnostic
must be `Error` or it does not land.

The `evidence-over-claim` rule applies to the report itself: a
report that omits any field listed in
[`docs/guarantees.md`](../../docs/guarantees.md) §3 is refused
by the conformance suite. This is not a soft hint.

---

## 4. The `--output json` shape

The JSON form of a diagnostic is what an agent reads.

```json
{
  "code": "field-overlap",
  "severity": "Error",
  "tier": "Static",
  "subject": {
    "kind": "Field",
    "block": "UartRegs",
    "register": "CTRL",
    "name": "PARITY"
  },
  "span": {
    "file": "examples/refusal/field-overlap.chw",
    "start": { "line": 6, "column": 12 },
    "end":   { "line": 6, "column": 18 }
  },
  "message": "Field 'PARITY' in register 'CTRL' overlaps field 'ENABLE'.",
  "expected": { "Identifier": "non-overlapping bit range" },
  "actual":   { "Identifier": "bits [1..2] intersect bits [0..0]" },
  "remediation": {
    "description": "Reduce PARITY to bits [1..2] only after removing or shrinking ENABLE.",
    "suggestion": null,
    "confidence": "Low"
  },
  "related": [
    {
      "code": "field-overlap",
      "span": {
        "file": "examples/refusal/field-overlap.chw",
        "start": { "line": 5, "column": 12 },
        "end":   { "line": 5, "column": 18 }
      },
      "message": "Field 'ENABLE' occupies bits [0..0] in the same register."
    }
  ],
  "notes": []
}
```

### 4.1 Stable field names and order

Field names do not change between schema versions. A new
field is additive (minor version bump); a renamed field is a
breaking change (major version bump). Consumers ignore unknown
fields. The serialization order is the declaration order in
§2. Consumers can rely on it for diff stability.

### 4.2 No embedded newlines in `message`

The `message` field is one line. A multi-line explanation goes
in `notes[]`, with one note per entry.

---

## 5. The text form

The human-readable form is parallel. `cancho-hdl check` without
`--output json` prints one block per diagnostic.

**The text form is derived from the JSON form**, not the other
way around. The renderer (`oracle/legacy/tools/check/text_format.py`) projects
the diagnostic onto its JSON dict (`—output json`'s exact value)
and renders only what the dict carries. No `span` in the JSON →
no `-->` line; no `remediation` → no `help:` line. This is a
tested property (`tests/text_format/golden_cancho.py`, "derivation
property"), not a style note.

### 5.1 The lanes

| Lane | Rendered as | When |
|---|---|---|
| header | `error[code]: message` or `warning[code]: message` — one line, never re-wrapped (the JSON `message` is one line per §4.2) | always |
| span, real | `   --> file:line:col`, then gutter + the source line + a caret under the span start | span carries a position other than `1:1` (today: only `parse-error` over the textual syntax) |
| span, file-only | `   --> file` | span is the whole-file pseudo-span the JSON wire form produces, or the file is unreadable — a snippet is never guessed |
| related | `   = related[code]: message` — one line per entry | any `related[]` |
| notes | `   = note: <text>` — one line per entry | any `notes[]` |
| remedy | `help: <remediation.description>` | any `remediation` |

Blocks are separated by a blank line. There is no other
separator syntax: everything after the header is indented
something other than `severity[code]`, so the header line is the
only lookahead a parser of this form needs.

### 5.2 Verified examples

Live output, pinned byte-for-byte by the golden test. First a
real-span lane (from the textual syntax's parser):

```text
$ cancho-hdl check examples/refusal/parse-error.chw
error[parse-error]: parse error: expected ':' after the register offset (before the access kind), found 'RW'.
   --> examples/refusal/parse-error.chw:2:26
   |
  2 |     register CTRL @ 0x00 RW, reset 0x00000000 {
   |                          ^
```

Then a file-only span with the related and remedy lanes (the
JSON wire form carries no source positions, so the span names a
file, not a token):

```text
$ cancho-hdl check examples/refusal/field-overlap.chw
error[field-overlap]: field 'PARITY' bits [2..4] overlap with ENABLE bits [0..3] in register 'CTRL'.
   --> examples/refusal/field-overlap.chw
   = related[field-overlap]: field 'ENABLE' occupies bits [0..3] in register 'CTRL'.
help: start PARITY at bits [4..6] (just after ENABLE, bits [0..3]), or shrink / move either field — the toolchain cannot say which side the hardware semantics live on
```

The `help:` text is a tool-derived hint, per §2.3: the
toolchain can compute and re-check the placement it suggests,
and it says explicitly what it cannot know (which side holds
the hardware semantics).

---

## 6. The evidence report

> **Status: Phase 2 — landed.** Implemented at
> `oracle/legacy/tools/report/report.py`; pinned by
> `tests/report/report_cancho_golden.py`. The example below is the
> landed shape: it adds `input`, the top-level restatements of
> §6.1, and `unknown.static_checks_not_run` to the Phase 0
> sketch.

`cancho-hdl report` produces a JSON document with five
sections, one per tier.

```json
{
  "schema": "cancho-hdl-report",
  "version": "0.1.0",
  "input": "examples/uart-contract/uart.chw",
  "static": {
    "checks_run": ["field-overlap", "register-offset-duplicate", "..."],
    "checks_passed": 17,
    "checks_failed": 1,
    "diagnostics": [
      // structured Diagnostic objects
    ]
  },
  "tested": {
    "roundtrips_run": ["c-header::clang", "systemverilog::yosys-read"],
    "roundtrips_passed": 3,
    "roundtrips_failed": 0,
    "details": [
      {
        "target": "c-header",
        "tool": "clang-19",
        "input": "examples/uart-contract/uart.chw",
        "outcome": "passed"
      }
    ]
  },
  "runtime": {
    "checks_performed": ["schema-version-unsupported"],
    "checks_passed": 1,
    "checks_failed": 0,
    "details": []
  },
  "trust": {
    "boundaries": [
      { "tool": "yosys", "version": "0.55", "tier": "Trust" },
      { "ip":     "uart-core",       "tier": "Trust" }
    ],
    "count": 2
  },
  "unknown": {
    "items": [
      {
        "description": "Vendor SystemVerilog subset accepted by the targeted toolchain",
        "tier": "Unknown"
      }
    ],
    "static_checks_not_run": []
  },
  // Top-level restatements of the tier sections (§6.1).
  "static_checks_run": ["field-overlap", "register-offset-duplicate", "..."],
  "tested_roundtrips_run": ["c-header::clang", "systemverilog::yosys-read"],
  "trust_boundaries": ["yosys", "uart-core"],
  "unknown_items": [ "...same as unknown.items..." ],
  // Verbatim restatement of every docs/guarantees.md §2 row —
  // no summary, no paraphrase, no omission (collected by the
  // golden suite against the markdown table itself).
  "non_guarantees": [
    "Functional correctness of generated RTL beyond the register map itself.",
    "Timing closure.",
    "Area, power, fanout.",
    "Functional correctness of third-party IP.",
    "Driver logic that uses a generated binding.",
    "That every real datasheet quirk has a structured encoding.",
    "That a passing `cancho-hdl check` proves the system works.",
    "That `cancho-hdl diff` flags semantic regressions a human would catch.",
    "That generated output for one vendor toolchain works under another."
  ]
}
```

### 6.1 Mandatory fields

Per [`docs/guarantees.md`](../../docs/guarantees.md) §3, the
fields `non_guarantees`, `trust_boundaries`,
`static_checks_run`, `tested_roundtrips_run`, and
`unknown_items` are mandatory. A report missing any of them is
refused with `report-schema-truncated`. An **empty list is
valid; an absent one is not** (an empty `trust_boundaries`
legitimately means nothing external was trusted this run).

The five are also restated at their tier sections —
`static_checks_run == static.checks_run`,
`tested_roundtrips_run == tested.roundtrips_run`,
`trust_boundaries == trust.boundaries[].tool`,
`unknown_items == unknown.items` — so a consumer can read either
way; the validator cross-checks the arithmetic both places.

**Provenance (the landed discipline):** `checks_run` lists the
catalog codes whose governing evaluation actually executed in
this run. The checker instruments its rule groups
(`checker.check(..., ran=set())`); the report maps groups to
codes. A group that could not run — no DMA buffers, no
interrupts, no `jsonschema` installed, a parse that never
reached the rules — appears in `unknown.static_checks_not_run`,
never in `checks_run`. An emitted diagnostic can never appear in
the not-run list (the code is promoted into `checks_run`).

### 6.2 What the report never contains

- A `trust` boundary labeled as anything other than `Trust`.
- A `static` check that did not actually run (it goes in
  `unknown.static_checks_not_run`).
- A `tested` roundtrip that was skipped (it is listed with
  `outcome: "skipped"`, not as `passed`).

### 6.3 The report's own refusals

`validate_report` (oracle/legacy/tools/report/report.py) refuses an (alleged)
report with exactly two codes — both live outside the §3 rule
catalog because they are refusals against the *report artifact*,
not against a contract:

- `report-schema-truncated` — a mandatory §6.1 field is absent,
  or `non_guarantees` is not the verbatim §2 restatement (a
  dropped or paraphrased row counts as omission).
- `evidence-over-claim` — a count that cannot add up
  (`passed + failed != len(list)` in either tier), a check
  claimed outside the catalog, a skipped roundtrip counted as
  run, a fired `Error` diagnostic not in `checks_run`, or a
  `Trust` boundary labeled otherwise.

The conformance `evidence-over-claim` lane is this function fed
intentionally corrupted report copies
(`tests/report/report_cancho_golden.py`).

---

## 7. The semantic-diff output

> **Status: Phase 2 — landed.** Implemented at
> `oracle/legacy/tools/diff/diff.py`; pinned by `tests/diff/diff_cancho_golden.py`.

`cancho-hdl diff <base> <candidate>` produces a JSON document
listing the semantic changes between two contract IRs.

A normal source diff is parallel (line-by-line). The semantic
diff is what an agent uses to decide whether a change is safe
to apply; the source diff is for a human to read.

```json
{
  "schema": "cancho-hdl-diff",
  "version": "0.1.0",
  "base_id":    "chw:UartRegs",
  "candidate_id": "chw:UartRegs",
  "added_registers": [],
  "removed_registers": [],
  "moved_registers": [
    {
      "id": "chw:UartRegs.register.STATUS",
      "from_offset": "0x04",
      "to_offset":   "0x08"
    }
  ],
  "widened_fields": [
    {
      "id": "chw:UartRegs.register.CTRL.field.BAUD_DIV",
      "from": { "lsb": 8, "msb": 15 },
      "to":   { "lsb": 8, "msb": 19 }
    }
  ],
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

### 7.0 What the diff refuses, matches, and classifies

- **Refuses invalid input.** Each contract is run through the
  static checker first; a refusal on either side aborts the diff
  with that refusal and exit code 1. An agent is never handed a
  semantic diff of a contract the checker does not accept.
- **Matches by identity, not order.** Registers match by name
  (fields by name within a register); reordering produces no
  entry. This is the ID scheme's premise (§7 of
  spec/contract-schema/README.md): order is not a semantic
  property of the map.
- **Hex is case-insensitive.** Offsets and reset values compare
  by value (`0x0C` and `0x0c` are the same register address); the
  output reports the candidate's literal form.
- **Classification is exhaustive.** A changed bit range is
  exactly one of widened (same or lower lsb, same or higher
  msb), narrowed (the mirror), or repositioned (same width,
  different lsb). No changed field is silently dropped.
- **Keys not in the sketch above are additive** (`0.1.0`):
  `repositioned_fields` (the same-width-different-position class
  the original sketch lost between widened and narrowed) and
  `changed_block_properties` (bus width, endianness, base
  address, block name — flat `{property, from, to}` entries).

Element shapes, verified by the golden suite:

| Key | Element |
|---|---|
| `added_registers` / `removed_registers` | `{ id, offset, kind }` |
| `moved_registers` | `{ id, from_offset, to_offset }` |
| `widened_fields` / `narrowed_fields` / `repositioned_fields` | `{ id, from: {lsb, msb}, to: {lsb, msb} }` |
| `added_fields` / `removed_fields` | `{ id, lsb, msb }` |
| `changed_enum_values` | `{ id, label, from, to }` — `from` is `null` for a label add, `to` is `null` for a label removal |
| `changed_reset_values` | `{ id, from, to }` |
| `changed_interrupts` | `{ id, changes: [{ role, from, to }] }` — role is `number`, `source`, `enable`, `status`, or `clear` |
| `added_interrupts` / `removed_interrupts` | `{ id }` |
| `changed_dma_layouts` | `{ id, added_field_ids, removed_field_ids, moved_fields }`, plus `owner_changes` / `coherence_changes` when those change |
| `changed_block_properties` | `{ property, from, to }` |

### 7.1 Impact

> **Status: Phase 2 — landed (path field omitted; see below).**

`cancho-hdl impact <base> <candidate>` returns the same diff
plus an `affected_artifacts` list — per generator target, whether
the artifact would be stale after applying the candidate:

```json
{
  "schema": "cancho-hdl-impact",
  "version": "0.1.0",
  "diff": { "...": "see §7" },
  "affected_artifacts": [
    { "target": "c-header",      "stale": true,  "reason": "moved_registers=5; widened_fields=1" },
    { "target": "cancho-binding","stale": false, "reason": "no change (byte-identical output for both contracts)" },
    { "target": "systemverilog", "stale": true,  "reason": "moved_registers=5; widened_fields=1" },
    { "target": "devicetree",    "stale": true,  "reason": "moved_registers=5; widened_fields=1" },
    { "target": "svd",           "stale": null,  "reason": "generator-unimplemented (Phase 2); not checked" }
  ]
}
```

Two properties carry the evidence, and both are pinned by the
golden suite:

1. **Staleness is decided by bytes, not guesses.** For every
   implemented target the generator runs on both contracts (with
   a neutral source label, so the banner cannot diverge) and the
   outputs are compared byte for byte.
2. **`stale: false` is a proof, `stale: null` is a refusal to
   claim.** A `stale: false` entry with a
   `no change (byte-identical output for both contracts)` reason
   means the generator actually ran. A target whose generator
   has not landed reports `stale: null` and
   `generator-unimplemented`; it can never masquerade as
   "no change."

The seeded-change pair also demonstrates why bytes beat
heuristics: the `cancho-binding` target reports `stale: false`
with the byte-identical proof — the binding encodes names,
widths, and kinds, not offsets — while a rule-based staleness
oracle ("an address changed, regenerate everything") would have
flagged it.

The `path` field of the Phase 0 sketch is omitted: there is no
build graph in the reference repo (generators stream to stdout),
so the document would have to invent artifact paths. It returns
when generators write to a conventional layout.

A `reason` is one of three fixed shapes: the no-change sentence
(same as above), a counted summary (`moved_registers=5;
widened_fields=1` — keys in §7 order, deterministic for a given
pair), or the unimplemented lane. No free prose.

---

## 8. Versioning

| Artifact | Schema | Version | Bump policy |
|---|---|---|---|
| Diagnostic | `cancho-hdl-diagnostic` | `0.1.0` (Phase 1) | Major = breaking field; minor = additive |
| Evidence report | `cancho-hdl-report` | `0.1.0` (Phase 2) | Same |
| Semantic diff | `cancho-hdl-diff` | `0.1.0` (Phase 2) | Same |
| Impact | `cancho-hdl-impact` | `0.1.0` (Phase 2) | Same |

A consumer that does not recognize the schema or version
refuses with `ir-version-unsupported` for IR inputs and
`schema-version-unsupported` for report / diff / impact inputs.

---

## 9. What Phase 1 must add to this sketch

- The full rule catalog in §3, each rule with at least one
  refusal fixture in `examples/refusal/` and one snapshot test
  under `tests/conformance/diagnostics.rs`.
- The JSON serializer for `Diagnostic` in §4.
- [x] The text formatter for §5 (`oracle/legacy/tools/check/text_format.py`),
  derived from the JSON form; the interpretive contract is §5.1
  and the pinned output is `tests/text_format/golden_cancho.py`.
- A `tests/diagnostics.rs` snapshot test that pins every
  fixture's diagnostic output, so the schema does not drift.

Anything else is Phase 2+. Phase 1 does not add a rule that is
not in §3, and does not modify a rule's `code` without a major
schema bump.

---

## 10. Phase 2 landing record (this repo)

- [x] §7 — the semantic-diff document: `oracle/legacy/tools/diff/diff.py`,
      pinned by `tests/diff/diff_cancho_golden.py` (identity across
      source forms, determinism, refusals of invalid contracts,
      classification units, the seeded roadmap change from
      `tests/diff/fixtures/uart_rebase.chw`).
- [x] §7.1 — impact: per-target staleness decided by
      byte-comparing generator output; unimplemented targets
      report `stale: null` ("not checked"), never "no change."
      The sketch's `path` field is omitted (no build graph;
      see §7.1).
- [x] §6 — the evidence report: `oracle/legacy/tools/report/report.py`,
      pinned by `tests/report/report_cancho_golden.py` (verbatim
      non-guarantee restatement, arithmetic provenance,
      skipped-vs-run discipline, and the §6.3 refusal codes fed
      corrupted copies).
- [ ] Remaining Phase 2 generators: `cancho-binding`
      **landed** (`oracle/legacy/gen/cancho-binding/cancho_binding.py`,
      pinned by `tests/roundtrip/cancho_binding_validates.py`;
      palette + DEVICE-no-setter + shared size refusal; joins
      the impact byte-comparison set — where it proved the
      seeded rebase leaves it byte-identical),
      `devicetree` **landed** (above), `svd` pending
      (registered in the dispatcher, refuses with
      `generator-unimplemented` until implemented).