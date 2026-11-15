"""Real local rehearsal of the Vercel app; uses Groq and actual Mithi weights."""
import argparse
import asyncio
import io
import json
import os
from pathlib import Path
import sys
import time
import wave

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir',required=True)
    args=parser.parse_args()
    os.environ['MITHI_MODEL_DIR']=args.model_dir
    for line in (ROOT/'cloud/private/vercel.env').read_text(encoding='utf8').splitlines():
        if '=' in line:
            key,value=line.split('=',1);os.environ[key]=value
    import httpx
    import numpy as np
    from scipy.signal import resample_poly
    import soundfile as sf
    from cloud.app import app
    sample,rate=sf.read(ROOT/'server/diagnostics/mithi/malini_0.wav',dtype='float32')
    audio=(np.clip(resample_poly(sample,16000,rate),-1,1)*32767).astype('<i2').tobytes()
    buf=io.BytesIO()
    with wave.open(buf,'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(audio)
    headers={'Authorization':'Bearer '+os.environ['DESKTER_DEVICE_KEY']}
    summary={}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver',timeout=180) as client:
        response=await client.get('/health');response.raise_for_status()
        assert not response.json()['tts_loaded']
        began=time.perf_counter()
        response=await client.post('/api/v1/transcribe',headers=headers,content=buf.getvalue())
        response.raise_for_status();text=response.json()['text']
        assert text.strip();summary['asr_seconds']=round(time.perf_counter()-began,3)
        began=time.perf_counter()
        response=await client.post('/api/v1/chat',headers=headers,json={'text':text})
        response.raise_for_status();reply=response.json()
        assert reply['text'].strip();summary['llm_seconds']=round(time.perf_counter()-began,3)
        for label in ('cold','cached'):
            began=time.perf_counter()
            response=await client.post('/api/v1/speech',headers=headers,json={'text':reply['text'][:300]})
            response.raise_for_status()
            with wave.open(io.BytesIO(response.content)) as wav:
                assert wav.getframerate()==24000 and wav.getnframes()>0
                summary['audio_seconds']=round(wav.getnframes()/24000,3)
            summary[label+'_tts_seconds']=round(time.perf_counter()-began,3)
        (ROOT/'cloud/private/live_speech.wav').write_bytes(response.content)
    if sys.platform=='win32':
        import ctypes
        from ctypes import wintypes
        class Memory(ctypes.Structure):
            _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in ('peak','working','paged_peak','paged','nonpaged_peak','nonpaged','pagefile','pagefile_peak','private')]
        memory=Memory();memory.cb=ctypes.sizeof(memory)
        if ctypes.windll.psapi.GetProcessMemoryInfo(wintypes.HANDLE(-1),ctypes.byref(memory),memory.cb):
            summary.update(working_mib=round(memory.working/2**20),peak_working_mib=round(memory.peak/2**20),private_mib=round(memory.private/2**20))
    summary['result']='PASS real Groq ASR + Groq LLM + lazy Mithi + WAV'
    (ROOT/'cloud/private/live-check.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    print(json.dumps(summary))


if __name__=='__main__':asyncio.run(main())
