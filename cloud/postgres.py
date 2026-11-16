"""Small encrypted PostgreSQL pool for serverless settings and conversation data."""
import asyncio
import json
import os
import time

from fastapi import HTTPException


class Postgres:
    def __init__(self):
        self.pool = None
        self.lock = asyncio.Lock()
        self.last_cleanup = 0

    @property
    def ready(self):
        return bool(os.getenv('DATABASE_URL') or os.getenv('POSTGRES_URL'))

    async def connection(self):
        if self.pool is None:
            async with self.lock:
                if self.pool is None:
                    import asyncpg
                    dsn = os.getenv('DATABASE_URL') or os.getenv('POSTGRES_URL')
                    # TLS is mandatory. Respect Aiven's supplied sslmode and allow
                    # verify-full with an sslrootcert when its CA is configured.
                    if not dsn or 'sslmode=disable' in dsn:
                        raise HTTPException(503, 'An encrypted PostgreSQL connection is required.')
                    pool = await asyncpg.create_pool(dsn, ssl='require' if 'sslmode=' not in dsn else None,
                        min_size=0, max_size=2, max_inactive_connection_lifetime=30,
                        command_timeout=10, timeout=12, statement_cache_size=0)
                    try:
                        async with pool.acquire() as db, db.transaction():
                            await db.execute("SELECT pg_advisory_xact_lock(hashtext('deskter-schema-v1'))")
                            await db.execute('''CREATE SCHEMA IF NOT EXISTS deskter;
                                CREATE TABLE IF NOT EXISTS deskter.kv (
                                  key text PRIMARY KEY, value text NOT NULL, expires_at timestamptz);
                                CREATE TABLE IF NOT EXISTS deskter.hashes (
                                  key text NOT NULL, field text NOT NULL, value text NOT NULL,
                                  PRIMARY KEY(key,field));
                                CREATE TABLE IF NOT EXISTS deskter.turns (
                                  id text PRIMARY KEY, device text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
                                  updated_at timestamptz NOT NULL DEFAULT now(), record jsonb NOT NULL);
                                CREATE INDEX IF NOT EXISTS deskter_turns_time ON deskter.turns(created_at DESC);
                                CREATE TABLE IF NOT EXISTS deskter.audio (
                                  turn_id text NOT NULL REFERENCES deskter.turns(id) ON DELETE CASCADE,
                                  kind text NOT NULL, data bytea NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
                                  PRIMARY KEY(turn_id,kind));''')
                    except BaseException:
                        await pool.close()
                        raise
                    self.pool = pool
        return self.pool

    async def run(self, operation, *args):
        try:
            pool = await self.connection()
            async with pool.acquire() as db:
                return await operation(db, *args)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, 'PostgreSQL storage is unavailable. Check the private database configuration.') from None

    async def get(self, key):
        async def op(db):
            return await db.fetchval('SELECT value FROM deskter.kv WHERE key=$1 AND (expires_at IS NULL OR expires_at>now())',key)
        return await self.run(op)

    async def set(self, key, value, ttl=None, nx=False):
        async def op(db):
            query='''INSERT INTO deskter.kv(key,value,expires_at) VALUES($1,$2,CASE WHEN $3::double precision IS NULL THEN NULL ELSE now()+$3*interval '1 second' END)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value,expires_at=excluded.expires_at'''
            if nx:
                query+=' WHERE deskter.kv.expires_at<=now()'
            return bool(await db.fetchval(query+' RETURNING key',key,str(value),ttl))
        return await self.run(op)

    async def cas(self,key,old,new):
        async def op(db):
            if old=='':
                return bool(await db.fetchval('INSERT INTO deskter.kv(key,value) VALUES($1,$2) ON CONFLICT(key) DO UPDATE SET value=excluded.value WHERE deskter.kv.value=$3 RETURNING key',key,new,old))
            return bool(await db.fetchval('UPDATE deskter.kv SET value=$3 WHERE key=$1 AND value=$2 RETURNING key',key,old,new))
        return await self.run(op)

    async def increment(self,key):
        async def op(db):
            return int(await db.fetchval('''INSERT INTO deskter.kv(key,value) VALUES($1,'1') ON CONFLICT(key) DO UPDATE
                SET value=CASE WHEN deskter.kv.expires_at<=now() THEN '1' ELSE (deskter.kv.value::bigint+1)::text END RETURNING value''',key))
        return await self.run(op)

    async def expire(self,key,seconds):
        async def op(db):
            await db.execute("UPDATE deskter.kv SET expires_at=now()+$2*interval '1 second' WHERE key=$1",key,float(seconds))
        return await self.run(op)

    async def hget(self,key,field):
        async def op(db):
            return await db.fetchval('SELECT value FROM deskter.hashes WHERE key=$1 AND field=$2',key,field)
        return await self.run(op)

    async def hgetall(self,key):
        async def op(db):
            return {row['field']:row['value'] for row in await db.fetch('SELECT field,value FROM deskter.hashes WHERE key=$1',key)}
        return await self.run(op)

    async def create_device(self,hashed,identity,record):
        async def op(db):
            async with db.transaction():
                await db.executemany('INSERT INTO deskter.hashes(key,field,value) VALUES($1,$2,$3)',[
                    ('deskter:keys',hashed,identity),('deskter:device-list',identity,record),('deskter:device-hashes',identity,hashed)])
        return await self.run(op)

    async def revoke_device(self,identity):
        async def op(db):
            async with db.transaction():
                hashed=await db.fetchval("SELECT value FROM deskter.hashes WHERE key='deskter:device-hashes' AND field=$1 FOR UPDATE",identity)
                await db.execute("DELETE FROM deskter.hashes WHERE (key IN ('deskter:device-list','deskter:device-hashes') AND field=$1) OR (key='deskter:keys' AND field=$2)",identity,hashed)
                await db.execute('DELETE FROM deskter.kv WHERE key=$1','deskter:history:'+identity)
        return await self.run(op)

    async def release(self,key,owner):
        async def op(db):
            return await db.execute('DELETE FROM deskter.kv WHERE key=$1 AND value=$2',key,owner)
        return await self.run(op)

    async def save_turn(self,record):
        async def op(db):
            await db.execute('''INSERT INTO deskter.turns(id,device,record) VALUES($1,$2,$3::jsonb)
                ON CONFLICT(id) DO UPDATE SET record=excluded.record,updated_at=now()''',record['id'],record['device'],json.dumps(record,ensure_ascii=False))
            if time.monotonic()-self.last_cleanup>60:
                self.last_cleanup=time.monotonic()
                await db.execute("DELETE FROM deskter.audio WHERE created_at<now()-interval '1 hour'")
                await db.execute("DELETE FROM deskter.turns WHERE created_at<now()-interval '24 hours' OR id IN (SELECT id FROM deskter.turns ORDER BY created_at DESC OFFSET 50)")
                await db.execute('DELETE FROM deskter.kv WHERE expires_at<now()')
        return await self.run(op)

    async def recent_turns(self):
        async def op(db):
            return [json.loads(row['record']) for row in await db.fetch("SELECT record::text FROM deskter.turns WHERE created_at>now()-interval '24 hours' ORDER BY created_at DESC LIMIT 50")]
        return await self.run(op)

    async def turn(self,identity):
        async def op(db):
            value=await db.fetchval('SELECT record::text FROM deskter.turns WHERE id=$1',identity)
            return json.loads(value) if value else None
        return await self.run(op)

    async def save_audio(self,identity,kind,data):
        async def op(db):
            await db.execute('INSERT INTO deskter.audio(turn_id,kind,data) VALUES($1,$2,$3) ON CONFLICT(turn_id,kind) DO UPDATE SET data=excluded.data',identity,kind,data)
            await db.execute('DELETE FROM deskter.audio WHERE turn_id NOT IN (SELECT id FROM deskter.turns ORDER BY created_at DESC LIMIT 10)')
        return await self.run(op)

    async def audio(self,identity,kind):
        async def op(db):
            return await db.fetchval("SELECT data FROM deskter.audio WHERE turn_id=$1 AND kind=$2 AND created_at>now()-interval '1 hour'",identity,kind)
        return await self.run(op)

    async def clear_turns(self):
        async def op(db):
            await db.execute('DELETE FROM deskter.turns')
        return await self.run(op)
