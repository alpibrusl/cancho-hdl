# gen/

> **Status: Phase 2 — complete.** All five generator
> implementations are landed: `c-header`, `systemverilog`
> (Phase 1), and `devicetree`, `cancho-binding`, `svd`
> (Phase 2), plus the `oracle/legacy/gen/common.py` shared-refusal helper.

| Subdirectory | Target | Phase |
|---|---|---|
| `oracle/legacy/gen/c-header/` | `c-header` | 1 — landed |
| `oracle/legacy/gen/systemverilog/` | `systemverilog` | 1 — landed |
| `oracle/legacy/gen/devicetree/` | `devicetree` | 2 — landed |
| `oracle/legacy/gen/cancho-binding/` | `cancho-binding` | 2 — landed |
| `oracle/legacy/gen/svd/` | `svd` | 2 — landed |

The directory for each target exists now so the repo layout
matches parent proposal §4 from day one. Each landed target has
a roundtrip test under `tests/roundtrip/`. The landed size
refusal in the c-header and the binding now share
`oracle/legacy/gen/common.py::GeneratorUnimplemented`.

Each generator is a deterministic function from a contract IR
(see [`../spec/contract-schema/README.md`](../spec/contract-schema/README.md))
to a text artifact. The contracts for each target are normative
and live at [`../spec/generators/README.md`](../spec/generators/README.md).