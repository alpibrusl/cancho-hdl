"""Verify the examples against the contract schema.

- Valid examples must load and schema-validate cleanly. Both the
  JSON wire form and the textual form are checked; the textual
  files go through the parser first, which is the point: what the
  parser emits must be schema-valid.
- Refusal examples either fail schema validation (caught at the
  wire level), fail to parse (`parse-error` for the textual
  syntax refusals), or validate but reference a semantic rule
  whose enforcement the checker demonstrates in conformance.
- This script prints what each example does; the rule-by-rule
  enforcement is `tools/check/conformance.py`.
"""

import json
import pathlib
import sys

import jsonschema

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "spec" / "contract-schema" / "cancho-hdl-contract.schema.json"
EXAMPLES = ROOT / "examples"

sys.path.insert(0, str(ROOT / "tools" / "parse"))
from parser import load_contract  # noqa: E402


def load(p):
    """Load a manifest entry as an IR, whatever format it is in."""
    ir, diags = load_contract(str(p))
    return ir, diags


def main():
    schema = json.loads(SCHEMA.read_text())
    validator = jsonschema.Draft202012Validator(schema)
    manifest = json.loads((EXAMPLES / "MANIFEST.json").read_text())

    print("== valid examples (must parse + pass schema) ==")
    rc = 0
    for rel in manifest["valid"] + manifest.get("textual_valid", []):
        f = ROOT / rel
        ir, diags = load(f)
        relname = f.relative_to(ROOT)
        if ir is None:
            print(f"  FAIL  {relname}  -> {diags[0].message}")
            rc = 1
            continue
        try:
            validator.validate(ir)
            print(f"  PASS  {relname}")
        except jsonschema.ValidationError as e:
            print(f"  FAIL  {relname}  -> {e.message}")
            rc = 1

    print()
    print("== refusal examples ==")
    for f in sorted((EXAMPLES / "refusal").glob("*.chw")):
        ir, diags = load(f)
        if ir is None:
            verdict = f"PARSE-FAIL ({diags[0].code})"
        else:
            try:
                validator.validate(ir)
                verdict = "SCHEMA-PASS"
            except jsonschema.ValidationError as e:
                verdict = f"SCHEMA-FAIL ({e.message[:60]})"
        sidecar = f.with_suffix(".expect.json")
        expect = json.loads(sidecar.read_text())["expect"]
        codes = sorted({e["code"] for e in expect})
        print(f"  {f.name:30s}  {verdict:25s}  expects: {', '.join(codes)}")

    return rc


if __name__ == "__main__":
    sys.exit(main())
