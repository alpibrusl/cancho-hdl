"""Test-only oracle driver for `ran` (docs/cancho-port.md, 32): compare the rule groups `chw check FILE --ran` reports
with the `ran` set `tools/check/checker.py` fills in (`check(ir, ran=...)`), on the same inputs as
tests/differential/check_json.py: every fixture, and every mutant of it.

The Python side is `checker.load_contract` then `checker.check(ir, ran=...)` in this process, `sorted(ran)` one name per
line; the cancho side is `chw check FILE --ran`. They must be byte for byte the same. A difference is allowed only on an
input that check_json.py's `judge` explains by one of the known classes of 13.5 (the text parser's 18-digit rule, a
duplicate key, ...: the same cause that makes the two loaders disagree on the IR); anything else is UNEXPLAINED and fails.
An input on which the Python checker raises (it assumes a schema-valid shape) is counted, and cancho must still answer.

Usage:

    python3 tests/differential/check_ran.py /path/to/built/chw [--jobs N] [--fixtures-only]

Oracle code only: it decides nothing about the product."""
import collections
import concurrent.futures
import pathlib
import sys
import tempfile
import threading

import check_json as cj  # the same inputs, the same oracle; it reads sys.argv[1] as the chw binary

ROOT = cj.ROOT
checker = cj.checker
SCHEMA = cj.SCHEMA

_lock = threading.Lock()


def python_ran(path):
    with _lock:
        try:
            ir, _ = checker.load_contract(path)
            ran = set()
            if ir is not None:
                checker.check(ir, source_path=path, ran=ran)
        except Exception as e:
            return None, type(e).__name__
    return "".join(n + "\n" for n in sorted(ran)), None


def compare(tmp, label, text, path=None):
    """-> (tag, problem or None)"""
    if path is None:
        path = str(pathlib.Path(tmp) / f"{threading.get_ident()}.chw")
        pathlib.Path(path).write_text(text, encoding="utf-8")
    else:
        text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    py, crash = python_ran(path)
    rc, out, err = cj.run("check", path, "--ran", "--schema", SCHEMA)
    if rc not in (0, 1):
        return None, f"{label}: cancho exited {rc}: {err.strip()[:160]}"
    rc_diags = cj.run("check", path, "--output", "json", "--schema", SCHEMA)[0]
    if rc != rc_diags:
        return None, f"{label}: --ran exits {rc}, the diagnostics' command exits {rc_diags}"
    if crash:
        return f"python-crash:{crash}", None
    if py == out:
        return "identical", None
    tags, problem = cj.judge(tmp, label, text)
    if problem is None and any(t.startswith("known:") for t in tags):
        return "known:" + ",".join(t for t in tags if t.startswith("known:")), None
    return None, f"{label}: python ran {py!r}, cancho ran {out!r}"


def main():
    jobs = 4
    if "--jobs" in sys.argv:
        jobs = int(sys.argv[sys.argv.index("--jobs") + 1])
    tally, bad = collections.Counter(), []
    with tempfile.TemporaryDirectory() as tmp:
        for f in cj.fixture_files():
            tag, problem = compare(tmp, f.name, None, str(f))
            tally["fixtures"] += 1
            if problem:
                bad.append(problem)
            else:
                tally[tag] += 1
        print(f"fixtures: {tally['fixtures']} files; groups identical on {tally['identical']}, known differences {sum(v for k, v in tally.items() if k.startswith('known:'))}")
        if "--fixtures-only" not in sys.argv:
            seen = set()
            with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
                futs = []
                for label, text in cj.mutants():
                    if text in seen:
                        continue
                    seen.add(text)
                    futs.append(pool.submit(compare, tmp, label, text))
                for fu in futs:
                    tag, problem = fu.result()
                    tally["mutants"] += 1
                    if problem:
                        bad.append(problem)
                    else:
                        tally["m:" + tag] += 1
            print(f"mutants: {tally['mutants']} distinct inputs; groups identical on {tally['m:identical']}")
            for k in sorted(tally):
                if k.startswith("m:known:") or k.startswith("m:python-crash:"):
                    print(f"  {k[2:]}: {tally[k]}")
    print(f"{len(bad)} unexplained differences")
    for b in bad[:20]:
        print("UNEXPLAINED", b)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
