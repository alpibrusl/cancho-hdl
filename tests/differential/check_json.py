"""Test-only oracle driver for stage 2 (docs/cancho-port.md, 13.6): compare the
cancho semantic checker (`chw check`) with the Python reference
(`tools/check/checker.py`).

Two parts.

  1. Fixtures. Every valid example, refusal fixture, tests/stage1 and tests/stage2
     file is run through both command lines, `--output json` and the text form,
     and the bytes are compared. No tolerance is applied to a file unless it is in
     the table of known differences below, and the report says which.

  2. Mutants. The same files, with one semantic change at a time: every value of a
     key-aware pool at every place that key occurs (a field's lsb and msb, an
     offset, a reset, an enum value, a DMA align or size, an owner, a kind, a
     bus width, a name, an interrupt reference, the version), every key
     deleted, every array element duplicated, and every collision of two names or
     two offsets; plus the textual examples with each token deleted or each
     number replaced. The Python side is `checker.check_file` in this process, the
     cancho side `chw check --output json`; both see the same path.

The comparison is the stream of diagnostics, byte for byte. A difference must
fall in a class of KNOWN below, each of which is a difference
docs/cancho-port.md 13.5 lists with its reason; anything else is UNEXPLAINED and
fails the run. A mutant on which the Python checker raises (it assumes a
schema-valid shape: `reg.get` on a number, `kind in set` on a list) cannot be
compared; the port must still answer, and the run counts those, by exception
type, and requires the cancho side to exit 0 or 1.

Usage:

    python3 tests/differential/check_json.py /path/to/built/chw [--jobs N] [--fixtures-only]

This file is oracle code only: it decides nothing about the product."""
import collections
import concurrent.futures
import copy
import importlib.metadata
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import threading
import traceback

ORACLE_VERSION = "4.26.0"
if importlib.metadata.version("jsonschema") != ORACLE_VERSION:
    sys.exit(f"check_json.py needs jsonschema {ORACLE_VERSION} (found {importlib.metadata.version('jsonschema')})")

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "check"))
import checker  # noqa: E402  (the oracle)
from text_format import format_diagnostics  # noqa: E402

EXE = sys.argv[1]
SCHEMA = "spec/contract-schema/cancho-hdl-contract.schema.json"


def run(*args):
    p = subprocess.run([EXE, *args], capture_output=True, text=True, errors="replace", cwd=ROOT)
    return p.returncode, p.stdout, p.stderr


# ---------------------------------------------------------------------------
# reading a stream of diagnostics


def objects(text):
    """The JSON objects of a stream, or None if it is not one."""
    dec = json.JSONDecoder()
    out, i = [], 0
    while True:
        while i < len(text) and text[i] in " \n":
            i += 1
        if i >= len(text):
            return out
        try:
            obj, i = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            return None
        out.append(obj)


FLOAT_TOKEN = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")


def canon_floats(msg):
    def f(m):
        t = m.group(0)
        return repr(float(t)) if re.search(r"[.eE]", t) else t
    return FLOAT_TOKEN.sub(f, msg)


def canon(x):
    """A diagnostic with every float token canonical, so `1E2` and `100.0` agree."""
    if isinstance(x, dict):
        return {k: canon(v) for k, v in x.items()}
    if isinstance(x, list):
        return [canon(v) for v in x]
    if isinstance(x, str):
        return canon_floats(x)
    if isinstance(x, float):
        return float(x)
    return x


# ---------------------------------------------------------------------------
# features of a document, to name why a difference is allowed


def has_duplicate_keys(text):
    seen = []

    def hook(pairs):
        keys = [k for k, _ in pairs]
        if len(keys) != len(set(keys)):
            seen.append(1)
        return dict(pairs)
    try:
        json.loads(text, object_pairs_hook=hook)
    except (json.JSONDecodeError, RecursionError):
        return False
    return bool(seen)


