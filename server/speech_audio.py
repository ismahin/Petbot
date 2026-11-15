"""Remove only very quiet edge padding, retaining phoneme guards and pauses."""
import numpy as np

def trim_padding(wave,rate=24000):
    wave=np.asarray(wave,dtype=np.float32).reshape(-1)
    if len(wave)<rate//4:return wave
    frame=rate//100 # 10 ms windows; never remove silence inside a sentence.
    blocks=len(wave)//frame
    rms=np.sqrt(np.mean(wave[:blocks*frame].reshape(blocks,frame)**2,axis=1))
    active=np.flatnonzero(rms>0.0002) # About -74 dBFS, well below normal speech.
    if not len(active):return wave
    start=min(max(0,(int(active[0])-5)*frame),int(rate*.6))
    finish=max(min(len(wave),(int(active[-1])+1+8)*frame),len(wave)-int(rate*.35))
    if start==0 and finish==len(wave):return wave
    result=wave[start:finish].copy()
    fade=min(rate//200,len(result)//2)
    if start:result[:fade]*=np.linspace(0,1,fade,dtype=np.float32)
    if finish<len(wave):result[-fade:]*=np.linspace(1,0,fade,dtype=np.float32)
    return result
