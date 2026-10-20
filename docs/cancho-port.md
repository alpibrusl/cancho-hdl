# Porting cancho-hdl to cancho

> **Status: design, a measured spike (§7), a built and measured stage 1
> (design §9, measurements §10), a built and measured first slice of stage 2:
> `Diagnostic` and the semantic checker (design §13, measurements §14,
> corrections §15), and a built and measured stage 3, the C header generator
> (design §17, measurements §18, corrections §19).** Decision (taken before this
> document): the product is rewritten from scratch as **pure cancho**. The
> Python under `tools/`, `gen/` and `scripts/` is the *legacy reference
> implementation*, kept until each part is replaced and then deleted. The
> `.chw` examples, the refusal fixtures (`examples/refusal/*.expect.json`)
> and `tests/behavioral/scenarios.json` are language-neutral specifications
> and do not move. Python may remain **only** as test-only oracle code (§5).
>
> What is measured here is four slices (the fourth, stage 3, is §18): the textual parser over the two textual
> examples (§7), the JSON wire loader, the structural validator and the
> conformance runner (§10), and the semantic checker with the `Diagnostic`
> record, its JSON and text forms, and a conformance runner that decides every
> sidecar entry (§14). Everything else in this document is a plan, and every
> number in it that is not from those is marked *estimate*.

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
| 1 | **JSON wire loader** (`std.json` tape to IR) and the **structural validator** that replaces `jsonschema` | `parser.load_contract` JSON branch, `checker._validate_schema`, `scripts/verify_examples.py` (78) | 0 | 11 of the 12 refusal fixtures are in JSON form (§6), so this gates the conformance suite. Validator verdict equals `jsonschema`'s on every example and every fixture mutant (oracle). **Built and measured: §9 and §10. The criterion holds except where the port is stricter on purpose (duplicate keys, integers over 18 digits, a newline after `$`), each counted and explained in §10.** |
| 2 | **Diagnostics + checker** | `tools/check/` (838 + 170 + 114 + 136) | 1 | `conform` passes: every sidecar matched, zero errors on the valid examples; `--output json` identical to Python's, key order included (`spec/diagnostics/README.md` §4.1). **First slice built and measured: §13 and §14. All 34 rules of `checker.py` are ported; `chw conform .` decides 19 of 19 sidecar entries; `--output json` is byte-identical on 16 of 16 valid examples and refusals; 0 unexplained differences over the mutants. What is not done is listed in §14.8.** |
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
    ir.cho                IR records, adders, attribute order      spike: 243, stage 1: 268
    parse.cho             recursive descent over the token tape    spike: 640
    json_out.cho          IR to the JSON wire form                 spike: 320, stage 1: 353
    json_in.cho           wire form to IR (std.json tape)          estimate 300; measured 376
    diag.cho              Diagnostic, tiers, subjects, spans       estimate 250; stage 1 slice: 140 (records, no tiers yet)
    diag_text.cho         human renderer (golden-pinned)           estimate 250
    check/
      schema.cho          structural validity (replaces jsonschema) est. 400; measured
                          schema 884 + pyrepr 204 + pattern 150 = 1,238 (§10, §11)
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
* **Conformance programs** (*as built: the `chw conform` subcommand, §9.2, not a
  separate `tests/conform.cho`*; it reads through a `Dir` handle on the root it is
  given, not an `Fs`): a
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
| `tests/differential/text_parse.py`, `json_validate.py` | the differential drivers: the cancho text parser against the Python parser; the cancho JSON loader and validator against `json` + `jsonschema` |

**Rules that prevent creep.** They are mechanical, because "Python is only an
oracle" is the kind of sentence that survives until the first deadline.

1. **Location.** A `*.py` file may exist only under `oracle/` (and, while a
   stage is unported, `tools/` `gen/` `scripts/`, which are the legacy
   reference). The gate fails on any other `.py` file. *(As built in stage 1 the
   differential drivers live in `tests/differential/`, not `oracle/`: they are
   tests, and `tests/` already holds the other Python test code. The lint that
   enforces this rule is not written; the gate only enforces the 2,000-line cap
   on `.py` files.)*
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
it. *(Stage 1 has landed, §10: the fixtures run, but only the stage-1 half of
each sidecar is decided. The conformance suite is not ported until stage 2.)*

---

## 7. Spike: lex and parse `examples/textual/uart.chw`, print the IR as JSON

**What was built** (`spike/` at the time; stage 1 moved the files to `src/`
and `tests/unit/`, renamed `json.cho` to `json_out.cho`, and replaced
`spike/run.sh` with `scripts/gate_cancho.sh`, whose steps 1 to 6 are the
spike's. The line counts below are the spike's; the files have grown since,
§10 has the current ones. All `.cho` passes `cancho fmt --check` and
`cancho check`):

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

## 9. Stage 1 design: the JSON wire loader, the structural validator, the conformance runner

> **Status: design, written before the code.** Section 10 records what was
> measured; where it showed this section wrong, the claim is corrected in place
> below and listed in section 11.

Scope is stage 1 of section 2 and nothing else. It replaces three things the
Python tools did with `json` and `jsonschema`: reading the JSON wire form
(`parser.load_contract`'s JSON branch), validating it against
`spec/contract-schema/cancho-hdl-contract.schema.json`
(`checker._validate_schema`), and running the refusal fixtures
(`tools/check/conformance.py`, for the part of it that stage 1 can decide).

### 9.1 What stage 1 decides, and what it cannot

The sidecars in `examples/refusal/` mix two kinds of expectation. Of the 12
fixtures, 5 expect a code that only the **schema level** can produce
(`parse-error` for the one text fixture; `schema-invalid` for `bus-width-invalid`,
`dma-owner-unknown`, `field-out-of-bounds`, `kind-unknown`), and every other
entry expects a **semantic** code (`block-bus-width-invalid`, `field-overlap`,
`dma-overlap`, ...) that is stage 2's. The runner therefore does not pretend to
the Python conformance verdict. For each fixture it requires:

1. every sidecar entry whose `code` is one of stage 1's (`parse-error`,
   `schema-invalid`) is matched by an emitted diagnostic with that code, the
   `Ir` subject kind, and a message containing `message_contains`;
2. no emitted diagnostic is left unaccounted for (a validator that flags a
   schema-valid fixture is a failure, which is what makes the 7 purely
   semantic fixtures a real stage-1 test: they must load and validate clean);
3. the entries it cannot decide are **counted and listed as deferred to stage 2**,
   never as passed. The summary says "N of M fixtures matched on the stage-1
   rules; K sidecar entries deferred", and the exit status is non-zero on any
   FAIL, not on a deferral.

Valid examples (`MANIFEST.json`, `valid` and `textual_valid`) must load and
validate with zero diagnostics.

### 9.2 Modules (all under `src/`, flat, dotted module names)

| File | Module | Role |
|---|---|---|
| `lex`, `ir`, `parse`, `json_out`, `front`, `io` | `chw.*` | the spike, moved unchanged except as listed below |
| `json_in.cho` | `chw.json_in` | JSON wire form (`std.json` tape) to the **same `Ir`** the text parser builds |
| `diag.cho` | `chw.diag` | a diagnostic as one tab-separated record line; line/column from a byte offset |
| `pyrepr.cho` | `chw.pyrepr` | a JSON value in Python's `repr`, because the sidecars quote `jsonschema` messages (`'GPU' is not one of ['CPU', 'DEVICE']`) |
| `pattern.cho` | `chw.pattern` | the regex subset the schema uses (`^`, `$`, literals, escapes, classes, `+`), no more |
| `schema.cho` | `chw.schema` | the validator: an interpreter for the JSON Schema subset, driven by the schema **file** |
| `load.cho` | `chw.load` | sniff the form, load, validate: bytes in, `Ir` + diagnostics out |
| `conform.cho` | `chw.conform` | the sidecar reader and the per-fixture verdict |
| `main.cho` | | `chw parse FILE`, `chw validate FILE`, `chw conform ROOT`, exit 0/1/2 |

The IR does not change shape. Names and literals stay spans into one byte
buffer; the **loader's buffer is the source followed by decoded strings** (a JSON
string with an escape has no contiguous span in the source, so its decoded form
is appended and the span points there). The printer takes that buffer as it took
the source before. Two IR facts the text parser never needed are added:
`version` and `$schema` (a JSON document carries both; the text form implies the
constants), so a loaded document prints back with the version it declared.

### 9.3 The validator is the schema, interpreted

The question section 10 left open, "can it be written without per-rule special
cases the JSON Schema expresses declaratively", is answered by not writing the
rules: `schema.cho` reads the schema file with `std.json` and interprets the
keywords the file uses.

* Keywords: `type`, `enum`, `pattern`, `minLength`, `minItems`, `minimum`,
  `maximum`, `required`, `properties`, `additionalProperties` (`false` or a
  schema), `items`, `$ref` (`#/$defs/...` only). Annotations
  (`$id`, `$schema`, `$defs`, `title`, `description`) are ignored.
* **A keyword outside that list is a refusal, not a skip**: `jsonschema`
  ignores an unknown keyword, which would make a future `maxLength` silently
  unenforced. It is reported as code `internal` (a toolchain fault, not the
  user's input), and the run exits 2.
* Messages follow `jsonschema` 4.26.0 word for word (the differential refuses to run against another release, and CI pins it: an older release words a minimum of 1 as `is too short`, which CI showed on its first run), with the instance quoted in
  Python's `repr` (`pyrepr.cho`): one message per keyword, two for `minLength`
  and `minItems` (`should be non-empty` when the minimum is 1, `is too short`
  otherwise) and two for `additionalProperties` (`was` / `were unexpected`, the
  extras sorted, as `jsonschema` sorts them).
* **Located spans where one exists.** A JSON-form diagnostic carries
  `line:column` of the offending node (1-based, columns in bytes, as the spike's
  lexer counts), which `jsonschema` never had (the Python diagnostic is a
  whole-file span, `1:1`). A text-form file is validated through its rendered
  JSON, where an offset means nothing to the author, so those diagnostics carry
  no span.
* The validator reports **every** violation (as `iter_errors`). *(Corrected:
  this said "in document order". The order is the schema file's keyword order at
  each node, as `jsonschema`'s is, preceded by the instance-only refusals of
  9.4, which run first. The differential compares the multisets.)*

### 9.4 Rule tags for stage 1

No new catalog code is introduced. A diagnostic is `code` plus a **keyword**, the
sub-tag a test can pin:

| `code` | `keyword` | When |
|---|---|---|
| `parse-error` | `-` | text form refused (stage 0, unchanged) |
| `schema-invalid` | `type` `enum` `pattern` `minimum` `maximum` `minLength` `minItems` `required` `additionalProperties` | the `jsonschema` violations, same words |
| `schema-invalid` | `json-syntax` | the file begins with `{` and is not RFC 8259 JSON (Python: `file is not valid JSON`, same code) |
| `schema-invalid` | `duplicate-key` | an object repeats a key. `json.loads` keeps the last, `std.json` the first; the port refuses rather than choose |
| `schema-invalid` | `integer-range` | an integer of more than 18 digits (cancho `int` traps on overflow, so it is refused; `jsonschema` accepts it) |
| `internal` | `unsupported-keyword` | the schema file uses a keyword the interpreter does not implement |

### 9.5 Known differences from `jsonschema` / `json`, predicted

Listed before measuring so the differential cannot quietly redefine them:

1. *Stricter*: duplicate keys; integers over 18 digits; a trailing newline after
   a `pattern` that ends in `$` (Python's `$` accepts `"0x10\n"`; the schema's
   intent does not); lone surrogates and invalid UTF-8 (`std.json` is strict,
   `json.loads` is not); `NaN`/`Infinity` tokens.
2. *Wording*: JSON syntax messages come from `std.json`, not `json.JSONDecodeError`;
   a float in a message is its source text, not `repr(float)` (`1E2` against
   `100.0`); a non-ASCII non-printable character outside `pyrepr`'s small table
   is not escaped as Python's `repr` would. *(Corrected: "printed by `std.fmt`"
   was the first intention; the source text is what was built, because the
   shortest-round-trip form is not worth a dependency for a message.)*
3. *Canonical IR printing* (the IR is a record, not a dict): required keys print in
   a fixed order, not the document's; optional register and DMA attributes keep
   the document's order; `"volatile": false` and `"polling": false` are not kept;
   an absent or empty `interrupts` / `fields` array is not printed and an absent
   `dma_buffers` prints `[]`; hex digits print lowercase (the text twin does too);
   an integral float (`8.0`) prints as an integer.
4. *Sniffing*: Python's `lstrip()` strips Unicode whitespace; the port skips ASCII
   whitespace.

### 9.6 The differential (test-only Python, `tests/differential/`)

`json_validate.py` runs, over the valid JSON examples, the 11 refusal fixtures,
the `tests/stage1` fixtures and their mutants (truncation at every byte offset, deletion of every token-sized
run, single-value substitutions that cross each schema keyword), the Python
oracle (`json.loads` + `jsonschema.Draft202012Validator.iter_errors`) and the
cancho `chw validate --machine` / `chw parse`, and compares:

* the verdict (valid or not) on every input;
* the set of `(pointer, keyword, message)` for every input the Python side reads;
* for inputs both sides accept, the IR JSON, after the normalisations of 9.5 (3)
  **and also raw**, so the report says how many were byte-identical before any
  normalisation.

