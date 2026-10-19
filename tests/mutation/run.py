"""Test-only harness for the mutation checks of docs/cancho-port.md, 14.3.

A test that cannot fail proves nothing. For each mutation below this copies
src/ to a temporary directory, changes ONE expression in the copy (the old text
must occur exactly once), builds `chw` from the copy, and runs the three things
that are meant to notice:

  unit    `cancho test` of tests/unit/test_check.cho (and test_hexval.cho,
          test_diagnostic.cho) against the copy: how many tests fail
  conform `chw conform . --fixtures tests/stage1,tests/stage2` with the mutated
          binary: its exit status and the fixtures that failed
  fixdiff `tests/differential/check_json.py --fixtures-only`: files that no
          longer match checker.py byte for byte (run only for a mutant that the
          three above did not notice, or with --fixdiff)
  trees   the seven "the runner can fail" trees of gate step 8, each changed in one
          place, which a sound runner refuses; how many the mutant accepted
  full    (only with --full, or for a mutation that survived the other three)
          `tests/differential/check_json.py`: unexplained differences over the
          mutants

A mutation is KILLED when any of them fails. The table printed at the end is the
evidence: each rule has a mutation, and the tier that caught it.

Usage: python3 tests/mutation/run.py [--only NAME,NAME] [--full] [--jobs N]
       (needs the compiler: $CANCHO, default ../cancho/target/release/cancho)
"""
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import concurrent.futures

ROOT = pathlib.Path(__file__).resolve().parents[2]
CANCHO = os.environ.get("CANCHO", str(ROOT.parent / "cancho/target/release/cancho"))

MODULES = """lex ir parse json_out json_in diag pyrepr pattern schema front load diagnostic hexval check_util
check_block check_regs check_intr check_dma check dg_json dg_text dg_report""".split()
PROGRAM = ["main"] + MODULES + ["io", "conform"]
CHECK = "ir json_out pyrepr diagnostic hexval check_util check_block check_regs check_intr check_dma check dg_json".split()
SUITES = [
    ("test_check", CHECK),
    ("test_hexval", ["hexval"]),
    ("test_diagnostic", ["diagnostic"]),
    ("test_dg_output", "ir json_out pyrepr diagnostic hexval check_util dg_json dg_text dg_report diag".split()),
]

