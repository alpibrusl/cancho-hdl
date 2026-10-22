"""Test-only oracle driver for stage 1 (docs/cancho-port.md, 9.6): compare the
cancho JSON loader and structural validator with the Python reference on the
valid JSON examples, the JSON refusal fixtures, and mutants of both.

For every input it runs

  * the Python side: `json.loads` + `jsonschema.Draft202012Validator.iter_errors`
    against spec/contract-schema/cancho-hdl-contract.schema.json;
  * the cancho side: `chw validate --machine` and `chw parse`;

and compares (1) the verdict, (2) the multiset of (pointer, keyword, message),
(3) for inputs both accept, the IR JSON, raw and after the normalisations the
design document lists.

Every disagreement must fall in a class of KNOWN below (each is a difference
docs/cancho-port.md 9.5 lists, with its reason). Anything else is UNEXPLAINED
and fails the run. Usage:

    python3 tests/differential/json_validate.py /path/to/built/chw [--jobs N] [--no-textual]

`--no-textual` leaves out the truncation and token-deletion mutants (about
half the inputs, and all about JSON syntax), for a quick run.

This file is oracle code only: it decides nothing about the product."""
import collections
import concurrent.futures
import copy
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import threading

import importlib.metadata

import jsonschema

# The port reproduces jsonschema 4.26's message wording ("[] should be non-empty"
# where older releases say "[] is too short"; docs/cancho-port.md section 9.4).
# Comparing against another release would report wording differences that are not
# the port's, so refuse to run rather than compare against the wrong oracle.
ORACLE_VERSION = "4.26.0"
if importlib.metadata.version("jsonschema") != ORACLE_VERSION:
    sys.exit(
        f"json_validate.py needs jsonschema {ORACLE_VERSION} (found "
        f"{importlib.metadata.version('jsonschema')}): pip install jsonschema=={ORACLE_VERSION}"
    )

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "spec/contract-schema/cancho-hdl-contract.schema.json").read_text())
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)

# ---------------------------------------------------------------- python side


def pointer(path):
    out = ""
    for seg in path:
        s = str(seg)
        s = s.replace("~", "~0").replace("/", "~1")
        s = "".join(c if ord(c) >= 32 else "~x%02x" % ord(c) for c in s)
        out += "/" + s
    return out


def python_side(text):
    """('syntax', None) | ('ok', doc, errors) where errors is a sorted list."""
    try:
        doc = json.loads(text)
    except (json.JSONDecodeError, RecursionError):
        return ("syntax", None, [])
    errs = sorted(
        (pointer(e.absolute_path), e.validator, e.message) for e in VALIDATOR.iter_errors(doc)
    )
    return ("ok", doc, errs)


# ---------------------------------------------------------------- cancho side

_local = threading.local()


def run(exe, *args):
    p = subprocess.run([exe, *args], capture_output=True, text=True, errors="replace")
    return p.returncode, p.stdout, p.stderr


def cancho_side(exe, path):
    rc, out, err = run(exe, "validate", path, "--machine")
    recs = []
    for line in out.splitlines():
        parts = line.split("\t", 5)
        if len(parts) == 6:
            recs.append((parts[0], int(parts[1]), int(parts[2]), parts[3], parts[4], parts[5]))
    return rc, recs, err


# ----------------------------------------------------------- known differences

FLOAT_TOKEN = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
ESCAPE = re.compile(r"\\\\|\\(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8})")


def canon_floats(msg):
    """Float tokens as Python's repr writes them, so `1E2` and `100.0` agree."""
    def f(m):
        t = m.group(0)
        return repr(float(t)) if re.search(r"[.eE]", t) else t
    return FLOAT_TOKEN.sub(f, msg)


def canon_escapes(msg):
    """Backslash escapes of non-printables decoded, so `\\u0378` and U+0378 agree."""
    def f(m):
        return m.group(0) if m.group(1) is None else chr(int(m.group(1)[1:], 16))
    return ESCAPE.sub(f, msg)


