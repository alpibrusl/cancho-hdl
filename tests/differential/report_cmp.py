"""Test-only oracle driver for stage 6 (docs/cancho-port.md, 35): compare `chw report` with `tools/report/report.py`.

Two parts.

1. The report. For every fixture and every mutant of the checker's differential (tests/differential/check_json.py)
   `report.py`'s `main()` runs in this process and `chw report` runs as a program, and the bytes of standard output,
   standard error and the exit status are compared. The product runs no tool, so the two roundtrip lanes of `report.py`
   (`_run_c_header_roundtrip`, `_run_systemverilog_roundtrip`) are replaced here by stubs that return a fixed, adversarial
   result (each of passed, failed, skipped, a tool name with a space and parentheses, a reason with quotes, a newline,
   non-ASCII text and trailing blanks), and `chw report --lanes` is given the same results as a file: the derivation of
   `roundtrips_run`, the counts, `trust` and `unknown` from the lanes is then the thing compared. The stub that returns what
   the product returns by default ("no tool run") is compared with `chw report` given no lanes at all. The real
   `clang`/`iverilog` results are used on the fixtures (`--real-lanes`, one run each). Each of `--no-roundtrips`,
   `--pretty`, `--output text` and `--strict` is compared on a rotating subset.
2. `validate_report`. Corrupted copies of three reports (a clean one, a refused one, a parse error) -- every key deleted, every
   scalar changed to each of several other values, every list element dropped or repeated, every string altered -- are
   fed to `report.validate_report` and to `chw report --validate`; the refusal lines must be the same.

A difference must fall in a KNOWN class (35.4) or it is UNEXPLAINED and fails the run: the loaders' known differences
(13.5), or an input on which Python raises (counted by exception type; cancho must still exit 0 or 1).

Usage:

    python3 tests/differential/report_cmp.py /path/to/built/chw [--jobs N] [--fixtures-only] [--real-lanes] [--no-validate] [--stride N]

Oracle code only: it decides nothing about the product."""
import collections
import concurrent.futures
import contextlib
import copy
import importlib.util
import io
import json
import pathlib
import re
import sys
import tempfile
import threading
import traceback

import check_json as cj  # the same inputs and the same oracle; it reads sys.argv[1] as the chw binary

ROOT = cj.ROOT
SCHEMA = cj.SCHEMA

spec = importlib.util.spec_from_file_location("reportpy", ROOT / "tools" / "report" / "report.py")
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)

_lock = threading.Lock()
REAL_C, REAL_SV = R._run_c_header_roundtrip, R._run_systemverilog_roundtrip

NO_TOOL = "the cancho product runs no external tool; supply the oracle's results with --lanes"


def detail(target, path, outcome, reason, tool=None):
    d = {"target": target, "input": path}
    if tool is not None:
        d["tool"] = tool
    d.update(outcome=outcome, reason=reason)
    return d


# name -> (c-header, systemverilog) as functions of the path
COMBOS = {
    "F": lambda p: (detail("c-header", p, "skipped", NO_TOOL), detail("systemverilog", p, "skipped", NO_TOOL)),
    "A": lambda p: (detail("c-header", p, "passed", "compiled clean (-Wall -Wextra -Werror -std=c11)", "clang (Ubuntu clang version 18.1.3 (1ubuntu1))"),
                    detail("systemverilog", p, "failed", "roundtrip.sv:91: syntax error\n/tmp/x/report_roundtrip.sv:127: error: Malformed \"statement\"\té€\U0001f600", "iverilog (Icarus Verilog version 12.0)")),
    "B": lambda p: (detail("c-header", p, "passed", "ok", "gcc (gcc 13.2.0)"), detail("systemverilog", p, "passed", "iverilog -g2012 parse clean", "iverilog (unknown version)")),
    "C": lambda p: (detail("c-header", p, "skipped", "no C compiler on $PATH", "clang/gcc/cc"),
                    detail("systemverilog", p, "skipped", "no SystemVerilog parser on $PATH; not checked", "iverilog (not on $PATH)")),
    "D": lambda p: (detail("c-header", p, "failed", "error: unused \\ variable 'x'\n  ", "cc"), detail("systemverilog", p, "passed", "", "iverilog")),
    "E": lambda p: (detail("c-header", p, "skipped", "reason with trailing blanks \t\n ", "clang"), detail("systemverilog", p, "skipped", "é tail  ")),
    "G": lambda p: (detail("c-header", p, "skipped", "separators \x1c\x1d\x1e\x1f \x0b\x0c\r\t\n ", "clang"), detail("systemverilog", p, "skipped", "x\r")),
}
LANE_COMBOS = ["A", "B", "C", "D", "E", "G"]


