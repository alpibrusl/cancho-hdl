#!/bin/sh
# The gate for the cancho half of the repository (docs/cancho-port.md, 9.7).
# Needs the built cancho compiler (CANCHO, default ../cancho/target/release/cancho)
# and python3, which is used ONLY as the oracle: the legacy reference implementation under oracle/legacy and jsonschema, driven
# by tests/differential/ and tests/mutation/. `python3 oracle/legacy/run_gate.py` is the oracle's own gate (its self-checks).
# `scripts/gate.sh` runs both.
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
#  8c the C header generator        `chw generate --target c-header` against oracle/legacy/tools/generate/generate.py:
#                                    bytes on every fixture and mutant, headers compiled with cc
#  8d the device-tree generator     `chw generate --target devicetree` against oracle/legacy/tools/generate/generate.py:
#                                    bytes on every fixture and mutant, fragments compiled with dtc
#  8e the CMSIS-SVD generator       `chw generate --target svd` against oracle/legacy/tools/generate/generate.py:
#                                    bytes on every fixture and mutant, documents checked with xmllint
#  8f the cancho-binding generator  `chw generate --target cancho-binding` against oracle/legacy/tools/generate/generate.py:
#                                    bytes on every fixture and mutant (no compiler for the output: the Python bytes are the oracle)
#  8g the SystemVerilog generator   `chw generate --target systemverilog` against oracle/legacy/tools/generate/generate.py:
#                                    bytes on every fixture and mutant (no RTL tool on the runner: the Python bytes are the oracle)
#  8h the rule groups that ran      `chw check --ran` against `checker.check(ir, ran=...)`, the fixtures and the mutants
#  8i diff and impact               `chw diff` and `chw impact` against oracle/legacy/tools/diff/diff.py, bytes and exit status
#  8j the SystemVerilog output       both tools' modules through iverilog: the verdicts must agree (both refuse them, 34)
#  8k the evidence report           `chw report` against oracle/legacy/tools/report/report.py, bytes and exit status; `validate_report` against `--validate`
#  8l the claims of the Python goldens, held against the binary: the text form of `chw check`, `chw diff` and `chw impact` on the
#                                    seeded change, the textual parser's twin of the JSON form, and the C-side behavioral roundtrip (the
#                                    header `chw generate` writes, compiled with gcc and clang, run op for op against the reference model)
#   9  JSON form                     differential against json + jsonschema,
#                                    then large and hostile inputs (never a trap or a hang)
#  10  cancho authority              what the program can reach, pinned in authority.expected
set -eu
cd "$(dirname "$0")/.."
CANCHO=${CANCHO:-../cancho/target/release/cancho}
OUT=${TMPDIR:-/tmp}/chw
. scripts/sources.sh

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
    python3 oracle/legacy/tools/parse/parser.py "$f" | cmp - "$("$OUT" parse "$f" >"$OUT.out"; echo "$OUT.out")" \
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

echo "== 8e the CMSIS-SVD generator against generate.py"
# Needs xmllint (libxml2-utils), the well-formedness and schema oracle (docs/cancho-port.md 23.5); without one the step fails.
python3 tests/differential/generate_svd.py "$OUT"

echo "== 8f the cancho-binding generator against generate.py"
# No tool parses the output, so the Python tool's bytes are the only oracle (docs/cancho-port.md 26.1).
python3 tests/differential/generate_binding.py "$OUT"

echo "== 8g the SystemVerilog generator against generate.py"
# No RTL tool is installed, so the Python tool's bytes are the only oracle (docs/cancho-port.md 29.1).
python3 tests/differential/generate_sv.py "$OUT"

echo "== 8h the rule groups the checker ran against checker.py"
# `chw check --ran` against `checker.check(ir, ran=...)`: the fixtures, then the mutants of the checker's differential
# (docs/cancho-port.md, 32).
python3 tests/differential/check_ran.py "$OUT"

echo "== 8i diff and impact against diff.py"
# `chw diff` and `chw impact` against oracle/legacy/tools/diff/diff.py: bytes, standard error and exit status, on pairs of the fixtures
# and on every mutant of a seed against its seed (docs/cancho-port.md, 33).
python3 tests/differential/diff_cmp.py "$OUT"

echo "== 8j SystemVerilog output read by a parser (iverilog)"
# Both tools' modules through `iverilog -g2012 -tnull`: today it refuses every one, in both, for the same two reasons
# (docs/cancho-port.md, 34); the step fails only if the two tools disagree, and does nothing if iverilog is not installed
# (CI does not install it, 34.3: the Python reference gate's own roundtrip lane then fails).
python3 tests/differential/sv_parse.py "$OUT"

echo "== 8k the evidence report against report.py"
# `chw report` against oracle/legacy/tools/report/report.py: bytes, standard error and exit status on every fixture and on every third
# mutant of the checker's differential, with the roundtrip lanes stubbed on the Python side and read from a file on the
# cancho side (the product runs no tool), and `validate_report` against `chw report --validate` on corrupted copies of
# five reports (docs/cancho-port.md, 35).
python3 tests/report/report_cancho_golden.py "$OUT"
python3 tests/differential/report_cmp.py "$OUT" --real-lanes --stride 3

echo "== 8l the claims of the Python goldens, held against the binary"
python3 tests/text_format/golden_cancho.py "$OUT"
python3 tests/diff/diff_cancho_golden.py "$OUT"
python3 tests/parser/parser_cancho_roundtrip.py "$OUT"
python3 tests/behavioral/c_behavior.py "$OUT"

echo "== 9 JSON form"
python3 tests/differential/json_validate.py "$OUT"

echo "== 9b large and hostile inputs"
python3 tests/differential/stress.py "$OUT"

echo "== 10 authority"
"$CANCHO" authority $PROGRAM --std | sed -n 1,13p >"$OUT.authority"
diff scripts/authority.expected "$OUT.authority"
cat "$OUT.authority"
