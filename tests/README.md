# tests/

> **Status: Phase 1 complete; Phase 2 in progress.** Conformance,
> refusal, c-header and systemverilog roundtrips, the textual
> parser roundtrip, the formatter golden, and the diff/impact
> golden are implemented and gated by `scripts/run_gate.py`.

| Directory | Phase | Contents |
|---|---|---|
| `tests/conformance/` | 1+ | Snapshot tests pinning every diagnostic, generator output, and report to a checked-in file |
| `tests/diff/` | 2 | Golden suite for the semantic diff and impact documents; includes the seeded Phase 2 change fixture (`fixtures/uart_rebase.chw`) |
| `tests/parser/` | 1 | Textual-parser roundtrip: identity with the JSON wire form, determinism, span positions |
| `tests/refusal/` | 1+ | Refusal fixtures (the canonical sources are in `examples/refusal/`; this directory holds CLI-level tests) |
| `tests/report/` | 2 | Golden suite for the evidence report: verbatim non-guarantee restatement, provenance arithmetic, over-claim refusals |
| `tests/roundtrip/` | 1+ | "Generate then compile / re-parse / re-validate" tests; one per landed generator (`c_header_compiles`, `systemverilog_parses`, `devicetree_generates`, `cancho_binding_validates`) |
| `tests/text_format/` | 1 | Golden blocks for the human-readable diagnostic form, plus the derive-from-JSON property |

## Phase 1 minimum

- [x] `tests/conformance/valid.rs` equivalent — every example in
      `examples/MANIFEST.json#valid` passes the checker.
      (Lives at `tools/check/conformance.py`.)
- [x] `tests/conformance/refusal.rs` equivalent — every sidecar
      in `examples/refusal/` is matched by the checker's output.
      (Lives at `tools/check/conformance.py`.)
- [x] `tests/conformance/diagnostics.rs` equivalent — every
      rule code in `spec/diagnostics/README.md` §3 has a
      snapshot test that pins the diagnostic JSON shape.
      (Live conformance in `tools/check/conformance.py`; full
      snapshot pinning lands in Phase 2.)

## Phase 1 roundtrip minimum

- [x] `tests/roundtrip/c_header_compiles.py` — generated C
      header compiles under `clang-21` and `gcc-15` with
      `-Wall -Wextra -Werror -std=c11`, and a smoke binary
      that touches the first register runs and returns the
      expected value.
- [x] `tests/roundtrip/systemverilog_parses.py` — generated
      SystemVerilog module passes a structural check (module
      declaration, register output ports, address localparams,
      reset values, access-kind handling, stable IDs, enum
      localparams, write-decode and read-decode branches). If
      `iverilog`, `slang`, or `yosys` is on `$PATH`, a real
      parse is also run.

## Phase 2 (in progress)

- [x] `tests/diff/diff_golden.py` — the semantic-diff document
      and impact list are pinned: identity across source forms,
      determinism, the seeded roadmap change
      (`fixtures/uart_rebase.chw`), refusal of invalid
      contracts, and the widened/narrowed/repositioned
      classification units.
- [x] `tests/report/report_golden.py` — the §6 evidence report
      is pinned: the non-guarantee catalog equals the
      `docs/guarantees.md` §2 table byte-for-byte, the report's
      counts are arithmetically derivable from what ran, refused
      contracts still yield complete reports, and corrupted
      report copies are refused by `validate_report` with
      `report-schema-truncated` / `evidence-over-claim`.
- [x] `tests/roundtrip/cancho_binding_validates.py` — the
      accessor palette per register kind, the DEVICE-no-setter
      rule, the shared size refusal (binding + c-header refuse
      the same input), and the dispatcher refusal lanes.
- [ ] Snapshot tests for the remaining Phase 2 generator (`svd`)
      as it lands.