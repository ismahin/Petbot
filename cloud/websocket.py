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
from cloud import conversations
from cloud.recognition import prepare

ACTIVE = set()
CAMERA_BN = {'camera_open': 'ক্যামেরা চালু হচ্ছে।', 'camera_close': 'ক্যামেরা বন্ধ হচ্ছে।'}


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
            lease=await store.set('deskter:session:'+identity,ownership,ttl=260,nx=True)
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
            raw=await store.get('deskter:history:'+identity)
            if raw:
                history=json.loads(raw)[-8:]

        async def message(kind,**fields):
            await socket.send_json({'type':kind,'session_id':session_id,**fields})

        async def respond(samples):
            current=await get_settings()
            record=conversations.new(identity)
            enabled=current.get('conversation_history',True)
            started=time.monotonic();input_task=None
            async def event(kind,**fields):
                await message(kind,turn_id=record['id'],**fields)
            async def save():
                if enabled:await conversations.save(record)
            async def heartbeat():
                while True:
                    await asyncio.sleep(15)
                    await event('tts',state='preparing')
            heartbeat_task=asyncio.create_task(heartbeat())
            try:
                await event('tts',state='preparing')
                await limit(identity,'voice-turn',10)
                pcm,record['metrics']=prepare(samples)
                audio=runtime.wav(pcm,16000)
                await save()
                if enabled and current.get('capture_audio',True):
                    clip=pcm[:16000*2*12]
                    input_task=asyncio.create_task(conversations.audio(record,'input',runtime.wav(clip,16000),len(clip)/32000,len(pcm)>len(clip)))
                began_asr=time.monotonic()
                recognized=await provider.recognize(audio,current)
                text=recognized['text'];record['heard']=text;record['asr']=recognized['metadata']
                record['timing']['asr_seconds']=round(time.monotonic()-began_asr,3)
                record['status']='thinking' if text else 'no_speech'
                await event('stt',text=text)
                await save()
                action=camera_command(text) if text else None
                if not text:
                    reply={'text':'I did not hear that clearly. Please try again.','emotion':'neutral'}
                    record['response_source']='clarification'
                elif action:
                    await event('device',action=action)
                    bangla=any('\u0980'<=c<='\u09ff' for c in text)
                    confirmation=CAMERA_BN[action] if bangla else ('Opening the camera.' if action=='camera_open' else 'Closing the camera.')
                    reply={'text':confirmation,'emotion':'neutral'}
                    record['response_source']='device_command'
                else:
                    record['llm_input']=provider.chat_messages(text,history,current)
                    began_llm=time.monotonic()
                    reply=await provider.chat(text,history,current)
                    record['timing']['llm_seconds']=round(time.monotonic()-began_llm,3)
                    record['response_source']='llm'
                record['llm_output']=reply['text'];record['emotion']=reply['emotion'];record['status']='generating_speech'
                await save()
                await event('llm',emotion=reply['emotion'])
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

                generated_audio=bytearray()
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
                        record['playback']={'state':'streaming','packets_sent':sent}
                        if sent>=prefill:
                            deadline=max(deadline,time.monotonic()-.12)+.06
                    while (item:=await queue.get()) is not None:
                        phrase,pcm=item
                        record['speech_text'].append(phrase)
                        if current.get('capture_audio',True):
                            remaining=24000*2*12-len(generated_audio)
                            if remaining>0:generated_audio.extend(pcm[:remaining])
                        if not started:
                            record['status']='speaking'
                            await save()
                            await event('tts',state='start');started=True
                        await event('tts',state='sentence_start',text=phrase)
                        for packet in encoder.encode(np.frombuffer(pcm,dtype='<i2')):
                            await send(packet)
                    for packet in encoder.finish():
                        await send(packet)
                    await asyncio.sleep(.24)
                async with asyncio.TaskGroup() as group:
                    group.create_task(generate());group.create_task(play())

                if enabled and generated_audio:
                    await conversations.audio(record,'output',runtime.wav(bytes(generated_audio)),len(generated_audio)/48000,len(generated_audio)>=24000*2*12)
                if text:
                    history.extend([{'role':'user','content':text},{'role':'assistant','content':reply['text']}])
                    del history[:-8]
                    if store.ready:
                        await store.set('deskter:history:'+identity,json.dumps(history,ensure_ascii=False),ttl=3600)
                record['status']='sent';record['playback']={'state':'sent'}
            except asyncio.CancelledError:
                record['status']='interrupted'
                raise
            except Exception as error:
                record['status']='error'
                record['error']=error.detail if isinstance(error,HTTPException) else 'Voice processing failed ('+type(error).__name__+').'
                with suppress(Exception):
                    await event('error',message=record['error'])
            finally:
                heartbeat_task.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat_task
                if input_task:
                    with suppress(Exception,asyncio.CancelledError):await input_task
                record['timing']['total_seconds']=round(time.monotonic()-started,3)
                with suppress(Exception):await save()
                segmenter.reset()
                with suppress(Exception):
                    await event('tts',state='stop')

        began=time.monotonic()
        hello=False
        try:
            while time.monotonic()-began<240:
                try:
                    event=await asyncio.wait_for(socket.receive(),timeout=min(30,max(.1,240-(time.monotonic()-began))))
                except TimeoutError:
                    continue
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
                    elif data.get('type')=='playback' and hello:
                        turn_id=data.get('turn_id','')
                        state=data.get('state')
                        if isinstance(turn_id,str) and len(turn_id)==32 and state in ('complete','partial','error'):
                            details={'state':state}
                            for key in ('packets','errors','drops','underruns'):
                                value=data.get(key,0)
                                details[key]=max(0,min(100000,value)) if type(value) is int else 0
                            with suppress(Exception):await conversations.playback(turn_id,identity,details)
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
                await store.release('deskter:session:'+identity,ownership)
