#!/bin/sh
# Build the Tang Nano 20K design with the open-source flow, as far as the tools on this machine go, and say which step ran.
#
#   CHW=./chw sh boards/tang-nano-20k/build.sh [OUTDIR] [--flash]      (from the repository root; OUTDIR defaults to boards/tang-nano-20k/build)
#   DESIGN=stats CHW=./chw sh boards/tang-nano-20k/build.sh boards/tang-nano-20k/build-stats [--flash]
#       DESIGN is leds (the default), lab, stats, gemv, table, deadman, img or mem; img and mem have no contract (hand-written, no register block).
#
#   1  chw check, chw generate --target systemverilog   the register block, from leds.chw           (needs $CHW)
#   2  yosys synth_gowin                                 the netlist                                 (needs yosys)
#   3  nextpnr-himbaechel (gowin uarch)                  place and route for GW2AR-LV18QN88C8/I7   (needs nextpnr-himbaechel + apycula)
#   4  gowin_pack                                        the bitstream top.fs                       (needs apycula)
#   5  openFPGALoader -b tangnano20k                     load the bitstream, with --flash           (needs the board on this machine)
#
# A step whose tool is missing is reported as skipped and the script exits 2: a build that stopped early is not a build.
set -eu
cd "$(dirname "$0")/../.."   # the repository root: chw finds its schema from here
B=boards/tang-nano-20k
CHW=${CHW:-./chw}
OUT=${1:-$B/build}
FLASH=no
[ "${2:-}" = "--flash" ] && FLASH=yes
mkdir -p "$OUT"
have() { command -v "$1" >/dev/null 2>&1; }
skipped=0
step() { printf '== %s\n' "$1"; }

DESIGN=${DESIGN:-leds}
case $DESIGN in
    leds)    CONTRACT=$B/leds.chw;          RTL="$B/rtl/top.v" ;;
    lab)     CONTRACT=$B/lab/lab.chw;       RTL="$B/rtl/top_lab.v $B/rtl/lab.v" ;;
    stats)   CONTRACT=$B/stats/stats.chw;   RTL="$B/rtl/top_stats.v $B/rtl/stats.v" ;;
    gemv)    CONTRACT=$B/gemv/gemv.chw;     RTL="$B/rtl/top_gemv.v $B/rtl/gemv.v" ;;
    table)   CONTRACT=$B/table/table.chw;   RTL="$B/rtl/top_table.v $B/rtl/table_agg.v" ;;
    deadman) CONTRACT=$B/deadman.chw;       RTL="$B/rtl/top_deadman.v $B/rtl/deadman.v" ;;
    img)     CONTRACT=;                     RTL="$B/rtl/top_img.v $B/rtl/img_stream.v" ;;
    mem)     CONTRACT=;                     RTL="$B/rtl/top_mem.v $B/rtl/mem_test.v" ;;
    *) echo "unknown DESIGN=$DESIGN"; exit 1 ;;
esac
GEN=
step "1 generate the register block"
if [ -n "$CONTRACT" ]; then
    "$CHW" check "$CONTRACT"
    "$CHW" generate "$CONTRACT" --target systemverilog >"$OUT/leds.sv"
    GEN="$OUT/leds.sv"
else echo "no contract for this design"; fi

step "2 yosys synth_gowin"
if have yosys; then
    yosys -q -l "$OUT/yosys.log" -p "read_verilog -sv $RTL $B/rtl/uart_axil_bridge.v $B/rtl/uart_rx.v $B/rtl/uart_tx.v $GEN; synth_gowin -top top -json $OUT/top.json"
    if grep -q '^Warning' "$OUT/yosys.log"; then echo "yosys warned:"; grep '^Warning' "$OUT/yosys.log"; exit 1; fi
else echo "skipped: yosys not found"; skipped=1; fi

step "3 nextpnr-himbaechel"
if have nextpnr-himbaechel && [ -f "$OUT/top.json" ]; then
    nextpnr-himbaechel --json "$OUT/top.json" --write "$OUT/top_pnr.json" --device GW2AR-LV18QN88C8/I7 \
        --vopt family=GW2A-18C --vopt cst=$B/tang_nano_20k.cst --freq 27
else echo "skipped: nextpnr-himbaechel not found (or no netlist)"; skipped=1; fi

step "4 gowin_pack"
if have gowin_pack && [ -f "$OUT/top_pnr.json" ]; then
    gowin_pack -d GW2A-18C -o "$OUT/top.fs" "$OUT/top_pnr.json"
else echo "skipped: gowin_pack not found (or no placed design)"; skipped=1; fi

step "5 openFPGALoader"
if [ "$FLASH" = yes ]; then
    if have openFPGALoader && [ -f "$OUT/top.fs" ]; then openFPGALoader -b tangnano20k "$OUT/top.fs"
    else echo "skipped: openFPGALoader not found (or no bitstream)"; skipped=1; fi
else echo "not asked (pass --flash with the board connected)"; fi

[ "$skipped" = 0 ] || { echo "build stopped early: a tool is missing"; exit 2; }
echo "build complete: $OUT/top.fs"
