"""Durable REST Redis; no mutable settings or API keys in ephemeral files."""
import os
import httpx
from fastapi import HTTPException
from cloud.postgres import Postgres


class Store:
    def __init__(self):
        self.client = None
        self.pg = Postgres()
    @property
    def ready(self):
        return self.pg.ready or bool((os.getenv('KV_REST_API_URL') or os.getenv('UPSTASH_REDIS_REST_URL')) and
                                     (os.getenv('KV_REST_API_TOKEN') or os.getenv('UPSTASH_REDIS_REST_TOKEN')))

    @property
    def backend(self):
        return 'postgresql' if self.pg.ready else 'redis' if self.ready else 'memory'

    async def get(self,key):
        return await self.pg.get(key) if self.pg.ready else await self.command('GET',key)

    async def set(self,key,value,ttl=None,nx=False):
        if self.pg.ready:
            return await self.pg.set(key,value,ttl,nx)
        args=['SET',key,value]
        if nx: args+=['NX']
        if ttl is not None: args+=['EX',ttl]
        return await self.command(*args)

    async def increment(self,key):
        return await self.pg.increment(key) if self.pg.ready else await self.command('INCR',key)

    async def expire(self,key,seconds):
        return await self.pg.expire(key,seconds) if self.pg.ready else await self.command('EXPIRE',key,seconds)

    async def hget(self,key,field):
        return await self.pg.hget(key,field) if self.pg.ready else await self.command('HGET',key,field)

    async def hgetall(self,key):
        if self.pg.ready: return await self.pg.hgetall(key)
        raw=await self.command('HGETALL',key)
        return dict(zip(raw[::2],raw[1::2])) if isinstance(raw,list) else raw or {}

    async def cas(self,key,old,new):
        if self.pg.ready: return await self.pg.cas(key,old,new)
        script="local v=redis.call('GET',KEYS[1]); if (not v and ARGV[1]=='') or v==ARGV[1] then redis.call('SET',KEYS[1],ARGV[2]); return 1 else return 0 end"
        return await self.command('EVAL',script,1,key,old,new)

    async def create_device(self,hashed,identity,record):
        if self.pg.ready: return await self.pg.create_device(hashed,identity,record)
        script="redis.call('HSET',KEYS[1],ARGV[1],ARGV[2]); redis.call('HSET',KEYS[2],ARGV[2],ARGV[3]); redis.call('HSET',KEYS[3],ARGV[2],ARGV[1]); return 1"
        return await self.command('EVAL',script,3,'deskter:keys','deskter:device-list','deskter:device-hashes',hashed,identity,record)

    async def revoke_device(self,identity):
        if self.pg.ready: return await self.pg.revoke_device(identity)
        script="local h=redis.call('HGET',KEYS[3],ARGV[1]); if h then redis.call('HDEL',KEYS[1],h); end; redis.call('HDEL',KEYS[2],ARGV[1]); redis.call('HDEL',KEYS[3],ARGV[1]); redis.call('DEL','deskter:history:'..ARGV[1]); return 1"
        return await self.command('EVAL',script,3,'deskter:keys','deskter:device-list','deskter:device-hashes',identity)

    async def release(self,key,owner):
        if self.pg.ready: return await self.pg.release(key,owner)
        return await self.command('EVAL',"if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) else return 0 end",1,key,owner)

    async def command(self, *args):
        if not self.ready:
            raise HTTPException(503, 'Configure KV_REST_API_URL and KV_REST_API_TOKEN for durable settings and device management.')
        url = os.getenv('KV_REST_API_URL') or os.environ['UPSTASH_REDIS_REST_URL']
        if not url.startswith('https://'):
            raise HTTPException(503, 'Redis REST storage must use HTTPS.')
        try:
            if self.client is None:
                self.client = httpx.AsyncClient(trust_env=False, timeout=5,
                    limits=httpx.Limits(max_connections=8,max_keepalive_connections=4))
            response = await self.client.post(url, json=list(args), headers={
                'Authorization':'Bearer '+(os.getenv('KV_REST_API_TOKEN') or os.environ['UPSTASH_REDIS_REST_TOKEN'])})
            response.raise_for_status()
            data = response.json()
            if data.get('error'):
                raise ValueError('Storage command failed')
            return data.get('result')
        except (httpx.HTTPError, ValueError):
            raise HTTPException(503, 'Persistent storage is unavailable.') from None


store = Store()
