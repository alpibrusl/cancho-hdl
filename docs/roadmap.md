# Roadmap

> **Status: copy of parent proposal §9 with the cancho-hdl repo
> pointers filled in.** Each phase below names the files it
> touches in this repo. Estimates are planning ranges, not
> commitments; the parent proposal §9 is the source of truth
> for the schedule.

---

## Phase 0 — Contract schema and decision record

**Indicative duration:** 1–2 weeks.

**In this repo, that is:**

| Artifact | Path | State |
|---|---|---|
| Contract schema | `spec/contract-schema/` | drafted |
| Guarantees / non-guarantees | `docs/guarantees.md` | drafted |
| Diagnostic format | `spec/diagnostics/` | drafted |
| Valid and invalid examples | `examples/` | drafted (5 valid + 8 invalid, see below) |
| Generator targets | `spec/generators/README.md` | drafted (5 targets: c-header, cancho-binding, devicetree, systemverilog, svd) |
| Bus protocol | `spec/generators/README.md` | drafted (AXI4-Lite, memory-mapped slave) |

**Example counts landed in `examples/` for Phase 0:**

- `examples/uart-contract/uart.chw` — valid
- `examples/simple-dma/dma.chw` — valid
- `examples/refusal/` (11 cases):
  - `register-overlap.chw` — overlapping registers
  - `field-overlap.chw` — overlapping fields within a register
  - `field-out-of-bounds.chw` — `msb >= bus_width`
  - `enum-overflow.chw` — enum value doesn't fit
  - `reset-overflow.chw` — reset value doesn't fit
  - `interrupt-unresolved.chw` — interrupt points to nonexistent register
  - `dma-overlap.chw` — DMA fields overlap
  - `dma-bad-align.chw` — DMA field offset not aligned
  - `dma-owner-unknown.chw` — unknown owner literal
  - `kind-unknown.chw` — unknown access kind
  - `bus-width-invalid.chw` — bus width other than 8/16/32

The full count is 2 valid + 11 refusal = 13 examples, which
exceeds the parent proposal's "10–20 valid and invalid
examples" target when read as "10–20 total examples."

**Reference-model simulator (lands in Phase 0, ahead of schedule):**

- `tools/sim/reference_model.py` — interprets the contract IR
  with full access semantics. Tier `Runtime`.
- `tools/sim/scenarios/uart_basic.py` — 5 scenarios.
- `tools/sim/scenarios/dma_basic.py` — 6 scenarios.
- `tools/sim/test_refusal_runtime.py` — runtime twin of the
  schema-level refusal suite, 11 cases.
- `python3 tools/sim/run_scenarios.py` — runs all 22.

This makes the schema's claims falsifiable today: every rule
in the catalog has a corresponding runtime scenario that
either passes (the rule preserves correct behaviour) or fails
(the rule is broken). It is the oracle Phase 1's roundtrip
suite will compare the generators against.

**Exit criteria** (from parent proposal §9 Phase 0):

- [x] Two real peripherals expressible without ambiguity.
      UART + DMA descriptor are drafted in `examples/`.
- [x] Every proposed check has an enforcing mechanism.
      The rule catalog is in `spec/diagnostics/README.md` §3.
- [x] Refusal cases listed. `examples/refusal/` lists ten.

Stop/rethink if: the schema cannot express real datasheet
semantics without inventing per-device special cases. The
open question list in [`contract-design.md`](contract-design.md)
§5 is the watch list for that signal.

---

## Phase 1 — Checker and first generators

**Indicative duration:** 2–3 weeks.

**Delivered into this repo:**

- `tools/check/checker.py` — runs the full Static rule catalog
  from `spec/diagnostics/README.md` §3. Emits the diagnostic
  shape from §2 as JSON, with the stable field order from §4.1.
- `tools/check/diagnostic.py` — the diagnostic type, shared with
  the reference-model simulator.
- `tools/check/conformance.py` — refuses every fixture in
  `examples/refusal/` per its sidecar, with zero errors on the
  valid examples.
