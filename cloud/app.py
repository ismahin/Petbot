"""Groq-only cloud API, authenticated Studio, and lazy in-process Mithi."""
import asyncio
import hmac
import json
import os
from pathlib import Path
import secrets
import sys
import time
from typing import Literal

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from dashboard import Settings, DEFAULTS, revision
from cloud import provider, runtime
from cloud.security import admin, admin_key, session_cookie, device, digest, new_key, limit
from cloud.storage import store

app=FastAPI(title='Deskter API',docs_url='/api/docs',openapi_url='/api/openapi.json',redoc_url=None)


async def settings():
    data={**DEFAULTS,'system_prompt':(ROOT/'server/persona.txt').read_text(encoding='utf-8-sig')}
    data['groq_model']=os.getenv('GROQ_MODEL',data['groq_model'])
    if store.ready:
        saved=await store.command('GET','deskter:settings')
        if saved:
            data.update(Settings.model_validate(json.loads(saved)).model_dump())
    return data


@app.middleware('http')
async def boundaries(request,call_next):
    if request.method not in ('GET','HEAD'):
        origin=request.headers.get('origin')
        if origin and origin.rstrip('/')!=str(request.base_url).rstrip('/'):
            return Response('Cross-origin writes are not permitted.',403)
    try:
        length=int(request.headers.get('content-length','0'))
    except ValueError:
        return Response('Invalid Content-Length',400)
    if length>1_100_000:
        return Response('Request too large',413)
    # Bound chunked bodies too. This remains under Vercel's request size limit.
    if request.method not in ('GET','HEAD'):
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>1_100_000:
                return Response('Request too large',413)
        request._body=bytes(body)
    response=await call_next(request)
    response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
        'Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; media-src 'self' blob:; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
    return response


@app.get('/')
async def index():
    return FileResponse(ROOT/'server/web/index.html')


@app.get('/assets/{name}')
async def asset(name: str):
    if name not in ('app.js','style.css'):
        raise HTTPException(404)
    return FileResponse(ROOT/'server/web'/name)


@app.get('/health')
async def health():
    configured=bool(os.getenv('GROQ_API_KEY')) and len(os.getenv('DESKTER_ADMIN_KEY',''))>=32 and len(os.getenv('DESKTER_DEVICE_KEY',''))>=32
    return {'ready':configured,'deployment':'vercel-experimental','tts_loaded':runtime.MODEL is not None,
        'tts_enabled':os.getenv('MITHI_ENABLED','1')!='0','storage_configured':store.ready,
        'groq_configured':bool(os.getenv('GROQ_API_KEY'))}


class Login(BaseModel):
    key: str=Field(min_length=1,max_length=256)


@app.post('/api/login')
async def login(body: Login,request: Request):
    await limit(request.client.host,'login',10)
    if not hmac.compare_digest(body.key,admin_key()):
        raise HTTPException(401,'Incorrect admin key.')
    response=Response('{}',media_type='application/json')
    response.set_cookie('deskter_session',session_cookie(),httponly=True,
        secure=bool(os.getenv('VERCEL')) or request.url.scheme=='https',samesite='strict',max_age=28800)
    return response


@app.post('/api/logout')
async def logout(request: Request):
    admin(request)
    response=Response('{}',media_type='application/json');response.delete_cookie('deskter_session')
    return response


@app.get('/api/settings')
async def get_settings(request: Request):
    admin(request);data=await settings()
    return {'settings':data,'revision':revision(data),'voices':sorted(runtime.VOICES),
        'cloud':True,'storage_ready':store.ready}


class Save(BaseModel):
    revision: str
    settings: Settings


@app.put('/api/settings')
async def save(body: Save,request: Request):
    admin(request)
    values=body.settings.model_dump()
    if values['mithi_voice'] not in runtime.VOICES:
        raise HTTPException(422,'Unknown Mithi voice.')
    if not values['system_prompt'].strip():
        raise HTTPException(422,'System prompt cannot be blank.')
    old=await settings()
    if body.revision!=revision(old):
        raise HTTPException(409,'Settings changed. Reload before saving.')
    # Compare-and-set protects against simultaneous writes across instances.
    script="local v=redis.call('GET',KEYS[1]); if (not v and ARGV[1]=='') or v==ARGV[1] then redis.call('SET',KEYS[1],ARGV[2]); return 1 else return 0 end"
    current=await store.command('GET','deskter:settings')
    if current:
        disk={**DEFAULTS,**json.loads(current)}
        if revision(disk)!=body.revision:
            raise HTTPException(409,'Settings changed. Reload before saving.')
    result=await store.command('EVAL',script,1,'deskter:settings',current or '',json.dumps(values,ensure_ascii=False))
    if not result:
        raise HTTPException(409,'Settings changed. Reload before saving.')
    return {'revision':revision(values),'message':'Saved securely. Changes apply to the next request or listening window.'}


@app.get('/api/status')
async def status(request: Request):
    admin(request);data=await settings()
    return {'ready':True,'device_connected':False,'connection_tracking':False,'busy':False,
        'provider':'groq','model':data['groq_model'],'voice':data['mithi_voice'],
        'speech_backend':'Mithi v1 Edge','speech_device':'CPU · lazy loading',
        'emotion_control':False,'cloud':True,'storage_ready':store.ready}