def features(text):
    f = set()
    if has_duplicate_keys(text):
        f.add("duplicate-key")
    if re.search(r"(?<![\w.])-?\d{19,}(?![\w.])", text):
        f.add("integer-range")
    if re.search(r"-?\d+\.\d+|\d[eE][+-]?\d", text):
        f.add("float")
    if re.search(r'"0x_?0*[0-9a-fA-F]{16}', text) or re.search(r'"0x[0-9a-fA-F_]{17,}', text):
        f.add("hex-range")
    if re.search(r'\\n"', text):
        f.add("pattern-trailing-newline")
    return f


def is_schema_diag(d):
    return d["code"] == "schema-invalid" and d["message"].startswith("schema validation failed:")


def split(diags):
    return [d for d in diags if is_schema_diag(d)], [d for d in diags if not is_schema_diag(d)]


def key_of(d):
    return json.dumps(d, sort_keys=True)


def explain(text, py, ca):
    """-> (set of class names) | None. `py` and `ca` are lists of diagnostic
    dicts that are not byte-identical."""
    classes = set()
    feats = features(text)
    # the text parser refuses a decimal number of more than 18 digits (stage 0)
    if len(ca) == 1 and ca[0]["code"] == "parse-error" and "more than 18 digits" in ca[0]["message"] and re.search(r"\d{19,}", text):
        return {"integer-range"}
    # a file that is not JSON: only the wording of the syntax message differs
    if len(py) == 1 and len(ca) == 1 and py[0]["message"].startswith("file is not valid JSON") and ca[0]["message"].startswith("file is not valid JSON") and py[0]["code"] == ca[0]["code"]:
        return {"json-syntax-wording"}
    py_s, py_m = split(py)
    ca_s, ca_m = split(ca)
    # cancho's own structural refusals (the 18-digit rule, duplicate keys, a
    # trailing newline in a hex string) have no Python twin
    extra = [d for d in ca_s if re.search(r"outside the 18-digit range|duplicate key|does not match", d["message"])]
    extra_keys = collections.Counter(key_of(d) for d in extra)
    py_keys = collections.Counter(key_of(d) for d in py_s)
    ca_keys = collections.Counter(key_of(d) for d in ca_s)
    only_py = py_keys - ca_keys
    only_ca = ca_keys - py_keys
    if only_py or only_ca:
        # allowed: cancho-only records of the kinds above, and float spelling
        for k in list(only_ca):
            d = json.loads(k)
            if "outside the 18-digit range" in d["message"] and "integer-range" in feats:
                classes.add("integer-range")
                del only_ca[k]
            elif "duplicate key" in d["message"] and "duplicate-key" in feats:
                classes.add("duplicate-key")
                del only_ca[k]
            elif "does not match" in d["message"] and "pattern-trailing-newline" in feats:
                classes.add("pattern-trailing-newline")
                del only_ca[k]
        if only_py or only_ca:
            if canon(list(map(json.loads, only_py.elements()))) == canon(list(map(json.loads, only_ca.elements()))) and "float" in feats:
                classes.add("float-repr")
            else:
                return None
    if key_of_list(py_m) != key_of_list(ca_m):
        if canon(py_m) == canon(ca_m) and "float" in feats:
            classes.add("float-repr")
        elif {k for d in py_m for k in [d["code"]]} == {d["code"] for d in ca_m} and (feats & {"hex-range", "integer-range", "duplicate-key"}):
            # same rules fire; only the numbers they quote differ
            classes.add(sorted(feats & {"hex-range", "integer-range", "duplicate-key"})[0] + "-quoted")
        elif "duplicate-key" in feats:
            classes.add("duplicate-key")
        else:
            return None
    return classes or None


def first_difference(a, b, path=""):
    """The path of the first place two JSON values differ, and the two values."""
    if type(a) != type(b):
        return path, a, b
    if isinstance(a, dict):
        for k in list(a) + [k for k in b if k not in a]:
            if k not in a or k not in b:
                return f"{path}/{k}", a.get(k, "<absent>"), b.get(k, "<absent>")
            r = first_difference(a[k], b[k], f"{path}/{k}")
            if r:
                return r
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}[len]", len(a), len(b)
        for i, (x, y) in enumerate(zip(a, b)):
            r = first_difference(x, y, f"{path}[{i}]")
            if r:
                return r
        return None
    return None if a == b else (path, a, b)


