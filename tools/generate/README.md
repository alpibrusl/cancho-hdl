# tools/generate/

> **Status: Phase 2 (partial).** The dispatcher loads four
> generator targets (`c-header`, `systemverilog`, `devicetree`,
> `cancho-binding`); `svd` is registered and refuses with
> `generator-unimplemented` until its implementation lands.
> Accepts both source forms (JSON wire file and the frozen
> textual `.chw` syntax) via the parser entry point.

## Command

```sh
python3 tools/generate/generate.py --target c-header <file.chw>
python3 tools/generate/generate.py --target systemverilog <file.chw>
python3 tools/generate/generate.py --target devicetree <file.chw>
python3 tools/generate/generate.py --target cancho-binding <file.chw>
```

| Target | Phase | Output |
|---|---|---|
| `c-header` | 1 — landed | `*.h` |
| `systemverilog` | 1 — landed | `*.sv` |
| `devicetree` | 2 — landed | `*.dtsi` |
| `cancho-binding` | 2 — landed | `*.cancho` |
| `svd` | 2 — pending (registered; refuses) | `*.svd` |

The dispatcher is the single source of truth for which targets
exist. `cancho-hdl generate --help` prints the supported set.

## Targets

| Target | Phase | Output |
|---|---|---|
| `c-header` | 1 — landed | `*.h` |
| `systemverilog` | 1 — landed | `*.sv` |
| `devicetree` | 2 — landed | `*.dtsi` |
| `cancho-binding` | 2 — landed | `*.cancho` |
| `svd` | 2 — pending (registered; refuses) | `*.svd` |

A `--target` invocation with an unimplemented target emits
`generator-unimplemented` (tier `Unknown`). An unknown target
emits `generator-target-unknown` (tier `Static`). A declared
feature the registered generator cannot emit (e.g. a `devicetree`
fragment whose base address does not fit one 32-bit address cell)
also refuses as `generator-unimplemented` — never a partial file.

The dispatcher loads the contract through the parser entry point
(both source forms), runs `cancho-hdl check` first, and any
structural failure aborts the generate run with the underlying
diagnostic unchanged — the same refusal lane `diff` uses.

## Exit codes

Same as `check`: `0` / `1` / `2` / `3`.

## Phase 1 exit criteria

- [x] The c-header generator is implemented.
- [x] `tests/roundtrip/c_header_compiles.py` passes: every
      valid example generates, clang + gcc compile clean, and
      the smoke binary runs and returns the expected value.
- [x] The systemverilog generator is implemented; structural
      check passes; if iverilog, slang, or yosys is on `$PATH`,
      a real parse is run.
- [ ] Roundtrip: the same scenario sequence runs through the C
      header accessors and the SystemVerilog module, and they
      agree on register state with the reference model. (Phase 2:
      needs Verilator or cocotb.)