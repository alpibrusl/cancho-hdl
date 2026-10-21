"""Test-only oracle driver for stage 5 (docs/cancho-port.md, 33): compare `chw diff` and `chw impact` with
`tools/diff/diff.py`, on pairs of contracts.

The pairs are the inputs of the checker's differential (tests/differential/check_json.py) taken two at a time:
  * each valid example, the refusal fixtures, tests/stage1 and tests/stage2 against itself and against every valid
    example, in both directions;
  * each seed against each of its mutants (one semantic change at a time: a field's bits, an offset, a reset, an enum
    value, a DMA align, an owner, a kind, a bus width, a name, an interrupt reference, the version; every key deleted,
    every array element duplicated), in both directions, and the textual examples against theirs;
  * the seeded Phase 2 change of tests/diff/fixtures, and the cross-form pair (a JSON file against its text form).

The Python side is `diff.py` in this process (`_load_or_refuse`, `compute_diff`, `compute_impact`, `json.dumps`), the
cancho side `chw diff` / `chw impact`; the bytes of standard output, standard error and the exit status are compared. A
difference must fall in a class of KNOWN below, each of which 33.3 and 33.4 give with its reason; anything else is
UNEXPLAINED and fails the run. A pair on which the Python tool raises (it assumes a checked shape) is counted by
exception type, and cancho must still answer with 0 or 1.

Usage:

    python3 tests/differential/diff_cmp.py /path/to/built/chw [--jobs N] [--fixtures-only] [--pretty-every N] [--label SUBSTRING]

Oracle code only: it decides nothing about the product."""
import collections
import concurrent.futures
import importlib.util
import itertools
import json
import pathlib
import re
import sys
import tempfile
import threading
import traceback

import check_json as cj  # the same inputs and the same oracle; it reads sys.argv[1] as the chw binary

ROOT = cj.ROOT
EXE = cj.EXE
SCHEMA = cj.SCHEMA

spec = importlib.util.spec_from_file_location("diffpy", ROOT / "tools" / "diff" / "diff.py")
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)

_lock = threading.Lock()


def py_run(cmd, base, cand, pretty):
    """-> (rc, stdout, stderr) or (None, crash, None)"""
    with _lock:
        try:
            ir_b, errs_b = D._load_or_refuse(base)
            ir_c, errs_c = D._load_or_refuse(cand)
            if ir_b is None or ir_c is None:
                err = "".join(f"error[{e.code}]: {e.message}\n" for e in (errs_b or []) + (errs_c or []))
                return 1, "", err
            doc = D.compute_diff(ir_b, ir_c) if cmd == "diff" else D.compute_impact(ir_b, ir_c)
            text = json.dumps(doc, indent=2) if pretty else json.dumps(doc)
            return 0, text + "\n", ""
        except Exception as e:
            frame = traceback.extract_tb(e.__traceback__)[-1]
            return None, f"{type(e).__name__}@{pathlib.Path(frame.filename).name}:{frame.lineno}", None


def feature_classes(*texts):
    """The loader classes of check_json.py that a file has. Its "float" also matches the version string "0.1.0", so a
    number outside the strings is looked for here instead."""
    f = set()
    for t in texts:
        f |= cj.features(t) - {"float"}
        if re.search(r"\d{19,}", t):
            f.add("integer-range")
        bare = re.sub(r'"(?:[^"\\]|\\.)*"', '""', t)
        if re.search(r"-?\d+\.\d+|\d[eE][+-]?\d", bare):
            f.add("float")
    return f


def compare(tmp, label, cmd, base_text, cand_text, pretty=False):
    """-> (tag, problem or None)"""
    tid = threading.get_ident()
    bp, cp = str(pathlib.Path(tmp) / f"{tid}.base.chw"), str(pathlib.Path(tmp) / f"{tid}.cand.chw")
    pathlib.Path(bp).write_text(base_text, encoding="utf-8")
    pathlib.Path(cp).write_text(cand_text, encoding="utf-8")
    return compare_paths(label, cmd, bp, cp, base_text, cand_text, pretty)


def compare_paths(label, cmd, bp, cp, base_text, cand_text, pretty=False):
    rc, out, err = py_run(cmd, bp, cp, pretty)
    flags = ["--pretty"] if pretty else []
    crc, cout, cerr = cj.run(cmd, bp, cp, "--schema", SCHEMA, *flags)
    if rc is None:
        # Python raised: cancho answered. 3 is a generator's internal refusal (a contract the Python generator cannot
        # write either), reported as such and never a trap.
        if crc not in (0, 1, 3):
            return None, f"{label}: {cmd} python raised {out}; cancho exited {crc}: {cerr.strip()[:200]}"
        return f"python-crash:{out}", None
    if crc not in (0, 1):
        return None, f"{label}: {cmd} cancho exited {crc}: {cerr.strip()[:200]}"
    if (rc, out, err) == (crc, cout, cerr):
        return "identical" if rc == 0 else "refused-identical", None
    # a file that is not JSON: only the wording of the syntax message differs (13.5)
    def unworded(e):
        return re.sub(r"(file is not valid JSON)[^\n]*", r"\1", e)

    if rc == crc == 1 and out == cout and unworded(err) == unworded(cerr) and "file is not valid JSON" in err:
        return "known:json-syntax-wording", None
    # the port narrows: it refuses where Python writes (33.3, 33.4)
    if rc == 0 and crc == 1 and re.match(r"error\[(diff-text-unsupported|generator-unimplemented)\]", cerr):
        return "known:port-narrowing", None
    feats = feature_classes(base_text, cand_text)
    classes = feats & {"duplicate-key", "integer-range", "pattern-trailing-newline", "float", "hex-range"}
    if classes and (crc == 1 or rc == 1 or cout != out):
        return "known:loader-" + sorted(classes)[0], None
    where = ""
    if rc == crc == 0:
        for i, (a, b) in enumerate(zip(out, cout)):
            if a != b:
                where = f" first byte difference at {i}: python {out[max(0, i - 40):i + 60]!r} cancho {cout[max(0, i - 40):i + 60]!r}"
                break
        else:
            where = f" lengths {len(out)} / {len(cout)}"
    return None, f"{label}: {cmd} rc {rc}/{crc}; stderr python {err.strip()[:100]!r} cancho {cerr.strip()[:100]!r};{where}"