# (name, file, old, new, what the rule is)
M = [
    ("field-overlap", "check_regs.cho", "if !(msb < o.lsb || lsb > o.msb) {", "if !(msb <= o.lsb || lsb >= o.msb) {", "overlap tests touching fields as overlapping"),
    ("field-bounds-overflow", "check_regs.cho", "    if msb >= bw {", "    if msb > bw {", "msb == bus_width allowed"),
    ("field-bounds-inverted", "check_regs.cho", "    if msb < lsb {", "    if msb <= lsb {", "one-bit fields refused"),
    ("field-enum-overflow", "check_regs.cho", "cu.int_val(src, tape, ev) <= mask;", "cu.int_val(src, tape, ev) < mask;", "the largest value refused"),
    ("field-enum-negative", "check_regs.cho", "cu.int_val(src, tape, ev) >= 0 &&", "cu.int_val(src, tape, ev) >= 0 - 1 &&", "-1 allowed"),
    ("field-name-missing", "check_regs.cho", "    if !cu.is_name(src, tape, name) {\n        let (d1, missing) = dg.word(heap, ds, \"<missing>\");\n        let (d2, m) = dg.mark(d1);\n        var d = dg.lit(heap, d2, \"field in register \");", "    if !json.is_string(tape, name) {\n        let (d1, missing) = dg.word(heap, ds, \"<missing>\");\n        let (d2, m) = dg.mark(d1);\n        var d = dg.lit(heap, d2, \"field in register \");", "an empty name accepted"),
    ("field-bounds-missing", "check_regs.cho", "if !cu.int_like(tape, lsb_node) || !cu.int_like(tape, msb_node) {", "if !cu.int_like(tape, lsb_node) && !cu.int_like(tape, msb_node) {", "one missing bound accepted"),
    ("register-offset-duplicate", "hexval.cho", "            if started || d > 0 {", "            if true {", "0x08 and 0x8 are different offsets"),
    ("register-offset-non-aligned", "check_regs.cho", "    if off.low % size != 0 {", "    if off.low % size > 1 {", "an offset off by one byte accepted"),
    ("register-offset-overflow", "check_regs.cho", "    if off.v + size > 1 << bw {", "    if off.v + size >= 1 << bw {", "the last register of the space refused"),
    ("register-offset-missing", "check_regs.cho", "    if !off.ok {", "    if !off.ok && off.v == 0 - 1 {", "an unreadable offset accepted"),
    ("register-kind-unknown", "check_regs.cho", " || cu.str_is(src, tape, k, \"W0S\");", ";", "W0S not a kind"),
    ("reset-overflow", "check_regs.cho", "if !rv.ok || rv.v > mask_of(bw) {", "if !rv.ok || rv.v >= mask_of(bw) {", "the largest reset refused"),
    ("reset-wo-nonzero", "check_regs.cho", "} else if cu.str_is(src, tape, kind, \"WO\") && !rv.zero {", "} else if cu.str_is(src, tape, kind, \"WO\") && rv.zero {", "warns on a zero reset"),
    ("dma-overlap", "check_dma.cho", "if !(end <= o.start || start >= o.end) {", "if !(end < o.start || start > o.end) {", "adjacent fields overlap"),
    ("dma-align-unsatisfied", "check_dma.cho", "    if hv.low % a == 0 {", "    if hv.low % a <= 1 {", "an offset one past the alignment accepted"),
    ("dma-align-illegal", "check_dma.cho", "    return k == n;", "    return k >= n;", "any alignment up to a power of two is legal"),
    ("dma-owner-unknown", "check_dma.cho", "cu.str_is(src, tape, owner, \"DEVICE\")", "cu.str_is(src, tape, owner, \"DEVICES\")", "DEVICE refused"),
    ("dma-field-size", "check_dma.cho", "    var size = 4;", "    var size = 3;", "a DMA field is three bytes"),
    ("dma-field-name-missing", "check_dma.cho", "    if !cu.is_name(src, tape, name) {\n        let (d1, missing) = dg.word(heap, ds, \"<missing>\");\n        let (d2, m) = dg.mark(d1);", "    if !json.is_string(tape, name) {\n        let (d1, missing) = dg.word(heap, ds, \"<missing>\");\n        let (d2, m) = dg.mark(d1);", "an empty field name accepted"),
    ("dma-name-missing", "check_dma.cho", "    if !cu.is_name(src, tape, name) {\n        let (d1, missing) = dg.word(heap, ds, \"<missing>\");\n        let (d2, msg) = dg.word(heap, d1, \"DMA buffer is missing", "    if !json.is_string(tape, name) {\n        let (d1, missing) = dg.word(heap, ds, \"<missing>\");\n        let (d2, msg) = dg.word(heap, d1, \"DMA buffer is missing", "an empty buffer name accepted"),
    ("block-bus-width-invalid", "check_block.cho", "cu.num_is(src, tape, width, 16) ||", "cu.num_is(src, tape, width, 17) ||", "16 refused"),
    ("block-endianness-unknown", "check_block.cho", "cu.str_is(src, tape, endian, \"big\")", "cu.str_is(src, tape, endian, \"bigg\")", "big refused"),
    ("block-base-address-missing", "check_block.cho", "if !base.ok || base.zero {", "if !base.ok {", "a zero base address accepted"),
    ("block-name-missing", "check_block.cho", "    if !cu.is_name(src, tape, name) {\n        let (d1, missing) = dg.word(heap, ds, \"<missing>\");\n        let (d2, msg) = say(heap, d1, \"block is missing", "    if !json.is_string(tape, name) {\n        let (d1, missing) = dg.word(heap, ds, \"<missing>\");\n        let (d2, msg) = say(heap, d1, \"block is missing", "an empty block name accepted"),
    ("schema-version-unsupported", "check_block.cho", "if major != 0 || minor != 1 {", "if major != 0 || minor != 2 {", "0.2 supported, 0.1 not"),
    ("version-shape", "check_block.cho", "    return ok && dots == 2;", "    return ok && dots >= 2;", "four-part versions accepted"),
    ("interrupt-unresolved-field", "check_intr.cho", "&& cu.same_str(heap, src, tape, fname, name) {", "&& !cu.same_str(heap, src, tape, fname, name) {", "a field resolves to any other field"),
    ("interrupt-unresolved-register", "check_intr.cho", "        reg = find_register(heap, src, tape, by_name, reg_name);", "        reg = 0 - 1;", "no register ever resolves"),
    ("interrupt-clear-kind", "check_intr.cho", "cu.str_is(src, tape, kind, \"RC\")", "cu.str_is(src, tape, kind, \"RX\")", "RC refused"),
    ("interrupt-duplicate-name", "check_intr.cho", "            dup = map.has(sm, contents(kr));", "            dup = false;", "duplicates not noticed"),
    ("interrupt-role-order", "check_intr.cho", "dg.Rule::InterruptEnableUnresolved, \"enable\"", "dg.Rule::InterruptStatusUnresolved, \"enable\"", "enable reported as status"),
    ("interrupt-name-missing", "check_intr.cho", "    if !cu.is_name(src, tape, name) {\n        let (d1, missing) = dg.word(heap, ds, \"<missing>\");\n        let (d2, msg) = dg.word(heap, d1, \"interrupt is missing", "    if !json.is_string(tape, name) {\n        let (d1, missing) = dg.word(heap, ds, \"<missing>\");\n        let (d2, msg) = dg.word(heap, d1, \"interrupt is missing", "an empty interrupt name accepted"),
    ("register-name-missing", "check_regs.cho", "    if !cu.is_name(src, tape, name) {\n        let (d1, missing) = dg.word(heap, ds, \"<missing>\");\n        let (d2, msg) = dg.word(heap, d1, \"register is missing", "    if !json.is_string(tape, name) {\n        let (d1, missing) = dg.word(heap, ds, \"<missing>\");\n        let (d2, msg) = dg.word(heap, d1, \"register is missing", "an empty register name accepted"),
    ("hex-underscore", "hexval.cho", "            if prev_us || nd == 0 {", "            if true {", "int(s, 16) underscore rule dropped"),
    ("hex-trailing-space", "hexval.cho", "        } else if is_space(c) {\n            tail = true;", "        } else if false {\n            tail = true;", "trailing whitespace refused"),
    ("remedy-confidence", "dg_json.cho", "dg.confidence_name(d.rem.conf)", "dg.confidence_name(dg.Confidence::High)", "the remediation says High"),
    ("json-key-order", "dg_json.cho", "    o = pair(heap, o, k, \"severity\", dg.severity_name(dg.rule_severity(d.rule)));\n    o = buffer.append(heap, o, \",\\n\");\n    o = pair(heap, o, k, \"tier\", dg.tier_name(dg.rule_tier(d.rule)));", "    o = pair(heap, o, k, \"tier\", dg.tier_name(dg.rule_tier(d.rule)));\n    o = buffer.append(heap, o, \",\\n\");\n    o = pair(heap, o, k, \"severity\", dg.severity_name(dg.rule_severity(d.rule)));", "severity and tier swapped"),
    ("json-related-dropped", "dg_json.cho", "    if d.kids.rel_n == 0 {\n        o = buffer.append(heap, o, \"[]\");", "    if d.kids.rel_n >= 0 {\n        o = buffer.append(heap, o, \"[]\");", "related never printed"),
    ("tier-runtime", "diagnostic.cho", "        Rule::SchemaVersionUnsupported => {\n            return Tier::Runtime;", "        Rule::SchemaVersionUnsupported => {\n            return Tier::Static;", "the version rule is Static"),
    ("severity-warning", "diagnostic.cho", "        Rule::ResetWoNonzero => {\n            return Severity::Warning;", "        Rule::ResetWoNonzero => {\n            return Severity::Error;", "a warning is an error"),
    ("subject-kind", "diagnostic.cho", "        Rule::FieldOverlap => {\n            return Kind::Field;", "        Rule::FieldOverlap => {\n            return Kind::Register;", "field-overlap has a Register subject"),
    ("json-pointer-index", "dg_json.cho", "    if is_digits(t) && len(t) < 16 {", "    if false {", "an array index printed as a string"),
    ("json-escape-undone", "dg_json.cho", "int_of(t[i + 1]) == '1' {", "int_of(t[i + 1]) == '2' {", "~1 not undone in a pointer"),
    ("report-prefix", "dg_report.cho", "        d = dg.lit(heap, d, \"schema validation failed: \");", "", "the schema message loses Python's prefix"),
    ("report-parse-span", "dg_report.cho", "ec: diag.end_column(rec) };", "ec: col };", "a parse error ends where it starts"),
    ("text-snippet", "dg_text.cho", "    o = spaces(heap, o, loc.sc - 1);", "    o = spaces(heap, o, loc.sc);", "the caret is one column off"),
    ("conform-ignores-code", "conform.cho", "    if !bytes.equal(dg.rule_name(d.rule), code) {\n        return false;\n    }", "", "the runner does not compare the code"),
    ("conform-ignores-subject", "conform.cho", "    var ok = subject_fits(ds, d, src, tape, entry);", "    var ok = true;", "the runner does not compare the subject"),
    ("conform-ignores-unexpected", "conform.cho", "    return (out, hit == total && extra == 0);", "    return (out, hit == total);", "the runner ignores a diagnostic nothing expects"),
]


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, **kw)


