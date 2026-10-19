# Porting cancho-hdl to cancho

> **Status: design, a measured spike (§7), and a built and measured stage 1
> (design §9, measurements §10).** Decision (taken before this
> document): the product is rewritten from scratch as **pure cancho**. The
> Python under `tools/`, `gen/` and `scripts/` is the *legacy reference
> implementation*, kept until each part is replaced and then deleted. The
> `.chw` examples, the refusal fixtures (`examples/refusal/*.expect.json`)
> and `tests/behavioral/scenarios.json` are language-neutral specifications
> and do not move. Python may remain **only** as test-only oracle code (§5).
>
> What is measured here is two slices: the textual parser over the two textual
> examples (§7), and the JSON wire loader, the structural validator and the
> conformance runner (§10). Everything else in this document is a plan, and
> every number in it that is not from those is marked *estimate*.

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
* Messages follow `jsonschema` 4.26 word for word, with the instance quoted in
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
`python3 scripts/run_gate.py` is untouched and still run by CI.

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

Stage 2: `Diagnostic` and the checker. The IR is now loaded from both forms and the
structural half of every sidecar is decided, so the 14 deferred entries are the
exit criterion: `chw conform` should report 12 of 12 with none deferred, and
`--output json` identical to the Python checker's. Its first questions are the
ones stage 1 raised: whether the `Diagnostic` record can stay a line of text
(9.4) or becomes a typed value; whether the semantic rules (overlap, reset fit,
DMA alignment) are compact enough to fit the 800-line budget per file that
`schema.cho` has already passed; and whether `schema.cho` should be split into a
base, a lint and a check before more is added to it.
