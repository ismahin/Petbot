"""Mithi client for the existing concurrent synthesis and Opus playback pipeline."""
import re
import unicodedata
import httpx
import numpy as np

VOICES = {'satvik','anirban','nakul','vasant','siddhant','charvi','ahana','vaidehi','malini','jahnavi'}


class MithiSpeech:
    def __init__(self, config):
        self.url = config.get('mithi_url', 'http://127.0.0.1:1925')
        if self.url not in ('http://127.0.0.1:1925','http://localhost:1925'):
            raise ValueError('Mithi must use the local loopback worker on port 1925')
        self.voice = config.get('mithi_voice', 'malini')
        if self.voice not in VOICES:
            raise ValueError('Unknown Mithi voice')
        self.timeout = 90
        self.client = None
        self.device = 'cpu'
        self.volume = config.get('speech_volume', 100)

    def request(self, text, emotion='neutral'):
        # This checkpoint has no learned emotion controls. Never speak tags or
        # pretend its pitch setting is an emotional reference-conditioning API.
        text = re.sub(r'<[^>]*>', '', unicodedata.normalize('NFC', text))
        text = ''.join(c for c in text if not '\ue000' <= c <= '\uf8ff').strip()
        return {'text': text, 'voice': self.voice,
                'language': 'bn' if re.search('[\u0980-\u09ff]', text) else 'en'}

    def synthesize(self,text,emotion='neutral'):
        with httpx.Client(base_url=self.url,trust_env=False,timeout=self.timeout) as client:
            response=client.post('/synthesize',json=self.request(text,emotion))
            response.raise_for_status()
            if response.headers.get('x-sample-rate')!='24000':
                raise ValueError('Unexpected Mithi audio sample rate')
            wave=np.frombuffer(response.content,dtype='<f4').copy()
            if not len(wave) or not np.isfinite(wave).all():raise ValueError('Invalid Mithi audio')
            return wave * (self.volume/100),24000

    async def stream(self,text,emotion='neutral'):
        if self.client is None:
            self.client=httpx.AsyncClient(base_url=self.url,trust_env=False,
                timeout=httpx.Timeout(self.timeout,connect=5))
        response=await self.client.post('/synthesize',json=self.request(text,emotion))
        response.raise_for_status()
        if response.headers.get('x-sample-rate')!='24000':
            raise ValueError('Unexpected Mithi audio sample rate')
        wave=np.frombuffer(response.content,dtype='<f4')
        if not len(wave) or not np.isfinite(wave).all():raise ValueError('Invalid Mithi audio')
        # HTTP worker buffers a full model phrase. Existing queues overlap this
        # with playback of the preceding phrase; do not claim native streaming.
        yield (np.clip(wave * (self.volume/100),-.98,.98)*32767).astype('<i2')

    async def close(self):
        if self.client:await self.client.aclose()
