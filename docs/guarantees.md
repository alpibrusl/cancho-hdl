# Guarantees and non-guarantees

> **Status: Phase 0.** This page is the contract for what the
> toolchain claims. The evidence report in `cancho-hdl report`
> restates the relevant rows on every run; nothing in a report
> may contradict this page.

The tier taxonomy (`Static` / `Tested` / `Runtime` / `Trust` /
`Unknown`) is inherited from cancho-ui
([`../spec/diagnostics/README.md`](../spec/diagnostics/README.md)
§2). Phase 0 does not add a new tier.

---

## 1. What cancho-hdl guarantees

| Guarantee | Tier | Mechanism |
|---|---|---|
| A `.chw` file compiles into a valid contract IR. | `Static` | JSON Schema validation; failure produces `schema-invalid` |
| Every register offset lies within its block, is a multiple of the register width, and is unique within the block. | `Static` | Checker, `register-offset-*` rules |
| Field bit ranges are within `[0, bus_width - 1]`, non-overlapping within a register, and `msb >= lsb`. | `Static` | Checker, `field-bounds-*` and `field-overlap` rules |
| Field enum values fit within the field width. | `Static` | Checker, `field-enum-overflow` |
| Reset values are representable in the register width and consistent with declared fields. | `Static` | Checker, `reset-overflow` and `reset-field-mismatch` |
| Interrupt linkages reference existing register/field IDs. | `Static` | Checker, `interrupt-link-unresolved` |
| DMA buffer fields are non-overlapping, aligned, and have valid `owner` values. | `Static` | Checker, `dma-overlap`, `dma-align-*`, `dma-owner-unknown` |
| DMA `DEVICE`-owned fields are not written by the generated C / Cancho binding. | `Static` (in generated code) | Code generator emits the read-only accessor; refusal is structural |
| Generated C header compiles under a real C compiler (clang/gcc). | `Tested` | Roundtrip suite under `tests/roundtrip/` |
| Generated SystemVerilog module parses in at least one open-source parser (Yosys / slang). | `Tested` | Roundtrip suite under `tests/roundtrip/` |
| Generated SystemVerilog register module, simulated with Icarus Verilog, answers the bus operations of the behavioral corpus (`R`, `Rf`, `W`, `Wf`, `RESET`) as the reference model does, and answers SLVERR at an address with no register, on a register of the wrong access kind, and never answers OKAY to a refused write. | `Tested` | `tests/behavioral/sv_behavior.py`, a master that holds its valids and one that follows AXI4-Lite; 47 bus operations per master (docs/sv-behavioral.md). Not covered: device-side writes, DMA and interrupts (the module has no port for them), `RC` clear-on-read, timing, synthesis. |
| Generated SVD validates against the CMSIS-SVD XSD. | `Tested` | Roundtrip suite under `tests/roundtrip/` |
| Generated device-tree fragment validates against the upstream DTS schema. | `Tested` | Roundtrip suite under `tests/roundtrip/` |
| `cancho-hdl diff` returns a JSON document listing every semantic change (offset, width, enum value, ownership, interrupt linkage). | `Static` | Snapshot test under `tests/conformance/` |
| `cancho-hdl impact` returns a list of every generated artifact affected by a candidate change. | `Static` | Snapshot test under `tests/conformance/` |
| `cancho-hdl report` states its non-guarantees in every run. | `Static` | Report generator; checked by snapshot test |

---

## 2. What cancho-hdl explicitly does not guarantee

| Non-guarantee | Tier | Why |
|---|---|---|
| Functional correctness of generated RTL beyond the register map itself. | `Trust` | The generator emits register decode only. The behavior wired to those registers is whatever the user / vendor IP connects. |
| Timing closure. | `Trust` | Vendor synthesis / P&R is a trusted boundary. |
| Area, power, fanout. | `Trust` | Same. |
| Functional correctness of third-party IP. | `Trust` | Out of scope by definition. |
| Driver logic that uses a generated binding. | `Unknown` | The driver is not part of the contract. The binding makes misuse harder; it does not prove the driver correct. |
| That every real datasheet quirk has a structured encoding. | `Unknown` | The Phase 0 schema accepts free-text constraints; Phase 1 either commits to an expression language or downgrades all constraints to documentation. The watch list is in [`contract-design.md`](contract-design.md) §5. |
| That a passing `cancho-hdl check` proves the system works. | `Unknown` | The checker proves structural correctness of the contract. It says nothing about the hardware behind the contract. |
| That `cancho-hdl diff` flags semantic regressions a human would catch. | `Unknown` | The diff is structural. A change that breaks undocumented behavior (e.g. a side-effect the datasheet does not name) will not be flagged. |
| That generated output for one vendor toolchain works under another. | `Trust` | Different vendors accept different SystemVerilog subsets. Generated RTL targets one open-source flow per parent proposal §9 Phase 1. |

---

## 3. What the evidence report must say, every run

In every `cancho-hdl report` JSON, the following are mandatory
fields. A report that omits any of them is refused with
`report-schema-truncated` (the report's own refusal codes;
`oracle/legacy/tools/report/report.py` §6.3):

- `non_guarantees`: an array containing every row of §2 above,
  as a structured list (not prose). The report must literally
  restate them; it may not summarize, paraphrase, or omit.
- `trust_boundaries`: a list naming every vendor toolchain or
  third-party IP encountered in the report (e.g. "yosys 0.55",
  "ARM CMSIS-SVD XSD 1.0").
- `static_checks_run`: a list of every `code` actually invoked
  in this run. A check that did not run goes in
  `unknown.static_checks_not_run`, not in this list.
- `tested_roundtrips_run`: analogous.
- `unknown_items`: free-form list of items the report cannot
  classify. An empty list is valid; an absent field is not.

The golden suite `tests/report/report_cancho_golden.py` asserts all of
the above: the report's catalog equals the §2 table (set + count),
and corrupted copies (missing fields, dropped rows, inflated
counts) are refused by `validate_report` with the two codes above.

---

## 4. Tier promotion rules

A guarantee may not be promoted to a higher tier without
explicit evidence:

| From | To | Requires |
|---|---|---|
| `Unknown` | `Static` | A checker rule that mechanically enforces it, with at least one refusal test |
| `Static` | `Tested` | A roundtrip suite that exercises the guarantee end to end, with at least one passing and one failing case |
| `Tested` | `Trust` | (Not used. `Trust` is for things outside the tool's control.) |

A tier that does not appear above is either forbidden
(`Static -> Trust`) or not yet defined. The report never
relabels `Trust` as `Static`. The report never relabels
`Unknown` as anything.