def build(srcdir, out):
    files = [str(srcdir / f"{m}.cho") for m in PROGRAM]
    r = sh([CANCHO, "build", *files, "--std", "-o", str(out)])
    return r.returncode == 0, r.stdout + r.stderr


def cant_fail(exe, tmp):
    """The trees of gate step 8: each is the contract-facing tree with one thing
    changed, and a sound runner refuses all seven. Returns how many it accepted."""
    edits = [
        ("examples/refusal/kind-unknown.expect.json", lambda t: t.replace('"schema-invalid"', '"parse-error"')),
        ("examples/refusal/field-overlap.expect.json", lambda t: t.replace('"code": "field-overlap"', '"code": "dma-overlap"')),
        ("examples/refusal/field-overlap.expect.json", lambda t: t.replace('"name": "PARITY"', '"name": "NOT_PARITY"')),
        ("examples/refusal/field-overlap.chw", lambda t: t.replace('"name": "ENABLE",  "lsb": 0, "msb": 3', '"name": "ENABLE",  "lsb": 0, "msb": 1')),
        ("examples/refusal/field-overlap.expect.json", lambda t: t.replace("overlap with ENABLE", "overlap with SOMETHING_ELSE")),
        ("examples/uart-contract/uart.chw", lambda t: t.replace('"offset": "0x04"', '"offset": "0x00"')),
        ("examples/refusal/field-overlap.expect.json", lambda t: '{"file": "x", "expect": []}\n'),
    ]
    accepted = 0
    for i, (rel, edit) in enumerate(edits):
        tree = pathlib.Path(tmp) / f"tree{i}-{exe.parent.name}"
        shutil.copytree(ROOT / "spec/contract-schema", tree / "spec/contract-schema")
        shutil.copytree(ROOT / "examples", tree / "examples")
        text = (tree / rel).read_text()
        (tree / rel).write_text(edit(text))
        assert (tree / rel).read_text() != text, f"edit {i} changed nothing"
        if sh([str(exe), "conform", str(tree)]).returncode == 0:
            accepted += 1
        shutil.rmtree(tree)
    return accepted