Every disagreement must fall in a class of 9.5, named in the output; anything
else fails the run. `text_parse.py` (the spike's differential) is kept as the
oracle for the text parser.

### 9.7 Gate

`scripts/gate_cancho.sh` (called from CI where `spike/run.sh` was), in order:
`cancho fmt --check src tests/unit`; `cancho check` of the program; `cancho test` of
every `tests/unit/test_*.cho`; the file-length lint (no `.cho`, `.py` or `.sh` over
2,000 lines); `cancho build`; the text parser (byte-identical JSON on the textual
examples, then its differential); `chw conform . --fixtures tests/stage1`; a
conformance run against a copy of the tree with one sidecar altered, which must
exit 1 (the runner can fail); the JSON differential and `stress.py`; and
`cancho authority` diffed against `scripts/authority.expected`.
`python3 scripts/run_gate.py` is untouched and still run by CI. Stage 2 adds to this gate (13.7): the new modules, three more unit suites, `tests/stage2`, three more "the runner can fail" trees (four, with the one 14.4 added), and step 8b.

---

## 10. Stage 1 measured

Reproduce everything below with `sh scripts/gate_cancho.sh` (needs the pinned
compiler and `pip install jsonschema lxml`). Every number is from
that run, on one 4-core Linux machine, unless a row says otherwise. The gate takes
about five minutes.

### 10.1 The conformance runner

`chw conform . --fixtures tests/stage1`:

| Measurement | Value |
|---|---|
| `examples/refusal` fixtures matched on the stage-1 rules | **12 of 12** |
| their stage-1 sidecar entries (`parse-error`, `schema-invalid`) matched | 5 of 5 |
| their sidecar entries deferred to stage 2 (semantic codes), **not counted as passed** | 14 of 19 (the Python conformance decides all 19) |
| valid examples (`valid` + `textual_valid`) that load and validate clean | 4 of 4 |
| `tests/stage1` fixtures (14 refusals and 2 files that must be clean) | 16 of 16; 19 of 19 entries |
| all of the above | 28 of 28 fixtures, 24 of 24 stage-1 entries |

The 7 fixtures whose only sidecar entries are semantic (`field-overlap`,
`register-overlap`, `dma-overlap`, ...) pass by loading and validating with zero
diagnostics, which is the check that the validator does not over-refuse. The
runner can fail: the gate (step 8) copies the tree, changes one sidecar's code,
and requires exit 1.

A located span where one exists, for the four `schema-invalid` fixtures:
`bus-width-invalid.chw:7:18`, `dma-owner-unknown.chw:17:58`,
`field-out-of-bounds.chw:15:45`, `kind-unknown.chw:10:51`
(line:column of the offending value; the Python diagnostic is `1:1`).

### 10.2 Tests and mutation checks

`cancho test`: **94 tests in 7 suites**, all passing (`diag` 6, `json_in` 15,
`load` 8, `parse` 11, `pattern` 7, `schema` 30, `validator_spans` 17). The
`jsonschema` messages in `test_schema.cho` were produced by running
`jsonschema` 4.26 on the same schema and document, not by running this port.

Mutation checks (a copy of `src/` with one change; "differential" is
`json_validate.py --no-textual`, 34,886 to 36,284 inputs depending on when its pool
of values last grew; a cell is how many things failed):

| Mutation | unit tests | `chw conform` on the repo | differential (unexplained) |
|---|---|---|---|
| `minimum` off by one (`order > 0`) | 1 failed (after `test_the_bounds_are_inclusive` was added; **0 before**) | exit 1 (10 of 28) | 25,350 |
| `enum` skips its last member | 2 failed | exit 1 (6 of 28) | 29,612 |
| loader swaps `lsb` and `msb` | 3 failed | exit 0 (it does not read the IR) | 2,327 |
| `repr` ignores the double-quote rule | 1 failed | exit 0 | **0 on the first run**; 522 after `"it's"` entered the value pool |
| extra properties not sorted | 1 failed | exit 0 | **0 on the first run**; 135 after the non-ASCII tolerance was tightened |
| runner ignores the code of a record | 0 failed | exit 0 on the repo | 0; **gate step 8 exit 0 instead of 1** |

Three of those rows are the point of the exercise. Two mutants survived the
differential on their first run (the pool of substituted values had no string
with an apostrophe, and the tolerance for non-ASCII messages was loose enough to
excuse an unsorted list), so the differential was changed (§11). One survived
every test except the gate's can-fail step, so the step exists.

### 10.3 The differential against `json` + `jsonschema`

`python3 tests/differential/json_validate.py chw`: **55,093 inputs**, 0
unexplained differences. The inputs are the 2 valid JSON examples, the 11 JSON
refusal fixtures and the 16 `tests/stage1` fixtures; for each, truncation at every
byte, deletion of every whitespace-delimited run, 50 substituted values at every
node of the parsed document (including 99999999999999999999, `1e30`, `8.0`,
`"0x10\n"`, strings with quotes and non-ASCII), deletion of every key, an extra
key, four extra keys in an unsorted order, every object's keys reversed and
rotated; plus 14 hand-made documents and 6 form-sniff cases.

| | Count |
|---|---|
| inputs both sides refuse as JSON text | 18,792 |
| inputs where the verdict (valid or not) agrees | 36,084 |
| inputs where it differs, each one explained below | 212 |
| `jsonschema` error records reproduced word for word (pointer, keyword, message) | 47,240 |
| inputs both accept, whose IR was compared | 3,736 |
| of those, IR byte-identical to `json.dumps(json.loads(...))` | 287 |
| of those, identical after the canonical-printing normalisations | 3,449 |

The 212 verdict differences and the 3,449 normalised IRs, by class (an input can
be in more than one class):

| Class | Inputs | Why |
|---|---|---|
| `integer-range` | 2,693 | an integer past 18 digits; `jsonschema` accepts or quotes it, this refuses (rule of 9.4) |
| `pattern-trailing-newline` | 107 | Python's `$` matches before a final `\n`, this does not |
| `duplicate-key` | 3 | refused; `json.loads` keeps the last value |
| `sniff-unicode-whitespace` | 6 | Python's `lstrip()` skips U+00A0 and five other characters, then `json.loads` refuses; this reads the text form. Both refuse the file, with `schema-invalid` and `parse-error` |
| `nan-infinity`, `lone-surrogate` | 1 each | `json.loads` accepts them, `std.json` does not |
| `float-repr`, `non-ascii-repr` | 1 each | the same message with a float or a non-printable written differently |
| IR `hex-case` | 2,201 | the printer writes hex digits lowercase |
| IR `dma-buffers-defaulted` | 1,356 | an absent `dma_buffers` prints `[]` |
| IR `integral-float` | 246 | `8.0` prints as `8` |
| IR `key-order` | 184 | required keys print in a fixed order; the mutants reverse and rotate each object's keys |
| IR `empty-array-dropped`, `false-attribute-dropped` | 26, 5 | an empty `fields` / `interrupts` is not kept; `"volatile": false` is not kept |

Predicted in 9.5 and not exercised by this corpus: the nesting limit (the 200-deep
hand-made case is a syntax error to both sides, so the difference between
`std.json`'s 128 and Python's recursion limit is not reached), invalid UTF-8 as a
*file* (Python's `read_text` raises; `chw` reports `json-syntax`; `stress.py` runs
it but does not compare), and columns on non-ASCII lines.

The text parser's differential is unchanged by the move: 2,765 of 2,767 inputs
identical, the same two known differences, 28 parse and 2,739 refused.

### 10.4 Large and hostile inputs, and three quadratic loops

`tests/differential/stress.py` runs 11 inputs through `chw validate` and requires
exit 0 or 1 within 20 seconds: no trap, no hang. It exists because the first
version of the port failed it:

| Input | First version | Now |
|---|---|---|
| one object of 5,000 keys | **48.3 s** | 0.01 s |
| 16,000 refusals in a 1.7 MB indented file | **29.5 s** | 0.11 s |
| 16,000 refusals on one line (0.8 MB) | **21.9 s** | 0.19 s |
| 8,000 valid registers (1 MB) | 0.12 s | 0.14 s |
| 5,000 unknown keys (one message, sorted) | not measured | 0.02 s |

The causes were all quadratic and none was a language problem: comparing every
pair of keys for duplicates (now `std.map`); reading record `i` of the report by
scanning from the start (`diag.record(report, i)` inside a loop; now a cursor);
working out each line and column from byte 0 (now one forward pass,
`schema.locate`; deferring the position alone did not help, measured at 41 s
under load, which is how the cursor was found); and an insertion sort of the
extra keys (now a merge sort). No input in the 55,093 or the 11 reached a trap.

### 10.5 Size, speed, authority

| | Value |
|---|---|
| new or rewritten modules, lines | `json_in` 376, `diag` 168, `pyrepr` 204, `pattern` 150, `schema` 984, `load` 196, `conform` 482, `main` 214: **2,774** (`io` and `front` also changed) |
| the Python they replace, lines | `load_contract`'s JSON branch 26, `_validate_schema` 39, `verify_examples.py` 78, `conformance.py` 170: **313**, plus the `jsonschema` package they call (4,580 lines, of which `_keywords.py` + `_types.py` + `_utils.py` are 1,008) |
| ratio | 8.9x against the 313 lines; 2.1x if the 1,008 lines of `jsonschema` that implement the keywords used are counted. Neither is like for like: the port also does `repr`, regex, sorting, located spans, duplicate keys and the 18-digit rule, none of which the Python side does |
| largest file | `schema.cho`, 984 lines: **over the 800-line design budget** (3), under the 2,000 ceiling |
| `cancho build`, 14 files, 4,422 lines | 5.8 s (the spike: 1.9 s for 1,550 lines) |
| binary | 374,912 bytes |
| `chw validate uart.chw` | 4.2 ms (20-run mean) against 154 ms for `json.loads` + `jsonschema` in a fresh interpreter, most of which is start-up and import |
| `chw conform . --fixtures tests/stage1` | 9.9 ms for 28 fixtures and 4 valid examples; `tools/check/conformance.py` is 174 ms for 12 and 4, and does the whole checker |
| `cancho authority` | `args`, `dir_read`, `err_write`, `file_read`, `fs_read("")`, `heap`, `io_write`; never the network, signals, other programs or foreign code. Pinned in `scripts/authority.expected`; the new label over the spike's is `dir_read` |

### 10.6 What was easy, and what was not (cancho)

Easy: the loader. The tape made a 376-line total function over any JSON easy to
write, and `std.json`'s strictness (UTF-8, surrogates, depth, leading zeros) is
the validator's syntax layer for nothing. `std.map` made duplicate-key detection
linear in one 25-line function. The whole of stage 1 drew about a dozen compiler
refusals in 4,400 lines, each fixed by a local edit, of a few kinds (below).

Not easy, measured where it can be:

* **A container node has no source offset.** `std.json`'s tape records where a
  scalar or string is, not where an object or array starts, so a span for
  `required` or `minItems` needed a 40-line scanner (`value_end`) that re-reads
  the document. A `json.offset(tape, node)` would delete it. One asker so far.
* **Four slices in every signature.** The validator reads two documents (an
  instance and a schema), each a source and a tape, and a reference cannot be
  stored in a struct (a field cannot be `[T]`), so 149 of `schema.cho`'s 984
  lines (15%) mention `isrc`, `itape`, `ssrc` or `stape`, and 12 functions carry
  a header of five or six region parameters. Same plumbing as 7.
* **A `res` struct cannot be updated or renamed.** `let Loaded { ir: ir3, ... }`
  is a parse error, so every table of the IR is added through a helper that takes
  the struct apart and puts it back (`with_reg`, `with_field`, `with_buf`, and
  the `add_*` of `ir.cho`); `borrow doc.report` is refused, so `Doc` needs
  accessors.
* **A test row is exact.** A test that takes `heap` and never allocates is refused
  (`declares heap but never performs it`), so pure tests take no parameters; a
  test cannot read a file, so every fixture-driven check is `chw conform`.
* **Library gaps met once each.** No sort in `std` (a 45-line merge sort);
  `index_of_byte` needs an edition the file did not have, so `diag.end_of` is a
  loop; `join` is a builtin name; naming `Dir` needs `edition 6;` in each file
  that does (an `edition 6` `main` importing editionless modules worked).
* **No Python-compatible float `repr`.** Messages quote a float as written.
* **Traps are near.** Every integer from input is a place to argue: `to_int`
  saturates, the 18-digit rule refuses before anything is added, a negative
  number is printed without negating it (`neg_digits`), and the stress file keeps
  watching.

### 10.7 What stage 1 does not show

Any semantic rule (the 14 deferred sidecar entries); the `Diagnostic` record and
tiers (a diagnostic here is a line of text, not yet the object of
`spec/diagnostics/README.md` §2); `--output json` of diagnostics; endianness and
other invalid enums survive in the IR only as `big: false` (a schema-invalid
`"endianness": "middle"` loads as little-endian, so stage 2 reads the validator's
report for that, not the IR); non-ASCII columns; a hostile key set against
`std.map`'s fixed seed; the memory of a very large file (the tape is 24 bytes per
input byte).

---

## 11. Corrections

