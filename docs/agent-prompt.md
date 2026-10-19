Install cancho-hdl and check it on this machine. Work in a new empty directory, keep every path free of spaces, and never use sudo. Run steps 2 to 5 in one shell session. Report honestly; do not retry a failing command in a loop and do not edit the repository to make a command pass.

1. Check that `git`, `cargo` (Rust, via rustup), a C compiler (`cc`), `clang`, `gcc`, `python3` with `pip`, and `sh` exist. If one is missing, stop and tell me which; do not install system packages on your own.

2. Get the two repositories side by side, both cloned into the new empty directory (call it the parent):
   git clone https://github.com/alpibrusl/cancho-hdl.git
   git clone https://github.com/alpibrusl/cancho.git
   git -C cancho checkout "$(cat cancho-hdl/.cancho-rev)"

3. Build the compiler (a few minutes) and point at it. Install the Python oracle's two packages at the pinned version (Python is only the test oracle, not part of the product):
   (cd cancho && cargo build --release -p cancho)
   export CANCHO="$PWD/cancho/target/release/cancho"
   pip install jsonschema==4.26.0 lxml

4. Prove the install works. This needs no network, no key and no model. It takes about five minutes:
   cd cancho-hdl
   sh scripts/gate_cancho.sh ; echo "exit $?"     # must print exit 0 (the script prints no final PASS line)
   python3 scripts/run_gate.py                     # must end with: GATE PASSED

5. Use the cancho tool `chw` on the examples (the gate built it at /tmp/chw):
   /tmp/chw validate examples/uart-contract/uart.chw ; echo "exit $?"            # expect exit 0
   /tmp/chw validate examples/refusal/bus-width-invalid.chw ; echo "exit $?"     # expect schema-invalid at a line:column, exit 1
   /tmp/chw parse examples/refusal/parse-error.chw ; echo "exit $?"              # expect parse-error at 2:26, exit 1
   /tmp/chw conform .                                                            # the refusal fixtures, a table
   python3 tools/diff/diff.py impact examples/uart-contract/uart.chw tests/diff/fixtures/uart_rebase.chw --pretty
   The last command is the Python reference implementation (being replaced). It lists which generated artifacts a register-map change makes stale.

6. Tell me, briefly:
   - whether the gate exited 0 and whether `run_gate.py` ended with GATE PASSED;
   - the first line each command printed in step 5, with its exit code, and the last line of `chw conform`;
   - which targets `impact` marked stale;
   - anything that failed, with the exact error.
Not claimed: that generated hardware works, timing, or a SystemVerilog behavioural check. Docs: README.md, docs/cancho-port.md (what is ported and what is still Python), docs/guarantees.md.
