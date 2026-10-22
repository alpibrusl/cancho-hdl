# oracle/legacy/tools/parse/

> **Status: Phase 1.** The textual `.chw` parser is implemented.
> The grammar is frozen at
> [`spec/contract-schema/README.md`](../../spec/contract-schema/README.md)
> §10.

## What it does

Turns the textual contract syntax (parent proposal §5.2, frozen
as of Phase 1) into the JSON wire form the checker and generators
consume. After this parser, JSON is an interchange concern, not a
user-facing one: a `register-block` is written in text and read
everywhere.

- Hand-written: tokenizer + recursive descent, no dependencies.
- Deterministic: same source, same IR, always.
- Position-accurate: parse errors carry real line/column spans
  (1-indexed), not whole-file spans.
- Format-tolerant: a `.chw` file whose first non-whitespace
  character is `{` is read as the JSON wire form; anything else
  goes through the tokenizer.

```sh
python3 oracle/legacy/tools/parse/parser.py examples/textual/uart.chw   # IR to stdout, on one line
```

## Public API

```python
from parser import parse_source_text, load_contract

ir, diags = parse_source_text(src, "uart.chw")   # text -> (IR | None, diagnostics)
ir, diags = load_contract("uart.chw")            # path -> (IR | None, diagnostics), sniffs format
```

On a syntax error, `ir` is `None` and `diagnostics` holds exactly
one `parse-error` diagnostic — code `parse-error`, tier `Static`,
subject `Ir`, span naming the offending token, message naming
what was expected. The diagnostic shape is the shared one from
[`oracle/legacy/tools/check/diagnostic.py`](../check/diagnostic.py).

## Where it plugs in

`oracle/legacy/tools/check/checker.py::check_file` runs `load_contract` first,
so both source forms flow through schema validation and the
static rule catalog unchanged. The roundtrip tests
(`tests/roundtrip/`) and `scripts/verify_examples.py` use the
same loader. Anything that loads a contract accepts both forms.

## Tests

- `tests/parser/parser_roundtrip.py` — textual examples parse to
  IR identical to their JSON twins; determinism; span positions
  pinned on synthetic inputs; the refusal fixture emits
  `parse-error` at the documented span.
- `examples/refusal/parse-error.chw` + sidecar — the fixture
  exercising the rule through the conformance suite.
- `examples/textual/` — the two valid examples in text form,
  normative cross-references of the frozen grammar.

## Not here

The inverse direction (JSON → text) is a Phase 2 nicety, not a
Phase 1 need: nothing consumes it, and a formatter without an
enforcing grammar is a silent-drift risk. The analogous promise
for diagnostics — the `--output json` / human-readable
discipline (`spec/diagnostics/README.md` §5) — is landed: the
JSON contract renders through `oracle/legacy/tools/check/text_format.py`, and
the golden test pins it.
