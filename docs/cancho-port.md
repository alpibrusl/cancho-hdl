# Porting cancho-hdl to cancho

> **Status: design plus a measured spike.** Decision (taken before this
> document): the product is rewritten from scratch as **pure cancho**. The
> Python under `tools/`, `gen/` and `scripts/` is the *legacy reference
> implementation*, kept until each part is replaced and then deleted. The
> `.chw` examples, the refusal fixtures (`examples/refusal/*.expect.json`)
> and `tests/behavioral/scenarios.json` are language-neutral specifications
> and do not move. Python may remain **only** as test-only oracle code (§5).
>
> What is measured here is one slice: the textual parser, over the two
> textual examples (§7). Everything else in this document is a plan, and
> every number in it that is not from the spike is marked *estimate*.

Written against the cancho compiler in `../cancho` (`target/release/cancho`,
`--std`), `CONTRIBUTING.md` (the gate, no source file over 2,000 lines, every
refusal has a rule tag, no input reaches a panic), `AGENTS.md`, and the
proposal (`Cancho-HW-Design-and-MVP-Roadmap.md`, §3 "Generate, don't replace",
§3.7 "No claims beyond evidence").

---

## 1. What "done" means

1. `cancho-hdl parse | check | generate | diff | impact | report` are one
   cancho program, built with `cancho build`.
2. `cancho authority` of that program shows no `exec`, no `ffi`, no network
   (§5, rule 4). The product cannot shell out to Python, mechanically.
3. Every fixture and golden that pinned the Python tools pins the cancho tools,
   byte for byte, where the Python output was a contract (§6).
4. The Python product code is deleted. What remains of Python is under
   `oracle/` and is run only by the gate.

Non-goals: new features, a changed `.chw` grammar, a changed diagnostic shape.
A port that also redesigns cannot be diffed against its oracle (the
`examples/selfhost` lexer makes the same choice: "a line-for-line port, so
that any difference in behaviour is a finding").

---

## 2. What moves, and in what order

The order is the dependency order, and each stage ends with a differential
check against the Python tool it replaces (the oracle) before the Python is
removed.

| # | Stage | Python it replaces (lines) | Needs | Exit criterion |
|---|---|---|---|---|
| 0 | **IR + JSON out, textual parser** | `tools/parse/parser.py` (634) | nothing | **Spike, §7: done for the textual examples.** Byte-identical JSON on both examples; identical refusal text/position on 2,739 mutants |
| 1 | **JSON wire loader** (`std.json` tape to IR) and the **structural validator** that replaces `jsonschema` | `parser.load_contract` JSON branch, `checker._validate_schema`, `scripts/verify_examples.py` (78) | 0 | 11 of the 12 refusal fixtures are in JSON form (§6), so this gates the conformance suite. Validator verdict equals `jsonschema`'s on every example and every fixture mutant (oracle) |
| 2 | **Diagnostics + checker** | `tools/check/` (838 + 170 + 114 + 136) | 1 | `conform` passes: every sidecar matched, zero errors on the valid examples; `--output json` identical to Python's, key order included (`spec/diagnostics/README.md` §4.1) |
| 3 | **c-header generator** | `gen/c-header/c_header.py` (340) | 2 | Output byte-identical to Python's for both examples; gcc and clang roundtrip (oracle lane) still green; behavioral roundtrip still green against `scenarios.json` |
| 4 | **Remaining generators**: devicetree, cancho-binding, svd, systemverilog | `gen/*` (138 + 211 + 254 + 330) | 3, and the shared emit helpers | Same, per target. SVD additionally validates against `spec/generators/CMSIS-SVD.xsd` (oracle lane) |
| 5 | **diff / impact** | `tools/diff/diff.py` (470) | 2, 3, 4 (staleness is decided by byte-comparing generator output) | `tests/diff/` goldens, including the seeded Phase 2 change across all five targets |
| 6 | **report** | `tools/report/report.py` (617) | 2, 3, 4 | `tests/report/` goldens, the verbatim `docs/guarantees.md` §2 restatement, both self-refusals (`report-schema-truncated`, `evidence-over-claim`) |
| 7 | **CLI and deletion** | `tools/generate/generate.py` (144), `scripts/run_gate.py` (85) | all | `scripts/gate.sh` (§4) green with no Python product file left |

Why this order. The parser and checker first because every other stage
consumes the IR and a refusal is the product's whole discipline. The c-header
generator first among the generators because it has the strongest oracle in
the repository (a C compiler, plus the op-for-op behavioral roundtrip), so a
wrong port fails loudly. `diff` and `report` last because both are defined in
terms of other stages' output ("stale" is a byte comparison of generator
output; the report counts what actually ran).

