---
name: cancho-hdl
description: Check hardware register contracts (.chw files) and see which generated artifacts a change makes stale, with cancho-hdl: one contract for registers, fields, interrupts and DMA layouts, refused with a located diagnostic when it contradicts itself. Use when the user wants a .chw contract checked or changed, a C header, device tree, SystemVerilog, bindings or SVD generated from it, or wants to know what a register-map change invalidates.
---

# cancho-hdl

cancho-hdl declares the software/hardware boundary once in a `.chw` file, refuses contradictions with a stable diagnostic code, and generates the copies (C header, Cancho bindings, device tree, SystemVerilog register RTL, CMSIS-SVD). The product is `chw`, one program written in cancho: `parse`, `validate`, `check`, `generate`, `diff`, `impact`, `report` and `conform`. The Python tools are kept under `oracle/legacy/` as the test oracle that `chw` is held to. Python is the test oracle, never new product logic.

## Rules (always)

- Never use `sudo`. Do not install system packages without asking.
- Paths that go into a shell command may hold only letters, digits and `. _ / + : = @ % , -`.
- Do not retry a failing command in a loop, and do not edit the repository to make a command pass. Report what failed, with the exact error.
- Do not claim more than was checked. Timing, vendor toolchains and working hardware are trust boundaries, never "verified". Semantic rules (overlaps, alignment, interrupts) are checked only by the Python reference today.
- The compiler is pinned in `.cancho-rev`; the Python oracle needs `jsonschema==4.26.0`.

## 1. Install (once)

Follow `docs/agent-prompt.md` in the cancho-hdl repository: clone `cancho-hdl` and `cancho` side by side, check out the compiler at `.cancho-rev`, build it, export `CANCHO`, run `sh scripts/gate_cancho.sh` (exit 0) and `sh scripts/gate.sh` (GATE PASSED).

## 2. Check a contract

```
chw validate FILE.chw          # structure, with a line:column; exit 0 ok, 1 refused
chw parse FILE.chw             # the textual syntax to the IR as JSON
python3 oracle/legacy/tools/check/checker.py FILE.chw --output json    # the semantic rules (reference implementation)
```

On a refusal read the `code` (`schema-invalid`, `field-overlap`, `dma-bad-align`, ...), the position and the remediation. Fix that and check again.

## 3. What does my change invalidate?

```
python3 oracle/legacy/tools/diff/diff.py impact BASE.chw CANDIDATE.chw --pretty
```

It lists, per target (`c-header`, `cancho-binding`, `devicetree`, `systemverilog`, `svd`), whether the generated artifact is stale and why, decided by byte-comparing generator output.

## 4. Generate

```
python3 oracle/legacy/tools/generate/generate.py --target c-header FILE.chw > out.h
```

Targets: `c-header`, `systemverilog`, `devicetree`, `cancho-binding`, `svd`. Generated output is deterministic: do not hand-edit it.

## More

`README.md`, `docs/cancho-port.md`, `docs/guarantees.md`, `docs/contract-design.md`, `spec/diagnostics/README.md`.