def classify_syntax(text):
    """Why cancho refuses as JSON text that Python's json.loads read."""
    if re.search(r"(?<![\w\"])(NaN|-?Infinity)(?![\w\"])", text):
        return "nan-infinity"
    if re.search(r"\\ud[89ab][0-9a-fA-F]{2}(?!\\ud[c-f])", text, re.I) or re.search(
        r"(?<!\\ud[89ab][0-9a-f]{2})\\ud[c-f][0-9a-f]{2}", text, re.I
    ):
        return "lone-surrogate"
    if text.count("[") + text.count("{") > 128:
        return "nesting-over-128"
    return None


def explain_error_diff(text, doc, py_errs, ca_errs):
    """Classes of difference between the jsonschema errors and cancho's shared
    records; None if the difference cannot be explained."""
    reasons = set()
    py = collections.Counter(py_errs)
    ca = collections.Counter(ca_errs)
    if py == ca:
        return reasons
    only_py = py - ca
    only_ca = ca - py
    # Messages that differ only because a float is quoted differently.
    rest_py, rest_ca = dict(), dict()
    for (ptr, kw, msg), n in list(only_py.items()):
        for (ptr2, kw2, msg2), n2 in list(only_ca.items()):
            if ptr == ptr2 and kw == kw2 and msg != msg2 and canon_floats(msg) == canon_floats(msg2):
                reasons.add("float-repr")
                only_py[(ptr, kw, msg)] -= 1
                only_ca[(ptr2, kw2, msg2)] -= 1
                break
    only_py = +only_py
    only_ca = +only_ca
    # Python's `$` also matches before a final newline: it accepts a string
    # that ends in one; cancho does not.
    for (ptr, kw, msg), n in list(only_ca.items()):
        if kw == "pattern":
            v = doc_at(doc, ptr)
            if isinstance(v, str) and v.endswith("\n"):
                reasons.add("pattern-trailing-newline")
                del only_ca[(ptr, kw, msg)]
    # Non-printable characters beyond the table pyrepr carries.
    for (ptr, kw, msg), n in list(only_py.items()):
        for (ptr2, kw2, msg2), n2 in list(only_ca.items()):
            if ptr == ptr2 and kw == kw2 and msg != msg2 and canon_escapes(msg) == canon_escapes(msg2):
                reasons.add("non-ascii-repr")
                del only_py[(ptr, kw, msg)]
                del only_ca[(ptr2, kw2, msg2)]
                break
    return reasons if not only_py and not only_ca else None


def doc_at(doc, ptr):
    cur = doc
    if ptr == "":
        return cur
    for seg in ptr.split("/")[1:]:
        seg = seg.replace("~1", "/").replace("~0", "~")
        try:
            cur = cur[int(seg)] if isinstance(cur, list) else cur[seg]
        except (KeyError, IndexError, ValueError, TypeError):
            return None
    return cur


# ------------------------------------------------------------- IR comparison


def normalise(doc):
    """The Python document as the canonical IR printer would write it. Returns
    (document, set of normalisations that changed something)."""
    changed = set()
    d = copy.deepcopy(doc)

    def num(x):
        if isinstance(x, float) and x.is_integer():
            changed.add("integral-float")
            return int(x)
        return x

    def hexs(x):
        if isinstance(x, str) and x != x.lower():
            changed.add("hex-case")
            return x.lower()
        return x

    b = d.get("block", {})
    for k in ("base_address",):
        if k in b:
            b[k] = hexs(b[k])
    if "bus_width" in b:
        b["bus_width"] = num(b["bus_width"])
    for r in b.get("registers", []):
        for k in ("offset", "reset"):
            if k in r:
                r[k] = hexs(r[k])
        for k in ("volatile", "polling"):
            if r.get(k) is False:
                del r[k]
                changed.add("false-attribute-dropped")
        if r.get("fields") == []:
            del r["fields"]
            changed.add("empty-array-dropped")
        for f in r.get("fields", []):
            for k in ("lsb", "msb"):
                f[k] = num(f[k])
            for e, v in list(f.get("enum", {}).items()):
                f["enum"][e] = num(v)
    if b.get("interrupts") == []:
        del b["interrupts"]
        changed.add("empty-array-dropped")
    for i in b.get("interrupts", []):
        if "number" in i:
            i["number"] = num(i["number"])
    if "dma_buffers" not in d:
        d["dma_buffers"] = []
        changed.add("dma-buffers-defaulted")
    for buf in d.get("dma_buffers", []):
        for f in buf.get("fields", []):
            f["offset"] = hexs(f["offset"])
            for k in ("align", "written_as"):
                if k in f:
                    f[k] = num(f[k])
    return d, changed