- `tools/check/checker.py --output json` — the agent-facing CLI
  surface. Exit codes match Cancho Core: `0` / `1` / `2` / `3`.
- `gen/c-header/c_header.py` — the c-header generator.
  Deterministic, byte-identical output for the same IR.
- `gen/systemverilog/systemverilog.py` — the AXI4-Lite
  register module generator. One-hot address decode, per-
  register storage, per-access-kind write logic, behavior
  output ports for the user to wire up, contract reset
  values applied on `!rst_n`.
- `tools/generate/generate.py` — the dispatcher. `--target`
  selects the generator; unknown targets emit
  `generator-target-unknown`; targets whose implementation is
  not yet on disk emit `generator-unimplemented`.
- `tests/roundtrip/c_header_compiles.py` — roundtrip test:
  generates the header for every valid example, compiles under
  clang and gcc with `-Wall -Wextra -Werror -std=c11`, runs a
  smoke program that touches the first register, and confirms
  the binary returns the value written.
- `tests/roundtrip/systemverilog_parses.py` — roundtrip test:
  structural check (module declaration, register output
  ports, address localparams, reset values, access-kind
  handling, stable IDs, enum localparams, write-decode and
  read-decode branches). If iverilog, slang, or yosys is on
  `$PATH`, the test also runs a real parse.
- `tools/parse/parser.py` — the textual `.chw` parser. Hand-
  written tokenizer + recursive descent, no dependencies,
  deterministic, position-accurate `parse-error` diagnostics.
  The grammar is frozen at
  [`spec/contract-schema/README.md`](../spec/contract-schema/README.md)
  §10. `checker.py::check_file` and every script load contracts
  through it, so both source forms flow through the whole
  pipeline.
- `tools/check/text_format.py` — the `Diagnostic` text
  formatter (spec §5). Derived from the JSON form: the renderer
  projects each diagnostic onto `to_dict()` and prints only what
  the dict carries. Lanes documented in
  [`spec/diagnostics/README.md`](../spec/diagnostics/README.md)
  §5.1; output pinned byte-for-byte by
  `tests/text_format/golden.py`. `check` without `--output json`
  renders through it.
- `examples/textual/uart.chw` and `examples/textual/dma.chw` —
  the two valid peripherals in the frozen text form. Their
  parsed IR is asserted identical (modulo hex case) to the JSON
  wire forms by `tests/parser/parser_roundtrip.py`.
- `examples/refusal/parse-error.chw` — the refusal fixture
  exercising `parse-error` through the conformance suite.

**Delivered (Phase 1 → 2 remainder, C side):**

- C-side behavioral roundtrip
  (`tests/behavioral/c_behavior.py`): every corpus scenario
  (`tests/behavioral/scenarios.json`, mirroring the 11 Python
  scenarios op-for-op) is executed against BOTH the reference
  model (`tools/sim/op_runner.py`) and a compiled C harness that
  binds the generated c-header — block struct as the register
  file, per-register view typedefs overlaid for field RMW,
  RESET_* macros sourced at reset, packed DMA structs, and
  `_Static_assert` offsets for every register and DMA field.
  Traces must be identical line by line, refusals included.
  Seeded-drift negative lanes prove the comparison catches a
  wrong reset value and a wrong field position. The harness's
  access-kind port is a test fixture, not generated; the SV
  module remains the only generated device model.

**Not yet delivered (Phase 1 remainder):**

- SV-side behavioral roundtrip: the SystemVerilog module must be
  driven with the same corpus (`tests/behavioral/scenarios.json`
  and `tools/sim/op_runner.py`'s trace shape are already
  engine-agnostic for it) and compared against the reference
  model. This needs hardware-simulation tooling (Verilator or
  cocotb are not in the reference environment); the C-side pair
  above is operational evidence for the criterion's C half.

**Exit criteria (in progress):**

- [x] `examples/uart-contract/uart.chw` and
      `examples/simple-dma/dma.chw` pass the checker.
