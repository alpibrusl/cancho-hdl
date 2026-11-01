"""Deadman kick-rate sweep (design DESIGN=deadman, 115200 baud): kick at 100 Hz for 20 s per timeout, count false trips and the largest gap between acknowledgements. 'python3 dmsweep.py idle|load' (load: 4 busy processes and 3 cameras streaming 1080p MJPG).
Run on the board's host (the robot Pi, 2026-11-01); needs pyserial. The board is at /dev/ttyUSB1.
"""
import serial, time, sys, json, subprocess, os, signal
PORT="/dev/ttyUSB1"; BAUD=115200
CTRL,TOUT,KICK,STAT=0x40000000,0x40000004,0x40000008,0x4000000C
s=serial.Serial(PORT,BAUD,timeout=0.5,write_timeout=2)
def wr(addr,data):
    s.write(b"W"+addr.to_bytes(4,"big")+data.to_bytes(4,"big"))
    a=s.read(1)
    return a[0] if a else -1
def status():
    s.write(b"R"+STAT.to_bytes(4,"big")); a=s.read(5)
    return a[4] if len(a)==5 else -1
def run(timeout_ms, secs, period_ms=10.0):
    s.reset_input_buffer()
    wr(CTRL,0); wr(TOUT,timeout_ms); wr(CTRL,1)
    seq=0; gaps=[]; trips=0; polls=0; last=None; end=time.perf_counter()+secs
    nxt=time.perf_counter(); lost=0
    while time.perf_counter()<end:
        seq=(seq+1)&0xFFFF or 1
        a=wr(KICK,seq)
        t=time.perf_counter()
        if a!=0: lost+=1
        if last is not None: gaps.append((t-last)*1000)
        last=t
        if seq%25==0:
            polls+=1
            if status()==2:
                trips+=1; wr(CTRL,0); wr(CTRL,1); last=None
        nxt+=period_ms/1000
        d=nxt-time.perf_counter()
        if d>0: time.sleep(d)
        else: nxt=time.perf_counter()
    wr(CTRL,0)
    gaps.sort(); n=len(gaps)
    return dict(timeout_ms=timeout_ms,kicks=n,trips=trips,lost_acks=lost,gap_median=round(gaps[n//2],1),gap_p99=round(gaps[int(n*.99)],1),gap_max=round(max(gaps),1),over_timeout=sum(1 for g in gaps if g>=timeout_ms))
load=sys.argv[1]=="load"
procs=[]
if load:
    for _ in range(4): procs.append(subprocess.Popen(["python3","-c","while True: pass"]))
    for n in (0,2,4):
        procs.append(subprocess.Popen(["v4l2-ctl","-d","/dev/video%d"%n,"--set-fmt-video=width=1920,height=1080,pixelformat=MJPG","--stream-mmap","--stream-count=100000","--stream-to=/dev/null"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
    time.sleep(3)
for T in (10,15,20,30,50,100):
    r=run(T,20); r["load"]=load; print(json.dumps(r),flush=True)
for p in procs: p.kill()