def valid_files():
    manifest = json.loads((ROOT / "examples/MANIFEST.json").read_text())
    return [ROOT / p for p in manifest["valid"] + manifest.get("textual_valid", [])]


def fixture_pairs():
    """-> [(label, base_path, cand_path)] of whole files"""
    valid = valid_files()
    others = [p for p in cj.fixture_files() if p not in valid]
    pairs = []
    for a in valid + others:
        for b in valid:
            pairs.append((f"{a.name}~{b.name}", a, b))
            pairs.append((f"{b.name}~{a.name}", b, a))
    pairs.append(("phase2", ROOT / "examples/uart-contract/uart.chw", ROOT / "tests/diff/fixtures/uart_rebase.chw"))
    pairs.append(("kind-only", ROOT / "examples/uart-contract/uart.chw", ROOT / "tests/diff/fixtures/uart_kind.chw"))
    pairs.append(("kind-only-reverse", ROOT / "tests/diff/fixtures/uart_kind.chw", ROOT / "examples/uart-contract/uart.chw"))
    pairs.append(("phase2-reverse", ROOT / "tests/diff/fixtures/uart_rebase.chw", ROOT / "examples/uart-contract/uart.chw"))
    return pairs


def mutant_pairs():
    for f in cj.seeds():
        src = f.read_text()
        for label, t in cj.semantic_mutants(json.loads(src)):
            yield f"{f.name}:{label}", src, t
    manifest = json.loads((ROOT / "examples/MANIFEST.json").read_text())
    for p in manifest.get("textual_valid", []):
        src = (ROOT / p).read_text()
        for label, t in cj.textual_mutants(src):
            yield f"{pathlib.Path(p).name}:{label}", src, t


def main():
    jobs = int(sys.argv[sys.argv.index("--jobs") + 1]) if "--jobs" in sys.argv else 4
    pretty_every = int(sys.argv[sys.argv.index("--pretty-every") + 1]) if "--pretty-every" in sys.argv else 7
    tally, bad = collections.Counter(), []

    def record(res):
        tag, problem = res
        tally["pairs"] += 1
        if problem:
            bad.append(problem)
        else:
            tally[tag] += 1

    # the refusals of the port's own (33.3) must be reached: a name with an escape, and a name with a non-ASCII byte
    esc = ROOT / "tests/stage1/escaped-names.chw"
    for cmd in ("diff", "impact"):
        crc, cout, cerr = cj.run(cmd, str(esc), str(esc), "--schema", SCHEMA)
        if (crc, cout) != (1, "") or not cerr.startswith("error[diff-text-unsupported]: the base contract"):
            bad.append(f"escaped-names.chw: {cmd} should be refused with diff-text-unsupported, got rc {crc}: {cerr.strip()[:120]}")
        else:
            tally["tag:diff-text-unsupported"] += 1
    for n, (label, a, b) in enumerate(fixture_pairs()):
        for cmd in ("diff", "impact"):
            record(compare_paths(f"{label}", cmd, str(a), str(b), a.read_text(errors="replace"), b.read_text(errors="replace"), pretty=(n % pretty_every == 0)))
    print(f"fixture pairs: {tally['pairs']} runs; identical {tally['identical']}, refused identically {tally['refused-identical']}, "
          f"known {sum(v for k, v in tally.items() if k.startswith('known:'))}")
    if "--fixtures-only" not in sys.argv:
        seen = set()
        with tempfile.TemporaryDirectory() as tmp:
            with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
                futs = []
                only = sys.argv[sys.argv.index("--label") + 1] if "--label" in sys.argv else None
                for n, (label, src, t) in enumerate(mutant_pairs()):
                    if only is not None and only not in label:
                        continue
                    if (src, t) in seen:
                        continue
                    seen.add((src, t))
                    for cmd, a, b in itertools.product(("diff", "impact"), ((src, t), (t, src)), (0,)):
                        pretty = n % pretty_every == 0
                        futs.append(pool.submit(compare, tmp, label, cmd, a[0], a[1], pretty))
                for fu in futs:
                    record(fu.result())
        print(f"with the mutant pairs: {tally['pairs']} runs; identical {tally['identical']}, refused identically {tally['refused-identical']}")
    for k in sorted(tally):
        if k.startswith("known:") or k.startswith("python-crash:") or k.startswith("tag:"):
            print(f"  {k}: {tally[k]}")
    print(f"{len(bad)} unexplained differences")
    for b in bad[:20]:
        print("UNEXPLAINED", b)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
