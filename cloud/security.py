import hashlib
import hmac
import os
import secrets
import time

from fastapi import HTTPException, Request
from cloud.storage import store

LOCAL_RATES = {}


def digest(key):
    return hashlib.sha256(key.encode()).hexdigest()


def admin_key():
    key = os.getenv('DESKTER_ADMIN_KEY', '')
    if len(key) < 32:
        raise HTTPException(503, 'Set DESKTER_ADMIN_KEY to a random secret of at least 32 characters.')
    return key


def session_cookie():
    expires = str(int(time.time())+28800)
    signature = hmac.new(admin_key().encode(), expires.encode(), 'sha256').hexdigest()
    return expires+'.'+signature


def admin(request: Request):
    key = admin_key()
    token = request.headers.get('authorization','').removeprefix('Bearer ')
    if token and hmac.compare_digest(token,key):
        return
    cookie = request.cookies.get('deskter_session','')
    try:
        expires, signature = cookie.split('.',1)
        expected = hmac.new(key.encode(), expires.encode(), 'sha256').hexdigest()
        if int(expires)>time.time() and hmac.compare_digest(signature,expected):
            return
    except ValueError:
        pass
    raise HTTPException(401, 'Sign in with your Deskter admin key.')


async def device(headers):
    key = headers.get('authorization','').removeprefix('Bearer ')
    if not 32 <= len(key) <= 256:
        raise HTTPException(401, 'A device API key is required.')
    bootstrap = os.getenv('DESKTER_DEVICE_KEY','')
    if len(bootstrap)>=32 and hmac.compare_digest(key,bootstrap):
        return 'bootstrap'
    if store.ready:
        identity = await store.hget('deskter:keys',digest(key))
        if identity:
            return identity
    raise HTTPException(401, 'Invalid or revoked device key.')


async def limit(identity, kind='request', maximum=20):
    if store.ready:
        key=f'deskter:rate:{kind}:{digest(identity)}:{int(time.time())//60}'
        value=await store.increment(key)
        if value==1:
            await store.expire(key,120)
        if int(value)>maximum:
            raise HTTPException(429,'Request limit reached. Try again in a minute.',headers={'Retry-After':'60'})
    else:
        # Best-effort per-instance fallback; Redis is required for global limits.
        bucket=int(time.time())//60
        for key in list(LOCAL_RATES):
            if key[0]!=bucket:
                del LOCAL_RATES[key]
        token=(bucket,kind,digest(identity))
        if len(LOCAL_RATES)>=256 and token not in LOCAL_RATES:
            raise HTTPException(429,'Server is busy. Retry shortly.')
        LOCAL_RATES[token]=LOCAL_RATES.get(token,0)+1
        if LOCAL_RATES[token]>maximum:
            raise HTTPException(429,'Request limit reached. Try again in a minute.',headers={'Retry-After':'60'})


def new_key():
    return 'dsk_'+secrets.token_urlsafe(32)