- [x] Every `examples/refusal/*.chw` is refused with the
      diagnostics named in its sidecar.
- [x] `tools/check/conformance.py` passes.
- [x] `cancho-hdl generate --target c-header` produces
      compile-ready output.
- [x] `cancho-hdl generate --target systemverilog` produces
      structurally-correct output (parse-ready when iverilog,
      slang, or yosys is available).
- [x] The textual `.chw` syntax is frozen and parsed. Both text
      references parse to the same IR as their JSON twins
      (`tests/parser/parser_roundtrip.py`), and the checker,
      generators, and scripts accept both forms.
- [x] Every diagnostic can be rendered human-readably, derived
      from the JSON form (`tools/check/text_format.py`), with
      the output pinned by `tests/text_format/golden.py`.

Stop/rethink if: generated SystemVerilog needs constant
hand-editing to be usable — that means the contract model is
too thin. The watch list is [`contract-design.md`](contract-design.md)
§5 questions 1, 2, 5.

---

## Phase 2 — Full generator set, diff, impact, report

**Indicative duration:** 2–3 weeks.

**Delivered into this repo (complete; only the SV-side behavioral roundtrip remains, needing Verilator or cocotb):**

- `cancho-hdl diff <base> <candidate>` (`tools/diff/diff.py`) —
  the semantic-diff JSON in `spec/diagnostics/README.md` §7,
  with the §7.0 matching/classification/refusal rules and the
  whole taxonomy pinned by `tests/diff/diff_golden.py`.
- `cancho-hdl impact <base> <candidate>` — the §7 document plus
  `affected_artifacts`. Staleness is decided by byte-comparing
  generator output for base vs candidate; implemented targets
  (c-header, systemverilog) get `stale: true/false` with
  reasons, unimplemented ones get `stale: null` ("not checked").
- The seeded-change exit criterion below is exercised by
  `tests/diff/diff_golden.py` ("seeded change" section) against
  `tests/diff/fixtures/uart_rebase.chw` — the criterion's status
  flips to `[x]` when all five targets participate (three
  generators still pending).

**Delivered into this repo:**

- **`devicetree` generator — landed**: `gen/devicetree/
  devicetree.py`, pinned by `tests/roundtrip/
  devicetree_generates.py` (shape, determinism, §4.2 reg
  formula, conditional interrupt lines, refusal lane, dispatcher
  refusal of invalid contracts). Joins the impact list's
  byte-comparison set — the seeded change now yields three
  measured `stale: true` rows and two honest `stale: null`s.

- **`cancho-binding` generator — landed**: `gen/cancho-binding/cancho_binding.py`,
  pinned by `tests/roundtrip/
  cancho_binding_validates.py` (accessor palette per register
  kind, uniform register-prefixed names, enum declarations,
  capability groups, the DEVICE-no-setter rule, and the shared
  size refusal — the binding and the c-header now refuse the
  same degenerate input together). Joins the impact
  byte-comparison set — and immediately proved its worth: for
  the seeded rebase the binding is byte-identical (it encodes
  names, widths, kinds — not offsets), so the impact tool
  correctly reports `stale: false` where a rule-based oracle
  would have flagged it.
