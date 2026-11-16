"""Bounded level correction and observable microphone quality, at 16 kHz."""
import math


def prepare(samples):
    import numpy as np
    raw=np.asarray(samples,dtype=np.float32).reshape(-1)
    if not len(raw) or not np.isfinite(raw).all():
        raise ValueError('Invalid microphone samples')
    dc=float(np.mean(raw,dtype=np.float64))
    audio=raw-dc
    rms=float(np.sqrt(np.mean(audio.astype(np.float64)**2)))
    peak=float(np.max(np.abs(audio)))
    gain=min(6.,max(1.,.06/max(rms,1e-8)),.95/max(peak,1e-8)) if rms>.0005 else 1.
    output=np.clip(audio*gain,-.98,.98)
    metrics={'seconds':round(len(raw)/16000,2),'rms_dbfs':round(20*math.log10(max(rms,1e-8)),1),
             'peak_dbfs':round(20*math.log10(max(peak,1e-8)),1),'gain':round(gain,2),
             'clipping_percent':round(float(np.mean(np.abs(raw)>=.999))*100,3),
             'dc_offset':round(dc,5)}
    return (output*32767).astype('<i2').tobytes(),metrics
