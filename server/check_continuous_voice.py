"""Real local speech generation concurrent with paced Opus playback simulation."""
import argparse
import asyncio
import json
from pathlib import Path
import time
import httpx
import numpy as np
import soundfile as sf
from audio import OpusOutput
from mithi_speech import MithiSpeech
from expression import SpokenPhrase
from text_chunks import SpokenChunks
from speech_lookahead import lookahead_audio

ROOT=Path(__file__).resolve().parent
TEXTS={
    'bn':'তোমার আজকের দিনটা ভালো কেটেছে শুনে আমার ভালো লাগছে। এখন একটু বিশ্রাম নাও, আর চাইলে আমাকে তোমার দিনের মজার কোনো ঘটনার কথা বলতে পারো।',
    'en':'I am happy to hear that your day went well. Take a little rest now, and tell me about something interesting that happened at work today.',
    'mixed':'আজ office-এ অনেক কাজ ছিল, I understand how you feel. এখন একটু rest নাও, তারপর চাইলে আমরা তোমার দিনের কথা বলতে পারি।',
}

async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--language',choices=list(TEXTS),default='bn')
    args=parser.parse_args()
    config=json.loads((ROOT/'private/config.json').read_text())
    voice=MithiSpeech(config)
    with httpx.Client(trust_env=False,timeout=5) as client:health=client.get(voice.url+'/health').json()
    out=ROOT/'diagnostics/mithi/continuous'
    out.mkdir(parents=True,exist_ok=True)
    chunks=SpokenChunks(sentence_mode=True,split_commas=True,max_sentence_words=12,
        first_sentence_words=6,min_sentence_words=3,min_clause_words=3)
    phrases=chunks.feed(TEXTS[args.language])+chunks.finish()
    queue=asyncio.Queue(4);results=[];waves=[];metrics={};began=time.perf_counter()
    async def generate():
        async with httpx.AsyncClient(trust_env=False,timeout=180) as client:
            for index,text in enumerate(phrases):
                request=voice.request(text,'caring');request['cache_audio']=False
                start=time.perf_counter()
                response=await client.post(voice.url+'/synthesize',json=request);response.raise_for_status()
                wave=np.frombuffer(response.content,dtype='<f4').copy()
                assert len(wave) and np.isfinite(wave).all()
                elapsed=time.perf_counter()-start
                waves.append(wave)
                sf.write(out/f'{args.language}_{index}.wav',wave,24000,subtype='PCM_16')
                result={'text':text,'generation_seconds':round(elapsed,3),'audio_seconds':round(len(wave)/24000,3)}
                results.append(result);print(json.dumps(result,ensure_ascii=True),flush=True)
                await queue.put((SpokenPhrase(text,'caring'),(wave*32767).astype('<i2')))
        await queue.put(None)
    async def play():
        encoder=OpusOutput(bitrate=48000);deadline=None;packets=0;max_gap=0;first=None
        async def packet(data):
            nonlocal deadline,packets,max_gap,first
            now=time.perf_counter()
            if deadline is not None:max_gap=max(max_gap,max(0,now-deadline))
            if deadline is None:deadline=now
            await asyncio.sleep(max(0,deadline-time.perf_counter()))
            if first is None:first=time.perf_counter()
            assert len(data)<=1275
            packets+=1;deadline=max(deadline,time.perf_counter())+.06
        async for _,pcm in lookahead_audio(queue,0,metrics):
            for data in encoder.encode(pcm):await packet(data)
        for data in encoder.finish():await packet(data)
        metrics.update(first_packet_ms=round((first-began)*1000),max_transport_gap_ms=round(max_gap*1000),packets=packets)
    try:
        async with asyncio.TaskGroup() as group:group.create_task(generate());group.create_task(play())
        sf.write(out/(args.language+'_joined.wav'),np.concatenate(waves),24000,subtype='PCM_16')
        summary={'device':health['device'],'runtime':health.get('runtime',health.get('model')),'voice':voice.voice,
            'language':args.language,'lead_ms':0,'chunks':results,**metrics}
        (out/(args.language+'.json')).write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(summary,ensure_ascii=True),flush=True)
    finally:await voice.close()

if __name__=='__main__':asyncio.run(main())