def py_run(path, flags, combo, pair=None):
    """-> (rc, stdout, stderr) or (None, crash, None). `pair` is two results to return instead of a stub's."""
    with _lock:
        if pair is None:
            R._run_c_header_roundtrip = lambda ir, p, tmp: COMBOS[combo](p)[0]
            R._run_systemverilog_roundtrip = lambda ir, p, tmp: COMBOS[combo](p)[1]
        else:
            R._run_c_header_roundtrip = lambda ir, p, tmp: pair[0]
            R._run_systemverilog_roundtrip = lambda ir, p, tmp: pair[1]
        out, err = io.StringIO(), io.StringIO()
        old = sys.argv
        sys.argv = ["report", path, *flags]
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    rc = R.main()
                except SystemExit as e:
                    rc = e.code
        except Exception as e:
            frame = traceback.extract_tb(e.__traceback__)[-1]
            return None, f"{type(e).__name__}@{pathlib.Path(frame.filename).name}:{frame.lineno}", None
        finally:
            sys.argv = old
        return rc, out.getvalue(), err.getvalue()


def lanes_file(tmp, path, combo):
    f = pathlib.Path(tmp) / f"{threading.get_ident()}.lanes.json"
    f.write_text(json.dumps(list(COMBOS[combo](path))), encoding="utf-8")
    return str(f)


def real_lanes_file(tmp, path):
    """The two results of `report.py` run for real on `path` (clang, iverilog), once, as a lanes file and a pair."""
    with _lock:
        R._run_c_header_roundtrip, R._run_systemverilog_roundtrip = REAL_C, REAL_SV
        ir, _ = R.load_contract(path)
        if ir is None:
            pair = COMBOS["F"](path)
        else:
            with tempfile.TemporaryDirectory(prefix="cancho-report-") as td:
                t = type("T", (), {"name": td})
                pair = (R._run_c_header_roundtrip(ir, path, t), R._run_systemverilog_roundtrip(ir, path, t))
    f = pathlib.Path(tmp) / f"{threading.get_ident()}.real.json"
    f.write_text(json.dumps(list(pair)), encoding="utf-8")
    return str(f), pair


def classes_of(text):
    f = set()
    f |= cj.features(text) - {"float"}
    if re.search(r"\d{19,}", text):
        f.add("integer-range")
    bare = re.sub(r'"(?:[^"\\]|\\.)*"', '""', text)
    if re.search(r"-?\d+\.\d+|\d[eE][+-]?\d", bare):
        f.add("float")
    return f


def first_difference(a, b):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return f" first byte difference at {i}: python {a[max(0, i - 40):i + 60]!r} cancho {b[max(0, i - 40):i + 60]!r}"
    return f" lengths {len(a)} / {len(b)}"


def judge(label, text, cflags, py, ca):
    """-> (tag, problem or None)"""
    rc, out, err = py
    crc, cout, cerr = ca
    if rc is None:
        if crc not in (0, 1):
            return None, f"{label} {cflags}: python raised {out}; cancho exited {crc}: {cerr.strip()[:200]}"
        return f"python-crash:{out}", None
    if (rc, out, err) == (crc, cout, cerr):
        return "identical", None
    classes = classes_of(text) & {"duplicate-key", "integer-range", "pattern-trailing-newline", "float", "hex-range"}
    if classes:
        return "known:loader-" + sorted(classes)[0], None
    if rc == crc == 0 or (rc == crc and out == cout):
        # a JSON syntax message is worded another way (13.5): only the message of the diagnostic
        if "file is not valid JSON" in out + cout:
            return "known:json-syntax-wording", None
    return None, f"{label} {cflags}: rc {rc}/{crc}; stderr python {err.strip()[:120]!r} cancho {cerr.strip()[:120]!r};{first_difference(out, cout)}"


