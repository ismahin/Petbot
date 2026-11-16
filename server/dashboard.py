"""Loopback-only settings panel. Shares the gateway's warmed engine."""
import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import wave

import httpx
import numpy as np
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from mithi_speech import VOICES

ROOT = Path(__file__).resolve().parent
DEFAULTS = dict(mithi_voice='malini', speech_volume=100, response_language='auto',
    backchannels='auto', temperature=.3, groq_model='openai/gpt-oss-120b',
    groq_max_tokens=384, first_phrase_words=6,
    following_phrase_words=12, silence_ms=700, max_utterance_seconds=20,
    vad_mode=1, output_bitrate=48000, playback_prefill_frames=4,
    log_transcripts=False, asr_model='whisper-large-v3', asr_language='auto',
    asr_prompt='Bangla, English, Banglish. Mahin, Deskter, Dexter.',
    conversation_history=True, capture_audio=True)


class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    system_prompt: str = Field(min_length=10, max_length=16000)
    mithi_voice: str
    speech_volume: int = Field(ge=0, le=100)
    response_language: Literal['auto', 'bn', 'en', 'bn-en']
    backchannels: Literal['auto', 'off']
    temperature: float = Field(ge=0, le=1)
    groq_model: str = Field(pattern=r'^[a-zA-Z0-9_./-]{1,120}$')
    groq_max_tokens: int = Field(ge=64, le=1024)
    first_phrase_words: int = Field(ge=4, le=16)
    following_phrase_words: int = Field(ge=6, le=24)
    silence_ms: int = Field(ge=200, le=1600, multiple_of=20)
    max_utterance_seconds: int = Field(ge=5, le=30)
    vad_mode: int = Field(ge=0, le=3)
    output_bitrate: int = Field(ge=24000, le=64000)
    playback_prefill_frames: int = Field(ge=1, le=4)
    log_transcripts: bool
    asr_model: Literal['whisper-large-v3','whisper-large-v3-turbo']='whisper-large-v3'
    asr_language: Literal['auto','bn','en']='auto'
    asr_prompt: str=Field(default='Bangla, English, Banglish. Mahin, Deskter, Dexter.',max_length=600)
    conversation_history: bool=True
    capture_audio: bool=True


class SaveRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: str
    settings: Settings


class Preview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    voice: str
    text: str = Field(min_length=1, max_length=300)


def editable(config, root=ROOT):
    result = {key: config.get(key, value) for key, value in DEFAULTS.items()}
    result['system_prompt'] = config.get('system_prompt') or (root/'persona.txt').read_text(encoding='utf-8-sig')
    return result


