exec(open('t.py').read().split('for p in')[0])
import sys
win=int(sys.argv[1])
fd=op("/dev/ttyUSB1"); termios.tcflush(fd,termios.TCIFLUSH)
n=3000; data=bytes((i*7+i//100)%256 for i in range(n))
os.write(fd,bytes([73,100,30,0,0]))
got=b''; sent=0; t0=time.time()
while len(got)<n and time.time()-t0<15:
    room=win-(sent-len(got))
    if sent<n and room>0:
        sent+=os.write(fd,data[sent:sent+min(room,n-sent)])
    got+=rd(fd,4096,0.002)
dt=time.time()-t0
print("window",win,"got",len(got),"bad",sum(1 for i in range(len(got)) if got[i]!=data[i]),"%.2fs"%dt,"%.0f B/s"%(len(got)/dt))
