"""Test-only oracle (docs/cancho-port.md, 13.4): the rule catalog in the code
against the rule catalog in the spec.

`chw catalog` prints every rule the cancho tools can emit with the subject kind,
severity and tier that src/diagnostic.cho gives it. spec/diagnostics/README.md,
section 3, is the table those four functions restate. This reads the table and
compares, and it also checks that every rule has a refusal fixture: a sidecar
entry in examples/refusal, tests/stage1 or tests/stage2 that names it, which is
the spec's own rule for the catalog ("a code listed here without a refusal
fixture is refused at the catalog level").

Known differences, each listed with its reason:

  * `internal` is listed in the spec with subject `core`, which is not a
    subject kind (section 2.4 closes the list); the tools report it with an `Ir`
    subject.
  * the spec lists rules no cancho tool emits (the generator and roundtrip
    rules of 3.5, `ir-version-unsupported`, `dma-written-by-binding`,
    `rule-has-no-refusal-fixture`); those are not the checker's.

Usage: python3 tests/differential/catalog.py /path/to/built/chw
"""
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
exe = sys.argv[1]

spec = {}
for line in (ROOT / "spec/diagnostics/README.md").read_text().splitlines():
    m = re.match(r"\|\s*`([a-z0-9-]+)`\s*\|\s*`(\w+)`\s*\|\s*`(\w+)`\s*\|\s*`(\w+)`\s*\|", line)
    if m and m.group(1) != "code":
        spec[m.group(1)] = m.groups()[1:]

ours = {}
out = subprocess.run([exe, "catalog"], capture_output=True, text=True, check=True).stdout
for line in out.splitlines():
    code, subject, severity, tier = line.split("\t")
    ours[code] = (subject, severity, tier)

KNOWN_SUBJECT = {"internal": ("core", "Ir")}
bad = []
agree = 0
for code, got in sorted(ours.items()):
    want = spec.get(code)
    if want is None:
        bad.append(f"{code}: emitted by the tools, not in the spec's tables")
        continue
    if want == got:
        agree += 1
    elif code in KNOWN_SUBJECT and want[0] == KNOWN_SUBJECT[code][0] and got[0] == KNOWN_SUBJECT[code][1] and want[1:] == got[1:]:
        agree += 1
        print(f"  known: {code} is subject {want[0]} in the spec, {got[0]} in the tools")
    else:
        bad.append(f"{code}: spec says {want}, code says {got}")

not_ours = sorted(set(spec) - set(ours))

# every rule has a fixture
named = set()
for d in ("examples/refusal", "tests/stage1", "tests/stage2"):
    for side in sorted((ROOT / d).glob("*.expect.json")):
        for e in json.loads(side.read_text())["expect"]:
            named.add(e["code"])
# `internal` is the validator's own fault on a schema it cannot interpret; the
# schema is not a fixture, so tests/unit/test_schema.cho covers it instead.
uncovered = sorted(set(ours) - named - {"internal"})
for code in uncovered:
    bad.append(f"{code}: no refusal fixture names it")

print(f"{len(ours)} rules in the code, {agree} agree with spec/diagnostics/README.md section 3")
print(f"{len(not_ours)} rules in the spec that no cancho tool emits: {', '.join(not_ours)}")
print(f"{len(ours) - len(uncovered) - 1} of {len(ours) - 1} rules named by a refusal fixture (`internal` is covered by a unit test instead)")
for b in bad:
    print("MISMATCH", b)
sys.exit(1 if bad else 0)
