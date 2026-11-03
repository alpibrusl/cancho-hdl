#!/usr/bin/env python3
"""Arm the tap design's analyzer (DESIGN=tap, rtl/top_tap.v) for a few seconds and report what the tap pin did.

An unconnected pin (internal weak pull-up) must show exactly one entry: the idle level, high. A pin on a quiet servo bus must show the
same. Anything else is a toggling input: noise, a wrong wire, or traffic. With --dump, every (tick, level) is printed.

    python3 tests/hardware/tap_idle.py --port /dev/ttyUSB1 --seconds 3 [--baud 115200] [--dump]

Protocol (rtl/uart_axil_bridge.v): 'W' addr(4, big endian) data(4) -> 1 answer byte; 'R' addr(4) -> 1 answer byte, 4 data bytes.
Registers (lab/lab.chw): CTRL 0x00 (bit0 AN_EN, bit4 PROBE_SEL: 0 = the tap), AN_POP 0x04, AN_STATUS 0x08, AN_TS 0x0C, AN_VAL 0x10.
"""
import argparse, struct, sys, time
import serial

BASE = 0x40000000

def wr(s, off, d):
    s.write(b"W" + struct.pack(">II", BASE + off, d)); a = s.read(1)
    if len(a) != 1: sys.exit("no answer to a write: board not loaded, or wrong port/baud")
    return a[0]

def rd(s, off):
    s.write(b"R" + struct.pack(">I", BASE + off)); a = s.read(5)
    if len(a) != 5: sys.exit("no answer to a read: board not loaded, or wrong port/baud")
    return struct.unpack(">I", a[1:])[0]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyUSB1"); ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--seconds", type=float, default=3.0); ap.add_argument("--dump", action="store_true")
    a = ap.parse_args()
    s = serial.Serial(a.port, a.baud, timeout=1.0)
    wr(s, 0x00, 0)
    wr(s, 0x00, 1)                      # AN_EN 0 -> 1: clears the FIFO and records the level at this moment first
    time.sleep(a.seconds)
    wr(s, 0x00, 0)
    st = rd(s, 0x08); n = st & 0xFFFF; ovf = (st >> 16) & 1
    ents = []
    for k in range(n):
        ents.append((rd(s, 0x0C), rd(s, 0x10) & 1)); wr(s, 0x04, k + 1)
    print(f"entries: {n}  overflow: {ovf}  first level: {ents[0][1] if ents else 'none'}")
    if a.dump:
        for t, v in ents: print(f"  tick {t:>12}  level {v}")
    ok = n == 1 and ents[0][1] == 1 and not ovf
    print("IDLE-HIGH, no edges" if ok else "NOT a quiet idle-high pin")
    sys.exit(0 if ok else 1)

main()
