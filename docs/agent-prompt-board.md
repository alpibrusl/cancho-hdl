Check cancho-hdl on a Tang Nano 20K attached to this machine. Work in a new empty directory, keep every path free of spaces. Do not use sudo: if loading the bitstream needs it, stop and tell me the exact command. Report honestly; do not retry a failing command in a loop and do not edit the repository to make a command pass.

1. Check that `git`, `yosys`, `nextpnr-himbaechel`, `gowin_pack`, `openFPGALoader` and `iverilog` are on PATH (the YosysHQ OSS CAD Suite has all of them) and that `lsusb` lists `0403:6010`. If one is missing, stop and tell me which; do not install system packages on your own.

2. Clone the repositories side by side and use the branch that has the board work:
   git clone https://github.com/alpibrusl/cancho-hdl.git
   git clone https://github.com/alpibrusl/cancho.git
   Build the cancho compiler as cancho/README says, and build `chw` with `sh scripts/build.sh chw`.

3. Prove the designs in simulation first (no board needed): `sh boards/tang-nano-20k/check.sh`. Every line ending in `RESULT:` must say `0 failed`, and Yosys must print no warning.

4. Build and load one design, for example the table query, then run its host test written in cancho (loading is the step that needs raw USB access, so ask me before running it):
   DESIGN=table CHW=./chw sh boards/tang-nano-20k/build.sh boards/tang-nano-20k/build-table --flash
   cd boards/tang-nano-20k/host && cancho run labio.cho table_test.cho --std

5. Tell me, briefly: the last line of `check.sh`; for the board test, the lines `figures different ... : N` (want 0); anything that failed, with the exact error.
Not claimed: any speed advantage, that a servo moved, or timing against an outside reference. Docs: docs/fpga-experiments.md, docs/tang-nano-20k.md.
