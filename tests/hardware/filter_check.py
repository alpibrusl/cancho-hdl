"""As filter_check_camera.py, plus the frames that actually exercise the arithmetic: random noise, a structured image, a 0/255 checkerboard (a flat dark camera frame proves little: Sobel is all zero).
Run on the board's host (the robot Pi, 2026-11-01); needs pyserial. The board is at /dev/ttyUSB1.
"""
import json, random, subprocess
exec(open("/tmp/filtertest.py").read().split("res=[]")[0])
random.seed(20261101)
noise=bytes(random.randrange(256) for _ in range(W*H))
def synth(x,y):
    dx,dy=x-50,y-60
    if dx*dx+dy*dy<35*35: return 220
    if 100<=x<145 and 20<=y<90: return 35
    if (x//10+y//10)%2==0 and y>95: return 200
    return 40+x+y//2
structured=bytes(synth(x,y) for y in range(H) for x in range(W))
extremes=bytes((255 if (x+y)%2 else 0) for y in range(H) for x in range(W))   # checkerboard 0/255: the largest Sobel sums
sources={"noise":noise,"structured":structured,"checker 0/255":extremes}
for c in "024":
    f=open("/tmp/frame_%s.raw"%c,"rb").read(); sources["camera %s (mean %.0f, %d distinct)"%(c,sum(f)/len(f),len(set(f)))]=f
tot=0
for name,img in sources.items():
    row=[]
    for mode,mn in MODES.items():
        got,dt,rc=board(img,mode); want=ref(img,mode)
        bad=sum(1 for i in range(W*H) if i>=len(got) or got[i]!=want[i]); tot+=bad
        row.append("%s:%s"%(mn,"ok" if bad==0 else "%d BAD"%bad))
        if name=="noise": open("/tmp/nz_%d.raw"%mode,"wb").write(got)
    print("%-38s %s"%(name," ".join(row)),flush=True)
print("TOTAL mismatching pixels:",tot)