def run_one(name, fname, old, new, why, full, tmp):
    srcdir = pathlib.Path(tmp) / name / "src"
    shutil.copytree(ROOT / "src", srcdir)
    text = (srcdir / fname).read_text()
    if text.count(old) != 1:
        return {"name": name, "error": f"old text occurs {text.count(old)} times in {fname}"}
    (srcdir / fname).write_text(text.replace(old, new))
    exe = pathlib.Path(tmp) / name / "chw"
    ok, log = build(srcdir, exe)
    if not ok:
        return {"name": name, "error": "mutant does not compile: " + log.strip()[:200]}
    res = {"name": name, "why": why}
    # unit tests, against the mutated copy (each suite with only the modules it needs)
    failed = 0
    ran = 0
    for t, mods in SUITES:
        lib = [str(srcdir / f"{m}.cho") for m in mods]
        r = sh([CANCHO, "test", f"tests/unit/{t}.cho", *lib, "--std"])
        m = re.search(r"(\d+) passed; (\d+) failed", r.stdout)
        if m:
            ran += int(m.group(1)) + int(m.group(2))
            failed += int(m.group(2))
        else:
            failed += 1
    res["unit"] = f"{failed} of {ran} failed"
    # the conformance runner, on the repository
    r = sh([str(exe), "conform", ".", "--fixtures", "tests/stage1,tests/stage2"])
    m = re.search(r"== (\d+) of (\d+) fixtures matched", r.stdout)
    res["conform"] = f"exit {r.returncode}" + (f" ({m.group(1)} of {m.group(2)} fixtures)" if m and r.returncode else "")
    accepted = cant_fail(exe, tmp)
    res["trees"] = f"{accepted} of 7 accepted"
    killed = failed > 0 or not res["conform"].startswith("exit 0") or accepted > 0
    # the fixtures against checker.py: only for a mutant nothing above noticed,
    # or when asked (--fixdiff), because it is the slowest of the cheap tiers
    res["fixdiff"] = "-"
    if not killed or "--fixdiff" in sys.argv:
        r = sh([sys.executable, "tests/differential/check_json.py", str(exe), "--fixtures-only"])
        m = re.search(r"--output json byte-identical to checker.py: (\d+) of (\d+)", r.stdout)
        res["fixdiff"] = f"{r.stdout.count('UNEXPLAINED')} unexplained" + (f" ({m.group(1)} of {m.group(2)} identical)" if m else "")
        killed = killed or r.returncode != 0
    res["killed_by_fast"] = killed
    if full or not killed:
        r = sh([sys.executable, "tests/differential/check_json.py", str(exe), "--jobs", "4"])
        m = re.search(r"(\d+) unexplained differences", r.stdout)
        res["full"] = f"{m.group(1)} unexplained" if m else "did not finish"
        if m and int(m.group(1)) > 0:
            res["killed_by_fast"] = True
    return res


