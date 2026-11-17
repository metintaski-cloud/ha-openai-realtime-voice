import numpy as np, wave
SR=44100; DUR=15.04; N=int(SR*DUR); rng=np.random.default_rng(7)
out=np.zeros((N,2))
def add(sig,t,pan=0.0,g=1.0):
    i=int(t*SR); j=min(N,i+len(sig)); s=sig[:j-i]*g
    out[i:j,0]+=s*np.sqrt(0.5*(1-pan)); out[i:j,1]+=s*np.sqrt(0.5*(1+pan))
def ks(freq,dur,bright=0.5):  # plucked string (oud like)
    n=int(SR*dur); p=int(SR/freq); buf=rng.uniform(-1,1,p); y=np.zeros(n)
    for k in range(n):
        y[k]=buf[k%p]; buf[k%p]=0.996*(bright*buf[k%p]+(1-bright)*buf[(k+1)%p])
    env=np.minimum(1,np.arange(n)/40); return y*env
def drum(kind):
    n=int(SR*0.35); t=np.arange(n)/SR
    if kind=='D':  # doum: low pitched membrane
        f=95*np.exp(-t*6)+60; s=np.sin(2*np.pi*np.cumsum(f)/SR)*np.exp(-t*9)
    else:  # tek: bright slap
        s=(rng.uniform(-1,1,n)*np.exp(-t*45)+0.5*np.sin(2*np.pi*620*t)*np.exp(-t*30))
    return s
bpm=104; beat=60/bpm
# maqsum: D T . T D . T .   (8 eighths)
pat=['D','T',None,'T','D',None,'T',None]
t=0.0
while t<DUR-0.3:
    for k,x in enumerate(pat):
        tt=t+k*beat/2
        if x and tt<DUR-0.3: add(drum(x),tt,pan=-0.2 if x=='D' else 0.25,g=0.55 if x=='D' else 0.32)
    # small riq like shimmer on offbeats
    for k in range(8):
        tt=t+k*beat/2+beat/4
        if tt<DUR-0.3:
            n=int(SR*0.06); add(rng.uniform(-1,1,n)*np.exp(-np.arange(n)/SR*70),tt,pan=0.5,g=0.06)
    t+=4*beat
# drone on D
tt=np.arange(N)/SR; d=146.83
dr=(np.sin(2*np.pi*d/2*tt)+0.4*np.sin(2*np.pi*d*tt)+0.15*np.sin(2*np.pi*d*1.5*tt))*0.07*(1+0.1*np.sin(2*np.pi*0.2*tt))
out[:,0]+=dr; out[:,1]+=dr
# Hijaz on D: D Eb F# G A Bb C D
sc=[293.66,311.13,369.99,392.0,440.0,466.16,523.25,587.33]
mel=[(0,1),(1,.5),(2,.5),(3,1),(2,.5),(1,.5),(0,2),
     (4,1),(5,.5),(4,.5),(3,1),(2,.5),(3,.5),(4,2),
     (5,.5),(6,.5),(7,1),(6,.5),(5,.5),(4,1),(3,.5),(2,.5),(1,1),(0,2),
     (2,.5),(3,.5),(4,1),(3,.5),(2,.5),(1,1),(0,3)]
t=1.0
for deg,b in mel:
    dur=b*beat
    if t>DUR-1.5: break
    f=sc[deg]; add(ks(f,min(dur*1.6,1.4)),t,pan=0.1,g=0.35)
    if b>=1: add(ks(f,0.3),t+dur*0.5,pan=0.1,g=0.18)  # tremolo pluck
    t+=dur
# simple reverb
ir=np.zeros(int(SR*1.2)); 
for k in range(40): ir[int(rng.uniform(0.02,1.1)*SR)]+=rng.uniform(0.2,1)*np.exp(-k/12)
for c in range(2):
    wet=np.convolve(out[:,c],ir)[:N]; out[:,c]=out[:,c]+0.12*wet
# fades
fi=int(SR*0.4); fo=int(SR*1.5); out[:fi]*=np.linspace(0,1,fi)[:,None]; out[-fo:]*=np.linspace(1,0,fo)[:,None]
out/=np.max(np.abs(out))*1.12
w=wave.open('oriental.wav','wb'); w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes((out*32767).astype('<i2').tobytes()); w.close()