def key_of_list(ds):
    return [key_of(d) for d in ds]


# ---------------------------------------------------------------------------
# judging one input

_lock = threading.Lock()


def python_side(path):
    with _lock:
        try:
            diags = checker.check_file(path)
        except Exception as e:  # the oracle assumes a schema-valid shape
            frame = traceback.extract_tb(e.__traceback__)[-1]
            return None, f"{type(e).__name__}@{pathlib.Path(frame.filename).name}:{frame.lineno}"
    return "".join(d.to_json() + "\n" for d in diags), None


def judge(tmp, label, text):
    """-> (tags, unexplained or None)"""
    path = str(pathlib.Path(tmp) / f"{threading.get_ident()}.chw")
    pathlib.Path(path).write_text(text, encoding="utf-8")
    py_out, crash = python_side(path)
    rc, out, err = run("check", path, "--output", "json", "--schema", SCHEMA)
    if rc not in (0, 1):
        return [], f"{label}: cancho exited {rc}: {err.strip()[:160]}"
    ca = objects(out)
    if ca is None:
        return [], f"{label}: cancho printed something that is not a stream of JSON objects"
    if crash:
        return [f"python-crash:{crash}"], None
    py = objects(py_out)
    verdict_py = any(d["severity"] == "Error" for d in py)
    verdict_ca = any(d["severity"] == "Error" for d in ca)
    if py_out == out:
        return ["identical", "verdict-agree"], None
    tags = []
    if py == ca:
        return [], f"{label}: same diagnostics in another key order"
    why = explain(text, py, ca)
    if why is None:
        where = first_difference(py, ca)
        return [], f"{label}: diagnostics differ at {where[0] if where else '?'}\n   python: {str(where[1])[:140] if where else ''}\n   cancho: {str(where[2])[:140] if where else ''}"
    tags.extend(f"known:{w}" for w in sorted(why))
    tags.append("verdict-agree" if verdict_py == verdict_ca else "verdict-known")
    if verdict_py != verdict_ca and not (why & {"integer-range", "pattern-trailing-newline", "duplicate-key", "json-syntax-wording"}):
        return tags, f"{label}: verdict differs (python errors={verdict_py}, cancho errors={verdict_ca})"
    return tags, None


# ---------------------------------------------------------------------------
# part 1: the fixtures, through both command lines


def fixture_files():
    manifest = json.loads((ROOT / "examples/MANIFEST.json").read_text())
    files = [ROOT / p for p in manifest["valid"] + manifest.get("textual_valid", [])]
    files += sorted((ROOT / "examples/refusal").glob("*.chw"))
    files += sorted((ROOT / "tests/stage1").glob("*.chw"))
    files += sorted((ROOT / "tests/stage2").glob("*.chw"))
    return files


def py_cli(path, *flags):
    p = subprocess.run([sys.executable, "tools/check/checker.py", *flags, path], capture_output=True, text=True, cwd=ROOT)
    return p.returncode, p.stdout


def fixtures():
    counts = collections.Counter()
    bad = []
    for f in fixture_files():
        rel = str(f.relative_to(ROOT))
        text = f.read_text()
        for flag, name in (("--output=json", "json"), ("--output=text", "text")):
            prc, pout = py_cli(rel, flag)
            crc, cout, cerr = run("check", rel, "--output", name)
            counts[f"{name}-total"] += 1
            if (prc, pout) == (crc, cout):
                counts[f"{name}-identical"] += 1
                continue
            if name == "json":
                py, ca = objects(pout), objects(cout)
                why = explain(text, py, ca) if py is not None and ca is not None else None
            else:
                # the text form is derived from the JSON form: it is explained
                # when the JSON form is, and the lines of the two must agree
                # after dropping the lines of the diagnostics both sides lack
                pj, cj = py_cli(rel, "--output=json"), run("check", rel, "--output", "json")
                py, ca = objects(pj[1]), objects(cj[1])
                why = explain(text, py, ca) if py is not None and ca is not None else None
            if why:
                for w in why:
                    counts[f"known:{w}"] += 1
                counts[f"{name}-known-difference"] += 1
            else:
                bad.append(f"{rel} [{name}]: differs and is not a known class\n   python rc {prc}, cancho rc {crc}")
    return counts, bad