The reference simulator (`tools/sim/`, 645 + 134 + ...) is **not** ported. It
is the oracle the generated artifacts are compared against, and an oracle
written in the same language by the same people as the thing it checks is a
weaker oracle (§5).

---

## 3. Module layout

One constraint drives it: no source file over 2,000 lines
(`crates/cancho/tests/files.rs` in the compiler repository; this repository
gets the same lint, §4). The target is **well under**: a design budget of 800
lines per file, so a file has room to grow before a split is forced.

Cancho modules are flat files with a dotted name (`module chw.lex;`), listed
on the command line; one concern per file, as `CONTRIBUTING.md` asks.

```
src/
  main.cho                CLI dispatcher: subcommands, exit codes 0/1/2/3
  chw/
    lex.cho               tokens                                   spike: 225
    ir.cho                IR records, adders, attribute order      spike: 243
    parse.cho             recursive descent over the token tape    spike: 640
    json_out.cho          IR to the JSON wire form                 spike: 320
    json_in.cho           wire form to IR (std.json tape)          estimate 300
    diag.cho              Diagnostic, tiers, subjects, spans       estimate 250
    diag_text.cho         human renderer (golden-pinned)           estimate 250
    check/
      schema.cho          structural validity (replaces jsonschema) est. 400
      block.cho           bus width, base, endianness              est. 200
      registers.cho       offsets, overlap, kinds, resets          est. 450
      fields.cho          bounds, overlap, enums, constraints      est. 600
      interrupts.cho      linkage resolution                       est. 250
      dma.cho             layout, alignment, owner                 est. 450
      driver.cho          order, severity, the catalog             est. 200
    emit.cho              indent / hex / identifier / line helpers est. 250
    gen/
      c_header.cho        est. 600      devicetree.cho  est. 250
      binding.cho         est. 370      svd.cho         est. 450
      systemverilog.cho   est. 600      dispatch.cho    est. 150
    diff/
      model.cho           semantic diff                            est. 600
      impact.cho          per-target staleness                     est. 250
    report/
      evidence.cho        what ran, counts                         est. 450
      guarantees.cho      the verbatim non-guarantees, as data     est. 200
      validate.cho        the two self-refusals                    est. 300
tests/
  unit_*.cho              `cancho test`, one file per module       (§4)
  conform.cho             fixture-driven runs, `cancho run`        (§6)
  golden/                 expected output, written only by the product
oracle/                   the only Python (§5)
```

*Estimates* are the Python line count times the one ratio measured so far,
**1.75** (parser: 634 Python lines against 1,108 for `lex`+`ir`+`parse`, §7),
rounded and then split by concern. One file's ratio is a thin basis: the
checker is arithmetic and comparisons, where the spike's ratio probably
overstates the cost; the SystemVerilog generator is text assembly, where it
probably understates it (§8.1). The estimates are there to show that no file
approaches the 2,000-line ceiling, not to schedule work. The largest estimate
is 600 lines.

---

## 4. How `cancho test` replaces the Python gates

`scripts/run_gate.py` runs thirteen checks. `cancho test` is part of the
replacement, not all of it, and one measured limit shapes the rest:

