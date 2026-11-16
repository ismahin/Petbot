"""One lazy CPU model per instance; serialized inference and a tiny RAM cache."""
import asyncio
from collections import OrderedDict
import gc
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import threading
import wave

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parent
MODEL = None
LOCK = threading.Lock()
SLOTS = asyncio.Semaphore(1)
CACHE = OrderedDict()
VOICES = ('satvik','anirban','nakul','vasant','siddhant','charvi','ahana','vaidehi','malini','jahnavi')


def load():
    global MODEL
    if MODEL is not None:
        return MODEL
    if os.getenv('MITHI_ENABLED','1')=='0':
        raise HTTPException(503, 'Mithi is disabled in this deployment.')
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', TOKENIZERS_PARALLELISM='false')
    import torch
    torch.set_num_threads(max(1,min(2,int(os.getenv('MITHI_THREADS','1')))))
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass
    folder = Path(os.getenv('MITHI_MODEL_DIR', str(ROOT/'models/mithi-v1-edge')))
    source = json.loads((ROOT/'model-source.json').read_text(encoding='utf8'))
    for entry in source['files']:
        path = (folder/entry['file']).resolve()
        if not path.is_relative_to(folder.resolve()) or not path.is_file():
            raise HTTPException(503, 'Mithi assets are missing. Run the model build step before deployment.')
        with path.open('rb') as handle:
            if hashlib.file_digest(handle,'sha256').hexdigest()!=entry['sha256']:
                raise HTTPException(503,'Mithi asset verification failed.')
    spec=importlib.util.spec_from_file_location('mithi_cloud_run',folder/'run.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    model=module.Mithi(str(folder),device='cpu')
    from mithi_cached_writer import enable_cached_writer
    enable_cached_writer(model)
    MODEL=model
    gc.collect()
    return model


def preload():
    with LOCK:
        return load()


def synthesize(text, voice, volume):
    import numpy as np
    import torch
    from speech_audio import trim_padding
    text=re.sub(r'<[^>]*>', '', text).strip()
    if not text:
        raise HTTPException(422,'Speech text cannot be empty.')
    language='bn' if re.search('[\u0980-\u09ff]',text) else 'en'
    key=(text,voice,volume)
    with LOCK:
        if key in CACHE:
            data=CACHE.pop(key);CACHE[key]=data
            return data
        model=load()
        with torch.inference_mode():
            audio=np.asarray(model.synthesize(text,lang=language,voice=voice,seed=0,gap=.06),dtype=np.float32).reshape(-1)
        if not len(audio) or not np.isfinite(audio).all():
            raise HTTPException(503,'Mithi produced invalid audio.')
        peak=float(np.max(np.abs(audio)))
        rms=float(np.sqrt(np.mean(audio.astype(np.float64)**2)))
        if rms>.002 and peak>0:
            audio*=min(3,.12/rms,.9/peak)
        audio=trim_padding(audio)
        data=(np.clip(audio*volume/100,-.98,.98)*32767).astype('<i2').tobytes()
        CACHE[key]=data
        cap=max(0,min(8,int(os.getenv('MITHI_CACHE_MB','4'))))*1024*1024
        while sum(map(len,CACHE.values()))>cap:
            CACHE.popitem(last=False)
        return data


async def pcm(text,voice='malini',volume=100):
    if voice not in VOICES:
        raise HTTPException(422,'Unknown Mithi voice.')
    try:
        await asyncio.wait_for(SLOTS.acquire(),timeout=2)
    except TimeoutError:
        raise HTTPException(429,'Speech engine is busy. Retry shortly.',headers={'Retry-After':'3'}) from None
    # Cancellation must not release the slot while a background CPU thread runs.
    task=asyncio.create_task(asyncio.to_thread(synthesize,text,voice,volume))
    try:
        return await asyncio.shield(task)
    finally:
        if task.done():
            SLOTS.release()
        else:
            def finished(future):
                if not future.cancelled():
                    future.exception()
                SLOTS.release()
            task.add_done_callback(finished)


def wav(data,rate=24000):
    output=io.BytesIO()
    with wave.open(output,'wb') as handle:
        handle.setnchannels(1);handle.setsampwidth(2);handle.setframerate(rate);handle.writeframes(data)
    return output.getvalue()
