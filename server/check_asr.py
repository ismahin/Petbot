from pathlib import Path
import os
os.environ['HF_HUB_OFFLINE']='1'
import sys,time
import soundfile as sf
from scipy.signal import resample_poly
import numpy as np
from faster_whisper import WhisperModel
sys.stdout.reconfigure(encoding='utf-8',errors='replace')
root=Path(__file__).resolve().parent
for compute in ['float32','int8']:
    model=WhisperModel(str(root/'models/whisper-small'),device='cpu',compute_type=compute,cpu_threads=4,local_files_only=True)
    print('Model multilingual:',model.model.is_multilingual,'compute',compute,'bn_id',model.hf_tokenizer.token_to_id('<|bn|>'),flush=True)
    for file,language in [('english_check.wav','en'),('raw_check.wav','bn')]:
        data,rate=sf.read(root/'diagnostics'/file,dtype='float32')
        if data.ndim>1:data=data.mean(axis=1)
        import math
        g=math.gcd(rate,16000);data=resample_poly(data,16000//g,rate//g).astype(np.float32)
        started=time.perf_counter()
        segments,info=model.transcribe(data,language=language,beam_size=1,temperature=0,condition_on_previous_text=False,max_new_tokens=50)
        rows=[{'text':s.text,'logprob':s.avg_logprob,'tokens':s.tokens[:10]} for s in segments]
        print(compute,file,'seconds',round(time.perf_counter()-started,2),'language',info.language,rows,flush=True)
