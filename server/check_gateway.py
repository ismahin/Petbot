"""Synthetic end-to-end protocol check; not a human microphone accuracy test."""
import asyncio
import argparse
import json
from pathlib import Path
import socket
import ssl
import sys
import time
import uuid
import httpx
import numpy as np
from scipy.signal import resample_poly
import soundfile as sf
from websockets.asyncio.client import connect
from audio import OpusInput, OpusOutput

ROOT = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding='utf-8')

async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample',default='mithi/malini_0.wav')
    args=parser.parse_args()
    config = json.loads((ROOT/'private/config.json').read_text())
    tls = ssl.create_default_context(cafile=str(ROOT/'private/ca.crt'))
    headers = {'Device-Id':config['allowed_device_mac'], 'Client-Id':str(uuid.uuid4()),
               'Authorization':'Bearer '+config['device_token']}
    base = f"{config['host']}:{config['port']}"
    async with httpx.AsyncClient(verify=tls,trust_env=False) as client:
        bad = await client.post('https://'+base+'/xiaozhi/ota/',json={})
        assert bad.status_code==401
        good = await client.post('https://'+base+'/xiaozhi/ota/',headers=headers,json={})
        assert good.status_code==200 and good.json()['websocket']['version']==1
    udp = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    udp.settimeout(2)
    request = bytearray(48); request[0]=0x23; request[40:48]=b'checkNTP'
    udp.sendto(request,(config['host'],8123))
    response,_ = udp.recvfrom(512); udp.close()
    assert response[24:32]==request[40:48]
    print('TLS, authentication and offline clock passed',flush=True)
    async with connect('wss://'+base+'/xiaozhi/v1/',ssl=tls,additional_headers=headers,proxy=None) as ws:
        await ws.send(json.dumps({'type':'hello','audio_params':{'format':'opus','sample_rate':16000,'channels':1,'frame_duration':60}}))
        hello = json.loads(await ws.recv()); assert hello['type']=='hello'
        await ws.send(json.dumps({'type':'listen','state':'start','mode':'auto'}))
        audio,rate = sf.read(ROOT/'diagnostics'/args.sample,dtype='float32')
        if rate!=16000:
            import math
            divisor=math.gcd(rate,16000)
            audio=resample_poly(audio,16000//divisor,rate//divisor).astype(np.float32)
        samples = np.r_[audio,np.zeros(16000,np.float32)]
        encoder = OpusOutput(rate=16000)
        packets = list(encoder.encode((samples*32767).astype('<i2')))+encoder.finish()
        for packet in packets:
            await ws.send(packet)
            await asyncio.sleep(.06)
        began = time.perf_counter(); output=[]; decoder=OpusInput()
        async with asyncio.timeout(90):
            async for packet in ws:
                if isinstance(packet,bytes):
                    output.append(decoder.decode(packet))
                else:
                    message=json.loads(packet)
                    if message.get('state')=='sentence_start':
                        assert '<happy>' not in message.get('text','') and '"emotion"' not in message.get('text','')
                    print(message.get('type'),message.get('state',''),message.get('text',''),flush=True)
                    if message.get('type')=='error':
                        raise RuntimeError(message.get('message'))
                    if message.get('type')=='tts' and message.get('state')=='stop':
                        break
        assert output,'No real speech returned'
        pcm=np.frombuffer(b''.join(output),dtype='<i2')
        sf.write(ROOT/'diagnostics/gateway_reply.wav',pcm,16000,subtype='PCM_16')
        print('PASS real ASR → LLM → TTS → Opus, returned_audio_s',len(pcm)/16000,flush=True)

if __name__=='__main__':
    asyncio.run(main())