def compare_ir(exe, path, doc):
    """'raw' | ('normalised', classes) | None (unexplained)."""
    rc, out, err = run(exe, "parse", path)
    if rc != 0:
        return None
    raw = json.dumps(doc) + "\n"
    if out == raw:
        return "raw"
    norm, changed = normalise(doc)
    try:
        theirs = json.loads(out)
    except json.JSONDecodeError:
        return None
    if theirs != norm:
        return None
    classes = set(changed)
    if out != json.dumps(norm) + "\n":
        classes.add("key-order")
    return ("normalised", classes)


# ------------------------------------------------------------------ mutation

POOL = [
    None, True, False, 0, -1, 1, 2, 7, 8, 16, 31, 32, 33, 64, 4096, 4097, 1.5, 100.0, 8.0, 1e2, 1e30,
    99999999999999999999, -99999999999999999999, "", "x", "0x", "0x1G", "0x10", "0x1F", "0X10", "0x10\n",
    "RW", "CPU", "GPU", "big", "caf\u00e9", "a\"b", "it's", "it's \"x\"", "\u65e5\u672c", "tab\there", "1.2.3", "0.1", "1.0.0\n",
    [], {}, [1], {"a": 1}, [[]], {"a": {"b": []}},
]


def leaves(node, path=()):
    yield path
    if isinstance(node, dict):
        for k, v in node.items():
            yield from leaves(v, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from leaves(v, path + (i,))


def get(node, path):
    for p in path:
        node = node[p]
    return node


def with_value(doc, path, value):
    d = copy.deepcopy(doc)
    if not path:
        return value
    get(d, path[:-1])[path[-1]] = value
    return d


def structural_mutants(doc):
    for path in leaves(doc):
        if not path:
            continue
        for n, v in enumerate(POOL):
            yield f"set@{pointer(path)}={n}", json.dumps(with_value(doc, path, v), indent=2)
        parent = get(doc, path[:-1])
        if isinstance(parent, dict):
            d = copy.deepcopy(doc)
            del get(d, path[:-1])[path[-1]]
            yield f"delete@{pointer(path)}", json.dumps(d, indent=2)
        if isinstance(get(doc, path), dict) and len(get(doc, path)) > 1:
            # Key order: reversed, and the first key moved last.
            for tag, order in (("reverse", lambda ks: ks[::-1]), ("rotate", lambda ks: ks[1:] + ks[:1])):
                d = copy.deepcopy(doc)
                node = get(d, path)
                items = [(k, node[k]) for k in order(list(node))]
                node.clear()
                node.update(items)
                yield f"{tag}@{pointer(path)}", json.dumps(d, indent=2)
        if isinstance(get(doc, path), dict):
            d = copy.deepcopy(doc)
            get(d, path)["extra"] = 1
            yield f"extra@{pointer(path)}", json.dumps(d, indent=2)
            d = copy.deepcopy(doc)
            get(d, path)["a/b~c\u00e9"] = [1]
            yield f"extra2@{pointer(path)}", json.dumps(d, indent=2)
            d = copy.deepcopy(doc)
            node = get(d, path)
            node["zzz"] = 1
            node["\u00e9"] = 2
            node["aaa"] = 3
            node["Zed"] = 4
            yield f"extra3@{pointer(path)}", json.dumps(d, indent=2)


def textual_mutants(src):
    for i in range(len(src)):
        yield f"truncate@{i}", src[:i]
    for m in re.finditer(r"\S+", src):
        yield f"delete-token@{m.start()}", src[: m.start()] + src[m.end():]


HANDMADE = [
    ("empty-object", "{}"),
    ("dup-key", '{"version": "0.1.0", "version": "0.2.0", "block": {}}'),
    ("escaped-name", json.dumps({"version": "0.1.0", "block": {"name": "A\u0042\\u00e9", "base_address": "0x0", "bus_width": 32, "endianness": "little", "registers": [{"name": "R\"q", "offset": "0x0", "kind": "RW"}]}}).replace("A\u0042", "A\\u0042")),
    ("bom", "\ufeff{}"),
    ("nested-deep", "{" * 200),
    ("trailing-comma", '{"version": "0.1.0",}'),
    ("nan", '{"version": "0.1.0", "block": NaN}'),
    ("lone-surrogate", '{"version": "\\ud800"}'),
    ("float-integer", '{"version": "0.1.0", "block": {"name": "B", "base_address": "0x0", "bus_width": 8.0, "endianness": "big", "registers": [{"name": "R", "offset": "0x0", "kind": "RW", "volatile": false, "fields": []}], "interrupts": []}}'),
    ("minus-zero", '{"version": "0.1.0", "block": {"name": "B", "base_address": "0x0", "bus_width": -0, "endianness": "big", "registers": [{"name": "R", "offset": "0x0", "kind": "RW"}]}}'),
    ("float-exponent", '{"version": "0.1.0", "block": {"name": "B", "base_address": "0x0", "bus_width": 1E2, "endianness": "big", "registers": [{"name": "R", "offset": "0x0", "kind": "RW", "fields": [{"name": "F", "lsb": 2.50, "msb": 1e1}]}]}}'),
    ("unassigned-char-in-message", '{"version": "0.1.0", "block": {"name": "B", "base_address": "0x0", "bus_width": 8, "endianness": "big", "registers": [{"name": "R", "offset": "0x0", "kind": "\u0378\u0085\u00a0"}]}}'),
    ("nested-value-in-message", '{"version": "0.1.0", "block": {"name": "B", "base_address": "0x0", "bus_width": [[], {"a": [1, "x", null, true, 1.5]}], "endianness": "big", "registers": [{"name": "R", "offset": "0x0", "kind": "RW"}]}}'),
    ("tabs-newlines", '\n\t{"version"\t:\n"0.1.0",\r\n"block":\n{}}\n'),
]


def inputs():
    files = []
    manifest = json.loads((ROOT / "examples/MANIFEST.json").read_text())
    for rel in manifest["valid"]:
        files.append(ROOT / rel)
    files += sorted((ROOT / "examples/refusal").glob("*.chw"))
    files += sorted((ROOT / "tests/stage1").glob("*.chw"))
    for f in files:
        src = f.read_text()
        if not src.lstrip().startswith("{"):
            continue
        yield f"{f.name}:original", src
        if "--no-textual" not in sys.argv:
            for label, text in textual_mutants(src):
                yield f"{f.name}:{label}", text
        try:
            doc = json.loads(src)
        except json.JSONDecodeError:
            continue  # a syntax-error fixture: only its textual mutants make sense
        for label, text in structural_mutants(doc):
            yield f"{f.name}:{label}", text
    for label, text in HANDMADE:
        yield f"handmade:{label}", text


# ----------------------------------------------------- the form sniff (9.5, 4)

SNIFF_WHITESPACE = ["\u00a0", "\u2003", "\u000b", "\u000c", "\u001c", "\u0085"]


def sniff_differences(exe, tmp):
    """Python's `lstrip()` skips Unicode whitespace before looking for `{`, then
    `json.loads` refuses it (JSON blanks are four). cancho skips the four, sees
    something that is not `{`, and reads the text form. Same refusal of the file,
    different code. Returns (events, unexplained)."""
    sys.path.insert(0, str(ROOT / "oracle" / "legacy" / "tools" / "parse"))
    from parser import load_contract  # the legacy loader, the oracle

    events, bad = [], []
    for ws in SNIFF_WHITESPACE:
        path = str(pathlib.Path(tmp) / "sniff.chw")
        pathlib.Path(path).write_text(ws + "{}", encoding="utf-8")
        ir, diags = load_contract(path)
        py_code = diags[0].code if ir is None else "ok"
        rc, recs, err = cancho_side(exe, path)
        ca_code = recs[0][0] if recs else "ok"
        if (py_code, ca_code) == ("schema-invalid", "parse-error"):
            events.append("known:sniff-unicode-whitespace")
        else:
            bad.append(f"sniff U+{ord(ws):04X}: python {py_code}, cancho {ca_code}")
    return events, bad


# ---------------------------------------------------------------------- main


def judge(exe, tmp, label, text):
    """-> (tags, unexplained message or None). Each tag is a counted event."""
    tags = []
    path = str(pathlib.Path(tmp) / f"{threading.get_ident()}.chw")
    pathlib.Path(path).write_text(text, encoding="utf-8")
    kind, doc, py_errs = python_side(text)
    rc, recs, err = cancho_side(exe, path)
    if rc not in (0, 1):
        # 2 is the tool failing to run; a negative status is a trap (a signal).
        return tags, f"{label}: cancho exited {rc}: {err.strip()[:120]}"
    ca_syntax = [r for r in recs if r[3] == "json-syntax"]
    ca_extra = [r for r in recs if r[3] in ("duplicate-key", "integer-range")]
    ca_shared = [(r[4], r[3], r[5]) for r in recs if r[3] not in ("json-syntax", "duplicate-key", "integer-range")]
    ca_valid = rc == 0
    if kind == "syntax":
        if len(ca_syntax) == 1 and len(recs) == 1:
            return ["both-syntax"], None
        return tags, f"{label}: python refuses the JSON, cancho says {recs}"
    py_valid = not py_errs
    if ca_syntax:
        why = classify_syntax(text)
        if why and len(recs) == 1:
            return [f"known:{why}"], None
        return tags, f"{label}: cancho syntax error on JSON python reads ({recs[0][5]})"
    # Duplicate keys: the verdict is cancho's own rule, whatever python made of them.
    if any(r[3] == "duplicate-key" for r in recs):
        return ["known:duplicate-key"], (None if not ca_valid else f"{label}: duplicate key accepted")
    reasons = explain_error_diff(text, doc, py_errs, ca_shared)
    if reasons is None:
        return tags, f"{label}: errors differ.\n   python: {py_errs}\n   cancho: {ca_shared}"
    for r in sorted(reasons):
        tags.append(f"known:{r}")
    if ca_extra:
        tags.append("known:integer-range")
    if py_valid == ca_valid:
        tags.append("verdict-agree")
        if py_errs and not reasons:
            tags.extend(["errors-identical"] * len(py_errs))
    elif ca_extra or "pattern-trailing-newline" in reasons:
        tags.append("verdict-known")
    else:
        return tags, f"{label}: verdict differs (python valid={py_valid}, cancho valid={ca_valid}): {recs}"
    if py_valid and ca_valid:
        res = compare_ir(exe, path, doc)
        if res is None:
            return tags, f"{label}: IR differs beyond the known classes"
        if res == "raw":
            tags.append("ir:raw-identical")
        else:
            tags.append("ir:normalised")
            for c in sorted(res[1]):
                tags.append(f"ir-class:{c}")
    return tags, None


def main():
    exe = sys.argv[1]
    jobs = 4
    if "--jobs" in sys.argv:
        jobs = int(sys.argv[sys.argv.index("--jobs") + 1])
    counts = collections.Counter()
    bad = []
    total = 0
    skipped = 0
    with tempfile.TemporaryDirectory() as tmp:
        with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
            futs = []
            for label, text in inputs():
                # Both loaders sniff the form: a text that does not begin with
                # `{` goes to the text parser, which tests/differential/text_parse.py covers.
                if not text.lstrip().startswith("{") or not text.lstrip(" \t\r\n").startswith("{"):
                    skipped += 1
                    continue
                futs.append(pool.submit(judge, exe, tmp, label, text))
            for fu in futs:
                tags, problem = fu.result()
                total += 1
                counts.update(tags)
                if problem:
                    bad.append(problem)
        events, problems = sniff_differences(exe, tmp)
        counts.update(events)
        bad.extend(problems)
    py_valid = counts["ir:raw-identical"] + counts["ir:normalised"]
    print(f"{total} inputs ({skipped} more skipped: not JSON-form after sniffing); {len(bad)} unexplained differences")
    print(f"  verdict agrees on {counts['verdict-agree']}, known verdict differences {counts['verdict-known']}, "
          f"both refuse as JSON {counts['both-syntax']}")
    print(f"  IR of inputs both accept: {py_valid} compared, {counts['ir:raw-identical']} byte-identical, "
          f"{counts['ir:normalised']} identical after normalisation")
    print(f"  jsonschema errors reproduced word for word: {counts['errors-identical']}")
    for k in sorted(counts):
        if k.startswith("ir-class:") or k.startswith("known:"):
            print(f"  {k}: {counts[k]}")
    for b in bad[:10]:
        print("UNEXPLAINED", b)
    sys.exit(0 if not bad else 1)


main()