class Speech(BaseModel):
    model_config=ConfigDict(extra='forbid')
    text: str=Field(min_length=1,max_length=300)
    voice: str|None=None


@app.post('/api/preview')
async def preview(body: Speech,request: Request):
    admin(request);await limit('admin','preview',10)
    data=await settings()
    audio=await runtime.pcm(body.text,body.voice or data['mithi_voice'],data['speech_volume'])
    return Response(runtime.wav(audio),media_type='audio/wav')


class DeviceName(BaseModel):
    name: str=Field(min_length=1,max_length=64,pattern=r'^[\w .-]+$')


@app.get('/api/devices')
async def devices(request: Request):
    admin(request)
    raw=await store.command('HGETALL','deskter:device-list')
    values=dict(zip(raw[::2],raw[1::2])) if isinstance(raw,list) else raw or {}
    return {'devices':[json.loads(value) for value in values.values()]}


@app.post('/api/devices')
async def add_device(body: DeviceName,request: Request):
    admin(request);await limit('admin','create-device',10)
    key=new_key();hashed=digest(key);identity=secrets.token_hex(8)
    record={'id':identity,'name':body.name,'created':int(time.time()),'fingerprint':hashed[:10]}
    # Store hashes only; the full device key is returned exactly once.
    script="redis.call('HSET',KEYS[1],ARGV[1],ARGV[2]); redis.call('HSET',KEYS[2],ARGV[2],ARGV[3]); redis.call('HSET',KEYS[3],ARGV[2],ARGV[1]); return 1"
    await store.command('EVAL',script,3,'deskter:keys','deskter:device-list','deskter:device-hashes',hashed,identity,json.dumps(record))
    return {**record,'api_key':key}


@app.delete('/api/devices/{identity}')
async def revoke(identity: str,request: Request):
    admin(request)
    if len(identity)!=16 or any(c not in '0123456789abcdef' for c in identity):
        raise HTTPException(422,'Invalid device ID.')
    script="local h=redis.call('HGET',KEYS[3],ARGV[1]); if h then redis.call('HDEL',KEYS[1],h); end; redis.call('HDEL',KEYS[2],ARGV[1]); redis.call('HDEL',KEYS[3],ARGV[1]); redis.call('DEL','deskter:history:'..ARGV[1]); return 1"
    await store.command('EVAL',script,3,'deskter:keys','deskter:device-list','deskter:device-hashes',identity)
    return {'revoked':True}


class Message(BaseModel):
    role: Literal['user','assistant']
    content: str=Field(min_length=1,max_length=2400)


class Chat(BaseModel):
    model_config=ConfigDict(extra='forbid')
    text: str=Field(min_length=1,max_length=4000)
    history: list[Message]=Field(default_factory=list,max_length=8)


@app.post('/api/v1/chat')
async def chat(body: Chat,request: Request):
    identity=await device(request.headers);await limit(identity)
    return await provider.chat(body.text,[m.model_dump() for m in body.history],await settings())


@app.get('/api/v1/voices')
async def voices(request: Request):
    await device(request.headers)
    return {'voices':list(runtime.VOICES),'sample_rate':24000,'format':'wav','emotion_control':False}


@app.post('/api/v1/speech')
async def speech(body: Speech,request: Request):
    identity=await device(request.headers);await limit(identity,'speech',10)
    data=await settings()
    pcm=await runtime.pcm(body.text,body.voice or data['mithi_voice'],data['speech_volume'])
    return Response(runtime.wav(pcm),media_type='audio/wav',headers={'X-Sample-Rate':'24000'})


@app.post('/api/v1/transcribe')
async def transcribe(request: Request):
    identity=await device(request.headers);await limit(identity,'asr',10)
    import io
    import wave
    data=await request.body()
    try:
        with wave.open(io.BytesIO(data),'rb') as audio:
            if audio.getnchannels()!=1 or audio.getsampwidth()!=2 or audio.getframerate()!=16000 or audio.getnframes()>480000:
                raise ValueError('Unsupported audio')
            if len(audio.readframes(audio.getnframes()))!=audio.getnframes()*2:
                raise ValueError('Truncated WAV')
    except (wave.Error, EOFError, ValueError):
        raise HTTPException(422,'Send a complete mono 16 kHz PCM16 WAV of at most 30 seconds.') from None
    return {'text':await provider.transcribe(data)}


@app.post('/xiaozhi/ota/')
async def configuration(request: Request):
    await device(request.headers)
    host=request.url.netloc
    return {'websocket':{'url':f'wss://{host}/xiaozhi/v1/','version':1,
        'token':request.headers['authorization'].removeprefix('Bearer ')},
        'server_time':{'timestamp':int(time.time()*1000),'timezone_offset':360}}


@app.websocket('/xiaozhi/v1/')
async def websocket(socket: WebSocket):
    from cloud.websocket import serve
    await serve(socket,settings)