> **A test may borrow only `Heap` and `Io`.** Measured: a `fn test_*` with an
> `Fs` parameter is refused, exit 2 ("a parameter that is not a unique `Heap`
> or `Io` reference", `docs/testing.md` §3). A test cannot open a fixture.

So there are two kinds of check, and the split is by what they need:

* **Unit tests** (`cancho test tests/unit_*.cho <src files> --std`): embedded
  sources, pure functions of bytes. The spike's `test_chw.cho` is the model
  (11 tests, §7). Expected values are taken **from the oracle, never from the
  port**: the three tests whose columns the author guessed failed against the
  port, and the right numbers came from the Python parser.
* **Conformance programs** (`cancho run tests/conform.cho ... -- <dir>`): a
  program with `Fs` (narrowed to the examples directory; `std.dirs` can list
  it) and `Args`, that walks fixtures, runs the product's own functions, and
  exits non-zero on the first mismatch. This is where the refusal fixtures
  and the goldens live.

| Python gate check | Replaced by |
|---|---|
| 1 schema validation of examples | `conform.cho`: validator verdict per example; oracle lane cross-checks against `jsonschema` (§5) |
| 2 checker conformance | `conform.cho` over `examples/refusal/*.expect.json` (§6) |
| 3 reference model + scenarios | stays Python, an oracle lane (§5) |
| 4 c-header roundtrip (clang + gcc) | oracle lane: product emits, `oracle/` compiles and runs |
| 5 systemverilog structural + iverilog/slang/yosys | product-side structural unit tests + oracle lane for the real parse |
| 6 textual parser roundtrip | `unit_parse.cho` + `conform.cho` (text twin equals JSON twin, modulo hex case) |
| 7 diagnostic text formatter golden | `unit_diag_text.cho` against `tests/golden/` |
| 8 diff / impact golden | `conform.cho` against `tests/golden/` |
| 9 evidence report golden | same |
| 10-12 devicetree / binding / svd | golden per generator, plus oracle lanes (`dtc`, XSD) when the tools exist |
| 13 C behavioral roundtrip | oracle lane (`tests/behavioral/c_behavior.py` stays: it is the comparison harness) |

`scripts/gate.sh` (replacing `run_gate.py`) runs, in order, and a failure of
any is a failure of the gate:

1. `cancho fmt --check src/ tests/`
2. `cancho check src/*.cho --std` (every file refusal-free)
3. `cancho test tests/unit_*.cho src/... --std`
4. `cancho run tests/conform.cho src/... --std -- examples/`
5. `cancho authority` of the CLI, diffed against the committed
   `authority.expected` (§5, rule 4)
6. the file-budget lint (rule 3 of §5)
7. the oracle lanes (`python3 oracle/run.py`), each reported as `ran` or
   `skipped: <tool missing>`; the report stage (6) reads this, so a skipped
   lane is never counted as passed, as today.

Mutation check (CONTRIBUTING: "a test that could not have failed proves
nothing"). Done for the spike: changing one order digit in `parse.cho`
(`note(order, 3)` to `note(order, 2)`) made `cancho test` fail 1 of 11 and the
differential oracle fail 12 of 2,767. The gate gets such a check per stage.

---

## 5. Python that stays, and the rule that keeps it from creeping

**Stays, as oracle only:**

| Kept | Why it is an oracle, not product |
|---|---|
| `tools/sim/` (reference model, op runner, scenarios) | the independent implementation the generated C and SV are compared to |
| `tests/behavioral/c_behavior.py`, `c_device.c` | the harness that drives generated C and the model op for op |
| `tests/roundtrip/*` gcc / clang / iverilog / slang / yosys / dtc lanes | they run third-party tools on product output |
| XSD validation of SVD (`lxml`) and `jsonschema` | independent validators of product output and of the structural validator |
| `legacy` parser, checker and generators, **until each stage lands** | the differential oracle for that stage; deleted when the stage's exit criterion is met |
| `spike/diff_oracle.py` | the spike's differential driver |

**Rules that prevent creep.** They are mechanical, because "Python is only an
oracle" is the kind of sentence that survives until the first deadline.

1. **Location.** A `*.py` file may exist only under `oracle/` (and, while a
   stage is unported, `tools/` `gen/` `scripts/`, which are the legacy
   reference). The gate fails on any other `.py` file.
2. **A ceiling that only comes down.** The legacy directories carry a
   committed line-count ceiling (the compiler repository's own device for
   over-budget files, `CONTRIBUTING.md` "Files"). When a stage lands, its
   Python is deleted in the same commit and the ceiling drops. Raising it is
   not a fix. A new line of legacy Python needs a ceiling raise and is refused.
3. **File budget.** The same lint caps every `.cho`, `.py` and `.c` file at
   2,000 lines (design budget 800).
4. **Authority pin.** `cancho authority` of the product, committed as
   `authority.expected`. Measured on the spike: `args`, `err_write`,
   `file_read`, `fs_read("")`, `heap`, `io_write`; "never touches: the network,
   signals, other programs, foreign code". A product that spawned `python3`
   would need an exec capability and the diff in the pin would fail the gate.
   This is the strongest rule: it is enforced by the type system, not by
   discipline.
5. **One-way data flow.** Oracle code reads product output (stdout, files)
   and compares. It never produces an input the product consumes, and goldens
   are written only by the product (`UPDATE_GOLDEN=1 cancho run tests/conform.cho`),
   never by a Python script. An oracle that regenerates its own expected
   values is a test that cannot fail.
6. **Oracles are independent.** An oracle may not import another oracle's
   logic, nor re-implement product logic it is checking (the reference model
   decides what a register does; it does not call the generator).

---

## 6. The refusal fixtures become the conformance suite

What exists: `examples/refusal/` has 12 `.chw` fixtures, each with a
`*.expect.json` sidecar of the form

```json
{ "file": "examples/refusal/field-overlap.chw",
  "expect": [ { "code": "field-overlap",
                "subject": { "kind": "Field", "block": "BadUart",
                             "register": "CTRL", "name": "PARITY" },
                "message_contains": "overlap with ENABLE" } ] }
```

`conform.cho` reads each sidecar with `std.json`, loads and checks `file`
with the product's own functions, and requires:

1. every expected entry is matched by a diagnostic with that `code`, a
   `subject` that contains the listed keys, and a message containing
   `message_contains`;
2. no `Error`-tier diagnostic is present that no entry accounts for (so a rule
   that starts firing on the wrong input is caught, not only a rule that stops
   firing);
3. the exit status is the one the sidecars imply (1 if any `Error`).

Plus lanes that are not in the sidecars today and are cheap to add:

* every valid example (4 files, `examples/MANIFEST.json`) yields zero errors;
* each text/JSON twin pair parses to the same IR (the current
  `tests/parser/parser_roundtrip.py`);
* `--output json` of every fixture equals the Python checker's, key order
  included (oracle diff; deleted with the legacy checker, after which the
  committed output is the golden);
* mutants: truncation and token deletion of every fixture, and the output is a
  refusal with a rule tag or a clean parse, never a trap (the spike's
  differential does this for the parser, §7; "no input may reach a panic").

**A measured fact that orders the work (§2, stage 1).** Eleven of the twelve
refusal fixtures are in the JSON wire form (they begin with `{`), not the
textual form; only `parse-error.chw` is text, and of the four valid examples
only the two under `examples/textual/` are. The spike's parser therefore
exercises 3 of the 16 `.chw` inputs the conformance suite will use. The other
thirteen need `json_in.cho` and the
structural validator, which is where the schema-level refusals
(`schema-invalid`, e.g. `bus-width-invalid`, `dma-owner-unknown`,
`field-out-of-bounds`, `kind-unknown`) live. Until stage 1 lands the
conformance suite cannot claim to have been ported; the spike does not claim
it.

---

## 7. Spike: lex and parse `examples/textual/uart.chw`, print the IR as JSON

**What was built** (`spike/`, all `.cho` passes `cancho fmt --check` and
`cancho check`; reproduce with `sh spike/run.sh`):

| File | Code lines | Total lines | Role |
|---|---|---|---|
| `lex.cho` | 169 | 225 | tokeniser, port of `tokenize` |
| `ir.cho` | 190 | 243 | typed IR records, one adder per table, attribute-order helpers |
| `parse.cho` | 546 | 640 | recursive descent, sticky first-error refusals |
| `json.cho` | 291 | 320 | IR to JSON, `json.dumps`-identical |
| `front.cho` | 51 | 62 | text to (JSON or refusal line, status) |
| `io.cho` | 52 | 59 | read a file |
| `chwparse.cho` | 42 | 51 | CLI |
| `test_chw.cho` | 64 | 96 | 11 `cancho test` tests |
| `diff_oracle.py` | | 104 | the differential driver (oracle only) |

It is wider than the minimal slice: the whole textual grammar, including
`dma-buffer` and every refusal message of `parser.py`, so that the comparison
is against the whole of the Python parser's behaviour on the inputs it covers
and not against a convenient subset.

**Result.**

| Measurement | Value |
|---|---|
| `uart.chw`: cancho JSON vs `python3 tools/parse/parser.py` | **byte-identical** (`cmp`) |
| `dma.chw` | **byte-identical** |
| Differential over 2,767 inputs (2 examples, truncation at every byte offset, deletion of every whitespace-delimited run, 10 hand-made edge cases): stdout, stderr and exit status | 2,765 identical, **2 known differences**, 0 unexplained |
| of those, inputs that parse / are refused | 28 / 2,739 |
| `cancho test` | 11 passed, 0 failed |
| Mutation (one digit in the attribute order) | unit tests: 1 of 11 fails; differential: 12 of 2,767 differ |
| Compile (`cancho build`, 6 library files, `--std`) | 1.9 s |
| Run, per invocation (20-run mean, `dma.chw`) | 2.2 ms (Python: 66 ms, of which interpreter start-up is most) |
| Binary | 158,672 bytes |
| `cancho authority` | `args`, `err_write`, `file_read`, `fs_read("")`, `heap`, `io_write`; no network, signals, other programs or foreign code |

The ratio used in §3: lexer + parser + IR = 1,108 total lines (905 code lines)
against `parser.py`'s 634 (522 code lines including its docstrings): **1.75x**
total, 1.73x code. The JSON writer (320 lines) has no Python counterpart in
`parser.py`; `json.dumps` is the standard library. Counting it, and `front.cho` and `io.cho`, the stage is
1,549 lines against 634.

**Known differences** (both exercised by the differential and listed in it;
neither is hidden in a tolerance):

1. *Columns count bytes.* Python counts characters. Identical for ASCII; on a
   non-ASCII source line the column of a later token differs (hand-made case:
   1:116 against 1:110). Non-ASCII in a `constraint` text is still escaped
   correctly (`\uXXXX`, surrogate pairs); only the *position* differs. Fix when
   `std.utf8` is used by the lexer; not done here.
2. *Decimal literals over 18 digits are refused.* Python's `int` is unbounded;
   cancho's `int` traps on overflow, so the port refuses with a `parse-error`
   rather than trap (`test_oversize_decimal_is_refused_not_trapped`). The
   Python tool then accepts a `bus_width` that the schema refuses anyway.

**What was easy.**

* The language fit the problem better than expected. The whole spike had
  **one** compile error that was a language rule (a `borrow` nested inside a
  `borrow mut` of the same value) and one formatter refusal (a redundant
  `import x.y as y`). Everything else compiled on the first try, including
  generic row/region parameters, struct literals in `Vec`, tuple
  destructuring and `match` on the file API.
* Records in a `Vec` work as expected: `std.vec` takes a `val` struct, and the
  IR holds only integers (names and literals are spans into the source), so it
  is a plain value that never owns a string.
* `std.buffer` and `std.fmt.put` cover output and message building; no custom
  string type was needed.
* Byte-identical output was reachable without special casing. The
  insertion-order behaviour of Python dicts (register attributes, interrupt
  linkages, DMA attributes appear in the order first written) was the one
  semantic trap; the port records it as base-8 digits in an `order` field and
  prints from that.
* `cancho test` + a differential oracle found the one genuine bug class
  quickly (mutation check above), and `cancho authority` gives the
  no-shelling-out guarantee for free.

**What was hard (measured where it can be).**

* **Plumbing, not logic.** `src, toks, st` is repeated on 128 of `parse.cho`'s
  640 lines (20%); 108 of `json.cho`'s 320 lines (34%) are
  `o = f(heap, o, ...)` buffer threading. 25 of the 39 functions in `parse.cho`
  carry three region parameters, and the 7 that allocate carry four
  (`[&h, &r, &t, &p]`). An attempt to give related
  parameters one region variable (`src: &r [byte], toks: &r ..., st: &!r ...`)
  was refused by the checker (`q does not outlive static`), so the four stay.
* **No exceptions, no `break`.** The Python parser raises `_ParseAbort`; the
  port makes the refusal *sticky*: the first failure writes the message into
  the state slice and every later `expect_*` is a no-op, with `failed` in
  every loop condition. It is the same behaviour as data, and 2,739 refused
  mutants agree with it, but it is a convention to be kept in every future
  parser-shaped function.
* **State lives in an `[int]`.** A function without a heap cannot own a
  growable message, so the cursor, flags, error position *and the message
  bytes (one int per byte)* are one `[int]` slice every parser function
  borrows uniquely. Workable, ugly.
* **Structs are values that cannot be updated in place.** Changing one field
  of an interrupt rebuilds all ten fields (five sites in `parse.cho`), and the DMA
  field has five near-identical `with_*` constructors. A linear `Ir` is taken
  apart and handed back by seven adder functions. This is ~110 lines of
  `ir.cho` and `parse.cho` that exist because of ownership and not because of
  the problem.
* **No constants.** A token kind is `fn k_ident() -> [] int`; an `enum`
  cannot be compared with `==` or stored in an `[int]`. 8 one-line functions.
* **A test cannot read a file** (§4); the fixtures need a program, not a test.
* **Integer overflow traps** (known difference 2). Every `int` parsed from
  input is a place a trap can hide, and "no input may reach a panic" has to be
  argued at each.

**What the spike does not show.** The JSON wire form and schema validation
(13 of the 16 `.chw` inputs, §6); any checker rule; any generator; sorted
output, maps or set operations; floating point (none is needed so far);
non-ASCII columns (known difference 1); the cost of `res` values flowing
through a deep call graph (the IR is one `res` struct and the parser is two
levels deep).

---

## 8. Known risks

Ordered by how much of the port each puts at risk.

### 8.1 String building under linear ownership (highest)

Four of the five generators and the report are text assembly. The spike's JSON
writer is the closest measured analogue: **34% of its lines** are buffer
threading, and every helper takes `heap`. Generators are bigger and more
conditional than a JSON dump (the SystemVerilog generator emits per-access-kind
write logic; the c-header generator emits masks, shifts and per-field macros).
Mitigations to try, in this order, and to measure rather than assume:

1. Build into a caller-provided fixed `[byte]` with `std.fmt.put` threading an
   offset (no heap; the parser's message does this) where the size is
   boundable, and fall back to `Buffer` only where it is not.
2. One `emit.cho` of line-oriented helpers (`line`, `indent`, `hex32`,
   `ident_upper`), so a generator reads as a list of `emit` calls rather than
   `x = f(heap, x, ...)`.
3. Templates as `&static [byte]` constants with holes filled by a two-pass
   scan, if (2) still reads badly for the SV generator.

The design question the spike cannot answer is the heap threading itself:
whether a generator should own one `Buffer` in a state record handed to every
emitter. That is a language-ergonomics finding to take to the compiler repository
if it measures badly (its bar is "two askers", `CONTRIBUTING.md`).

### 8.2 Collections and ownership

The checker needs lookup by name (register, field, interrupt reference),
overlap detection, and sorted output; `diff` needs name-keyed matching of two
IRs. `std.map` exists (a hash map keyed by bytes, `V: val`), `std.vec` takes
`val` only, and `std.list` is the collection that holds resources. Risks:

* *Nested collections.* A register owns its fields; Python nests dicts. The
  spike flattens (a register is a `first`/`n` range into one field `Vec`),
  which works for read-only traversal and loses cheap per-register mutation.
  The checker and `diff` are read-only over the IR, so this probably holds;
  the report builder, which assembles a nested document, is the stage that may
  not.
* *No sorting in `std`* (to be confirmed per use; the stable-order requirement
  of the diagnostics is the exposure). Plan: sort index arrays with an
  insertion sort written once in `emit.cho`/`diag.cho`; sizes are tens.
* *Maps over spans.* Keys are spans into source text, not strings; a map keyed
  by `src[a..b]` slices works because the source outlives the IR. `diff`
  holds two sources at once; keep the two lifetimes distinct.

### 8.3 Smaller risks

* **Fidelity of Python's behaviour we do not mean to keep.** `json.dumps`
  details (`ensure_ascii`, key order, `", "` separators) are reproduced; float
  formatting is not needed. Each stage needs its own list of known differences
  in the document that introduces it, as §7 has.
* **Unbounded integers.** Reset values, offsets and masks up to 32 bits fit
  `int` easily; 64-bit buses would not be a problem either; anything that
  parses arbitrary decimal input must bound it (§7).
* **`Fs("")` in the CLI.** The spike reads a path from `args`, so it holds
  `fs_read("")`, every file. Narrowing needs a path known at the call; the
  report-time authority pin will show it. Not a regression (Python could read
  anything), but a missed chance to say so in `cancho authority`.
* **Compile time.** 1.9 s for 1,550 lines. If it grows linearly, the full
  product is a ~15 s build; the compiler's own incremental story
  (`cancho vcs`) is not evaluated here.
* **Diverging oracles during the port.** Python and cancho both change while
  stages are in flight. Rule: the Python is frozen (bug fixes only, ceiling
  rule §5.2) once its stage has started.
* **The reference model stays Python and so does its blind spot.** If the
  model and the cancho generators are both wrong the same way the roundtrip
  passes. The scenarios were written from the spec, not from either
  implementation, and that is the only protection; not changed by the port.

---

## 9. Corrections

None yet. A claim in this document that a later slice shows to be false is
corrected here, in place, with the PR that corrected it
(`CONTRIBUTING.md`, "How a slice is done").

## 10. Next slice

Stage 1: `json_in.cho` (wire form to IR through `std.json`'s tape) and
`check/schema.cho`, with `conform.cho` reading the eleven JSON-form fixtures and
the oracle lane comparing the validator's verdict to `jsonschema` over the
fixtures and their mutants. Its first question is whether the validator can be
written without per-rule special cases the JSON Schema expresses declaratively;
`docs/contract-design.md` §5's stop/rethink signal applies to the rule count.