- **`svd` generator — landed**: `gen/svd/svd.py`, the CMSIS-SVD
  XML (schema 1.3 XSD vendored at `spec/generators/CMSIS-SVD.xsd`
  with ARM's license header), pinned by `tests/roundtrip/
  svd_validates.py` (XSD validation via lxml, the §6.1 access
  map — including `modifiedWriteValues`/`readAction` for
  `W1C`/`W0C`/`W1S`/`W0S`/`RC` — the §6.2 undefined-reset and
  comment rules, the §6.3 no-`<interrupt>` rule, and the
  zero-register / `--`-in-name / unknown-kind refusals). The
  peripheral `<name>` is the block name verbatim; enum fields
  emit `<enumeratedValues>`. Joins the impact byte-comparison
  set — for the seeded rebase the `svd` row flips from
  `stale: null` to a measured `stale: True` (its bytes carry
  the map's offsets), and the impact criterion is now
  measured across all five targets with zero `null` rows.
- Roundtrip suite for all five generators (all five landed).
- **`cancho-hdl report` — landed**: `tools/report/report.py`
  produces the §6 evidence report with every mandatory
  `docs/guarantees.md` §3 field (`non_guarantees` restates §2
  verbatim — the golden suite pins the catalog against the
  markdown table itself), honest provenance
  (`unknown.static_checks_not_run` for rule groups that did not
  execute; skipped roundtrips never counted as passed), and the
  report's self-refusals (`report-schema-truncated`,
  `evidence-over-claim`) exercised by
  `tests/report/report_golden.py` on corrupted copies.

**Exit criteria:**

- [x] A seeded register-map change (widen `BAUD_DIV` from 8 to
      12 bits, move `STATUS`; the fixture rebases the whole map
      by +8 to stay overlap-free) produces a correct impact
      list across all five generated artifacts — four stale
      with reasons (c-header, systemverilog, devicetree, svd),
      one measured NOT stale with the byte-identical proof
      (cancho-binding: it encodes names, not offsets). No
      `stale: null` rows remain: every MVP generator is
      implemented.
- [x] The report never claims more than it checked. The
      `evidence-over-claim` rule catches over-claiming —
      `validate_report` refuses the report itself, and the
      conformance lane feeds it corrupted copies (landed with
      the report generator; §6.3).
- The report restates every row of [`docs/guarantees.md`](guarantees.md)
  §2 verbatim — [x] pinned by the golden catalog equality test.

Stop/rethink if: impact analysis needs per-language plugins
for every question — scope the queries harder. (Byte-comparison
staleness avoided the per-language plugin entirely: the
generator's output *is* the impact oracle.)

---

## Phase 3 — Demo integration and agent benchmark

**Indicative duration:** 2–4 weeks.

**Delivered:**

- UART + DMA demo, simulator-first; board optional.
- Seeded-change task set, hand-maintained baseline.
- Benchmark protocol and results report published under
  `docs/benchmarks/` (to be created at Phase 3 start).

**Example agent tasks:**

- Widen `BAUD_DIV` and update the driver correctly.
- Move a register without breaking the device tree.
- Change a DMA descriptor field and fix all affected code.
- Attempt an access-semantics violation and be refused.

**Metrics:**

- Correctness of propagated changes.
- Missed artifacts.
- Repair iterations.
- Human interventions.
- Contract violations introduced.

**Exit criteria:**

- Tasks repeatable via documented protocol.
- Results include failures and limitations.

Stop/rethink if: no measurable reduction in drift/regression
errors versus the baseline. Per the parent §9, the action in
that case is "publish the checker and diff tooling as
standalone utilities and stop before Stage B."

---

## Phase 4 — Stage B decision gate

**Indicative duration:** 1 week.

A written decision record at `docs/stage-b-decision.md` (created
at gate time): proceed to the HDL front end only with evidence
from Phase 3 and a concrete use case. Otherwise maintain Stage
A as a tool. The `hdl/` subtree from parent proposal §4 is
**not** created in this repo until the gate passes.

---

## Status summary

| Phase | Status |
|---|---|
| 0 — Schema and decisions | **Done** |
| 1 — Checker + first generators | **Code complete** (checker, both generators, simulator, textual parser, text formatter landed; C-side behavioral roundtrip landed — only the SV side, needing Verilator/cocotb, remains, shared with Phase 2) |
| 2 — Full generators + diff + impact + report | **Code complete** (diff, impact, report, all five generators, all five roundtrip tests, C-side behavioral roundtrip landed; only the SV-side behavioral roundtrip still needs Verilator/cocotb — the single open item) |
| 3 — Demo + benchmark | Not started |
| 4 — Stage B gate | Not started |

A phase is "done" only when its exit criteria pass under CI.
A phase is "started" when the first commit lands against its
deliverables. The status table updates at every commit.