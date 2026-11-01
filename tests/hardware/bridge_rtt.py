"""Round trip of a register write through the USB serial bridge, and pipelined writes (design DESIGN=deadman, 115200 baud).
Run on the board's host (the robot Pi, 2026-11-01); needs pyserial. The board is at /dev/ttyUSB1.
"""
import serial,time,statistics as st
s=serial.Serial("/dev/ttyUSB1",115200,timeout=1,write_timeout=2)
CTRL,TOUT,KICK=0x40000000,0x40000004,0x40000008
def pk(a,d): return b"W"+a.to_bytes(4,"big")+d.to_bytes(4,"big")
s.reset_input_buffer()
s.write(pk(CTRL,0)); s.read(1); s.write(pk(TOUT,1000)); s.read(1); s.write(pk(CTRL,1)); s.read(1)
r=[]
for i in range(200):
    t=time.perf_counter(); s.write(pk(KICK,i+1)); a=s.read(1); r.append((time.perf_counter()-t)*1000)
r.sort(); print("single kick RTT ms: min %.1f median %.1f p95 %.1f max %.1f"%(r[0],r[100],r[190],r[-1]))
# a status-size read for comparison and a 1-byte-answer for the smallest case
for N in (1,4,8,16,32):
    t=time.perf_counter()
    for i in range(N): s.write(pk(KICK,1000+i))
    got=s.read(N); dt=(time.perf_counter()-t)*1000
    print("pipelined %2d kicks: %d acks in %.1f ms (%.1f ms per kick)"%(N,len(got),dt,dt/N))
s.write(pk(CTRL,0)); s.read(1)
