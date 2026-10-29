#!/bin/sh
# The gate lane of the Tang Nano 20K design: the generated register block and the hand-written UART bridge, simulated with iverilog
# against the bench in tb/ (the bridge's protocol, the LED pins, SLVERR), and synthesised for the Gowin GW2A-18C with Yosys if it is
# installed (no warning allowed). It does not place, route, pack or flash: those need nextpnr-himbaechel and the board (build.sh).
#
#   sh boards/tang-nano-20k/check.sh /path/to/chw
set -eu
cd "$(dirname "$0")/../.."   # the repository root: chw finds its schema from here
B=boards/tang-nano-20k
CHW=${1:?usage: check.sh /path/to/chw}
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
"$CHW" check $B/leds.chw
"$CHW" generate $B/leds.chw --target systemverilog >"$T/leds.sv"
if ! command -v iverilog >/dev/null 2>&1; then echo "iverilog not found: the bench did not run"; exit 2; fi
iverilog -g2012 -o "$T/tb.vvp" $B/tb/top_tb.v $B/rtl/uart_axil_bridge.v $B/rtl/uart_rx.v $B/rtl/uart_tx.v $B/rtl/top.v "$T/leds.sv"
vvp "$T/tb.vvp" | tee "$T/tb.out"
grep -q '^RESULT: [1-9][0-9]* passed, 0 failed$' "$T/tb.out"
"$CHW" generate $B/lab/lab.chw --target systemverilog >"$T/lab_axi.sv"
iverilog -g2012 -o "$T/lab.vvp" $B/tb/lab_tb.v $B/rtl/lab.v $B/rtl/top_lab.v $B/rtl/uart_axil_bridge.v $B/rtl/uart_rx.v $B/rtl/uart_tx.v "$T/lab_axi.sv"
vvp "$T/lab.vvp" | tee "$T/lab.out"
grep -q '^RESULT: [1-9][0-9]* passed, 0 failed$' "$T/lab.out"
"$CHW" generate $B/stats/stats.chw --target systemverilog >"$T/stats_axi.sv"
iverilog -g2012 -o "$T/stats.vvp" $B/tb/stats_tb.v $B/rtl/stats.v $B/rtl/top_stats.v $B/rtl/uart_axil_bridge.v $B/rtl/uart_rx.v $B/rtl/uart_tx.v "$T/stats_axi.sv"
vvp "$T/stats.vvp" | tee "$T/stats.out"
grep -q '^RESULT: [1-9][0-9]* passed, 0 failed$' "$T/stats.out"
"$CHW" generate $B/gemv/gemv.chw --target systemverilog >"$T/gemv_axi.sv"
iverilog -g2012 -o "$T/gemv.vvp" $B/tb/gemv_tb.v $B/rtl/gemv.v $B/rtl/top_gemv.v $B/rtl/uart_axil_bridge.v $B/rtl/uart_rx.v $B/rtl/uart_tx.v "$T/gemv_axi.sv"
vvp "$T/gemv.vvp" | tee "$T/gemv.out"
grep -q '^RESULT: [1-9][0-9]* passed, 0 failed$' "$T/gemv.out"
if command -v yosys >/dev/null 2>&1; then
    yosys -q -l "$T/yosys.log" -p "read_verilog -sv $B/rtl/top.v $B/rtl/uart_axil_bridge.v $B/rtl/uart_rx.v $B/rtl/uart_tx.v $T/leds.sv; synth_gowin -top top -json $T/top.json"
    if grep -q '^Warning' "$T/yosys.log"; then grep '^Warning' "$T/yosys.log"; exit 1; fi
    echo "yosys synth_gowin: no warning"
else
    echo "yosys not found: not synthesised"
fi
