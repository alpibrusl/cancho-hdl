#!/bin/sh
# Build the one entry point of the product: `chw`, parse, validate, check, generate, diff, impact, report, conform.
#
#   sh scripts/build.sh [OUTPUT]        OUTPUT defaults to ./chw
#
# Needs the cancho compiler named in .cancho-rev (CANCHO, default ../cancho/target/release/cancho). Nothing else: the product
# is cancho and only cancho, and `cancho authority` of it is pinned by the gate (scripts/authority.expected).
set -eu
cd "$(dirname "$0")/.."
CANCHO=${CANCHO:-../cancho/target/release/cancho}
. scripts/sources.sh
"$CANCHO" build $PROGRAM --std -o "${1:-chw}"
