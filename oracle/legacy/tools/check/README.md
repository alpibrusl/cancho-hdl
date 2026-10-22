# oracle/legacy/tools/check/

> **Status: Phase 1.** The static checker is implemented. The
> schema, the rule catalog, and the refusal examples are the
> contract the checker enforces.

## Command

```sh
python3 oracle/legacy/tools/check/checker.py <file.chw>...                  # parse + structural checks
python3 oracle/legacy/tools/check/checker.py <file.chw>... --output json    # ... and which rule, as data
```

The full gate is `scripts/gate.sh`, which runs schema
validation, the checker conformance suite, and the reference-model
scenarios. All three must pass for the gate to exit 0.

## Exit codes (per Cancho Core `agent-errors.md`)

| Code | Meaning |
|---|---|
| `0` | All files passed every check |
| `1` | One or more files emitted at least one `Error` |
| `2` | Usage error (no files, unknown flag, etc.) |
| `3` | Internal toolchain error (`internal` diagnostic) |

## What it does

1. Reads each `<file.chw>` through `oracle/legacy/tools/parse/parser.py`, which
   sniffs the format: the JSON wire form and the textual `.chw`
   form per
   [`spec/contract-schema/README.md`](../../spec/contract-schema/README.md)
   §10 are both accepted, and files in the textual form are
   parsed first (a syntax error emits `parse-error` with a real
   line/column span per `spec/diagnostics/README.md` §3.1).
2. Validates against the JSON Schema in
   `spec/contract-schema/cancho-hdl-contract.schema.json`. Failure
   emits `schema-invalid` per file.
3. Runs every Static rule in
   [`spec/diagnostics/README.md`](../../spec/diagnostics/README.md)
   §3 against the IR. Every rule has at least one refusal fixture
   in `examples/refusal/` and one snapshot test in
   `chw conform .` (the retired `conformance.py` was its Python twin).
4. Emits every independent refusal. The first refusal does not
   stop the run.
5. Writes diagnostics to stdout in the requested form. `--output
   json` is the contract (`spec/diagnostics/README.md` §4).
   With no flags, the text form of §5 is printed — derived from
   the JSON value by `oracle/legacy/tools/check/text_format.py`, never the
   other way around.

## What it does not do
- Generate anything. `cancho-hdl generate` does that.
- Diff or impact. `cancho-hdl diff` and `cancho-hdl impact` do
  that.
- Verify generated RTL beyond what the generators test. Tier
  `Trust`; reported in `cancho-hdl report` only.

## What Phase 1 has added

- `checker.py` — runs the full Static rule catalog.
- `diagnostic.py` — the diagnostic shape, shared with the
  reference-model simulator.
- `conformance.py` (retired; `chw conform .` replaces it) — the refusal-fixture harness. Loads every
  `examples/refusal/<name>.expect.json` and asserts the checker
  emits the named diagnostic(s).

## Exit criteria met

- `examples/uart-contract/uart.chw` and
  `examples/simple-dma/dma.chw` exit `0` (only a
  `field-constraint-ignored` warning for `BAUD_DIV`, which is
  the documented Phase-0 limitation).
- Every `examples/refusal/<name>.chw` exits `1`, and the
  emitted diagnostics match the sidecar
  `examples/refusal/<name>.expect.json`.
- `chw conform .` (the retired `conformance.py` was its Python twin) passes.
- `scripts/gate.sh` passes (schema + checker + simulator).