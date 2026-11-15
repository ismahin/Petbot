"""Bounded Xiaozhi Opus sessions; reconnect before Vercel's function deadline."""
import asyncio
from contextlib import suppress
import io
import json
import time
import uuid

from fastapi import HTTPException, WebSocketDisconnect
from cloud import provider, runtime
from cloud.security import device, limit
from cloud.storage import store
from cloud.device_commands import camera_command

ACTIVE = set()


async def serve(socket, get_settings):
    try:
        identity=await device(socket.headers)
        await limit(identity,'connect',10)
    except HTTPException:
        await socket.close(1008);return
    if len(ACTIVE)>=2 or identity in ACTIVE:
        await socket.close(1013);return
    ACTIVE.add(identity)
    ownership=uuid.uuid4().hex
    lease=False
    try:
        if store.ready:
            lease=await store.command('SET','deskter:session:'+identity,ownership,'NX','EX',260)
            if not lease:
                await socket.close(1013);return
        await socket.accept()
        # Heavy audio libraries load only for actual audio sessions.
        import numpy as np
        from audio import OpusInput, OpusOutput, Utterances
        from expression import JsonSpeechChunks
        config=await get_settings()
        decoder=OpusInput();segmenter=Utterances(config)
        session_id=str(uuid.uuid4());history=[];listening=False;turn_task=None
        if store.ready:
            raw=await store.command('GET','deskter:history:'+identity)
            if raw:
                history=json.loads(raw)[-8:]

        async def message(kind,**fields):
            await socket.send_json({'type':kind,'session_id':session_id,**fields})

        async def respond(samples):
            current=await get_settings()
            async def heartbeat():
                while True:
                    await asyncio.sleep(15)
                    await message('tts',state='preparing')
            heartbeat_task=asyncio.create_task(heartbeat())
            try:
                await message('tts',state='preparing')
                await limit(identity,'voice-turn',10)
                audio=runtime.wav((np.clip(samples,-1,1)*32767).astype('<i2').tobytes(),16000)
                text=await provider.transcribe(audio)
                if not text:
                    return
                await message('stt',text=text)
                action=camera_command(text)
                if action:
                    await message('device',action=action)
                    bangla=any('\u0980'<=c<='\u09ff' for c in text)
                    confirmation=('ক্যামেরা চালু হচ্ছে।' if bangla else 'Opening the camera.') if action=='camera_open' else ('ক্যামেরা বন্ধ হচ্ছে।' if bangla else 'Closing the camera.')
                    reply={'text':confirmation,'emotion':'neutral'}
                else:
                    reply=await provider.chat(text,history,current)
                await message('llm',emotion=reply['emotion'])
                chunks=JsonSpeechChunks(sentence_mode=True,split_commas=True,
                    first_sentence_words=current['first_phrase_words'],
                    max_sentence_words=current['following_phrase_words'],min_sentence_words=3,min_clause_words=3)
                phrases=chunks.feed(json.dumps(reply,ensure_ascii=False))+chunks.finish()
                queue=asyncio.Queue(2)

                async def generate():
                    for phrase in phrases:
                        pcm=await runtime.pcm(phrase.text,current['mithi_voice'],current['speech_volume'])
                        await queue.put((phrase.text,pcm))
                    await queue.put(None)

                async def play():
                    encoder=OpusOutput(bitrate=current['output_bitrate'])
                    started=False;deadline=None;sent=0
                    prefill=max(1,min(4,current['playback_prefill_frames']))
                    async def send(packet):
                        nonlocal deadline,sent
                        if deadline is None:
                            deadline=time.monotonic()
                        if sent>=prefill:
                            await asyncio.sleep(max(0,deadline-time.monotonic()))
                        await socket.send_bytes(packet)
                        sent+=1
                        if sent>=prefill:
                            deadline=max(deadline,time.monotonic()-.12)+.06
                    while (item:=await queue.get()) is not None:
                        phrase,pcm=item
                        if not started:
                            await message('tts',state='start');started=True
                        await message('tts',state='sentence_start',text=phrase)
                        for packet in encoder.encode(np.frombuffer(pcm,dtype='<i2')):
                            await send(packet)
                    for packet in encoder.finish():
                        await send(packet)
                    await asyncio.sleep(.24)
                async with asyncio.TaskGroup() as group:
                    group.create_task(generate());group.create_task(play())
                history.extend([{'role':'user','content':text},{'role':'assistant','content':reply['text']}])
                del history[:-8]
                if store.ready:
                    await store.command('SET','deskter:history:'+identity,json.dumps(history,ensure_ascii=False),'EX',3600)
            except asyncio.CancelledError:
                raise
            except Exception:
                with suppress(Exception):
                    await message('error',message='Voice service unavailable. Please retry shortly.')
            finally:
                heartbeat_task.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat_task
                segmenter.reset()
                with suppress(Exception):
                    await message('tts',state='stop')

        began=time.monotonic()
        hello=False
        try:
            while time.monotonic()-began<240:
                event=await asyncio.wait_for(socket.receive(),timeout=min(30,240-(time.monotonic()-began)))
                if event['type']=='websocket.disconnect':
                    break
                if event.get('text') is not None:
                    if len(event['text'])>4096:
                        await socket.close(1009);break
                    data=json.loads(event['text'])
                    if data.get('type')=='hello':
                        audio=data.get('audio_params',{})
                        if audio.get('format')!='opus' or audio.get('sample_rate')!=16000 or audio.get('channels')!=1:
                            await socket.close(1003);break
                        await message('hello',version=1,transport='websocket',audio_params={
                            'format':'opus','sample_rate':24000,'channels':1,'frame_duration':60})
                        hello=True
                    elif data.get('type')=='listen' and hello:
                        listening=data.get('state')=='start'
                        config=await get_settings();segmenter=Utterances(config)
                    elif data.get('type')=='abort' and turn_task:
                        turn_task.cancel()
                        with suppress(asyncio.CancelledError):
                            await turn_task
                elif event.get('bytes') is not None:
                    packet=event['bytes']
                    if len(packet)>1500:
                        await socket.close(1009);break
                    if hello and listening and (turn_task is None or turn_task.done()):
                        samples=segmenter.feed(decoder.decode(packet))
                        if samples is not None:
                            listening=False
                            turn_task=asyncio.create_task(respond(samples))
        except (WebSocketDisconnect,TimeoutError,ValueError):
            pass
        finally:
            if turn_task and not turn_task.done():
                turn_task.cancel()
                with suppress(asyncio.CancelledError):
                    await turn_task
            with suppress(Exception):
                await socket.close(1012,'Reconnect to continue')
    except (HTTPException,WebSocketDisconnect):
        with suppress(Exception):
            await socket.close(1013)
    finally:
        ACTIVE.discard(identity)
        if lease:
            with suppress(Exception):
                await store.command('EVAL',"if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) else return 0 end",1,'deskter:session:'+identity,ownership)
