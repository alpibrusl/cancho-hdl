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
#                                    (examples/refusal, tests/stage1)
#   8  the runner can fail           a tree with one sidecar altered must exit 1
#   9  JSON form                     differential against json + jsonschema,
#                                    then large and hostile inputs (never a trap or a hang)
#  10  cancho authority              what the program can reach, pinned in authority.expected
set -eu
cd "$(dirname "$0")/.."
CANCHO=${CANCHO:-../cancho/target/release/cancho}
OUT=${TMPDIR:-/tmp}/chw
LIB="src/lex.cho src/ir.cho src/parse.cho src/json_out.cho src/json_in.cho src/diag.cho src/pyrepr.cho src/pattern.cho src/schema.cho src/front.cho src/load.cho"
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
"$OUT" conform . --fixtures tests/stage1

echo "== 8 the runner can fail"
tree=$(mktemp -d)
mkdir -p "$tree/spec" "$tree/examples" "$tree/tests"
cp -r spec/contract-schema "$tree/spec/"
cp -r examples/. "$tree/examples/"
sed 's/"schema-invalid"/"parse-error"/' examples/refusal/kind-unknown.expect.json >"$tree/examples/refusal/kind-unknown.expect.json"
if "$OUT" conform "$tree" >/dev/null; then
    echo "conform accepted a sidecar that names the wrong code"
    exit 1
fi
echo "refused, as it must"
rm -r "$tree"

echo "== 9 JSON form"
python3 tests/differential/json_validate.py "$OUT"

echo "== 9b large and hostile inputs"
python3 tests/differential/stress.py "$OUT"

echo "== 10 authority"
"$CANCHO" authority $PROGRAM --std | sed -n 1,13p >"$OUT.authority"
diff scripts/authority.expected "$OUT.authority"
cat "$OUT.authority"