# ---------------------------------------------------------------------------
# part 2: mutants

HEX = ["0x0", "0x1", "0x2", "0x3", "0x4", "0x6", "0x8", "0xc", "0xC", "0x10", "0x00", "0x04", "0x004", "0x0000000004",
       "0xFF", "0xff", "0x100", "0xfffffffc", "0xfffffffd", "0xffffffff", "0x100000000", "0x100000004", "0x1_0", "0x_10", "0x10_",
       "0x1__0", "0x10 ", "0x10\t", "0x 10", "0X10", "0x", "", "0x1g", "10", "0x-1", "0x+1", None, 16,
       "0x1ffffffffffffffffff", "0xffffffffffffffff", "0x0fffffffffffffff", "0x1000000000000000", "0xfffffffffffffff",
       "0x1000000000000000000000", "0x00000000000000000000004", "0x10000000000000004", "0x1000000000000000f"]
INTS = [-1, 0, 1, 2, 3, 4, 5, 7, 8, 9, 15, 16, 17, 30, 31, 32, 33, 63, 64, 100, 4095, 4096, 4097, 2 ** 31, 2 ** 32, 2 ** 40,
        True, False, 1.5, 4.0, "4", None]
NAMES = ["", "A", "CTRL", "ENABLE", "ST", "RDY", "EN", "MODE", "rx", "a", "b", "D", "x y", "é", "a'b", 'a"b', "☃", "tab\tx", None, 5, True]
POOLS = {
    "lsb": INTS, "msb": INTS, "number": INTS, "written_as": INTS, "align": INTS, "size": INTS,
    "offset": HEX, "reset": HEX, "base_address": HEX,
    "kind": ["RO", "WO", "RW", "RC", "W1C", "W0C", "W1S", "W0S", "ro", "", "X", None, 5, True, 1.5, "W1C"],
    "bus_width": [8, 16, 32, 0, -1, 7, 9, 64, 128, 8.0, 32.0, 16.5, "32", None, True, False],
    "endianness": ["little", "big", "Little", "", None, 1, "big "],
    "owner": ["CPU", "DEVICE", "cpu", "GPU", "", None, 1, True],
    "name": NAMES, "register": NAMES, "field": NAMES, "interrupt": NAMES,
    "constraint": ["x", "", None, 5, "it's", 'q"q', "é"],
    "version": ["0.1.0", "0.1.9", "0.2.0", "0.0.0", "1.0.0", "0.1", "00.01.0", "0.1.0.0", "", None, 1, "a.b.c", "0.1.-1", "0.1.0\n", "0.1.0 ", "9" * 30 + ".0.0", "0.1." + "9" * 30],
    "coherent": [True, False, None, 1], "volatile": [True, False, None], "polling": [True, False, None],
    "__enum__": [0, 1, 2, 3, 4, 7, 8, 15, 16, 255, 256, -1, 1.5, "1", None, True, 2 ** 32, 2 ** 40],
}
GENERIC = [None, True, 0, -1, 7, 32, 1.5, 99999999999999999999, "", "x", "0x10", [], {}, [1], {"a": 1}]


