#!/bin/sh
# Where Python may be (docs/cancho-port.md, 5 and 36): the rules that keep "Python is only an oracle" from creeping.
#
#   1  location   a *.py file may exist only under oracle/ (the legacy reference implementation and its gate) and tests/
#                 (the differential drivers, mutation harnesses and goldens, which are test code). Nowhere else: not in src/,
#                 not in scripts/, not at the root.
#   2  ceiling    the Python of oracle/legacy has a committed line count (oracle/legacy/CEILING) that only comes down. A new
#                 line of legacy Python raises it and is refused; lowering it is part of the commit that deletes lines.
set -eu
cd "$(dirname "$0")/.."
bad=$(git ls-files '*.py' | grep -v '^oracle/' | grep -v '^tests/' || true)
if [ -n "$bad" ]; then
    echo "Python outside oracle/ and tests/:"
    echo "$bad"
    exit 1
fi
have=$(git ls-files 'oracle/legacy/*.py' | xargs cat | wc -l | tr -d ' ')
ceiling=$(tr -d '[:space:]' < oracle/legacy/CEILING)
echo "oracle/legacy: $have lines of Python, ceiling $ceiling"
if [ "$have" -gt "$ceiling" ]; then
    echo "over the ceiling: the legacy Python only shrinks"
    exit 1
fi
if [ "$have" -lt "$ceiling" ]; then
    echo "under the ceiling: lower oracle/legacy/CEILING to $have in this commit"
    exit 1
fi
