"""Test-only harness for the mutation checks of `ran` (docs/cancho-port.md, 32).

A differential that cannot fail proves nothing. For each break below this copies src/ to a temporary directory,
changes ONE expression in the copy (the old text must occur exactly once in the named file), builds `chw` from the copy
and runs

  fixtures   tests/differential/check_ran.py --fixtures-only: the 50 fixtures, `chw check --ran` against checker.py
  unit       `cancho test` of tests/unit/test_check.cho

A break is KILLED when either fails. The table printed at the end is the evidence: each decision of `ran` has a break,
and the tier that caught it.

Usage: python3 tests/mutation/run_ran.py [--only NAME,NAME] [--jobs N]   (needs $CANCHO, default ../cancho/target/release/cancho)
"""
import concurrent.futures
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
CANCHO = os.environ.get("CANCHO", str(ROOT.parent / "cancho/target/release/cancho"))
MODULES = """lex ir parse json_out json_in diag pyrepr pattern schema front load diagnostic hexval check_util
check_block check_regs check_intr check_dma check dg_json dg_text dg_report gen_c gen_dts gen_svd gen_binding gen_sv""".split()
PROGRAM = ["main"] + MODULES + ["io", "conform"]

# (name, file, old, new, what it breaks)
M = [
    ("items-count", "check", "return json.is_array(tape, node) && json.count(tape, node) > 0;", "return json.is_array(tape, node);", "an empty list runs its group"),
    ("items-array", "check", "return json.is_array(tape, node) && json.count(tape, node) > 0;", "return json.count(tape, node) > 0;", "a value that is not a list runs its group"),
    ("no-block", "check", "    if !json.is_object(tape, block) {\n        return 1;\n    }\n    var mask = 3;", "    var mask = 3;", "a block that is not an object runs the block group"),
    ("no-block-mask", "check", "        return 1;\n    }\n    var mask = 3;", "        return 3;\n    }\n    var mask = 3;", "a block that is not an object reports the block group"),
    ("block-bit", "check", "    var mask = 3;", "    var mask = 1;", "an object block does not report the block group"),
    ("registers-bit", "check", "        mask = mask + 4;", "        mask = mask + 8;", "registers are reported as interrupts"),
    ("interrupts-bit", "check", "        mask = mask + 8;", "        mask = mask + 16;", "interrupts are reported as dma"),
    ("dma-bit", "check", "        mask = mask + 16;", "        mask = mask + 4;", "dma is reported as registers"),
    ("dma-in-block", "check", 'if has_items(tape, json.get(src, tape, root, "dma_buffers")) {', 'if has_items(tape, json.get(src, tape, block, "dma_buffers")) {', "dma buffers are looked up in the block"),
    ("registers-key", "check", 'json.get(src, tape, block, "registers")) {\n        mask', 'json.get(src, tape, block, "register")) {\n        mask', "the registers key is misspelled"),
    ("run-same-test", "check", "    if has_items(tape, regs_node) {\n        ds = regs.registers", "    if json.is_array(tape, regs_node) {\n        ds = regs.registers", "run and ran test registers differently"),
    ("doc-not-set", "load", "        ran = check.ran(bytes, tape);", "        ran = 0;", "a JSON document reports no group"),
    ("text-not-set", "load", "            ran = check.ran(rendered, contents(r));", "            ran = 0;", "a text document reports no group"),
    ("text-not-passed", "load", "            ran = groups;", "            ran = 0;", "the text form's groups are dropped"),
    ("show-order", "main", '    if mask / 2 % 2 == 1 {\n        out = buffer.append(heap, out, "block\\n");\n    }\n    if mask / 16 % 2 == 1 {\n        out = buffer.append(heap, out, "dma\\n");\n    }', '    if mask / 16 % 2 == 1 {\n        out = buffer.append(heap, out, "dma\\n");\n    }\n    if mask / 2 % 2 == 1 {\n        out = buffer.append(heap, out, "block\\n");\n    }', "the groups are not in sorted order"),
    ("show-dma-bit", "main", "if mask / 16 % 2 == 1 {", "if mask / 8 % 2 == 1 {", "dma is printed for interrupts"),
    ("show-intr-bit", "main", "if mask / 8 % 2 == 1 {", "if mask / 4 % 2 == 1 {", "interrupts are printed for registers"),
    ("show-regs-bit", "main", "if mask / 4 % 2 == 1 {", "if mask / 2 % 2 == 1 {", "registers are printed for the block"),
    ("show-version", "main", "    if mask % 2 == 1 {\n        out = buffer.append(heap, out, \"schema-version\\n\");", "    if mask % 2 == 5 {\n        out = buffer.append(heap, out, \"schema-version\\n\");", "the schema version is not printed"),
    ("show-name", "main", '"schema-version\\n"', '"schema_version\\n"', "a group name is misspelled"),
    ("status-ran", "main", "                            status = diag_status(load.diags(dr));", "                            status = 0;", "--ran hides the exit status"),
    ("flag-ignored", "main", 'if flag_at(g, "--ran") > 0 {', "if false {", "--ran is ignored"),
]


# Breaks that change no output, each with the reason. They are reported, not counted as survivors.
EQUIVALENT = {
    "run-same-test": "an empty list of registers given to the registers rules produces no diagnostic, so `run` is the same with or without the count test; the shared `has_items` is what keeps `run` and `ran` together, and the break that changes `has_items` (items-count) is killed",
}


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, **kw)


def one(m):
    name, fname, old, new, what = m
    with tempfile.TemporaryDirectory() as tmp:
        src = pathlib.Path(tmp) / "src"
        shutil.copytree(ROOT / "src", src)
        text = (src / f"{fname}.cho").read_text()
        if text.count(old) != 1:
            return name, what, f"BAD BREAK: the old text occurs {text.count(old)} times"
        (src / f"{fname}.cho").write_text(text.replace(old, new))
        exe = pathlib.Path(tmp) / "chw"
        r = sh([CANCHO, "build", *[str(src / f"{x}.cho") for x in PROGRAM], "--std", "-o", str(exe)])
        if r.returncode != 0:
            return name, what, "BUILD FAILED: " + (r.stdout + r.stderr).strip()[:200]
        tiers = []
        if sh([sys.executable, "tests/differential/check_ran.py", str(exe), "--fixtures-only"]).returncode != 0:
            tiers.append("fixtures")
        lib = [str(src / f"{x}.cho") for x in MODULES]
        t = sh([CANCHO, "test", "tests/unit/test_check.cho", "tests/unit/support.cho", *lib, "--std"])
        if t.returncode != 0:
            tiers.append("unit")
        if tiers:
            return name, what, "KILLED by " + "+".join(tiers)
        return name, what, "EQUIVALENT" if name in EQUIVALENT else "SURVIVED"


def main():
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    jobs = int(sys.argv[sys.argv.index("--jobs") + 1]) if "--jobs" in sys.argv else 3
    todo = [m for m in M if only is None or m[0] in only]
    with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
        results = list(pool.map(one, todo))
    survived = 0
    equivalent = 0
    for name, what, verdict in results:
        print(f"{verdict:34} {name:18} {what}")
        if verdict == "EQUIVALENT":
            equivalent += 1
            print(f"  equivalent: {EQUIVALENT[name]}")
        elif not verdict.startswith("KILLED"):
            survived += 1
    print(f"{len(results) - survived - equivalent} of {len(results)} breaks killed, {equivalent} equivalent")
    sys.exit(1 if survived else 0)


main()
