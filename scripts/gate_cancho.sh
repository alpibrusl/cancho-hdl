#!/bin/sh
# The gate for the cancho half of the repository (docs/cancho-port.md, 9.7).
# Needs the built cancho compiler (CANCHO, default ../cancho/target/release/cancho)
# and python3, which is used ONLY as the oracle: the legacy parser and
# jsonschema in tests/differential/. `python3 scripts/run_gate.py` is the
# separate gate for the Python reference implementation.
#
#   1  cancho fmt --check            src/ tests/unit/
#   2  cancho check                  the program (src/*.cho), refusal-free
#   3  cancho test                   every tests/unit/test_*.cho
#   4  no .cho or .py file over 2,000 lines
#   5  cancho build                  the chw binary
#   6  text form                     byte-identical JSON on the textual examples,
#                                    differential against the Python parser
#   7  chw conform                   the examples and every refusal fixture
#                                    (examples/refusal, tests/stage1, tests/stage2): every
#                                    sidecar entry decided by cancho, none deferred
#   8  the runner can fail           trees with a sidecar altered, a fixture mended and
#                                    a rule's subject changed must each exit 1
#   8b the checker against checker.py  --output json and the text form byte for byte on
#                                    every fixture, the rule catalog against the spec,
#                                    then the semantic mutants (about four minutes)
#  8c the C header generator        `chw generate --target c-header` against tools/generate/generate.py:
#                                    bytes on every fixture and mutant, headers compiled with cc
#  8d the device-tree generator     `chw generate --target devicetree` against tools/generate/generate.py:
#                                    bytes on every fixture and mutant, fragments compiled with dtc
#   9  JSON form                     differential against json + jsonschema,
#                                    then large and hostile inputs (never a trap or a hang)
#  10  cancho authority              what the program can reach, pinned in authority.expected
set -eu
cd "$(dirname "$0")/.."
CANCHO=${CANCHO:-../cancho/target/release/cancho}
OUT=${TMPDIR:-/tmp}/chw
LIB="src/lex.cho src/ir.cho src/parse.cho src/json_out.cho src/json_in.cho src/diag.cho src/pyrepr.cho src/pattern.cho src/schema.cho src/front.cho src/load.cho src/diagnostic.cho src/hexval.cho src/check_util.cho src/check_block.cho src/check_regs.cho src/check_intr.cho src/check_dma.cho src/check.cho src/dg_json.cho src/dg_text.cho src/dg_report.cho src/gen_c.cho src/gen_dts.cho"
PROGRAM="src/main.cho $LIB src/io.cho src/conform.cho"

echo "== 1 fmt"
"$CANCHO" fmt --check src tests/unit

echo "== 2 check"
"$CANCHO" check $PROGRAM --std

echo "== 3 test"
for t in tests/unit/test_*.cho; do
    echo "-- $t"
    "$CANCHO" test "$t" tests/unit/support.cho $LIB --std | tail -n 2
done

echo "== 4 file length"
long=$(find src tests scripts -name '*.cho' -o -name '*.py' -o -name '*.sh' | xargs wc -l | awk '$2 != "total" && $1 > 2000 {print $2 " " $1}')
if [ -n "$long" ]; then
    echo "over 2,000 lines: $long"
    exit 1
fi
wc -l src/*.cho | sort -n | tail -n 4

echo "== 5 build"
"$CANCHO" build $PROGRAM --std -o "$OUT"

echo "== 6 text form"
for f in examples/textual/uart.chw examples/textual/dma.chw; do
    python3 tools/parse/parser.py "$f" | cmp - "$("$OUT" parse "$f" >"$OUT.out"; echo "$OUT.out")" \
        && echo "identical JSON: $f"
done
python3 tests/differential/text_parse.py "$OUT"

echo "== 7 conform"
"$OUT" conform . --fixtures tests/stage1,tests/stage2

echo "== 8 the runner can fail"
# Each tree is a copy of the contract-facing files with ONE thing changed; the
# runner must refuse every one (exit 1). A runner that passed them would pass
# anything.
fails() {
    label=$1
    tree=$2
    if "$OUT" conform "$tree" >/dev/null; then
        echo "conform accepted: $label"
        exit 1
    fi
    echo "refused, as it must: $label"
    rm -r "$tree"
}
fresh() {
    tree=$(mktemp -d)
    mkdir -p "$tree/spec" "$tree/examples" "$tree/tests"
    cp -r spec/contract-schema "$tree/spec/"
    cp -r examples/. "$tree/examples/"
    echo "$tree"
}
tree=$(fresh)
sed 's/"schema-invalid"/"parse-error"/' examples/refusal/kind-unknown.expect.json >"$tree/examples/refusal/kind-unknown.expect.json"
fails "a sidecar that names the wrong structural code" "$tree"
tree=$(fresh)
sed 's/"code": "field-overlap"/"code": "dma-overlap"/' examples/refusal/field-overlap.expect.json >"$tree/examples/refusal/field-overlap.expect.json"
fails "a sidecar that names the wrong semantic code" "$tree"
tree=$(fresh)
sed 's/"name": "PARITY"/"name": "NOT_PARITY"/' examples/refusal/field-overlap.expect.json >"$tree/examples/refusal/field-overlap.expect.json"
fails "a sidecar whose subject names another field" "$tree"
tree=$(fresh)
sed 's/"name": "ENABLE",  "lsb": 0, "msb": 3/"name": "ENABLE",  "lsb": 0, "msb": 1/' examples/refusal/field-overlap.chw >"$tree/examples/refusal/field-overlap.chw"
cmp -s examples/refusal/field-overlap.chw "$tree/examples/refusal/field-overlap.chw" && { echo "the fixture mender changed nothing"; exit 1; }
fails "a fixture mended so that its overlap is gone" "$tree"
tree=$(fresh)
sed 's/overlap with ENABLE/overlap with SOMETHING_ELSE/' examples/refusal/field-overlap.expect.json >"$tree/examples/refusal/field-overlap.expect.json"
fails "a sidecar that expects another message" "$tree"
tree=$(fresh)
sed 's/"offset": "0x04"/"offset": "0x00"/' examples/uart-contract/uart.chw >"$tree/examples/uart-contract/uart.chw"
cmp -s examples/uart-contract/uart.chw "$tree/examples/uart-contract/uart.chw" && { echo "the example mender changed nothing"; exit 1; }
fails "a valid example made to share an offset" "$tree"
tree=$(fresh)
printf '{"file": "x", "expect": []}\n' >"$tree/examples/refusal/field-overlap.expect.json"
fails "a sidecar that expects nothing of a fixture that is refused" "$tree"

echo "== 8b checker.py"
python3 tests/differential/catalog.py "$OUT"
python3 tests/differential/check_json.py "$OUT"

echo "== 8c the C header generator against generate.py"
# Needs cc, the compile oracle (docs/cancho-port.md 17.5): two of its known-difference classes are admitted only because
# a header does or does not compile, so without one the step fails and does not pass quietly.
python3 tests/differential/generate_c.py "$OUT"

echo "== 8d the device-tree generator against generate.py"
# Needs dtc (device-tree-compiler), the compile oracle (docs/cancho-port.md 20.5); without one the step fails.
python3 tests/differential/generate_dts.py "$OUT"

echo "== 9 JSON form"
python3 tests/differential/json_validate.py "$OUT"

echo "== 9b large and hostile inputs"
python3 tests/differential/stress.py "$OUT"

echo "== 10 authority"
"$CANCHO" authority $PROGRAM --std | sed -n 1,13p >"$OUT.authority"
diff scripts/authority.expected "$OUT.authority"
cat "$OUT.authority"
