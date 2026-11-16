import json
import os
from pathlib import Path

import httpx
from fastapi import HTTPException

from groq_llm import api_key, tokens, GroqError

CLIENT = None


def client():
    global CLIENT
    if CLIENT is None:
        CLIENT = httpx.AsyncClient(trust_env=False,timeout=30,
            limits=httpx.Limits(max_connections=8,max_keepalive_connections=4))
    return CLIENT


async def recognize(data, settings=None, filename='speech.wav'):
    settings=settings or {}
    model=settings.get('asr_model') or os.getenv('GROQ_ASR_MODEL','whisper-large-v3')
    language=settings.get('asr_language','auto')
    fields={'model':model,'response_format':'verbose_json','temperature':'0',
            'prompt':settings.get('asr_prompt','')[:600]}
    if language in ('bn','en'):
        fields['language']=language
    try:
        response=await client().post('https://api.groq.com/openai/v1/audio/transcriptions',
                headers={'Authorization':'Bearer '+api_key()}, data=fields,
                files={'file':(filename,data,'audio/wav')})
        response.raise_for_status()
        result=response.json()
        segments=result.get('segments') or []
        metadata={'model':model,'language':result.get('language',language)}
        for name in ('avg_logprob','no_speech_prob','compression_ratio'):
            values=[float(s[name]) for s in segments if s.get(name) is not None]
            if values:metadata[name]=round(sum(values)/len(values),3)
        text=result.get('text','').strip()[:4000]
        # Reject strong no-speech evidence instead of feeding hallucinations to the LLM.
        if metadata.get('no_speech_prob',0)>.85 and metadata.get('avg_logprob',0)<-.8:
            text='';metadata['rejected']='No reliable speech detected'
        return {'text':text,'metadata':metadata}
    except (httpx.HTTPError, ValueError, GroqError):
        raise HTTPException(502,'Speech recognition is unavailable. Check Groq access and quotas.') from None


async def transcribe(data, filename='speech.wav'):
    return (await recognize(data,filename=filename))['text']


def chat_messages(text,history,settings):
    prompt=settings['system_prompt']
    hints={'bn':'Reply in colloquial Bangladeshi Bangla.', 'en':'Reply in English.',
        'bn-en':'Reply in natural Banglish using Bengali script for Bangla words and Latin script for English.'}
    prompt+='\n'+hints.get(settings.get('response_language'),"Match the user's Bangla, English, or Banglish. Use Bengali script for Bangla words.")
    if settings.get('backchannels')=='off':
        prompt+='\nAnswer directly without fillers or backchannel acknowledgments.'
    prompt+='\nUse short spoken sentences. Return only JSON with emotion and text. No control tags or stage directions.'
    return [{'role':'system','content':prompt}]+history[-8:]+[{'role':'user','content':text}]


async def chat(text,history,settings):
    config={**settings,'llm_provider':'groq','groq_strict_json':True,
        'groq_model':settings.get('groq_model','openai/gpt-oss-120b'),
        'groq_fallback_model':os.getenv('GROQ_FALLBACK_MODEL','')}
    messages=chat_messages(text,history,settings)
    try:
        result=''
        async for part in tokens(client(),config,messages):
            result+=part
        reply=json.loads(result)
        if len(reply['text'])>2400:
            raise ValueError('Reply too long')
        return reply
    except (GroqError, ValueError):
        raise HTTPException(502,'Conversation is unavailable. Check Groq credentials, model access, and quotas.') from None
