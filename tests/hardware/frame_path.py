"""Frame path to the HDMI design (DESIGN=hdmi, 1 Mbaud): random 320x240 frames, written whole and in 512- and 4096-byte chunks, no pacing; the board answers 'H' for a header and 'F' for a stored frame. The last line reproduces the one thing that loses a frame: a pause of more than ~78 ms inside it.
Run on the board's host (the robot Pi, 2026-11-01); needs pyserial. The board is at /dev/ttyUSB1.
"""
import serial,time,random
W,H=320,240
random.seed(1)
s=serial.Serial("/dev/ttyUSB1",1000000,timeout=2,write_timeout=10)
def frame(): return bytes([0xA5,0x5A,0xC3,0x3C])+bytes(random.randrange(256) for _ in range(W*H))
res={}
for label,fn in (("one write of the whole frame",lambda f:s.write(f)),
                 ("512-byte chunks, no gap",lambda f:[s.write(f[o:o+512]) for o in range(0,len(f),512)]),
                 ("4096-byte chunks, no gap",lambda f:[s.write(f[o:o+4096]) for o in range(0,len(f),4096)])):
    ok=0;ts=[]
    for _ in range(20):
        f=frame(); s.reset_input_buffer(); t=time.perf_counter(); fn(f); s.flush(); a=s.read(2); ts.append(time.perf_counter()-t); ok+=(a==b"HF")
    print("%-30s %2d/20 ok  mean %.2fs  %.0f KB/s"%(label,ok,sum(ts)/20,W*H/ (sum(ts)/20)/1000),flush=True)
print("control: a 0.2 s pause after the header (my first test):",end=" ")
s.reset_input_buffer(); f=frame(); s.write(f[:4]); time.sleep(0.2); s.write(f[4:]); s.flush(); print(s.read(2))
