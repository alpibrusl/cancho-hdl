"""Image filter on the board (DESIGN=img, 115200 baud, host program host/camfilter.cho built as /tmp/camfilter) against an independent Python implementation of the definition in rtl/img_stream.v. Needs /tmp/ch_auto (examples/camera_hello.cho of cancho) for the camera frames. First version: camera frames only.
Run on the board's host (the robot Pi, 2026-11-01); needs pyserial. The board is at /dev/ttyUSB1.
"""
import subprocess, sys, time, json
W,H=160,120
MODES={0:"pass",1:"invert",2:"threshold",3:"sobel",4:"box blur"}
def grab(dev):
    p=subprocess.run(["/tmp/ch_auto"],input=(dev+"\n").encode(),capture_output=True,timeout=60)
    d=p.stdout
    assert d.startswith(b"P5\n320 240\n255\n"), d[:20]
    px=d[15:]; assert len(px)==76800
    out=bytearray(W*H)
    for y in range(H):
        for x in range(W):
            a=px[(2*y)*320+2*x]+px[(2*y)*320+2*x+1]+px[(2*y+1)*320+2*x]+px[(2*y+1)*320+2*x+1]
            out[y*W+x]=a//4
    return bytes(out)
def ref(img,mode,thr=100):
    out=bytearray(W*H)
    for y in range(H):
        for x in range(W):
            p=img[y*W+x]
            if mode==0: v=p
            elif mode==1: v=255-p
            elif mode==2: v=255 if p>=thr else 0
            elif x<2 or y<2: v=0
            else:
                g=lambda dx,dy: img[(y+dy)*W+(x+dx)]
                if mode==3:
                    gx=(g(0,-2)+2*g(0,-1)+g(0,0))-(g(-2,-2)+2*g(-2,-1)+g(-2,0))
                    gy=(g(-2,0)+2*g(-1,0)+g(0,0))-(g(-2,-2)+2*g(-1,-2)+g(0,-2))
                    v=min(255,abs(gx)+abs(gy))
                else:
                    s=sum(g(dx,dy) for dx in (-2,-1,0) for dy in (-2,-1,0))
                    v=(s*57)>>9
            out[y*W+x]=v
    return bytes(out)
def board(img,mode):
    t=time.time()
    p=subprocess.run(["/tmp/camfilter"],input=bytes([mode,W,H])+img,capture_output=True,timeout=120)
    return p.stdout, time.time()-t, p.returncode
res=[]
for dev in ("/dev/video0","/dev/video2","/dev/video4"):
    img=grab(dev)
    open("/tmp/frame_%s.raw"%dev[-1],"wb").write(img)
    for mode,name in MODES.items():
        got,dt,rc=board(img,mode); want=ref(img,mode)
        bad=[i for i in range(W*H) if i>=len(got) or got[i]!=want[i]]
        r=dict(cam=dev,mode=name,bytes=len(got),mismatch=len(bad),first=(bad[0] if bad else None),secs=round(dt,1),rc=rc)
        print(json.dumps(r),flush=True); res.append(r)
        open("/tmp/out_%s_%d.raw"%(dev[-1],mode),"wb").write(got)
print("TOTAL",sum(r["mismatch"] for r in res),"mismatching pixels over",len(res),"runs")
