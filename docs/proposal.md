# Proposal

This is the cancho-hdl entry point. The full proposal lives at
[`../Cancho-HW-Design-and-MVP-Roadmap.md`](../Cancho-HW-Design-and-MVP-Roadmap.md).
This page exists so the repo stands alone.

## Status

Initial proposal, Phase 0 → 1. The static checker is now
implemented and the conformance suite passes every refusal
fixture. Working name in the parent document is `cancho-hw`;
this repo is `cancho-hdl`. See the repo
[`README.md`](../README.md) for why.

## One paragraph

A typed source of truth for the software/hardware boundary —
register maps, fields, interrupts, DMA buffer layouts — from
which C headers, Cancho bindings, device-tree fragments,
SystemVerilog register modules, and CMSIS-SVD XML are generated,
checked, and diffed. The differentiator is not a new HDL; it is
explicit contracts and machine-readable evidence at the place
where AI agents already lose the most information today.

## Where to read

| Question | Where |
|---|---|
| What does the contract language express? | [`contract-design.md`](contract-design.md) |
| What does the tool verify, and what does it explicitly not? | [`guarantees.md`](guarantees.md) |
| When does each piece ship? | [`roadmap.md`](roadmap.md) |
| What does a diagnostic look like? | [`../spec/diagnostics/README.md`](../spec/diagnostics/README.md) |
| What does a `.chw` file look like? | [`../spec/contract-schema/README.md`](../spec/contract-schema/README.md) |
| What do the generators produce? | [`../spec/generators/README.md`](../spec/generators/README.md) |
| What do working examples look like? | [`../examples/`](../examples/) |

## Decisions taken in Phase 0

| Decision | Choice | Rationale |
|---|---|---|
| Repo name | `cancho-hdl` | Distinguishes Stage A (contract layer) from Stage B (HDL front end) |
| File extension | `.chw` (Cancho HardWare) | Matches the parent proposal §7 |
| Source schema | JSON, validated by JSON Schema | Stays out of "yet-another-parser" territory in Phase 1 |
| Bus protocol for MVP | AXI4-Lite (memory-mapped slave) | Listed in parent proposal §8.3; one protocol done well beats five done badly |
| License direction | EUPL-1.2 (matches Cancho) | Per parent proposal header |
| First deliverable order | schema → c-header generator → remaining generators → diff/impact/report | `c-header` is the primary software consumer; the parent proposal §8.2 places it first |

## Decisions deferred to Phase 1

- Concrete syntax of the `.chw` source. The parent proposal §5.2
  is explicit that the syntax "must not be frozen until the
  checker and generators have validated the model on two real
  peripherals." Phase 0 lands the **schema**; Phase 1 lands the
  parser that produces it from `.chw` text.
- Tool implementation language. The parent ecosystem is Rust
  (see `cancho-ui/`); the natural choice is also Rust, but no
  commitment is made in Phase 0.