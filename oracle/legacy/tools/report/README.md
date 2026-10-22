# oracle/legacy/tools/report/

> **Status: Phase 2 — landed.** Implemented at `report.py`; pinned
> by `tests/report/report_cancho_golden.py`. The output shape is
> [`spec/diagnostics/README.md`](../../spec/diagnostics/README.md)
> §6, restating every row of
> [`docs/guarantees.md`](../../docs/guarantees.md) §2 verbatim.

## Command

```sh
python3 oracle/legacy/tools/report/report.py <contract.chw>             # JSON
python3 oracle/legacy/tools/report/report.py <contract.chw> --pretty    # indented JSON
python3 oracle/legacy/tools/report/report.py <contract.chw> --output text
python3 oracle/legacy/tools/report/report.py <contract.chw> --strict    # exit 1 if any tier not "passed"
python3 oracle/legacy/tools/report/report.py <contract.chw> --strict    # exit 1 if any tier not "passed"
python3 oracle/legacy/tools/report/report.py <contract.chw> --no-roundtrips
```

## Where the evidence comes from

Every claim in the report is derived from a run performed during
this invocation — nothing is hardcoded:

| Tier | What runs | Claim |
|---|---|---|
| `Static` | the schema pass (when `jsonschema` is importable) + the static checker with its instrumented rule groups | `checks_run` lists the catalog codes whose governing evaluation executed; groups that could not run (no DMA buffers, no interrupts, no schema library) are listed in `unknown.static_checks_not_run` |
| `Tested` | the c-header generator + a real compile (`clang`/`gcc`, `-Wall -Wextra -Werror -std=c11`); the systemverilog generator + a real parse when iverilog is on `$PATH` | `roundtrips_run` lists what ran; a skipped roundtrip is `outcome: "skipped"` — it never counts as passed |
| `Runtime` | the schema-version compatibility check (the Runtime-tier rule family) | `checks_performed` |
| `Trust` | each compiler / parser the roundtrip leaned on, with its `--version` string | `boundaries` — always labeled `Trust`, never relabelled |
| `Unknown` | unavailable lanes, unenforced constraint semantics, the missing behavioral roundtrip | `items` + `static_checks_not_run` |

## The self-refusals (§6.2)

`validate_report(doc)` re-checks the document before it is emitted
and refuses its own output with exactly two codes:

- `report-schema-truncated` — a mandatory field
  (`non_guarantees`, `trust_boundaries`, `static_checks_run`,
  `tested_roundtrips_run`, `unknown_items`) is **absent**, or the
  §2 restatement is not verbatim (a dropped or paraphrased row).
- `evidence-over-claim` — a count that cannot add up
  (`passed+failed != len(list)`), a check claimed outside the
  catalog, a skipped roundtrip counted as run, a fired `Error`
  not in `checks_run`, or a `Trust` boundary labeled as anything
  other than `Trust`.

The conformance `evidence-over-claim` lane is this function fed
intentionally corrupted report copies — `tests/report/
report_golden.py` ("corrupted reports are refused" section).

## Honesty rules

- A **refused contract gets a complete report**: the refusal is
  the `static` evidence, and the roundtrips are listed
  `outcome: "skipped"` with the refusal as the reason — the
  generators never run on an invalid IR.
- A **contract that does not parse** reports only the parse
  refusal and skipped roundtrips; `--strict` exits 1.
- An **empty optional lane is valid** (absent is not): an empty
  `trust_boundaries` simply means nothing external was trusted
  this run.

## Exit codes

`0` for a report with every tier passed (or no `--strict`).
`1` when `--strict` found a tier not passed — refused contract,
failed roundtrip, skipped roundtrip, or a runtime failure. The
full JSON was already emitted. `2` usage.
