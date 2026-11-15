"""Local speech inference with Groq text generation."""
import os
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import threading
import time
import httpx
import numpy as np
from scipy.signal import resample_poly
import sherpa_onnx
from expression import JsonSpeechChunks, SPEECH_SCHEMA, SpokenPhrase

ROOT = Path(__file__).resolve().parent


class Engine:
    def __init__(self, config):
        self.config = config
        self.persona = config.get('system_prompt') or (ROOT / "persona.txt").read_text(encoding="utf-8-sig")
        model = ROOT / 'models/sherpa-onnx-streaming-zipformer-bn-vosk-2026-02-09'
        self.asr = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(model/'tokens.txt'), encoder=str(model/'encoder.onnx'),
            decoder=str(model/'decoder.onnx'), joiner=str(model/'joiner.onnx'),
            num_threads=config.get('asr_threads', 2), model_type='zipformer2')
        self.language_router = None
        self.asr_pool = None
        self.last_asr_route = {}
        self.last_asr_alternative = ''
        if config.get('english_asr', False):
            from faster_whisper import WhisperModel
            self.language_router = WhisperModel(str(ROOT/'models/whisper-tiny-router'),
                device='cpu',compute_type='int8',cpu_threads=3,local_files_only=True)
            self.asr_pool = ThreadPoolExecutor(max_workers=1,thread_name_prefix='bangla-asr')
        from speech import Speech
        self.speech = Speech(config)
        self.tts_lock = threading.Lock()
        self.asr_lock = threading.Lock()
        self.llm_client = httpx.AsyncClient(trust_env=False,timeout=httpx.Timeout(180,connect=5))

    async def close(self):
        await self.llm_client.aclose()
        if self.speech.backend in ('mithi',):
            await self.speech.voice.close()
        if self.asr_pool:
            self.asr_pool.shutdown(wait=False,cancel_futures=True)

    def transcribe(self, audio):
        with self.asr_lock:
            self.last_asr_alternative = ''
            if self.language_router is None:
                self.last_asr_route={'asr_route':'bangla'}
                return self._bangla(audio)
            # Recognition and language detection overlap on separate CPU workers.
            bangla=self.asr_pool.submit(self._bangla,audio)
            try:
                language,probability,probabilities=self.language_router.detect_language(audio)
            except Exception as error:
                self.last_asr_route={'asr_route':'bangla','routing_error':type(error).__name__}
                return bangla.result()
            self.last_asr_route={'asr_route':'bangla','detected_language':language,
                                 'language_probability':round(probability,3)}
            scores=dict(probabilities)
            english_primary=language=='en' and probability>=self.config.get('english_language_threshold',0.75)
            mixed=scores.get('en',0)>=self.config.get('english_mixed_threshold',0.15) and scores.get('bn',0)>=0.1
            if english_primary or mixed:
                segments,_=self.language_router.transcribe(audio,language='en',beam_size=1,
                    temperature=0,condition_on_previous_text=False,max_new_tokens=80,
                    compression_ratio_threshold=None,log_prob_threshold=None)
                text=' '.join(s.text.strip() for s in segments).strip()
                if text and english_primary:
                    bangla.result()  # Join before this recognizer can be reused.
                    self.last_asr_route['asr_route']='english'
                    return text
                if text and mixed:
                    self.last_asr_alternative=text
                    self.last_asr_route['asr_route']='bangla+english_alternative'
            return bangla.result()

    def heard_message(self,text):
        if self.last_asr_alternative:
            return text+'\n[English alternative: '+self.last_asr_alternative+']'
        return text

    def _bangla(self,audio):
        stream = self.asr.create_stream()
        stream.accept_waveform(16000, audio)
        stream.accept_waveform(16000, np.zeros(11200, np.float32))
        stream.input_finished()
        while self.asr.is_ready(stream):
            self.asr.decode_stream(stream)
        return self.asr.get_result(stream).strip()

    def synthesize(self, text):
        text = re.sub(r"[*_`#<>]", "", text).strip()
        with self.tts_lock:
            waveform, rate = self.speech.synthesize(text)
        waveform = np.nan_to_num(waveform)
        peak = float(np.max(np.abs(waveform))) if len(waveform) else 0
        if peak > 0.98:
            waveform *= 0.98 / peak
        # Model sample rate is read from the actual checkpoint.
        if rate != 24000:
            import math
            divisor = math.gcd(rate, 24000)
            waveform = resample_poly(waveform, 24000 // divisor, rate // divisor)
        return np.clip(waveform * 32767, -32768, 32767).astype("<i2")

    async def synthesize_chunks(self, phrase):
        text = re.sub(r"[*_`#]", "", phrase.text).strip()
        if self.speech.backend in ('mithi',):
            async for pcm in self.speech.voice.stream(text,phrase.emotion):
                yield pcm
        else:
            yield await asyncio.to_thread(self.synthesize,text)

    async def sentences(self, history, metrics=None):
        async for phrase in self.reply_phrases(history,metrics):
            yield phrase.text

    async def reply_phrases(self, history, metrics=None, language_hint=None):
        began = time.perf_counter()
        messages=[{"role":"system","content":self.persona}]
        hints={'en':'The user spoke English. Reply in English unless they explicitly request another language.',
               'bn-en':'The user mixed Bangla and English. Reply naturally in Banglish: Bengali script with familiar English words in Latin script.',
               'bn':'Reply in colloquial Bangladeshi Bangla unless the user requests another language.'}
        if self.config.get('response_language','auto') != 'auto':
            language_hint = self.config['response_language']
        if self.config.get('backchannels','auto') == 'off':
            messages[0]['content']+='\nDo not add conversational fillers or backchannel acknowledgments. Answer directly.'
        if language_hint in hints:
            messages[0]['content']+='\nFor this turn: '+hints[language_hint]
        if self.speech.backend in ('mithi',):
            messages[0]['content']+='\nFor spoken delivery, use short complete sentences of about 6–14 words. Avoid long comma chains, lists and repeated explanations. Answer the actual question; give longer detail when the user asks for it.'
        from expression import EMOTIONS
        messages[0]['content']+='\nAllowed emotion values: '+', '.join(sorted(EMOTIONS))+'.'
        chunks = JsonSpeechChunks(first_words=self.config.get('first_phrase_words', 6),
                              following_words=self.config.get('following_phrase_words', 14),
                              split_commas=True,
                              sentence_mode=True,
                              max_sentence_words=self.config.get('following_phrase_words',12),
                              first_sentence_words=self.config.get('first_phrase_words',6),
                              min_sentence_words=3,
                              min_clause_words=3,
                              first_wait=self.config.get('first_phrase_wait_ms',450)/1000)
        async def provider_tokens():
            from groq_llm import tokens
            async for token in tokens(self.llm_client,self.config,messages+history[-8:],metrics):
                yield token
        async for token in provider_tokens():
            if token and metrics is not None and 'llm_first_token_ms' not in metrics:
                metrics['llm_first_token_ms']=round((time.perf_counter()-began)*1000)
            for sentence in chunks.feed(token):
                if metrics is not None and 'llm_first_phrase_ms' not in metrics:
                    metrics['llm_first_phrase_ms']=round((time.perf_counter()-began)*1000)
                yield sentence
        for sentence in chunks.finish():
            if metrics is not None and 'llm_first_phrase_ms' not in metrics:
                metrics['llm_first_phrase_ms'] = round((time.perf_counter()-began)*1000)
            yield sentence