def main():
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    full = "--full" in sys.argv
    jobs = 3
    if "--jobs" in sys.argv:
        jobs = int(sys.argv[sys.argv.index("--jobs") + 1])
    todo = [m for m in M if not only or m[0] in only]
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        def job(m):
            name, fname, old, new, why = m
            res = run_one(name, fname, old, new, why, full, tmp)
            shutil.rmtree(pathlib.Path(tmp) / name, ignore_errors=True)
            print(f"-- {name}: " + str({k: v for k, v in res.items() if k != "name"}), flush=True)
            return res
        with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
            rows = list(pool.map(job, todo))
    print()
    print(f"{'mutation':32} {'unit tests':16} {'conform':28} {'fixtures vs checker.py':32} {'can-fail trees':16} {'full differential'}")
    survived = []
    for r in rows:
        if "error" in r:
            print(f"{r['name']:32} ERROR {r['error']}")
            survived.append(r["name"])
            continue
        print(f"{r['name']:32} {r['unit']:16} {r['conform']:28} {r['fixdiff']:32} {r['trees']:16} {r.get('full', '-')}")
        if not r["killed_by_fast"]:
            survived.append(r["name"])
    print()
    print(f"{len(rows)} mutations, {len(rows) - len(survived)} killed, {len(survived)} survived: {', '.join(survived) or 'none'}")
    sys.exit(1 if survived else 0)


main()
