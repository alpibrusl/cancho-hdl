# oracle/legacy/tools/diff/

> **Status: Phase 2 (partial).** `diff` and `impact` are
> implemented and pinned by `tests/diff/diff_golden.py`. Four
> of five targets have joined the byte-comparison set
> (c-header, systemverilog, devicetree, cancho-binding — where
> the seeded rebase proved a byte-identical binding stays
> fresh); only `svd` remains a `stale: null` lane.

## What it does

Two documents, one tool:

- **`diff <base> <candidate>`** — the §7 semantic-diff document.
  What the change *means*: registers added/removed/moved, fields
  widened/narrowed/repositioned/added/removed, enum value
  changes, interrupt linkage changes, DMA layout changes, reset
  value changes, block property changes. Stable IDs
  (`chw:<block>.register.<name>.field.<field>`) are the handles
  an agent greps generated code by.
- **`impact <base> <candidate>`** — the §7.1 document: the same
  diff plus `affected_artifacts`. For each generator target,
  staleness is decided by **byte-comparing the generator's
  output for base vs candidate** — `stale: false` means the
  generator actually ran and produced identical bytes;
  `stale: null` means the generator has not landed and the
  target is reported as *not checked*, never as "no change."

```sh
python3 oracle/legacy/tools/diff/diff.py diff   examples/uart-contract/uart.chw tests/diff/fixtures/uart_rebase.chw --pretty
python3 oracle/legacy/tools/diff/diff.py impact examples/uart-contract/uart.chw tests/diff/fixtures/uart_rebase.chw
```

## Refusals

Both inputs go through the static checker first. A contract the
checker refuses fails the diff with that refusal on stderr and
exit 1 — a semantic diff of an invalid contract is worse than
no answer.

## Matching and classification

The rules are normative at
[`spec/diagnostics/README.md`](../../spec/diagnostics/README.md)
§7.0; in short:

- Registers (and fields) match **by name**, not order —
  reordering is not a diff.
- Offsets and resets are hex-case-insensitive (`0x0C == 0x0c`);
  the report carries the candidate's literal form.
- A changed bit range is exactly one of widened / narrowed /
  repositioned. The three classes are mutually exclusive and
  exhaustive.
- Interrupts match by name; linkages are compared per role
  (`number`, `source`, `enable`, `status`, `clear`).
- DMA buffers match by name; fields per field; an ownership or
  coherence flip is called out explicitly (it is the flip the
  whole DMA model is built on).

## Why byte-comparison for staleness

A rule-based staleness oracle ("field changes → header is
stale") duplicates the generator's knowledge and will drift the
first time someone enriches the header with a new section. The
bytes do not lie: if both contracts produce the same artifact,
the artifact is not stale; if they differ, it is. The cost is
two generator runs per implemented target, which is nothing at
this scale.