def revision(settings):
    return hashlib.sha256(json.dumps(settings, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def persist(root, config, values):
    """Replace one file atomically; preserve private fields and external edits."""
    path = root/'private/config.json'
    disk = json.loads(path.read_text(encoding='utf-8-sig'))
    disk.update(values)
    temporary = path.with_suffix('.tmp')
    try:
        with temporary.open('w', encoding='utf8') as handle:
            json.dump(disk, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    config.update(values)


def create_dashboard(state, root=ROOT):
    panel = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    preview_lock = asyncio.Lock()
    allowed_hosts = {'127.0.0.1:8787', 'localhost:8787', '[::1]:8787'}

    @panel.middleware('http')
    async def local_only(request, call_next):
        host = request.headers.get('host', '')
        origin = request.headers.get('origin')
        if (not request.client or request.client.host not in ('127.0.0.1', '::1', 'testclient')
                or host not in allowed_hosts or
                (origin and origin not in {'http://'+h for h in allowed_hosts}) or
                request.headers.get('sec-fetch-site') == 'cross-site'):
            return Response('Local access only', status_code=403)
        if request.method not in ('GET', 'HEAD'):
            if request.headers.get('x-deskter-panel') != '1':
                return Response('Panel request required', status_code=403)
            if int(request.headers.get('content-length', '0')) > 100000:
                return Response('Request too large', status_code=413)
        response = await call_next(request)
        response.headers.update({'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; media-src 'self' blob:; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            'Referrer-Policy':'no-referrer'})
        return response

    def busy():
        conversation = state.ACTIVE_CONVERSATION
        return bool(conversation and conversation.busy)

    @panel.get('/')
    async def index():
        return FileResponse(root/'web/index.html')

    @panel.get('/assets/{name}')
    async def asset(name: str):
        if name not in ('app.js', 'style.css'):
            raise HTTPException(404)
        return FileResponse(root/'web'/name)

    @panel.get('/api/settings')
    async def settings():
        values = editable(state.CONFIG, root)
        return {'settings':values, 'revision':revision(values), 'voices':sorted(VOICES)}

    @panel.get('/api/status')
    async def status():
        model = state.MODEL
        return {'ready':model is not None, 'device_connected':state.DEVICE_LOCK.locked(),
                'busy':busy(), 'provider':state.CONFIG.get('llm_provider', 'groq'),
                'model':state.model_name(state.CONFIG), 'voice':state.CONFIG.get('mithi_voice', 'malini'),
                'speech_backend':'Mithi v1 Edge', 'speech_device':'CPU · 2 threads',
                'emotion_control':False}

    @panel.put('/api/settings')
    async def save(body: SaveRequest):
        if body.revision != revision(editable(state.CONFIG, root)):
            raise HTTPException(409, 'Settings changed in another tab. Reload before saving.')
        if busy() or preview_lock.locked():
            raise HTTPException(409, 'Wait for the current reply or voice preview to finish, then save again.')
        values = body.settings.model_dump()
        if values['mithi_voice'] not in VOICES:
            raise HTTPException(422, 'Unknown Mithi voice')
        if not values['system_prompt'].strip():
            raise HTTPException(422, 'System prompt cannot be blank')
        persist(root, state.CONFIG, values)
        if state.MODEL:
            state.MODEL.persona = values['system_prompt']
            state.MODEL.speech.voice.voice = values['mithi_voice']
            state.MODEL.speech.voice.volume = values['speech_volume']
        return {'revision':revision(values), 'message':'Saved. Prompt and voice apply to the next reply; listening settings apply on the next wake.'}

    @panel.post('/api/preview')
    async def preview(body: Preview):
        if body.voice not in VOICES:
            raise HTTPException(422, 'Unknown Mithi voice')
        if busy() or state.DEVICE_LOCK.locked():
            raise HTTPException(409, 'Let Deskter return to waiting before previewing a voice.')
        if preview_lock.locked():
            raise HTTPException(409, 'A voice preview is already generating.')
        async with preview_lock:
            import re
            text = re.sub(r'<[^>]*>', '', body.text).strip()
            if not text:
                raise HTTPException(422, 'Enter some words to preview.')
            try:
                async with httpx.AsyncClient(trust_env=False, timeout=90) as client:
                    response = await client.post('http://127.0.0.1:1925/synthesize', json={
                        'text':text, 'voice':body.voice,
                        'language':'bn' if re.search('[\u0980-\u09ff]', text) else 'en'})
                    response.raise_for_status()
                if response.headers.get('x-sample-rate') != '24000':
                    raise ValueError('Unexpected sample rate')
                samples = np.frombuffer(response.content, dtype='<f4')
                if not len(samples) or not np.isfinite(samples).all():
                    raise ValueError('Invalid samples')
                samples = samples * state.CONFIG.get('speech_volume', 100)/100
                output = io.BytesIO()
                with wave.open(output, 'wb') as wav:
                    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
                    wav.writeframes((np.clip(samples, -.98, .98)*32767).astype('<i2').tobytes())
                return Response(output.getvalue(), media_type='audio/wav')
            except (httpx.HTTPError, ValueError):
                raise HTTPException(503, 'Mithi could not generate the preview. Check that the speech worker is ready.') from None

    return panel