A claim in this document that a later slice shows to be false is corrected here,
in place, with the change that corrected it (`CONTRIBUTING.md`, "How a slice is
done").

Stage 1 (this change):

1. §9.3 said the validator reports violations "in document order". It reports them
   in the schema file's keyword order at each node, preceded by the instance-only
   refusals. Corrected in 9.3.
2. §9.5 (2) said a float in a message is printed by `std.fmt`. It is the source
   text. Corrected in 9.5.
3. §3's estimate for the structural validator was 400 lines. Measured:
   `schema` + `pyrepr` + `pattern` = 1,238, three times the estimate, because the
   validator turned out to be a schema interpreter with `repr`, a regex subset and
   located spans, not a set of rules. The estimates for `check/` that follow it
   (the semantic rules) were made with the same 1.75 ratio and should be read with
   that in mind. `json_in` was estimated at 300 and is 376.
4. §5 rule 1 named `oracle/` for the Python test code; as built it is
   `tests/differential/`. Corrected in 5.
5. §2 said the validator's verdict "equals `jsonschema`'s on every example and
   every fixture mutant". It does except where the port is deliberately stricter
   (duplicate keys, integers past 18 digits, a newline before `$`): 212 of 55,093
   inputs, each classified. Corrected in 2.
6. The differential itself was corrected twice by mutation checks (10.2): its pool
   of values gained strings with apostrophes, and its tolerance for messages that
   differ only in escaping was narrowed from "any non-ASCII" to "equal after
   decoding the escapes" (and likewise for floats).
7. The first version of the port had three quadratic loops (10.4). They were
   fixed before this change landed; the stress test keeps them fixed.

## 12. Next slice

*Done, as §13 to §15.* The questions this section asked: whether the `Diagnostic`
record can stay a line of text (no: §13.2), whether the semantic rules fit the
800-line budget per file (yes, all of them, apart from the catalog: §14.6), and
whether `schema.cho` should be split before more is added to it (nothing was
added to it; the checker is six files of its own). The exit criterion (the 14
deferred entries decided, `--output json` identical to the Python checker's) is
met: §14.1 and §14.2.

---

## 13. Stage 2 design: `Diagnostic` and the semantic checker

> **Order of work, stated plainly.** `CONTRIBUTING.md` says design before code.
> This slice did not keep to it: the checker, its output and the differential were
> written and run first, and this section was written during the second run of
> the mutant differential, after the first one (408 unexplained differences) had
> been read. So 13.5 below is **not** a prediction made in advance. It is what
> reading `checker.py` led me to expect, written down late; section 15 says, run by
> run, what the differential found that it did not list. The section is here so
> that the claims can be checked, not to claim that the order was kept.

### 13.1 What this slice decides

Stage 1 loads both forms and decides the structural half of every sidecar. The
checker is what is left of exit criterion 2 in section 2:

* **`Diagnostic`** as the object of `spec/diagnostics/README.md` section 2, not
  a line of text (the question 9.4 and 12 left open);
* **`chw check` and `--output json`**, in the shape the Python checker prints, byte
  for byte, and `chw validate --output json` for the structural half alone;
* **every rule of `tools/check/checker.py`**, in its order and its words: 34
  rule tags (the catalog's `parse-error` and `internal` are stage 0 and 1's);
* **`chw conform` deciding all 19 entries** of the 12 refusal sidecars, none
  deferred, and the same for the 16 `tests/stage1` fixtures once their sidecars
  name the semantic diagnostics Python also emits for them.

Not in this slice: the generators, `diff`, `report` (stages 3 to 7), real source
spans for the semantic rules (every Python semantic diagnostic carries the
whole-file span 1:1; the tape has the offsets, so a located span is a later,
additive change), and `ran`, the argument by which `check()` tells `report.py`
which rule groups executed (the report is still Python and reads the Python
checker).

### 13.2 The record

```
Dg { rule: Rule, subj: Subj, loc: Loc, kw: Sp, msg: Sp, exp: Sp, act: Sp, rem: Rem, kids: Kids }
```

* `Rule` is an **enum of the 36 rule tags**. The severity, the tier and the
  subject kind are **functions of the rule** (`rule_severity`, `rule_tier`,
  `rule_kind`), section 3 of the diagnostics spec written as code: a rule cannot
  be emitted with another rule's tier, and a tag that is not in the enum cannot
  be spelt. `chw catalog` prints the table and `tests/differential/catalog.py`
  compares it with the README.
* Text is **not owned by the record**. Every string it holds is a span (`Sp`) of
  one byte pool the table (`Diags`) owns, the way the IR holds names (`ir.cho`).
  A diagnostic is built by appending its pieces to the pool, closing the span,
  and pushing the record: `mark`, `lit`/`put_*`, `close`, `push`.
* A **related** entry or a **note** is a record of the same table, pushed right
  after its parent and found through the parent's `Kids`. A reader that walks the
  table skips `nest != 0`.
* `expected` and `actual` are held as the **JSON text they print as** (a string,
  a number, an array), formatted for a top-level diagnostic: that is all the JSON
  form can show, and the text form does not print them.
* The record is a `val` value, so it lives in a `std.vec`; a field of a record
  cannot be assigned (`d.n = 5` is refused), so a diagnostic is built with `mk`
  and rebuilt by the `with_*` functions, each of which copies the nine fields.

Alternatives, and why not:

| | Why not |
|---|---|
| keep the stage-1 line of text (`code TAB line TAB ...`) | related entries, notes, a remediation and `expected`/`actual` have no place in it without growing a parser for it; it stays, unchanged, as the validator's report (`validate --machine`) and is converted by `chw.dg_report` |
| a record of owned `Buffer`s | a `Buffer` is a `res`; a struct holding one is a `res`; a `Vec` holds `val` only, so a table of diagnostics would be a `std.list` read newest-first |
| JSON text built directly by the rules | the conformance runner, the text form and a test would all have to parse it back; the object is what `spec` section 5 says the text form is derived from |

### 13.3 The wire

* `chw check FILE [--output text|json] [--located]`: load, validate against the
  schema, run every rule, print. Exit 0 with no Error, 1 with one, 2 for the
  tool's own fault (`internal`). `chw validate FILE --output json` prints the
  structural half in the same shape. `chw catalog` prints the rule table.
* **`--output json` is `Diagnostic.to_json()` of `diagnostic.py`**, one object
  after another, `json.dumps(indent=2)` with `ensure_ascii`, keys in the order
  `code, severity, tier, message, related, notes, subject, span, expected,
  actual, remediation`. The structural diagnostics are converted from the stage-1
  report into the words `checker.py` gives them: `schema validation failed: ` +
  the `jsonschema` message, the pointer as a list (`["block", "registers", 0]`),
  `expected` the schema name, `actual` the message.
* **Spans.** A semantic diagnostic and a structural one both carry the file span
  1:1, as Python's do; a `parse-error` carries the token it stopped at, to its
  end (`line:col` to `line:col + max(len(token), 1)`, which needed the parser to
  expose the token it opened the refusal at). `--located` puts the position of the
  offending node (stage 1's) on a structural diagnostic and adds the schema
  `keyword` to its `Ir` subject: the one place the JSON is not Python's, and only
  when asked.
* The text form is `text_format.py`'s: the header, `--> file` (and the source
  snippet for a real position), `= related[...]`, `= note:`, `help:`.

### 13.4 Modules (all under `src/`)

| Module | Does |
|---|---|
| `diagnostic` | the record, the catalog, the pool, `mk`/`with_*`/`push` |
| `hexval` | `_parse_hex`: `int(s, 16)` with its underscores and trailing blanks; exact below 2^60, saturated and keyed above |
| `check_util` | reading a node as Python would (`isinstance`, `in`, `str()`, `repr()`, `json.dumps`) and appending text to the pool |
| `check_block`, `check_regs`, `check_intr`, `check_dma` | the rules, one concern per file, statement for statement |
| `check` | `check()`: the order of the groups |
| `dg_report` | the stage-1 report as records |
| `dg_json`, `dg_text` | the two output forms |

`conform`, `load`, `main`, `front`, `parse` and `diag` change: `conform` decides
every entry from the records, `load` keeps them beside the stage-1 report, `main`
gains `check` and `catalog`, and the parser's refusal now also says where its
token ends.

The checker runs on the **JSON tape of the contract**, not on the IR: the IR is
lossy for it (an invalid `endianness` survives only as `big: false`, a missing
`lsb` as 0, a kind as a span) and the Python checker reads the dict it
`json.loads`ed. A text-form file is checked through the JSON its IR renders as,
the document `chw.load` already validates. One checker, both forms.

### 13.5 Known differences from `checker.py`, expected

Listed from reading `checker.py`; see the note at the head of this section for
when:

1. *`checker.py` raises, the port answers.* The module says "the checker is
   total" and is not: `reg.get` on a number, `kind in set` on a list. The port
   skips an element that is not an object and treats an unhashable kind as
   unknown; a mutant on which Python raises is counted, by exception, not compared.
2. *Past 2^60 a hex value is saturated.* A cancho `int` traps on overflow. A hex
   literal of more than 15 significant digits is exact for equality (its canonical
   digits are the key), for alignment (the low 16 bits are kept) and for every
   comparison against a bus mask or address space; it is not exact for a sum
   (`offset + size`) or for an overlap of two such DMA fields. A JSON integer past
   18 digits is read as +-10^18 by the checker after the validator has refused it
   (`integer-range`, stage 1).
3. *Floats are source text.* A float in a message or in `actual` prints as written;
   Python prints `repr(float)` (stage 1, 9.5).
4. *Non-ASCII digits and whitespace.* `int(s, 16)` accepts Unicode digits and
   `str.strip()` Unicode blanks; the port reads ASCII.
5. *Duplicate keys.* `json.loads` keeps the last, `std.json` the first; the
   validator refuses the document (stage 1).
6. *The width of an enum past 62 bits.* `1 << width` is a Python bignum; the
   largest mask the port prints is 2^62 - 1 (reachable only with a negative `lsb`
   the schema refuses).
7. *JSON syntax errors* are worded by `std.json` (stage 1).

### 13.6 The differentials (test-only Python, `tests/differential/`)

* `check_json.py`, **fixtures**: every valid example, refusal, `tests/stage1` and
  `tests/stage2` file through both command lines, `--output json` and the text
  form, bytes compared. **Mutants**: one semantic change at a time to the JSON
  seeds (every value of a key-aware pool wherever that key occurs, every key
  deleted, every array element duplicated, every collision of two names or
  offsets, every pair of field bounds), and to the textual examples (every token
  deleted, every number replaced); the Python side in process, the cancho side
  `chw check --output json`. A difference must fall in a class of 13.5 or fail.
* `catalog.py`: the rule table against `spec/diagnostics/README.md` section 3, and
  that every rule has a refusal fixture.
* `tests/mutation/run.py`: one deliberate break per rule; 14.3.

### 13.7 Gate

`scripts/gate_cancho.sh` gains the new modules in its program, the three new unit
suites, the conformance run over `tests/stage2`, three more "the runner can fail"
trees, and step 8b (the catalog and `check_json.py`).

---

## 14. Stage 2 measured

Reproduce everything below with `sh scripts/gate_cancho.sh` (needs the pinned
compiler and `pip install jsonschema==4.26.0 lxml`), and the mutation table with
`python3 tests/mutation/run.py`. Every number is from those runs on one 4-core
Linux machine, unless a row says otherwise. The compiler was the build at
`7ad4d50`, three commits after `.cancho-rev`; it did not refuse over the pin, so no
flag was needed.

### 14.1 The conformance runner decides every entry

`chw conform .` (the 12 refusal fixtures and the 4 valid examples):

| Measurement | Stage 1 | Now |
|---|---|---|
| refusal fixtures matched | 12 of 12, on the stage-1 rules | **12 of 12** |
| sidecar entries decided by cancho | 5 of 19, 14 deferred and not counted as passed | **19 of 19, none deferred** |
| valid examples | 4 of 4 clean | 4 of 4 without an error; 2 warnings (the `constraint` of `uart.chw`, in both forms), as `conformance.py` allows |

`chw conform . --fixtures tests/stage1,tests/stage2`: **46 of 46 fixtures, 83 of 83
entries** (the 12 refusals, the 16 `tests/stage1` fixtures whose sidecars now also
name the semantic diagnostics `checker.py` emits for them, 31 entries where there
were 19, and the 18 `tests/stage2` fixtures, 33 entries). The `tests/stage2`
sidecars were generated from `checker.py`'s output, the oracle, and checked in;
cancho is not their author.

The runner can fail: gate step 8 and the mutation harness run it on six trees, each
the contract-facing files with one thing changed (a sidecar naming the wrong
structural code, the wrong semantic code, another field, another message; a
fixture mended so its overlap is gone; a valid example made to share an offset),
and require every one to be refused.

### 14.2 Against `checker.py`, byte for byte

`python3 tests/differential/check_json.py chw` (fixtures part): 50 files: the 4
valid examples, the 12 refusals, the 16 `tests/stage1` and the 18 `tests/stage2`
fixtures, each through both command lines.

| | Files |
|---|---|
| `--output json` byte-identical to `checker.py --output json` | **47 of 50** |
| the text form byte-identical to `checker.py` | **47 of 50** |
| the target set (4 valid examples, 12 refusals), both forms | **16 of 16**, both |
| the other 3, each a stage-1 rule that is stricter on purpose | `json-syntax` (the wording of the syntax message), `integer-range`, `duplicate-key` |

### 14.3 The mutants

The same check over 55,182 distinct inputs (66,620 generated, 11,438 of them
repeats): the 2 valid JSON examples, the 11 JSON refusal fixtures and the 18
`tests/stage2` documents (31 seeds) with one semantic change at a time: every value of
a key-aware pool (lsb, msb, offset, reset, base address, kind, bus width,
endianness, owner, align, size, number, written_as, name, register and field
references, enum values, constraint, version, flags) wherever that key occurs, 15
generic values at every node, every key deleted, every array element duplicated,
copied under another name and emptied, every collision of two names, offsets,
bounds or references, and every (lsb, msb) pair from a 10 by 10 grid; and the two
textual examples and the parse-error fixture with every token deleted, every
number replaced by 20 values and every keyword replaced by 9.

| | Inputs |
|---|---|
| distinct inputs | 55,182 |
| diagnostics byte-identical to `checker.py` (same objects, same order, same bytes) | **48,176** |
| differ, each in a class below | 1,192 |
| `checker.py` raises; compared only for "cancho answered, exit 0 or 1, no trap" | 5,814 |
| differ and unexplained | **0** |
| verdict (any Error) agrees | 49,362 of the 49,368 both sides answered; the other 6 are in the classes below |

The 1,192 by class (an input is in exactly one):

| Class | Inputs | Why |
|---|---|---|
| `integer-range` | 1,160 | an integer of more than 18 digits is refused by the validator (stage 1) and, in the text form, by the parser; Python reads it |
| `pattern-trailing-newline` | 30 | Python's `$` accepts a string with a final newline (`"0.1.0\n"`); the validator does not (stage 1) |
| `duplicate-key` | 1 | refused (stage 1) |
| `json-syntax-wording` | 1 | the syntax message is `std.json`'s (stage 1) |

The 5,814 inputs on which `checker.py` raises, by the statement that raised
(`checker.py` line; the cancho side answered every one with exit 0 or 1):

| `checker.py` line | Statement | Exception | Inputs |
|---|---|---|---|
| 170 | `for reg in registers`, `registers` a number | `TypeError` | 102 |
| 171 | `reg.get`, a register that is not an object | `AttributeError` | 666 |
| 251 | `kind not in _KNOWN_KINDS`, `kind` a list or an object | `TypeError` | 232 |
| 310 | `f.get`, a field that is not an object | `AttributeError` | 1,006 |
| 452 | `block.get("registers")` iterated for `registers_by_name` | `TypeError` | 118 |
| 455 | `for intr in interrupts`, `interrupts` a number | `TypeError` | 108 |
| 456 | `intr.get`, an interrupt that is not an object | `AttributeError` | 332 |
| 494 | `kind not in _VALID_CLEAR_KINDS`, `kind` unhashable | `TypeError` | 72 |
| 523 | `ref.get`, a reference that is not an object | `AttributeError` | 996 |
| 527 | `registers_by_name.get(reg_name)`, `reg_name` unhashable | `TypeError` | 168 |
| 544 | `reg.get("fields")` iterated, or `f.get("name")` on a non-object | `TypeError`, `AttributeError` | 404, 105 |
| 545 | `field_name not in field_names`, `field_name` unhashable | `TypeError` | 316 |
| 571, 572 | `for buf in buffers`; `buf.get` | `TypeError`, `AttributeError` | 108, 306 |
| 586, 587 | `for f in fields` of a buffer; `f.get` | `TypeError`, `AttributeError` | 144, 631 |

All are the same property: `checker.py` assumes a schema-valid shape (the module's
docstring says the checker "is total", which it is not). The port skips an element
that is not an object and treats an unhashable kind as unknown; the schema validator
reports the shape, so such a document is still refused.

Listed in 13.5 and **not exercised**: the float spelling (the pool has floats, and the
ones in it, such as `4.0` and `16.5`, are spelt as Python's `repr` spells them; no
mutant had one that is not), the saturated hex (the pool has six hex
literals past 2^60, in offsets, resets and base addresses, and the messages
agreed), and the width past 62 bits. They are not shown to be harmless; the
corpus did not reach a difference.

### 14.4 Mutation checks: one deliberate break per rule

`python3 tests/mutation/run.py` copies `src/`, changes one expression in the copy
(the old text must occur exactly once), builds `chw` from the copy and runs, in
order: the four new unit suites against the copy; `chw conform . --fixtures
tests/stage1,tests/stage2` with the mutant; the "runner can fail" trees with it;
and, for a mutant none of those noticed, the fixtures and then the full mutant
differential against `checker.py`. A mutant is killed when any of them fails.
50 mutations: one or more per rule of the catalog (at its boundary where it has
one), the reading of hex (`int(s, 16)`), the catalog's tier, severity and
subject, the JSON writer (key order, the related list, pointers, escapes), the
conversion of the stage-1 report, the text form's caret, and three in the
conformance runner.

First run of all 50 (a runner with six trees, and five fewer assertions in the
unit tests): **44 were killed by the unit tests, the runner or its trees, 4 by the
differential alone, 2 survived everything.**

* The 4 that only the differential noticed were an empty name accepted for a
  field, a DMA field and a DMA buffer, and a version of four numbers: the unit
  tests had tried an empty *register*, interrupt and block name and a version
  with a dot too many, not these. The differential reported 78, 45, 22 and 30
  unexplained differences. The unit tests now try each, and the four are killed by
  them (the table).
* Of the 2 survivors, one was **not a defect**: `dma-align-illegal` replaced
  `> 4096` by `> 8192`, which cannot change an answer because the power-of-two test
  next to it already refuses 8192 (an equivalent mutant). It was replaced by a
  break of the power-of-two test itself (`k == n` to `k >= n`), which 1 unit test
  kills. The other was **a gap in the runner's own tests**: `conform-ignores-unexpected`
  (the runner stops counting a diagnostic nothing expects) passed all six trees,
  because none removed an expectation. The seventh tree (a sidecar that expects
  nothing of a fixture that is refused) was added to the gate and to the harness,
  and the runner now fails it (11 of 12).
* The 6 mutations that were killed by unit tests alone and that `conform` did not
  see (`field-overlap`, `field-bounds-overflow`, `register-offset-non-aligned`,
  `register-offset-overflow`, `reset-overflow`, `block-bus-width-invalid`: the
  fixtures hold none of the values at the edge) were also run against the full
  differential: **525, 783, 124, 56, 27 and 31 unexplained differences**, so the
  differential would have noticed each by itself.

Table, after the gaps were closed (a mutant killed by the unit tests is not run
against the differential, so that column is empty except for the 6 above and, for
the 4, the first run's count):

| Mutation | What it breaks | unit tests failing (of 50) | `conform` fixtures failing (of 46) | runner trees accepted | full differential: unexplained |
|---|---|---|---|---|---|
| `field-overlap` | overlap tests touching fields as overlapping | 1 | - | - | 525 |
| `field-bounds-overflow` | msb == bus_width allowed | 1 | - | - | 783 |
| `field-bounds-inverted` | one-bit fields refused | 9 | 31 of 46 fail | - | not run |
| `field-enum-overflow` | the largest value refused | 1 | 16 of 46 fail | - | not run |
| `field-enum-negative` | -1 allowed | 1 | 1 of 46 fail | - | not run |
| `field-name-missing` | an empty name accepted | 1 | - | - | 78 before the unit test was added |
| `field-bounds-missing` | one missing bound accepted | 1 | 1 of 46 fail | - | not run |
| `register-offset-duplicate` | 0x08 and 0x8 are different offsets | 3 | - | - | not run |
| `register-offset-non-aligned` | an offset off by one byte accepted | 2 | - | - | 124 |
| `register-offset-overflow` | the last register of the space refused | 1 | - | - | 56 |
| `register-offset-missing` | an unreadable offset accepted | 1 | 1 of 46 fail | - | not run |
| `register-kind-unknown` | W0S not a kind | 1 | - | - | not run |
| `reset-overflow` | the largest reset refused | 1 | - | - | 27 |
| `reset-wo-nonzero` | warns on a zero reset | 2 | 1 of 46 fail | - | not run |
| `dma-overlap` | adjacent fields overlap | 1 | 15 of 46 fail | - | not run |
| `dma-align-unsatisfied` | an offset one past the alignment accepted | 2 | 1 of 46 fail | - | not run |
| `dma-align-illegal` | any alignment up to a power of two is legal | 1 | 1 of 46 fail | - | 0 before the unit test was added |
| `dma-owner-unknown` | DEVICE refused | 1 | 16 of 46 fail | - | not run |
| `dma-field-size` | a DMA field is three bytes | 1 | 1 of 46 fail | - | not run |
| `dma-field-name-missing` | an empty field name accepted | 1 | - | - | 45 before the unit test was added |
| `dma-name-missing` | an empty buffer name accepted | 1 | - | - | 22 before the unit test was added |
| `block-bus-width-invalid` | 16 refused | 6 | - | - | 31 |
| `block-endianness-unknown` | big refused | 1 | - | - | not run |
| `block-base-address-missing` | a zero base address accepted | 1 | - | - | not run |
| `block-name-missing` | an empty block name accepted | 1 | 1 of 46 fail | - | not run |
| `schema-version-unsupported` | 0.2 supported, 0.1 not | 28 | 42 of 46 fail | - | not run |
| `version-shape` | four-part versions accepted | 1 | - | - | 30 before the unit test was added |
| `interrupt-unresolved-field` | a field resolves to any other field | 3 | 17 of 46 fail | - | not run |
| `interrupt-unresolved-register` | no register ever resolves | 3 | 17 of 46 fail | - | not run |
| `interrupt-clear-kind` | RC refused | 1 | - | - | not run |
| `interrupt-duplicate-name` | duplicates not noticed | 1 | 1 of 46 fail | - | not run |
| `interrupt-role-order` | enable reported as status | 1 | 4 of 46 fail | - | not run |
| `interrupt-name-missing` | an empty interrupt name accepted | 1 | - | - | not run |
| `register-name-missing` | an empty register name accepted | 1 | - | - | not run |
| `hex-underscore` | int(s, 16) underscore rule dropped | 2 | - | - | not run |
| `hex-trailing-space` | trailing whitespace refused | 1 | - | - | not run |
| `remedy-confidence` | the remediation says High | 1 | - | - | not run |
| `json-key-order` | severity and tier swapped | 3 | - | - | not run |
| `json-related-dropped` | related never printed | 1 | - | - | not run |
| `tier-runtime` | the version rule is Static | 1 | - | - | not run |
| `severity-warning` | a warning is an error | 3 | - | - | not run |
| `subject-kind` | field-overlap has a Register subject | 0 | 2 of 46 fail | - | not run |
| `json-pointer-index` | an array index printed as a string | 2 | - | - | not run |
| `json-escape-undone` | ~1 not undone in a pointer | 1 | - | - | not run |
| `report-prefix` | the schema message loses Python's prefix | 2 | - | - | not run |
| `report-parse-span` | a parse error ends where it starts | 1 | - | - | not run |
| `text-snippet` | the caret is one column off | 1 | - | - | not run |
| `conform-ignores-code` | the runner does not compare the code | 0 | - | 2 | not run |
| `conform-ignores-subject` | the runner does not compare the subject | 0 | - | 1 | not run |
| `conform-ignores-unexpected` | the runner ignores a diagnostic nothing expects | 0 | - | 1 | 0 before the unit test was added |

All 50 are killed. The cost: a mutant is about two minutes of compiler time (a
build and four suites), so the harness took 30 minutes for 50 on a machine that
was also running someone else's builds (load average 7 to 14).

### 14.5 Tests

`cancho test`: **144 tests in 11 suites**, all passing (stage 1: 94 in 7). The 50
new: `check` 29, `dg_output` 7, `diagnostic` 6, `hexval` 8. The `check` suite tests
each rule at its edge, the value just inside and the one just outside (a field
ending at the bus width and one bit past it; an enum value equal to the mask and one
over; an offset of `0xfffffffc` and `0x100000000`; adjacent and overlapping DMA
fields; an alignment of 4096, 4097, 0, -4, 6 and 4.0), and the
hostile inputs (integers past 18 digits, hex literals past 2^60, elements that are
not objects). Its expectations are what `checker.py` says; the differential is what
checks that.

### 14.6 Size, speed, authority

| | Value |
|---|---|
| new product modules, lines | `diagnostic` 877, `check_regs` 449, `check_util` 442, `dg_json` 312, `check_intr` 236, `check_dma` 222, `check_block` 194, `dg_text` 153, `hexval` 133, `dg_report` 88, `check` 57: **3,163**. Changed: `conform` 482 to 536, `main` 214 to 324, `load` 196 to 245, `diag`, `front`, `parse`, `json_out` by a few lines each |
| the Python they replace, lines | `checker.py` 838 (80 of them, `_validate_schema`, `check_file` and the CLI loop, were already stage 1's), `diagnostic.py` 114, `text_format.py` 136: **1,088**; `conformance.py` 170 was stage 1's |
| ratio | 2.9x. Not like for like: the port also does Python's `repr`, `str`, `int(s, 16)` and `json.dumps(indent=2)` for the values it quotes, and keeps the catalog as code |
| largest files | `schema.cho` 984 and `diagnostic.cho` 877 (the catalog is 568 of them): both over the 800-line design budget, under the 2,000 ceiling |
| program | 25 files, 7,842 lines (stage 1: 14 files, 4,422 lines of the program) |
| `cancho build` | 13.1 s (machine idle), 14.8 s (load average 5) |
| `cancho check` of the program | 8.0 s (idle), 15.5 s (loaded) |
| binary | 807,320 bytes (stage 1: 374,912) |
| `chw check uart.chw` | 2.0 ms (20-run mean, machine busy) against 172.0 ms for `checker.py` in a fresh interpreter, most of which is start-up and import |
| `chw conform .` | 6.2 ms for the 12 refusals and 4 valid examples, 9.6 ms with the 34 `tests/stage1` and `tests/stage2` fixtures; `conformance.py` 188.8 ms for the first |
| hostile inputs | `stress.py` now runs 19 inputs through both `chw validate` and `chw check`, 38 runs, each exit 0 or 1 as wanted in under 20 s: the slowest is 500 fields on the same 32 bits, 124,750 overlap diagnostics, 2.35 s (quadratic, as `checker.py` is). No trap |
| the gate | 12 min 45 s, `exit 0`, on a machine whose load average was 7 to 14 from other work; `python3 scripts/run_gate.py` 5.0 s, `GATE PASSED` |
| `cancho authority` | unchanged: `args`, `dir_read`, `err_write`, `file_read`, `fs_read("")`, `heap`, `io_write`; never the network, signals, other programs or foreign code. `scripts/authority.expected` was not touched, and no `Ffi` or foreign call is used |

### 14.7 What was easy, and what was not (cancho)

Easy: translating `checker.py`. Each rule is its Python statement and its
f-string; the compiler's refusals during the whole slice were about ten (below), each a
local edit. A match over an enum with 36 arms is checked for exhaustiveness, which
is the property the catalog wants. `std.map` made `registers_by_name`, the offset
table and the duplicate-interrupt set linear without a thought. Every integer that
came from a document is read through a clamp or a saturating hex parse, and no input
in 55,182 reached a trap.

Not easy, with the measure where there is one:

* **A struct field cannot be assigned** (`d.n = 5` is refused: "`Dg` is not a
  reference, so this would write one field and leave the rest"). A diagnostic is
  built once and rebuilt by `with_expected`, `with_remedy`, `with_loc`,
  `with_keyword`, `with_pointer`, `with_nest`, each copying the nine fields:
  about 45 of `diagnostic.cho`'s lines, but the shape forced the sub-records
  (`Subj`, `Loc`, `Rem`, `Kids`) that keep the copy at nine.
* **An enum has no `==` and no iteration.** `rule_name`, `rule_severity`,
  `rule_tier` and `rule_kind` are four matches of 36 arms (the catalog is 568 of
  `diagnostic.cho`'s 877 lines, 110 of them `rule_at`), and "every rule" is a hand-written `rule_at(i)`
  that a unit test pins to `rule_count()`. A `static` table of structs would
  replace most of it.
* **Text is built by appending to a threaded `Buffer`.** The message of
  `field-overlap` is 14 appends where Python has one f-string; `Diags` (which
  owns the pool) must be taken apart and put back by every helper that appends
  to it (60 sites mention `Diags {`). The same cost as stage 1's 6.
* **No hex formatting in `std`** (`std.fmt` has floats only): `put_hex` is 12 lines.
  **No Python `repr`** for floats (stage 1) or `int(s, 16)`; `hexval.cho` is 133
  lines for what `int(s, 16)` does with its underscores and blanks.
* **A pure test takes no parameters and a test that takes `heap` must use it**
  (`declares heap but never performs it`), which cost three rewrites.
* **`\u` is not an escape** in a string literal; the em dash and the section sign in
  two messages are written as the characters.
* **`val` is a reserved word** (`let val = ...` is "expected an identifier").
* **`cancho fmt` removes the parentheses of `(1 << bw)`** (`a + b > 1 << bw` is
  `a + b > (1 << bw)`: shift binds tighter than comparison), which a mutation
  harness that matches source text has to know.
* **The compiler is slow to say no:** `cancho check` of the program is 8 s,
  `cancho build` 13 s, and a `cancho test` of one suite against the whole library
  about 15 s, so a mutation run is about two minutes a mutation.

### 14.8 What stage 2 does not show, and what is not done

Not done:

* **Located spans for the semantic rules.** Every semantic diagnostic carries the
  whole-file span 1:1, as Python's do. The tape has the offsets (stage 1 already
  uses them), so a located span is additive.
* **`ran`**, the argument by which `check()` tells `tools/report/report.py` which
  rule groups executed. The report is still Python and reads the Python checker;
  the cancho checker does not yet expose it.
* **Several files in one invocation** (`checker.py FILE...`), and `chw check -`
  (standard input). `chw check` takes one file.
* **`Warning` severity in the exit status of the structural half** is as Python's
  (warnings do not fail), but `chw conform` cannot yet pin a *severity* in a
  sidecar; the sidecar format has no field for it.
* The rule `dma-written-by-binding` and the generator and roundtrip rules of the
  catalog (`generator-*`, `roundtrip-failed`, `evidence-over-claim`,
  `ir-version-unsupported`) are not the checker's: no cancho tool emits them yet.

Not shown by this slice:

* Non-ASCII digits and blanks in `int(s, 16)` (the port reads ASCII), `splitlines`
  on `\x0b`, `\x0c`, `\x1c` to `\x1e`, U+2028 in the text form's snippet, and a
  non-ASCII character that `repr` escapes and `pyrepr` does not (all as in stage 1).
* A float quoted in a message (source text, not `repr(float)`).
* A DMA field whose `offset` is past 2^60 *and* overlaps another such field: the
  offsets saturate to the same value, so the pair is reported as overlapping where
  Python decides by the exact sum.
* Memory and time on a very large contract: the checker is quadratic in the number
  of fields of one register and of one DMA buffer, as `checker.py` is, and linear in
  everything else; `tests/differential/stress.py` (stage 1) runs the 11 hostile
  inputs through `chw validate`, not through `chw check`.

---

## 15. Corrections (stage 2)

Stage 2 (this change):

1. **The order of work.** This slice wrote the design (13) after the checker
   existed and after the first mutant run, not before; `CONTRIBUTING.md` asks for the
   design first. Stated in 13 as well.
2. **§12** asked whether the `Diagnostic` could stay a line of text. It could not
   (13.2), and whether the semantic rules fit 800 lines a file. They do, in six
   files of 57 to 449 lines. The catalog does not: `diagnostic.cho` is 877 lines,
   over the budget the way `schema.cho` (984) is, for the reason in 14.7.
3. **§3's estimates for `check/`**, from the 1.75 ratio: block 200, registers 450,
   fields 600, interrupts 250, dma 450, driver 200, `diag` 250, `diag_text` 250:
   2,650 lines. Measured: `check_block` 194, `check_regs` (registers and fields)
   449, `check_intr` 236, `check_dma` 222, `check` 57, `diagnostic` 877 + `check_util`
   442 + `hexval` 133, `dg_json` 312 + `dg_text` 153 + `dg_report` 88: 3,163 lines. The
   rules came in at 1,158 against 2,000 estimated (the ratio overstated them, as
   §3 said it probably would: the checker is comparisons and the fields of a
   register fit one function), and everything around them at 2,005 against 650
   (the catalog, the reading of values as Python reads them, and the two output
   forms were not in the estimate).
4. **§9.4's report line** gains a seventh field for a `parse-error` (the column its
   token ends at), after the message so that every reader of the first six is
   unchanged; the Python tool's span ends `max(len(token), 1)` columns on, and its
   end-of-file token is the text `<end of file>`, 13 wide, which is what the
   differential found (3 inputs) after the first version used 1.
5. **§10.1** says 14 of 19 entries are deferred. That was true of stage 1 and is
   left as it was; §14.1 is the present.
6. **What §13.5 did not list and the differential found.** The first run of the
   mutants had 408 unexplained differences; the classes, in the order they were
   found and fixed:
   * *The block's `name` is not always a string in Python's subject* (276 + 48
     inputs): `block.get("name", "<missing>")` is whatever the document held, a
     number, `null`, an array, and the subject dict carries it as that value, while
     messages say `str()` of it. The `Sp` of a name now carries the JSON text of
     such a value after its plain text (`dg.Sp.x`), and the JSON form prints it
     re-indented to the depth it sits at (10 inputs found the indent wrong the first time:
     a related entry is deeper than its parent).
   * *Hand-built JSON strings in `actual`* (4 inputs): `"offset shared with " + name`
     was assembled with literal quotes, so a name with a `"` or a non-ASCII
     character was not escaped. Every JSON string is now written by one function
     (`jquote`, `put_jtext`).
   * *`pattern-trailing-newline` applies to the version string too* (72 inputs), not
     only to hex strings as 13.5 and stage 1's table suggested.
   * *The text parser's refusal of a decimal past 18 digits* (stage 0) was a
     class of the check differential as well (1 input).
7. **The gate** takes about thirteen minutes now (12 min 45 s on a loaded machine),
   not the "about five" of §10: the checker differential is 3.5 of them and the
   unit suites compile against a library twice the size.
8. **The differential itself** was changed three times by what it found (the above)
   and once by its own report: the exception type alone ("`AttributeError`: 4,042")
   hid which statements raise, so it now names the `checker.py` line.

---

## 16. Next slice

Stage 3: the c-header generator (stage 3 of section 2), which reads the IR, not the
tape: the IR is still there, loaded from both forms, and the generators are the
first consumers that need its typed records rather than a document. What stage 2
leaves it:

* the `Diagnostic` record and its two output forms, which `generator-target-unknown`
  and `generator-unimplemented` (catalog 3.5) will use without a new shape;
* the open question of the IR's losses (an invalid enum value survives only as a
  default): a generator is run on a contract the checker accepted, so it may not
  matter, and the first generator is where to find out;
* the `ran` argument of `check()`, which `report` (stage 6) needs, and located spans
  for the semantic rules, both additive (14.8);
* the first question stage 3 asks: whether text assembly under linear ownership
  (8.1) is as costly as the 14 appends of one message suggests. The C header is
  about 340 lines of Python; the budget to beat is 14.7's, that a message built from
  pieces costs about three lines a piece.

---

## 17. Stage 3 design: the C header generator

> **Status: design, now built; measured in §18.** Written before the code, from reading `gen/c-header/c_header.py`
> (340 lines), `tools/generate/generate.py` (the dispatcher) and `spec/generators/README.md`
> §1 and §2. Nothing below is measured until §18 exists; a number marked *estimate* is a guess.
> A claim that turns out false is corrected here, in place (§19).

### 17.1 What this slice decides

1. **Whether a generator in cancho reads the typed IR comfortably.** Stage 2 read the JSON
   tape; the generators are the first consumers of `chw.ir` (§16). The IR holds spans into the
   source, not strings, and every number the generator prints comes from one of them.
2. **What text assembly costs** (§8.1, §14.7): the budget to beat is "about three lines a
   piece". A C header is mostly fixed text with names spliced in, so the measure is lines of
   cancho per line of Python, per emitted line.
3. **The command line**: `chw generate FILE --target c-header`, and what it says for the four
   other targets.

It does **not** decide the other four generators (SystemVerilog, devicetree, cancho-binding,
SVD), which stay Python until their own slice, and it does not change what any generator emits:
the oracle is the Python generator's bytes.

### 17.2 The command

```
chw generate FILE --target T [--schema S]
```

Exactly the dispatcher of `tools/generate/generate.py`, in its order and with its exit codes,
because the differential compares both:

| step | refusal | exit |
|---|---|---|
| FILE missing | `error: file not found: FILE` | 2 |
| FILE does not load (text or JSON form) | `error[CODE]: MESSAGE`, one per diagnostic, stderr | 1 |
| the checker reports an Error | `error[CODE]: MESSAGE` for each, then `error: not generating from a refused contract.` | 1 |
| `--target` not one of the five | `error[generator-target-unknown]: target 'T' is not supported. Known: c-header, cancho-binding, devicetree, svd, systemverilog` | 1 |
| a known target not yet ported | `error[generator-unimplemented]: target T: not ported to cancho yet` | 1 |
| the generator refuses a feature (DMA field of a size with no C type) | `error[generator-unimplemented]: target c-header: DMA field 'X' has size N, ...` | 1 |

The two `generator-*` tags are the spec's (`spec/diagnostics` §3.5), and they are **not** in
`chw catalog`: the gate's catalog check lists them among "6 rules in the spec that no cancho tool
emits". The Python dispatcher does not build `Diagnostic` records for them either; it prints one
`error[tag]: message` line, and the oracle is that line's bytes. So this slice prints the line,
keeps the two tags as named constants in `main.cho`, and does not add them to the `Rule` enum (36
arms, four matches of 36 each, §14.7) until `report` (stage 6) needs them as records. *(An earlier
draft of this section said the tags were already in `chw catalog` and that the `Diagnostic` record
would carry them; both were wrong, found by reading the gate's own output before writing code.)*
Each is reached by a test (§17.5, items 2 and 3).
One deviation from the Python tool is deliberate and stated: the Python dispatcher reports a
registered-but-unported target as `generator-unimplemented` only when the module is *missing
on disk*, which cannot occur here, so the cancho command uses the tag for what is true, that
the target exists in the tool and not yet in this binary. The differential covers `c-header`
only; the other four are tested as refusals with their tag.

### 17.3 Shape

* **One new module, `src/gen_c.cho`** (estimate 350 lines), a pure function
  `chw.gen_c.generate(heap, ir, source, path) -> Result`, where the result is the header text
  or a refusal (the DMA size, with the field name and the size). It prints nothing and touches
  no file: `main.cho` owns the I/O (`[heap]` only).
* **`load.cho` gains two accessors**, `ir_of(doc)` and `source_of(doc)`; the `Doc` already holds
  both (`ir`, `text`), which is the reason the generator can run on either form.
* **Naming helpers** (`UartRegs` → `UART_REGS` / `uart_regs`, and the Python docstring's own
  "wrong but discouraged" case `UartCTRLx` → `uart_c_t_r_lx`) are ported rule for rule from
  `_to_lower_snake`, not "improved": the oracle is the bytes.
* **Hex**: the IR keeps offsets, resets and the base address as spans of the hex text. They are
  read with `chw.hexval` (the checker's reading, §13.5), and printed with a `put_hex` of a given
  minimum width (the 12-line helper §14.7 asked `std` for).

### 17.4 What the generator assumes, and what it does when that is false

The generators assume a checked IR (`spec/generators` §1 rule 5). The command guarantees it by
running the checker first. Inside the function, though, no input may reach a trap, and the
Python version would raise on an unchecked one, so:

* a value past `hexval`'s 2^60 (`big`), a width not in {8, 16, 32}, or a field outside its
  register can only occur after a checker miss; the function answers a refusal with the tag
  **`internal`** (exit 3, the Python `error[internal]`), never a partial header and never a
  trap. A unit test hands it each of these directly.
* the DMA size rule (1, 2, 4, 8) is *not* a checker rule; it is the generator's refusal
  (`generator-unimplemented`, exit 1) and is the one refusal path in normal use.

### 17.5 The oracle, and what would make this slice fail

All test-only Python, `tests/differential/generate_c.py` (the same discipline as §13.6):

1. **Bytes.** For every file that loads and checks clean (the 2 valid examples, the 2 textual
   examples, the clean `tests/stage1` and `tests/stage2` files), `chw generate` and
   `generate.py --target c-header` give the same stdout, stderr and exit code.
2. **Refusals.** For every other fixture the two give the same stderr and exit code (the
   dispatcher's refusal text is the checker's, already identical byte for byte, §14.2).
3. **Mutants** (the key-aware pool of §13.6, restricted to the mutants that still check clean):
   same comparison. The DMA `size` mutants are what reach `generator-unimplemented`.
4. **The header compiles.** The cancho header is compiled with `cc -std=c11 -Wall -Wextra
   -Werror -fsyntax-only` (a test oracle, as `tests/behavioral/c_behavior.py` is) for every clean
   file; the contract of `spec/generators` §2.1 says it must.
5. **No trap.** A hostile-input pass as stage 1/2: 0 traps required.
6. **The checks can fail.** Deliberate breaks of the generator (a field order, a mask, a
   dropped `_rsvd`, a dropped stable ID, the guard) must each fail the differential, run and
   reported as stage 2's mutation checks were (§14.4).

### 17.6 Gate and size

`scripts/gate_cancho.sh` gains the unit suite for `gen_c`, the differential (step 8c), and the
`cc -fsyntax-only` check when a C compiler is present (reported as skipped otherwise, never as
passed). The authority report (`scripts/authority.expected`) must be unchanged except for what
`generate` adds, which is nothing new: `heap`, `io_write`, `err_write`, `fs_read("")`,
`file_read`, `args`, as `check` already has. Files stay under 2,000 lines (`main.cho` is 324).

### 17.7 Risks, in order

1. **Text assembly volume.** ~150 `write` calls in Python; if the cancho cost is far above three
   lines a piece, the result is a finding to report (§8.1), and the likely remedy is a small
   `emit` table (a template with holes), not a change to `std`.
2. **Python quirks the oracle will expose** (`str.lower()` on a non-ASCII letter; the two
   `vol` branches that are identical; the sort on `(lsb, msb, dict)` that would raise on a tie).
   The checker excludes the last two; the first is excluded by the schema's name pattern. Each
   is written down in §18 if the differential disagrees.
3. **Integers past 2^60** in an enum value or a base address: handled as §17.4.


---

## 18. Stage 3 measured

Compiler cancho `7e4088b`, Linux x86-64; gcc 13.3 as the compile oracle. Everything below is the output of
`tests/differential/generate_c.py` (the gate's step 8c), `tests/mutation/run_gen_c.py` and `cancho test`.

### 18.1 What was built

| file | lines | what |
|---|---:|---|
| `src/gen_c.cho` | 590 | the generator: 230 lines of emission, the rest naming helpers, the stable sort, the checks of 17.4 |
| `src/main.cho` | 475 (+151) | `chw generate FILE --target T [--schema S]`, the dispatcher of `generate.py` in its order |
| `src/load.cho` | +31 | `ir_of`, `source_of`, `loaded` |
| `tests/unit/test_gen_c.cho` | 240 | 12 tests |
| `tests/differential/generate_c.py` | 315 | the oracle driver |
| `tests/mutation/run_gen_c.py` | 99 | 19 deliberate breaks |

`cancho check` of the program is unchanged in kind; `cancho build` of `chw` takes about 15 s. The authority
report of `chw` is unchanged (gate step 10): `generate` adds `heap`, `io_write`, `err_write`, `fs_read("")`,
`file_read`, `args`, which `check` already has.

### 18.2 Against `generate.py`, byte for byte

Fixtures (50 files: valid examples, refusals, `tests/stage1`, `tests/stage2`): stdout, stderr and exit status
identical on **45**, and 5 known differences (3 are the checker's, already explained in 14.2; the other two are
in 18.3). Seven of them generate a header, and **all seven compile** with `cc -std=c11 -Wall -Wextra -Werror`.

Mutants (the 55,182 distinct inputs of `check_json.py`, plus 27 hand-made ones (23 for the generator, 4 hostile and large), **55,209**): 

| | inputs |
|---|---:|
| identical (stdout, stderr, exit status) | 47,789 (a header on 3,952, a refusal on 43,837) |
| the two checkers differ in a class 14.2 explains | 1,192 |
| cancho refuses a name the header cannot spell; Python's header does not compile | 338 |
| cancho refuses a non-ASCII name (18.3, item 2) | 47 |
| `"bus_width": 8.0` and `32.0` (18.3, item 3) | 2 written, 8 where Python raises |
| both tools answer `internal` | 2 |
| a DMA offset of 2^60 or more (18.3, item 4) | 17 |
| `generate.py` raised (checker.py assumes a schema-valid shape); cancho answered with exit 0 or 1 | 5,814 |
| **unexplained** | **0** |

No input reached a trap: the largest hostile ones (20,000 registers in descending offset order, 20,000 DMA
fields in descending order, a 100,000-byte name) are in the hand-made set, compared with Python's bytes, and
take 0.3 s each.

### 18.3 What the oracle found, and what was decided

1. **The Python generator writes C that does not compile for names a contract may have.** The schema requires
   a name to be a non-empty string; no rule requires an identifier. Of the 23 hand-made inputs for the generator, nine produced a
   header with `generate.py` that gcc rejects: a register called `INT` (the member `int`), a field called
   `Register`, a DMA field called `while`, `A-B`, `x y`, a block called `9Blk` or `int`, a register called
   `A*/B` (the `*/` ends the comment that carries its stable ID, so what follows is code), and enum labels containing `*/` or `/*` (the second is a `-Wcomment` error). A block called `int` or a buffer called `for` compile (the suffix `_t` and the upper case save them), so they are not refused. An empty name is the checker's refusal, not the generator's.
   Across the mutants 338 more. **The port refuses these** with `generator-unimplemented` and a message that
   names the name (a keyword once lower-cased, not an identifier, or a comment delimiter); it does not mangle,
   because a mangled name is a different name in the stable ID. This is a **deliberate difference** from the
   Python tool, admitted by the oracle only when Python's header really does not compile. A contract whose
   names are all identifiers is unaffected.
2. **Non-ASCII names are refused although gcc and clang accept them.** Python lower-cases and snake-cases by
   Unicode rules; the port has no Unicode tables (the JSON loader decodes escapes, so a name arrives as UTF-8
   bytes, not as a code point list). `tests/stage1/escaped-names.chw` (a block called `Té😀`) is the fixture. A
   narrowing, stated here and not hidden: the port writes ASCII names only.
3. **Python writes `32.0` into C for a bus width written `3.2e1`.** The schema accepts it as an integer;
   `generate.py` formats `31.0` into a bit-field width (`uint32_t _rsvd1 : 31.0;`), which does not compile,
   in the valid fixture `tests/stage1/valid-float-integer.chw`; for `8.0` and `32.0` set on a mutant it
   raises (`Precision not allowed in integer format specifier`). The port reads the integer and writes the
   header the schema describes. Admitted only when the cancho header compiles and equals Python's once `N.0`
   is read as `N`.
4. **A DMA offset of 2^60 or more is refused.** `hexval` is exact below 2^60 (a cancho `int` traps on
   overflow), so the port cannot size the gap; Python writes an array that many bytes long, which a 64-bit
   compiler accepts. A limit of the port.
5. **The checker reads a float bus width as 32; the generator reads it as the integer.** A contract with
   `"bus_width": 8.0` and a field at bit 31 passes `chw check` (the stage-2 quirk, 13.5) and would have been
   written as a field outside an 8-bit register. The generator now checks every field against the width and
   answers `internal`. The quirk belongs to the checker; this slice does not change it.
6. **The Python docstring is wrong about its own rule.** `_to_lower_snake` says `UartCTRLx` becomes
   `uart_c_t_r_lx`; the code gives `uart_ctr_lx` (the `L` before a lower-case letter ends the abbreviation).
   The port follows the code; a unit test pins it.

### 18.4 The checks can fail

`tests/mutation/run_gen_c.py` changes one expression of `gen_c.cho` at a time, builds `chw`, and runs the
fixtures, the hand-made inputs and the unit suite. **19 of 19 breaks are killed**: register order, field
order, the two reserved-gap tests, a field one bit narrow, the include guard, a stable ID, the kind note, the
reset and base digit counts, a gap counted in registers, a DMA field of eight bytes, the end of an
abbreviation, a keyword allowed, any byte an identifier byte, a comment delimiter allowed, 32 not a bus width,
a base past 2^60, an unreadable register offset. Three are killed **only by the unit tests**: the keyword, the
comment delimiter and the unreadable offset. That is the shape of the oracle, not a gap in it: where the
Python tool writes the same wrong bytes, a differential cannot tell, so those rules are pinned by a test that
says what the right answer is. Two earlier breaks did not count and were replaced: one changed the order of
fields by the wrong key, which no valid contract can tell (fields do not overlap), and one changed the owner
default, which the schema makes unreachable.

### 18.5 What was easy, and what was not

Easy: the translation. Each Python `out.write(f"...")` becomes a chain of `put` calls: 72 `o = put...`
statements in `gen_c.cho` for the 34 Python writes, about two statements a write, inside the budget of three
that 14.7 set (counted by `grep`, not by tracing each write). The stable sort is a copy of stage 1's merge sort with an index
array; the generator is linear on every hostile input.

Not easy:

* **The oracle is a bug-compatible target.** The first full run left 83 unexplained differences; every one
  was the port being right, or at a stated limit, and Python's bytes wrong or astronomical (18.3, 3, 4 and
  5). Each needed a class with a stated reason and a condition that
  the compiler confirms, rather than a tolerance.
* **A test harness that shares a directory between threads gives wrong compile verdicts.** The compile oracle
  first said the header with `A*/B` compiled, because two pool threads wrote the same `x.h`. Fixed by one
  directory per call, and noted because a wrong "compiles" would have hidden finding 1.
* **`front.parse_text` and `json_in.load` give spans into different buffers** (the text itself, or a decoded
  copy of it). The generator takes the buffer the IR indexes (`load.source_of`) and never the file's bytes.
* **No Unicode in `std`** (item 2 above).
* **A test cannot take the `Fs`**, so the command-line paths (file missing, unknown target, unported target)
  are covered by the gate's differential and by `generate.py`'s own text, not by a unit test.

### 18.6 What stage 3 does not show

* The four other generators (SystemVerilog, devicetree, cancho-binding, SVD) are not ported *(corrected: devicetree is, §20 to §22)*. `chw generate`
  answers `generator-unimplemented` for them and `generator-target-unknown` for anything else; the Python tool
  has all five.
* Only Linux x86-64 and gcc. clang was not run as the compile oracle, MSVC cannot be.
* Name collisions are not checked: two registers whose lower-cased names are equal, or a register called
  `uint32` (whose type `uint32_t` is the standard one). The Python tool does not check them either.
* The behavioural test that compiles a header against a device model (`tests/behavioral/`) is still Python
  and was not run against the cancho headers; the compile oracle here is syntax only (`-fsyntax-only`).

---

## 19. Corrections (stage 3)

* 17.2 said the two `generator-*` tags were in `chw catalog` and that the stage-2 `Diagnostic` record
  would carry them. Neither is true (the gate lists them among "6 rules in the spec that no cancho tool
  emits"); the section was corrected before any code was written, and the command prints the dispatcher's
  `error[tag]: message` line, as `generate.py` does.
* 17.1 and 17.4 spoke of a DMA field size with no C type as "the one refusal path in normal use". The schema
  has no `size` key for a DMA field (it is `additionalProperties: false`), so the size is always 4 and the
  refusal cannot be reached from a contract that passes the schema. The generator keeps no size logic.
* 17.4 predicted that names would be taken from the contract as they are. They are not: 18.3 (1) and (2).
* 17.5 predicted the oracle's classes as `checker-known`, `python-crash` and `unspellable`. Six were needed
  (adding non-ASCII names, `32.0` widths, both-internal and offsets past 2^60), each in 18.3.

---

## 20. Stage 4 design: the device-tree generator

> **Status: design, now built; measured in §21.** Written from reading `gen/devicetree/devicetree.py`
> (138 lines), `tools/generate/generate.py` and `spec/generators/README.md` §4, with the stage 3 generator
> (§17 to §19) as the pattern. *Order of work, honestly:* the code was written first as a probe of the Python
> generator's behaviour and this section was written to match what it had to decide; the differential in §21
> is what judges it, and a claim found false is corrected in §22.

### 20.1 What this slice decides

1. **Whether the stage 3 shape carries a second generator**: a pure function of the IR and the source bytes,
   `(text, status)`, the same three statuses (0 written, 1 `generator-unimplemented`, 3 `internal`), the same
   dispatcher. The test is whether the second generator costs a fraction of the first.
2. **What a fragment's oracle is.** The C header had `cc -fsyntax-only`. A DTSI fragment has `dtc`: the fragment is
   appended to a small tree that defines the `soc` node and the `intc` label it refers to, and compiled with
   `dtc -I dts -O dtb`. That is a syntax and reference check, not a check against a board's bindings (the
   fragment is block-level by the spec's own words, §4.3).

It does **not** decide SystemVerilog, cancho-binding or SVD, which stay Python, and it does not change what
the generator emits: the oracle is the Python generator's bytes.

### 20.2 What the fragment is

One node per block under `&soc`: label and node name `snake(block)`, unit address `base` in upper-case hex,
`compatible = "cancho,<snake with dashes>-v<major>"`, `reg = <base size>` with `size = max register offset +
bus_width / 8`, an `interrupt-parent` and one `<number 4>` cell per interrupt in declaration order when the block
has any, and `bus-width`. Stable IDs go in comments (`chw:Block`, `chw:Block.interrupt.name, IRQ n`). Its
refusals are the Python tool's: **no register** (the range is undefined) and **a base that does not fit one
32-bit address cell** (refused, never widened).

### 20.3 Where the port must be careful

* **`_snake` is not the C header's.** It is two regular expressions: a capital that follows a capital and
  precedes a lower-case letter starts a word, then a capital that follows a lower-case letter *or a digit*
  does. `HTTPServer2Name` is `http_server2_name`; the C header's rule would not split at the digit. The
  port is two passes over the bytes and says so.
* **Upper-case hex without padding** (`f"{base:X}"`), also for a base past 2^60, whose digits come from
  `hexval.canon_into` upper-cased, so the refusal quotes the exact value.
* **Names.** The block name becomes a label, so it must be an ASCII identifier; the Python tool writes anything.
  A name that is not, an interrupt name, version or source path with a JSON escape, a non-ASCII byte or `*/`
  (which would end the comment that carries it) is refused (`generator-unimplemented`), a narrowing admitted by
  the oracle only where `dtc` really rejects the Python fragment, or where the name is non-ASCII (§21).
  `/*` inside a comment is only text to `dtc` and is allowed, unlike in C.
* **Integers are exact below 2^60** (`hexval.cho`). A register offset past it is refused; a checked contract
  cannot have one (its offsets must fit the bus range, so the refusal is reachable only from an IR built by hand).

### 20.4 Gate and size

Step 8d of `scripts/gate_cancho.sh` (and `dtc` in CI). Budget (estimate, written before counting): about 250 lines for
the generator against 138 of Python, since text assembly costs about three lines a piece (§14.7).

### 20.5 The oracle, and what would make this slice fail

1. **Fixtures**: the 50 files through both command lines; stdout, stderr and exit status compared byte for byte;
   every fragment either tool writes compiled with `dtc`.
2. **Mutants**: the mutants of `check_json.py`, through both command lines.
3. **Hand-made inputs** only a generator can get wrong: names a label cannot spell, versions, bases at and past 32
   bits, interrupts, one block with no register, large contracts.
4. **Known classes**, as in §18.3, each admitted only for its stated reason; anything else is an unexplained
   difference and fails the step. A hand-made input whose fragment `dtc` rejects must be *refused* by cancho: writing
   the same broken fragment as Python is not an agreement (the exceptions are two names, 21.3).
5. **Unit tests** for what the command line cannot reach (an IR built by hand, a source path).
6. **Mutation checks**: one deliberate break per decision of the generator, each killed by one of the three tiers.

The slice fails if the second generator costs as much as the first, if any difference is unexplained, or if a break
survives without a stated reason.

---

## 21. Stage 4 measured

Compiler cancho `7e4088b`, Linux x86-64; `dtc` 1.7.0 as the compile oracle. Everything below is the output of
`tests/differential/generate_dts.py` (the gate's step 8d), `tests/mutation/run_gen_dts.py` and `cancho test`.

### 21.1 What was built

| file | lines | what |
|---|---:|---|
| `src/gen_dts.cho` | 343 | the generator |
| `src/gen_c.cho` | 7 words | `pub` on the seven helpers both generators use (`put`, `put_span`, `put_int`, `is_identifier`, `is_empty`, `refusal`, `internal_text`) |
| `src/main.cho` | 491 (+16) | the dispatcher answers `devicetree` as it does `c-header` |
| `tests/unit/test_gen_dts.cho` | 374 | 16 tests |
| `tests/differential/generate_dts.py` | 322 | the oracle driver |
| `tests/mutation/run_gen_dts.py` | 111 | 31 deliberate breaks |

The estimate of 20.4 (about 250 lines) was missed: **343 lines against 138 of Python, 2.5 times**. The C header's
ratio was 590 against 340. The cost is the same kind: spans instead of strings, every append a call with the heap
threaded through, and two passes where Python has two regular expressions. `chw` builds in about 15 s; the
authority report of `chw` is unchanged.

### 21.2 Against `generate.py`, byte for byte

Fixtures (50 files): stdout, stderr and exit status identical on **43**, 7 known differences, and all 5 fragments
the tools write compile with `dtc` (both tools write the same 5).

Inputs (55,224 distinct: the mutants of `check_json.py` and 42 hand-made inputs; 11,438 repeats skipped):

| | count |
|---|---:|
| identical to `generate.py` (a fragment on 3,123, a refusal on 43,896) | 47,019 |
| the checker's known differences (§13.5) | 1,192 |
| both answer `internal` | 1,172 |
| `generate.py` raised (`AttributeError` 4,042, `TypeError` 1,772), cancho answered with exit 0 or 1 and no trap | 5,814 |
| a name cancho refuses and Python writes: `dtc` rejects Python's fragment (`unspellable`) | 20 |
| the same with a non-ASCII byte or an escape, where Python's fragment compiles (`non-ascii-name`) | 7 |
| **unexplained** | **0** |

### 21.3 What the oracle found, and what was decided

1. **`Block.big` is the endianness, not a size.** The first version refused a block with `big` set as having "a bus
   width that is not a number". The differential found it at once (`endianness: 1`, then every big-endian contract):
   a guess about what a field meant, not a reading of `ir.cho`. Fixed, and a unit test writes a big-endian block.
2. **Refusal order.** Python finds an interrupt with no number only while writing, after its two refusals; the first
   version checked it before the base. Fixed: the order is Python's.
3. **`/*` in a comment.** The first version refused it as the C header does; `dtc` accepts it, so the refusal was
   too much. The check is for `*/` only (the harness reported it as "Python's fragment compiles").
4. **A block called `soc` or `intc`** redefines a label of the tree the fragment is appended to, and `dtc` rejects the
   result. Python writes the same fragment and so does this generator: a **shared defect**, not fixed (the
   oracle's tree has those labels because the spec's fragment refers to `&soc` and `&intc`; a board whose node has
   another name is the board's concern). The harness lists the two names and fails on any other hand-made input
   whose fragment `dtc` rejects but cancho writes.
5. **Names.** A block name must be an ASCII identifier (a label); an interrupt name, a version and the source path
   must be ASCII, free of a JSON escape and of `*/`. This narrows Python, which writes anything: 20 inputs where
   Python's fragment does not compile and 7 where it does (non-ASCII).
6. **Register offsets past 2^60** cannot occur in a checked contract (offsets must fit the bus range, so the checker
   refuses them: `register-offset-overflow`); the refusal is reachable only from an IR built by hand, and a unit test
   reaches it.

### 21.4 The checks can fail

`tests/mutation/run_gen_dts.py` makes one break per decision of `gen_dts.cho` (the zero-register refusal, the 32-bit
limit, the size formula, hex case and prefix, both passes of the snake rule, the dashed form, the major of the
version, the interrupt layout, the name and comment guards, the internal checks). **31 of 31 are killed.** A first run
killed 28 of 32; the four survivors were each a finding:

* `base-big` was an equivalent break: `base.big || base.v > 2^32-1` and `base.v > 2^32-1` are the same because the
  value saturates at 2^60. The redundant test was removed rather than excused.
* `label` and `interrupt-name`: nothing could fail them. The only unit test for a name that is not a label used the
  text form, whose lexer rejects `A-B`, so the generator saw an empty IR and refused it for having no register: the
  right answer for the wrong reason. And the harness accepted any input on which both tools wrote the same broken
  fragment. The unit tests now build the name as spans, and the harness fails on that case (21.3, 4).
* `base-internal` had no test: the checker never lets an unreadable base through. A unit test builds one.

### 21.5 What was easy, and what was not

* **Easy:** the shape. `(text, status)`, the three statuses, the helpers of §18 and the dispatcher carried over;
  the generator was written in one sitting once the Python was read, and `dtc` as an oracle needed one small tree.
* **Not easy:** two guesses were wrong in ways the byte comparison found in the first run (21.3, 1 and 2), and the
  hand-made inputs were not enough to find the third and fourth survivors (21.4). The mutation tier found what the
  differential could not, as in §18.4.
* **Cost:** the differential over 55k mutants takes about 35 minutes on 4 cores, most of it the Python side.

### 21.6 What stage 4 does not show

* SystemVerilog, cancho-binding and SVD are not ported *(corrected: SVD is, §23 to §25)*. `chw generate` answers `generator-unimplemented` for them.
* `dtc` checks syntax, labels and references in a tree that has `soc` and `intc`; it does not check the fragment
  against a board's bindings (the fragment is block-level by the spec, §4.3), and no kernel or Zephyr build was run.
* The compatible string and the interrupt flag cell are the Python tool's placeholders (the spec's sketch); this
  port reproduces them and does not improve them.
* Only Linux x86-64.

---

## 22. Corrections (stage 4)

* 20.4 estimated about 250 lines for the generator; it is 343 (21.1).
* 20.3 predicted that names would be refused only where `dtc` rejects Python's fragment, or where they are non-ASCII.
  The first version also refused `/*`, which `dtc` accepts; corrected (21.3, 3).
* 20.2 listed no refusal for an interrupt without a number; there is one, `internal`, after Python's two refusals
  (21.3, 2).
* §18.6 said four generators were not ported; three are not (§21.6).
* The Python reference gate's `devicetree roundtrip` has a `dtc` lane (`tests/roundtrip/devicetree_generates.py`) that
  parsed the bare fragment, which `dtc` rejects (`&soc {` is not a tree). It had never run: no image the project ran on had
  `dtc`, so it printed "NOTE dtc not on $PATH". Installing `dtc` for gate step 8d turned it on and CI failed at once
  (found by CI, not locally: the local gate does not run the Python reference). The lane now appends the fragment to the
  same small tree as step 8d, and the test says so.

---

## 23. Stage 5 design: the CMSIS-SVD generator

> **Status: design, now built; measured in §24.** Written from reading `gen/svd/svd.py` (254 lines) and `spec/generators/README.md` §6, with
> the two earlier generators (§17 to §22) as the pattern. The code follows; what it measures is §24, and a claim
> found false is corrected in §25.

### 23.1 What this slice decides

1. **Whether the shape carries a third generator at a smaller marginal cost.** `(text, status)`, the three
   statuses, the helpers in `gen_c.cho`. The test is whether the generator costs a fraction of the device tree's.
2. **What an XML document's oracle is.** The Python tool's bytes remain the oracle; `xmllint --noout` stands in for
   `dtc`/`cc`: a known-difference class is admitted only where the Python document is not well-formed. The
   vendored `CMSIS-SVD.xsd` is also available (`xmllint --schema`), and the differential checks both tools'
   documents against it as well, because well-formed is a weaker claim than valid.

It does **not** decide SystemVerilog or cancho-binding, which stay Python.

### 23.2 What the document is

One `<device>` with one `<peripheral>` for the block; registers in offset order (Python's stable sort), each with
its access mapping, a reset value (`0x0` and a comment when the contract has none), `modifiedWriteValues` or
`readAction` for the write-one/zero and read-clear kinds, fields with `lsb`/`msb`, and `<enumeratedValues>`.
Interrupts and DMA buffers are comments naming their stable IDs. Refusals are the Python tool's: **no register**
and **a name that cannot sit in an XML comment** (`--`), checked in the order the Python tool meets them while
writing.

### 23.3 Where the port must be careful

* **The refusal message quotes the joined stable ID** for an interrupt, a DMA buffer, a register and a field
  (`'chw:Blk.register.R'`), the bare text for the block name and the source path. The order is the order of writing.
* **Upper-case hex**, unpadded for the base and the offsets, padded to `bus_width / 4` digits for a reset value
  (and exact past 2^60 for the digits the checker lets through).
* **`<description>` carries the source path unescaped**, so a path with `&` or `<` makes the Python document not
  well-formed. This port refuses it (a narrowing, admitted by the oracle only where `xmllint` rejects Python's).
* **Names**: `&`, `<`, `>` are escaped in text; a name with a JSON escape or a non-ASCII byte is refused, as for the
  device tree (the spans index the undecoded source).

### 23.4 Gate and size

Step 8e of `scripts/gate_cancho.sh` (and `libxml2-utils` in CI). Budget, written before counting: about 300 lines
for the generator against 254 of Python (the device tree was 2.5 times; the XML text is more regular but there are
more entities).

### 23.5 The oracle, and what would make this slice fail

The same six tiers as §20.5: the 50 fixtures, the `check_json.py` mutants, hand-made inputs only a generator can get
wrong, known classes each admitted for a stated reason, unit tests, and one deliberate break per decision. The slice
fails if any difference is unexplained, or a break survives without a stated reason.

---

## 24. Stage 5 measured

Compiler cancho `7e4088b`, Linux x86-64; `xmllint` (libxml2) as the XML oracle. Everything below is the output of
`tests/differential/generate_svd.py` (gate step 8e), `tests/mutation/run_gen_svd.py` and `cancho test`.

### 24.1 What was built

| file | lines | what |
|---|---:|---|
| `src/gen_svd.cho` | 611 | the generator |
| `src/gen_c.cho` | 1 word | `pub` on `order_by` (the stable offset sort the C header already used) |
| `src/main.cho` | 498 (+7) | the dispatcher answers `svd` as it does the other two |
| `tests/unit/test_gen_svd.cho` | 683 | 35 tests |
| `tests/differential/generate_svd.py` | 388 | the oracle driver |
| `tests/mutation/run_gen_svd.py` | 145 | 65 deliberate breaks |

The estimate of 23.4 (about 300 lines) was missed by a factor of two: **611 lines against 254 of Python, 2.4 times**
(the device tree was 2.5). The cost is the same kind as before, plus one that is new here: the Python tool refuses in
the order it meets a problem while writing, so the port needs a pass that finds those problems in that order before
it writes anything (`found_while_writing`), and a second pass for what this port narrows (`unspellable`).

### 24.2 Against `generate.py`, byte for byte

Fixtures (50 files): stdout, stderr and exit status identical on **43**, 7 known differences; the 5 documents the
tools write are the same bytes, well-formed for `xmllint`, and valid against the vendored `CMSIS-SVD.xsd`.

Inputs (55,262 distinct: the mutants of `check_json.py`, 74 hand-made inputs and 6 source paths; 11,439 repeats skipped):

| | count |
|---|---:|
| identical to `generate.py` (a document on 3,110, a refusal on 43,860) | 46,970 |
| the checker's known differences (§13.5) | 1,192 |
| both answer `internal` | 1,202 |
| `generate.py` raised (`AttributeError` 4,042, `TypeError` 1,772), cancho answered with exit 0 or 1 and no trap | 5,814 |
| a name or path with an escape, a non-ASCII byte or markup that cancho refuses (`non-ascii-name` 79, `unspellable` 2) | 81 |
| `"number": 4.0` (`float-irq-number`) | 3 |
| **unexplained** | **0** |

### 24.3 What the oracle found, and what was decided

1. **An interrupt number written as `4.0`.** The schema calls it an integer, so the checker accepts it; Python
   prints the float it read (`IRQ 4.0`) in a comment, cancho the integer (`IRQ 4`). Found by 2 of the 55k mutants and
   nothing else (the first full run reported exactly those two as unexplained). Not a defect of the port: the class
   `float-irq-number` is admitted only if substituting `N.0` by `N` in Python's document gives cancho's, byte for
   byte; a hand-made input now reaches it in the quick tier.
2. **The document is valid, not only well-formed.** The 5 fixture documents and the 37 of 47 hand-made documents that
   validate against the vendored XSD are the same bytes from both tools; the 10 that do not are shared (empty enum,
   names the XSD's patterns exclude); they are listed as `schema-invalid` and not hidden behind "well-formed".
3. **Python's `<description>` carries the source path unescaped.** A path with `&` or `<` gives a document that is not
   well-formed. This port refuses it (`unspellable`, 2 cases) and the harness admits the refusal only where `xmllint`
   rejects Python's document.
4. **Everything else was identical on the first run**, including the order of refusals (a `--` in a block name, then
   the zero-register refusal, then the path, then interrupts, DMA buffers, and each register's name, kind, fields and
   enum labels), which 23.3 had spelled out in advance from reading the Python tool.

### 24.4 The checks can fail

`tests/mutation/run_gen_svd.py` makes one break per decision of `gen_svd.cho` (the escapes, the hex case and padding,
each of the eight access mappings, the unknown kind, the reset comment, `modifiedWriteValues` and `readAction`, the
field and enum lines, every double-dash check in the order the tool makes it, every narrowing, every internal check,
the span check). **65 of 65 are killed.** A first run killed 51; the 14 survivors were each a finding, as in §21.4:

* The seven **`plain-*`** narrowings (a name or version with a JSON escape or a non-ASCII byte, per entity) and
  **`plain-path`**: the differential cannot see them. When cancho writes the name it writes the same bytes Python does,
  so the break makes cancho *agree* with Python. Only a unit test that builds the IR by hand can fail it; there are now
  eight, one per entity.
* **`kind-message`, `base-internal`, `reset-internal`, `fields-internal`, `enums-internal`, `spans-block`**: a checked
  contract never reaches them. `base-internal` had a test that passed for the wrong reason: its source text put a
  letter where a register offset belongs, so the offset check answered `internal` first (§21.4 had the same kind of
  false pass). All have a unit test that builds the IR by hand.

### 24.5 What was easy, and what was not

* **Easy:** the shape and the helpers carried over (`gen_c.put`, `put_span`, `put_int`, `refusal`, `order_by`); the
  document needed no new abstraction.
* **Not easy:** matching an order of refusals the Python tool never states, and the linear-ownership rule (a buffer
  assigned over must be dropped first) in three places where a tuple or a result is built across branches.
* **Cost:** the differential takes about 35 minutes on 4 cores, as the device tree did.

### 24.6 What stage 5 does not show

* SystemVerilog and cancho-binding are not ported. `chw generate` answers `generator-unimplemented` for them.
* No CMSIS tool (svd2rust, cortex-debug) read the document; the XSD and `xmllint` are the oracle. The spec's non-guarantee
  (§6.3) stands: CMSIS tools interpret the elements, the generator does not verify them.
* Names are ASCII only; a name with an escape or a non-ASCII byte is refused where Python writes it.
* Only Linux x86-64.

---

## 25. Corrections (stage 5)

* 23.4 estimated about 300 lines for the generator; it is 611 (24.1).
* 23.1 said the differential would also check the vendored XSD "as well"; it does, for the 5 fixture documents and
  the hand-made inputs, and reports `schema-invalid` (10) as a shared fact rather than a failure (24.3, 2).
* §21.6 and §18.6 said SVD was not ported; it is (SystemVerilog and cancho-binding are not).

---

## 26. Stage 6 design: the cancho-binding generator

> **Status: design, now built; measured in §27.** Written from reading `gen/cancho-binding/cancho_binding.py` (211 lines) and
> `spec/generators/README.md` §3, with the three earlier generators (§17 to §25) as the pattern. What it measures is
> §27, and a claim found false is corrected in §28.

### 26.1 What this slice decides

1. **Whether the shape carries a fourth generator** at the cost the third showed (2.4 times the Python).
2. **What the oracle is when there is no compiler for the output.** The output is accessor declarations in a sketch
   syntax (`module`, `foreign block`, `capability`, `buffer`) that no cancho tool parses; the Python
   `cancho_binding_validates` roundtrip is a structural check. So the oracle is the Python tool's bytes and nothing else, and
   this slice says so: a known-difference class can be admitted only for a stated structural reason (an escape or a
   non-ASCII byte in a name, which the spans cannot decode), never by "it compiles".

It does **not** decide SystemVerilog, which stays Python, and it does not change what the generator emits.

### 26.2 What the declarations are

`module <snake block> { foreign block <Block> @ <upper hex> : u<width>; ... }`; per register, in **declaration order**
(not offset order, unlike the C header and SVD), per field: a stable-ID comment and the accessors its register kind
allows (`RO`/`RC` get; `WO`/`W1S`/`W0S` set; `RW` both; `W1C`/`W0C` clear), typed `bool` for width 1, an `enum` for a field
that has one, else `u32`; per interrupt a `capability` with `arm`/`status`/`clear` for the linkages it declares; per DMA
buffer a `buffer` with a getter per field and a setter unless it is device-owned; then one `enum` declaration per distinct
enum field name. Refusals are the Python tool's: an access kind with no mapping, and two enum fields whose names
collide as types but carry different label lists.

### 26.3 Where the port must be careful

* **`_pascal` of the snake form**, which is the device tree's two-regex `_snake` then a split on `_`: `a__b` is `AB`.
* **An empty `enum {}` is falsy in Python**: the field is typed `bool`/`u32` and declares no enum. Duplicate labels
  collapse to their first occurrence (a dict), and the collision test compares the label *lists*.
* **The DMA field size is not in the IR** (the schema has none), so it is always 4 and `u32`; the Python refusal for
  another size is unreachable from a checked contract, and the port has no code for it.
* **Names are verbatim** in the `foreign block` line, the capability and the buffer; an escape or a non-ASCII byte is
  refused (spans index undecoded text), as before.

### 26.4 Gate and size

Step 8f of `scripts/gate_cancho.sh`. Budget, written before counting: about 450 lines for the generator against
211 of Python (2 to 2.5 times).

### 26.5 The oracle, and what would make this slice fail

The six tiers of §20.5, with `xmllint`/`dtc`/`cc` replaced by nothing: bytes against the Python tool on the 50
fixtures, the `check_json.py` mutants, hand-made inputs (every kind, enums with equal and different label lists,
`a__b` names, empty enums, linkages of every shape, DMA owners), known classes each with a stated reason, unit tests,
and one deliberate break per decision. It fails if any difference is unexplained or a break survives without a stated
reason.

---

## 27. Stage 6 measured

Compiler cancho `7e4088b`, Linux x86-64. There is no compiler or parser for the output (26.1), so everything below
is bytes against `tools/generate/generate.py`: `tests/differential/generate_binding.py` (gate step 8f),
`tests/mutation/run_gen_binding.py` and `cancho test`.

### 27.1 What was built

| file | lines | what |
|---|---:|---|
| `src/gen_binding.cho` | 483 | the generator |
| `src/gen_dts.cho`, `src/gen_svd.cho` | 3 words | `pub` on `put_snake`, `is_plain` and `put_hex`, which this generator reuses |
| `src/main.cho` | 505 (+7) | the dispatcher answers `cancho-binding` |
| `tests/unit/test_gen_binding.cho` | 544 | 31 tests |
| `tests/differential/generate_binding.py` | 349 | the oracle driver | |
| `tests/mutation/run_gen_binding.py` | 139 | 59 deliberate breaks |

The estimate of 26.4 (about 450 lines) was close: **483 lines against 211 of Python, 2.3 times**. The generator needs
no ordering pass (declaration order) and no numeric formatting beyond the base, which is what kept it near the
estimate; the Python tool's one piece of state, the dict of declared enums, is a `std.map` here.

### 27.2 Against `generate.py`, byte for byte

Fixtures (50 files): stdout, stderr and exit status identical on **46**, 4 known differences; the 8 outputs the tools
write are the same bytes.

Inputs (55,269 distinct: the mutants of `check_json.py`, 82 hand-made inputs and 5 source paths; 11,439 repeats skipped):

| | count |
|---|---:|
| identical to `generate.py` (declarations on 4,250, a refusal on 43,846) | 48,096 |
| the checker's known differences (§13.5) | 1,192 |
| `generate.py` raised (`AttributeError` 4,042, `TypeError` 1,772), cancho answered with exit 0 or 1 and no trap | 5,814 |
| a name or path with an escape or a non-ASCII byte that cancho refuses (`non-ascii-name`) | 167 |
| **unexplained** | **0** |

### 27.3 What the oracle found, and what was decided

1. **Nothing in the bytes.** Every hand-made input and every mutant that both tools answer, they answer identically,
   including the order of a refusal against another, the empty `enum {}` that Python treats as no enum, two names that
   are one type once cased, and a register kind that has no mapping. That is the finding: a generator that is a
   string of decisions about names and kinds ported without a single byte of disagreement on the first full run.
2. **The only class admitted is a narrowing**, and it is admitted only where the input holds a non-ASCII byte or a JSON
   escape (checked on the input text, not assumed), since there is nothing to compile.
3. **A duplicate enum label cannot reach the generator.** Python's dict would collapse it; the loader refuses a
   repeated key (`duplicate-key`), so the port does not collapse and no input in the 55k exercises the difference.
4. **The DMA field size is not in the IR**, so the Python refusal for a size outside 1, 2, 4, 8 is unreachable from
   a checked contract; the port has no code for it, and 26.3 said so before it was written.

### 27.4 The checks can fail

`tests/mutation/run_gen_binding.py` makes one break per decision of `gen_binding.cho` (each of the eight kind
mappings, the unknown kind and its message, the empty enum, both halves of the label-list comparison and the collision
message, the bool/`u32` split and the `_get` suffix, each interrupt linkage, the DMA owner test and its comment, the base
and the width, the enum layout, every internal check, every span check, and one narrowing per entity). **59 of 59 are
killed.** A first run killed 46; of the 13 that did not:

* **10 were the harness's own mistake** (a `\n` written where the source holds a backslash and an `n`), reported as
  `BAD BREAK: the old text occurs 0 times` and corrected, not counted as kills.
* **`labels-count`**: the length test of the label comparison had no test. Without it, `Mode{X,Y}` against `Mode{X}`
  reads the next entry in the table, which is another field's. A unit test now puts a `Y` there.
* **`dma-fields-internal`** and **`spans-register`**: a checked contract never reaches them; each has a unit test
  that builds the IR by hand.

As for the narrowings, the differential cannot see them (when cancho writes the name it writes the bytes Python
does); the seven `plain-*` breaks and `plain-path` are killed by unit tests that build the IR by hand, as in §24.4.

### 27.5 What was easy, and what was not

* **Easy:** nearly everything. The shape, the helpers and the gate step carried over; the decisions are in the
  Python tool's tables, which were ported as tables.
* **Not easy:** only the shape of the unit tests (an IR with one of everything and one piece of text swapped), which
  took the same effort as for SVD and is now a pattern for the next generator.
* **Cost:** the differential takes about 35 minutes on 4 cores.

### 27.6 What stage 6 does not show

* SystemVerilog is not ported. `chw generate` answers `generator-unimplemented` for it.
* **The output is a sketch syntax no tool reads.** Byte equality with the Python tool shows the port is faithful; it
  shows nothing about whether `module`, `foreign block` and `capability` are what the language will take. That is the
  open question of the spec (§3), not of the port.
* Names are ASCII only; a name with an escape or a non-ASCII byte is refused where Python writes it.
* Only Linux x86-64.

---

## 28. Corrections (stage 6)

* 26.4 estimated about 450 lines; it is 483 (27.1), the first estimate of the four that came close.
* §23.6 and §24.6 said SystemVerilog and cancho-binding were not ported; cancho-binding is (SystemVerilog is not).
