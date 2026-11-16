"""Admin-only, bounded conversation diagnostics. No API secrets are stored."""
from collections import OrderedDict
from copy import deepcopy
import time
import uuid

from fastapi import HTTPException
from cloud.storage import store

RECORDS = OrderedDict()
AUDIO = OrderedDict()


def new(device,source='robot'):
    return {'id':uuid.uuid4().hex,'device':device,'source':source,'created':time.time(),
            'status':'recognizing','heard':'','llm_input':[],'llm_output':'','speech_text':[],
            'playback':{'state':'not_sent'},'timing':{},'audio':{},'metrics':{}}


async def save(record):
    record['updated']=time.time()
    RECORDS[record['id']]=deepcopy(record)
    RECORDS.move_to_end(record['id'])
    for key,value in list(RECORDS.items()):
        if len(RECORDS)>50 or value['created']<time.time()-86400:
            RECORDS.pop(key,None)
    if store.pg.ready:
        try:
            await store.pg.save_turn(record)
        except HTTPException:
            record['storage_warning']='Database unavailable; this instance only.'


async def audio(record,kind,data,seconds,truncated=False):
    # Twelve seconds per clip; never retain full unlimited audio conversations.
    if len(data)>800000:
        return
    key=(record['id'],kind)
    AUDIO[key]=(time.time(),data)
    while sum(len(item[1]) for item in AUDIO.values())>8*1024*1024:
        AUDIO.popitem(last=False)
    record['audio'][kind]={'seconds':round(seconds,2),'truncated':truncated}
    if store.pg.ready:
        try:
            await store.pg.save_audio(record['id'],kind,data)
        except HTTPException:
            record['storage_warning']='Audio is available on this instance only.'
    await save(record)


async def recent():
    if store.pg.ready:
        return {'storage':'postgresql','retention':'Latest 50 turns / 24 hours. Audio: latest 10 turns / 1 hour.',
                'turns':await store.pg.recent_turns()}
    return {'storage':'instance-memory','retention':'Temporary on this server instance; connect PostgreSQL for shared history.',
            'turns':list(reversed(list(RECORDS.values())))}


async def get(identity):
    if store.pg.ready:
        return await store.pg.turn(identity)
    return deepcopy(RECORDS.get(identity))


async def read_audio(identity,kind):
    if store.pg.ready:
        return await store.pg.audio(identity,kind)
    item=AUDIO.get((identity,kind))
    return item[1] if item and time.time()-item[0]<3600 else None


async def clear():
    if store.pg.ready:
        await store.pg.clear_turns()
    RECORDS.clear();AUDIO.clear()


async def playback(identity,device,details):
    record=await get(identity)
    if not record or record['device']!=device:
        return
    record['playback']=details
    if record['status'] not in ('error','interrupted'):
        record['status']='playback_complete' if details['state']=='complete' else 'playback_incomplete'
    await save(record)
