#!/bin/sh
# Reproduce every number in docs/cancho-port.md "Spike". Needs the built cancho
# compiler (CANCHO, default ../cancho/target/release/cancho) and python3, which
# is used ONLY as the oracle (the legacy parser and diff_oracle.py).
set -eu
cd "$(dirname "$0")/.."
CANCHO=${CANCHO:-../cancho/target/release/cancho}
LIB="spike/lex.cho spike/ir.cho spike/parse.cho spike/json.cho spike/front.cho"
OUT=${TMPDIR:-/tmp}/chwparse

"$CANCHO" fmt --check spike/
"$CANCHO" check spike/chwparse.cho $LIB spike/io.cho --std
"$CANCHO" test spike/test_chw.cho $LIB --std
"$CANCHO" build spike/chwparse.cho $LIB spike/io.cho --std -o "$OUT"
for f in examples/textual/uart.chw examples/textual/dma.chw; do
    python3 tools/parse/parser.py "$f" | cmp - "$("$OUT" "$f" >"$OUT.out"; echo "$OUT.out")" \
        && echo "identical JSON: $f"
done
python3 spike/diff_oracle.py "$OUT"
"$CANCHO" authority spike/chwparse.cho $LIB spike/io.cho --std | sed -n 1,12p