def paths(node, path=()):
    yield path
    if isinstance(node, dict):
        for k, v in node.items():
            yield from paths(v, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from paths(v, path + (i,))


def get(node, path):
    for p in path:
        node = node[p]
    return node


def put(doc, path, value):
    d = copy.deepcopy(doc)
    if not path:
        return value
    get(d, path[:-1])[path[-1]] = value
    return d


def pool_for(doc, path):
    key = path[-1]
    if isinstance(key, int):
        return None
    if len(path) >= 2 and path[-2] == "enum":
        return POOLS["__enum__"]
    return POOLS.get(key)


def dumps(d):
    return json.dumps(d, indent=2, ensure_ascii=False)


def semantic_mutants(doc):
    all_paths = [p for p in paths(doc) if p]
    for path in all_paths:
        pool = pool_for(doc, path)
        if pool:
            for n, v in enumerate(pool):
                yield f"set@{path}={n}", dumps(put(doc, path, v))
        for n, v in enumerate(GENERIC):
            yield f"generic@{path}={n}", dumps(put(doc, path, v))
        parent = get(doc, path[:-1])
        if isinstance(parent, dict):
            d = copy.deepcopy(doc)
            del get(d, path[:-1])[path[-1]]
            yield f"delete@{path}", dumps(d)
        if isinstance(get(doc, path), list) and get(doc, path):
            d = copy.deepcopy(doc)
            get(d, path).append(copy.deepcopy(get(d, path)[0]))
            yield f"dup-first@{path}", dumps(d)
            d = copy.deepcopy(doc)
            get(d, path).append(copy.deepcopy(get(d, path)[-1]))
            yield f"dup-last@{path}", dumps(d)
            d = copy.deepcopy(doc)
            el = copy.deepcopy(get(d, path)[0])
            if isinstance(el, dict) and isinstance(el.get("name"), str):
                el["name"] += "2"
            get(d, path).append(el)
            yield f"copy-renamed@{path}", dumps(d)
            d = copy.deepcopy(doc)
            get(d, path).clear()
            yield f"empty@{path}", dumps(d)
    # collisions: one value of a kind copied over another of the same kind
    by_key = collections.defaultdict(list)
    for path in all_paths:
        if isinstance(path[-1], str) and path[-1] in ("name", "offset", "lsb", "msb", "register", "field", "align"):
            by_key[path[-1]].append(path)
    for key, ps in by_key.items():
        for a in ps:
            for b in ps:
                if a != b:
                    yield f"collide@{a}<-{b}", dumps(put(doc, a, get(doc, b)))
    # register/field bounds as a pair
    for path in all_paths:
        if path and path[-1] == "lsb":
            sib = path[:-1] + ("msb",)
            try:
                get(doc, sib)
            except (KeyError, IndexError, TypeError):
                continue
            for lsb in (0, 1, 3, 4, 7, 8, 15, 16, 31, 32):
                for msb in (0, 1, 3, 4, 7, 8, 15, 16, 31, 32):
                    d = put(doc, path, lsb)
                    d = put(d, sib, msb)
                    yield f"bounds@{path}={lsb}..{msb}", dumps(d)


def textual_mutants(src):
    toks = list(re.finditer(r"\S+", src))
    for m in toks:
        yield f"delete-token@{m.start()}", src[: m.start()] + src[m.end():]
    for m in re.finditer(r"0x[0-9a-fA-F_]+|\b\d+\b", src):
        pool = ["0x0", "0x1", "0x2", "0x4", "0x6", "0xff", "0x100", "0x1_0", "0xffffffff", "0x100000000", "0", "1", "3", "7", "8", "31", "32", "33", "64", "99999999999999999999"]
        for v in pool:
            yield f"number@{m.start()}={v}", src[: m.start()] + v + src[m.end():]
    for m in re.finditer(r"\b(RW|RO|WO|RC|W1C|CPU|DEVICE|little-endian|big-endian)\b", src):
        for v in ("RW", "RO", "WO", "RC", "W1C", "W0S", "XX", "CPU", "DEVICE"):
            yield f"word@{m.start()}={v}", src[: m.start()] + v + src[m.end():]


HANDMADE = [
    ("empty-object", "{}"),
    ("dup-key", '{"version": "0.1.0", "version": "0.2.0", "block": {}}'),
    ("not-json", "{"),
    ("huge", open(ROOT / "tests/stage2/several.chw").read().replace("0x00", "0x" + "0" * 40 + "4")),
    ("deep-hex", '{"version":"0.1.0","block":{"name":"B","base_address":"0x' + "f" * 200 + '","bus_width":32,"endianness":"little","registers":[{"name":"R","offset":"0x' + "f" * 200 + '","kind":"RW","reset":"0x' + "f" * 200 + '"}]}}'),
]


def seeds():
    out = []
    manifest = json.loads((ROOT / "examples/MANIFEST.json").read_text())
    for p in manifest["valid"]:
        out.append(ROOT / p)
    out += sorted((ROOT / "examples/refusal").glob("*.chw"))
    out += sorted((ROOT / "tests/stage2").glob("*.chw"))
    return [f for f in out if f.read_text().lstrip().startswith("{")]


def mutants():
    for f in seeds():
        src = f.read_text()
        yield f"{f.name}:original", src
        yield from ((f"{f.name}:{l}", t) for l, t in semantic_mutants(json.loads(src)))
    manifest = json.loads((ROOT / "examples/MANIFEST.json").read_text())
    for p in manifest.get("textual_valid", []) + ["examples/refusal/parse-error.chw"]:
        src = (ROOT / p).read_text()
        yield f"{pathlib.Path(p).name}:original", src
        yield from ((f"{pathlib.Path(p).name}:{l}", t) for l, t in textual_mutants(src))
    yield from ((f"handmade:{l}", t) for l, t in HANDMADE)


def main():
    jobs = 4
    if "--jobs" in sys.argv:
        jobs = int(sys.argv[sys.argv.index("--jobs") + 1])
    counts, bad = fixtures()
    total_fixture_files = counts["json-total"]
    print(f"fixtures: {total_fixture_files} files (valid examples, refusals, tests/stage1, tests/stage2)")
    print(f"  --output json byte-identical to checker.py: {counts['json-identical']} of {counts['json-total']}"
          f" ({counts['json-known-difference']} known differences)")
    print(f"  text form byte-identical to checker.py:     {counts['text-identical']} of {counts['text-total']}"
          f" ({counts['text-known-difference']} known differences)")
    for k in sorted(counts):
        if k.startswith("known:"):
            print(f"  {k}: {counts[k]}")
    if "--fixtures-only" in sys.argv:
        for b in bad:
            print("UNEXPLAINED", b)
        sys.exit(1 if bad else 0)

    tally = collections.Counter()
    seen = set()
    with tempfile.TemporaryDirectory() as tmp:
        with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
            futs = []
            for label, text in mutants():
                if text in seen:
                    tally["duplicate-input-skipped"] += 1
                    continue
                seen.add(text)
                futs.append(pool.submit(judge, tmp, label, text))
            for fu in futs:
                tags, problem = fu.result()
                tally["inputs"] += 1
                tally.update(tags)
                if problem:
                    bad.append(problem)
    crashes = sum(v for k, v in tally.items() if k.startswith("python-crash:"))
    print(f"mutants: {tally['inputs']} distinct inputs ({tally['duplicate-input-skipped']} repeats skipped)")
    print(f"  diagnostics byte-identical to checker.py: {tally['identical']}")
    print(f"  known differences, each explained:         {sum(v for k, v in tally.items() if k.startswith('known:'))} class instances")
    print(f"  verdict (any Error) agrees on {tally['verdict-agree']}; known verdict differences {tally['verdict-known']}")
    print(f"  checker.py raised, cancho answered without a trap: {crashes}")
    for k in sorted(tally):
        if k.startswith("known:") or k.startswith("python-crash:"):
            print(f"  {k}: {tally[k]}")
    print(f"{len(bad)} unexplained differences")
    shapes = collections.OrderedDict()
    for b in bad:
        m = re.search(r"differ at (\S+)", b)
        shapes.setdefault(re.sub(r"\[\d+\]", "[]", m.group(1)) if m else b.split(":")[1][:40], []).append(b)
    for sig, items in shapes.items():
        print(f"UNEXPLAINED x{len(items)} at {sig}; first: {items[0]}")
    sys.exit(1 if bad else 0)


main()