def compare(tmp, label, text, path=None, index=0, real=False):
    """All the comparisons for one input. -> list of (tag, problem or None)"""
    if path is None:
        path = str(pathlib.Path(tmp) / f"{threading.get_ident()}.chw")
        pathlib.Path(path).write_text(text, encoding="utf-8")
    else:
        text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    results = []

    def one(pflags, cflags, combo, tag_suffix=""):
        py = py_run(path, pflags, combo)
        ca = cj.run("report", path, "--schema", SCHEMA, *cflags)
        results.append(judge(label, text, pflags + ["|"] + cflags, py, ca))

    extra = [[], ["--pretty"], ["--output", "text"], ["--strict"], ["--pretty", "--strict"]][index % 5]
    one(["--no-roundtrips", *extra], ["--no-roundtrips", *extra], "F")
    one([*extra], [*extra], "F")  # the product default is the stub F
    combo = LANE_COMBOS[index % len(LANE_COMBOS)]
    one(["--output", "text"] if index % 4 == 0 else extra, ["--lanes", lanes_file(tmp, path, combo), *(["--output", "text"] if index % 4 == 0 else extra)], combo)
    if real:
        lf, pair = real_lanes_file(tmp, path)
        py = py_run(path, [], None, pair=pair)
        ca = cj.run("report", path, "--schema", SCHEMA, "--lanes", lf)
        results.append(judge(label, text, "real-lanes", py, ca))
    return results


# ---------------------------------------------------------------------------
# part 2: validate_report


def corruptions(doc):
    """Yield (label, corrupted document) -- structured damage, no floats."""
    def walk(node, path):
        yield path, node
        if isinstance(node, dict):
            for k, v in node.items():
                yield from walk(v, path + (k,))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                yield from walk(v, path + (i,))

    def at(d, path):
        for p in path:
            d = d[p]
        return d

    for path, node in list(walk(doc, ())):
        if not path:
            continue
        label = "/".join(map(str, path))
        parent_path, key = path[:-1], path[-1]

        def with_value(v):
            c = copy.deepcopy(doc)
            at(c, parent_path)[key] = v
            return c

        yield f"{label}:null", with_value(None)
        yield f"{label}:int", with_value(99)
        yield f"{label}:zero", with_value(0)
        yield f"{label}:true", with_value(True)
        yield f"{label}:str", with_value("x")
        yield f"{label}:empty-list", with_value([])
        yield f"{label}:empty-dict", with_value({})
        if isinstance(node, str):
            yield f"{label}:suffix", with_value(node + "!")
            yield f"{label}:Trust", with_value("Trust")
            yield f"{label}:skipped", with_value("skipped")
            yield f"{label}:Error", with_value("Error")
        c = copy.deepcopy(doc)
        container = at(c, parent_path)
        if isinstance(container, dict):
            del container[key]
            yield f"{label}:delete", c
        else:
            container.pop(key)
            yield f"{label}:drop", c
            c2 = copy.deepcopy(doc)
            at(c2, parent_path).insert(key, copy.deepcopy(node))
            yield f"{label}:repeat", c2
    yield "root:list", []
    yield "root:string", "report"
    yield "root:null", None
    yield "root:empty", {}
    # the combinations the single edits cannot make
    c = copy.deepcopy(doc)
    c["static"]["checks_run"].append("not-in-the-catalog")
    c["static"]["diagnostics"].append({"code": "made-up", "severity": "Error"})
    c["tested"]["roundtrips_run"] = ["c-header::clang"]
    c["tested"]["details"] = [{"target": "c-header", "outcome": "skipped"}, {"outcome": "skipped"}, {"target": None, "outcome": "skipped"}]
    c["trust"]["boundaries"] = [{"tool": "t", "tier": "Unknown"}, {"tier": "Trust"}, 5, "s"]
    yield "combined", c
    c = copy.deepcopy(doc)
    c["static"]["diagnostics"] = [{"severity": "Error"}, {"code": "b", "severity": "Error"}, {"code": "a", "severity": "Error"}, {"code": "b", "severity": "Error"}, {"code": "é", "severity": "Error"}, {"code": 7, "severity": "Error"}, {"code": "ok", "severity": "Warning"}]
    c["static"]["checks_run"] = ["aé", "q'uote", "tab\t", 5, None, True]
    yield "codes", c


def py_validate(doc):
    try:
        refusals = R.validate_report(doc)
    except Exception as e:
        frame = traceback.extract_tb(e.__traceback__)[-1]
        return None, f"{type(e).__name__}@{pathlib.Path(frame.filename).name}:{frame.lineno}"
    return "".join(f"internal[{c}]: {m}\n" for c, m in refusals), None


