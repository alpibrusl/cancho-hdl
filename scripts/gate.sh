#!/bin/sh
# The gate of the repository: everything that must pass before anything is called done (docs/cancho-port.md, 36).
#
#   1  scripts/lint_python.sh        Python only under oracle/ and tests/, and the legacy line count only comes down
#   2  scripts/gate_cancho.sh        the product: format, check, tests, build, the conformance runner, the differentials against the
#                                    legacy reference implementation, the claims of its goldens held against the binary, authority
#   3  oracle/legacy/run_gate.py     the oracle's own self-checks (the legacy generators and the reference simulator)
#
# A failed part does not hide the others: each is run, each result is printed, and the exit status is 1 if any failed.
# Needs the cancho compiler of .cancho-rev (CANCHO, default ../cancho/target/release/cancho), python3 with jsonschema and
# lxml, cc, dtc and xmllint. On a machine with iverilog installed part 3 fails at the systemverilog roundtrip lane, in the legacy
# generator and the product alike (docs/cancho-port.md, 34 and 36.5); CI does not install it.
cd "$(dirname "$0")/.."
status=0
run() {
    label=$1
    shift
    echo "######## $label"
    if "$@"; then
        echo "######## $label: passed"
    else
        echo "######## $label: FAILED"
        status=1
    fi
}
run "python location and ceiling" sh scripts/lint_python.sh
run "the product" sh scripts/gate_cancho.sh
run "the oracle's self-checks" python3 oracle/legacy/run_gate.py
if [ "$status" -eq 0 ]; then
    echo "######## GATE PASSED"
else
    echo "######## GATE FAILED"
fi
exit "$status"
