# tools/

> **Status: Phase 1 complete; Phase 2 in progress.** `check/`
> and `generate/` (two of five targets) are landed and gated;
> `diff/` landed with `diff` + `impact`; `report/` landed
> (self-validating §6 evidence document).

This is the implementation entry point descending from the
Phase 0 layout. Each subdirectory contains a single command,
with its README as the contract it was built to satisfy:

| Directory | Command | Phase |
|---|---|---|
| [`check/`](check/) | `cancho-hdl check <file.chw>...` | Phase 1 — landed |
| [`generate/`](generate/) | `cancho-hdl generate --target <t> <file.chw>` | Phase 1 — landed (`c-header`, `systemverilog`); Phase 2 pending (`devicetree`, `cancho-binding`, `svd`) |
| [`diff/`](diff/) | `cancho-hdl diff <base> <candidate>` / `... impact ...` | Phase 2 — `diff` + `impact` landed; unimplemented generator targets report `stale: null` in impact |
| [`report/`](report/) | `cancho-hdl report` | Phase 2 — landed (`report.py`, §6 self-validating; `tests/report/report_golden.py`) |

Phase 0 has **no** tool implementations. Each subdirectory's
README is a contract for what Phase 1+ must build.

See [`docs/roadmap.md`](../docs/roadmap.md) for the
deliverable schedule.