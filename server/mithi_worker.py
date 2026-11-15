"""One warmed, offline Mithi model on loopback; no conversation audio is saved."""
import os
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
from collections import OrderedDict
from contextlib import asynccontextmanager
import hashlib
import importlib.util
import json
from pathlib import Path
import threading
import time
from typing import Literal

from fastapi import FastAPI, Response
import numpy as np
from pydantic import BaseModel, Field
import torch
from speech_audio import trim_padding
from mithi_cached_writer import enable_cached_writer

ROOT = Path(__file__).resolve().parent
MODEL = None
LOCK = threading.Lock()
CACHE = OrderedDict()
VOICES = ('satvik','anirban','nakul','vasant','siddhant','charvi','ahana','vaidehi','malini','jahnavi')


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    language: Literal['bn','en'] = 'bn'
    voice: Literal['satvik','anirban','nakul','vasant','siddhant','charvi','ahana','vaidehi','malini','jahnavi'] = 'malini'
    cache_audio: bool = True


def generate(request):
    with torch.inference_mode():
        wave = MODEL.synthesize(request.text, lang=request.language,
                                voice=request.voice, seed=0, gap=0.06)
    wave = np.asarray(wave, dtype=np.float32).reshape(-1)
    if not len(wave) or not np.isfinite(wave).all():
        raise ValueError('Mithi returned empty or non-finite audio')
    peak = float(np.max(np.abs(wave)))
    rms = float(np.sqrt(np.mean(wave.astype(np.float64) ** 2)))
    # Bounded gain for this quieter model; preserve headroom and never clip.
    if rms > .002 and peak > 0:
        wave *= min(3.0, .12 / rms, .9 / peak)
    return trim_padding(wave).astype('<f4').tobytes()


@asynccontextmanager
async def lifespan(app):
    global MODEL
    source = json.loads((ROOT / 'mithi-model-source.json').read_text())
    folder = Path(source['model_dir']).resolve()
    for item in source['files']:
        path = (folder / item['file']).resolve()
        if not path.is_relative_to(folder):
            raise ValueError('Invalid Mithi model path')
        with path.open('rb') as handle:
            if hashlib.file_digest(handle, 'sha256').hexdigest() != item['sha256']:
                raise ValueError('Mithi model hash mismatch: ' + item['file'])
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    spec = importlib.util.spec_from_file_location('deskter_mithi_run', folder / 'run.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    MODEL = module.Mithi(str(folder), device='cpu')
    enable_cached_writer(MODEL)
    # Warm both G2P paths and neural kernels before accepting robot requests.
    generate(SpeechRequest(text='হ্যালো, আমি তোমার সঙ্গে বাংলায় কথা বলতে পারি।'))
    generate(SpeechRequest(text='Hello, I am ready to talk with you.', language='en'))
    yield
    MODEL = None
    CACHE.clear()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get('/health')
def health():
    return {'ready': MODEL is not None, 'offline': True, 'model': 'mithi-v1-edge',
            'device': 'cpu', 'threads': 2, 'sample_rate': 24000,
            'voices': list(VOICES), 'emotion_control': False, 'cached_writer': True,
            'cached_phrases': len(CACHE)}


@app.post('/synthesize')
def synthesize(request: SpeechRequest):
    started = time.perf_counter()
    with LOCK:
        key = (request.text, request.language, request.voice)
        cached = request.cache_audio and key in CACHE
        if cached:
            data = CACHE.pop(key)
            CACHE[key] = data
        else:
            data = generate(request)
            if request.cache_audio:
                CACHE[key] = data
            while sum(map(len, CACHE.values())) > 32 * 1024 * 1024:
                CACHE.popitem(last=False)
    return Response(data, media_type='application/octet-stream', headers={
        'X-Sample-Rate': '24000', 'X-Generation-Ms': str(round((time.perf_counter()-started)*1000)),
        'X-Voice': request.voice, 'X-Emotion-Control': 'none',
        'X-Cache': 'hit' if cached else 'miss'})