def compare_validate(tmp, label, doc):
    py, crash = py_validate(doc)
    f = pathlib.Path(tmp) / f"{threading.get_ident()}.report.json"
    f.write_text(json.dumps(doc), encoding="utf-8")
    rc, out, err = cj.run("report", "--validate", str(f))
    if rc not in (0, 1):
        return None, f"validate {label}: cancho exited {rc}: {err.strip()[:160]}"
    if out:
        return None, f"validate {label}: cancho wrote to standard output"
    if label.endswith("checks_run:str") or label.endswith("roundtrips_run:str"):
        # Python iterates the characters of a string (35.4, 4): the port reads a list that is not one as absent
        return ("known:string-list" if rc in (0, 1) else None), (None if rc in (0, 1) else f"validate {label}: cancho exited {rc}")
    if crash:
        return f"python-crash:{crash}", None
    want = 1 if py else 0
    if py == err and rc == want:
        return "identical", None
    return None, f"validate {label}: python {py!r} cancho {err!r} (rc {rc})"


def base_reports(tmp):
    out = []
    for name in ("examples/uart-contract/uart.chw", "examples/refusal/field-overlap.chw", "examples/refusal/parse-error.chw"):
        path = str(ROOT / name)
        out.append(copy.deepcopy(json.loads(py_run(path, [], "A")[1])))
    # a report with a trust boundary and a skipped lane, so the corruptions have something to bite
    path = str(ROOT / "examples/uart-contract/uart.chw")
    out.append(json.loads(py_run(path, [], "B")[1]))
    out.append(json.loads(py_run(path, [], "C")[1]))
    return out


def main():
    jobs = 4
    if "--jobs" in sys.argv:
        jobs = int(sys.argv[sys.argv.index("--jobs") + 1])
    real = "--real-lanes" in sys.argv
    stride = int(sys.argv[sys.argv.index("--stride") + 1]) if "--stride" in sys.argv else 1
    tally, bad = collections.Counter(), []

    def record(prefix, results):
        for tag, problem in results:
            tally[prefix + "runs"] += 1
            if problem:
                bad.append(problem)
            else:
                tally[prefix + tag] += 1

    with tempfile.TemporaryDirectory() as tmp:
        for n, f in enumerate(cj.fixture_files()):
            tally["fixtures"] += 1
            record("f:", compare(tmp, f.name, None, str(f), index=n, real=real))
        # a path that is not ASCII, in both the JSON and the text output
        odd = pathlib.Path(tmp) / "café-€ \"q\".chw"
        odd.write_text((ROOT / "examples/uart-contract/uart.chw").read_text(), encoding="utf-8")
        for n in range(5):
            record("f:", compare(tmp, "non-ascii-path", None, str(odd), index=n, real=real))
        print(f"fixtures: {tally['fixtures']} files, {tally['f:runs']} comparisons: identical {tally['f:identical']}, "
              f"known {sum(v for k, v in tally.items() if k.startswith('f:known:'))}, python raised {sum(v for k, v in tally.items() if k.startswith('f:python-crash:'))}")
        for k in sorted(tally):
            if k.startswith("f:known:") or k.startswith("f:python-crash:"):
                print(f"  {k[2:]}: {tally[k]}")
        if "--fixtures-only" not in sys.argv:
            seen = set()
            with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
                futs = []
                for n, (label, text) in enumerate(cj.mutants()):
                    if text in seen:
                        continue
                    seen.add(text)
                    if n % stride:
                        continue
                    futs.append(pool.submit(compare, tmp, label, text, None, n))
                for fu in futs:
                    tally["mutants"] += 1
                    record("m:", fu.result())
            print(f"mutants: {tally['mutants']} distinct inputs (every {stride}th of the stream), {tally['m:runs']} comparisons: identical {tally['m:identical']}")
            for k in sorted(tally):
                if k.startswith("m:known:") or k.startswith("m:python-crash:"):
                    print(f"  {k[2:]}: {tally[k]}")
        if "--no-validate" not in sys.argv:
            reports = base_reports(tmp)
            jobs_v = []
            with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
                for r, doc in enumerate(reports):
                    for label, bad_doc in corruptions(doc):
                        jobs_v.append(pool.submit(compare_validate, tmp, f"{r}:{label}", bad_doc))
                for fu in jobs_v:
                    tag, problem = fu.result()
                    tally["v:runs"] += 1
                    if problem:
                        bad.append(problem)
                    else:
                        tally["v:" + tag] += 1
            print(f"validate_report: {tally['v:runs']} corrupted documents: identical {tally['v:identical']}, "
                  f"python raised {sum(v for k, v in tally.items() if k.startswith('v:python-crash:'))}")
            for k in sorted(tally):
                if k.startswith("v:python-crash:") or k.startswith("v:known:"):
                    print(f"  {k[2:]}: {tally[k]}")
    print(f"{len(bad)} unexplained differences")
    for b in bad[:25]:
        print("UNEXPLAINED", b)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
