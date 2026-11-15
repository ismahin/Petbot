"""Groq text generation; credentials stay on the PC, outside firmware/examples."""
import asyncio
import json
import os
import re
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parent


def model_name(config):
    return config.get('groq_model','openai/gpt-oss-120b')


class GroqError(RuntimeError):
    pass


def api_key():
    key=os.environ.get('GROQ_API_KEY','').strip()
    if not key:
        path=ROOT/'private/groq.key'
        if path.exists():key=path.read_text(encoding='utf-8-sig').strip()
    if not key:raise GroqError('Groq API key is missing from the private key file.')
    return key


async def tokens(client,config,messages,metrics=None):
    primary=config.get('groq_model','qwen/qwen3.8-27b')
    fallback=config.get('groq_fallback_model','qwen/qwen3.8-27b' if primary=='openai/gpt-oss-120b' else 'openai/gpt-oss-120b')
    models=[primary,primary]+([fallback] if fallback and fallback!=primary else [])
    last_error='Groq reply unavailable.'
    request_timeout=max(3,min(15,float(config.get('groq_timeout_seconds',5))))
    for attempt,model in enumerate(models):
        body={'model':model,'messages':messages,'stream':True,
              'response_format':{'type':'json_object'},'temperature':config.get('temperature',.3),
              'max_completion_tokens':config.get('groq_max_tokens',384)}
        strict=config.get('groq_strict_json',False)
        if strict:
            from expression import SPEECH_SCHEMA
            body.update(stream=False,response_format={'type':'json_schema','json_schema':{
                'name':'spoken_reply','strict':True,'schema':SPEECH_SCHEMA}})
        if model.startswith('qwen/'):
            body.update(reasoning_effort='none',reasoning_format='hidden')
        elif model.startswith('openai/gpt-oss-'):
            body.update(reasoning_effort='low',include_reasoning=False)
        delay=.2
        try:
            async with client.stream('POST','https://api.groq.com/openai/v1/chat/completions',
                    headers={'Authorization':'Bearer '+api_key()},json=body,
                    timeout=httpx.Timeout(request_timeout,connect=3)) as response:
                if response.status_code in (401,403):
                    raise PermissionError(f'Groq request failed (HTTP {response.status_code}). Check key and model access.')
                if response.status_code!=200:
                    try:delay=min(2,max(.2,float(response.headers.get('retry-after','.2'))))
                    except ValueError:pass
                    raise GroqError(f'Groq request failed (HTTP {response.status_code}).')
                done=False;parts=[];usage_metrics={}
                async for line in completion_lines(response,strict):
                    if not line.startswith('data:'):continue
                    data=line[5:].strip()
                    if data=='[DONE]':
                        done=True;break
                    event=json.loads(data)
                    if event.get('error'):
                        # Record only a bounded machine code; never provider text,
                        # failed_generation content, request headers or credentials.
                        code=event['error'].get('code','generation_error')
                        code=code if isinstance(code,str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',code) else 'generation_error'
                        raise GroqError('Groq generation failed ('+code+').')
                    for choice in event.get('choices',[]):
                        if choice.get('finish_reason')=='length':
                            raise GroqError('Groq reply exceeded its token limit.')
                        content=choice.get('delta',{}).get('content')
                        if content:parts.append(content)
                    usage=event.get('x_groq',{}).get('usage',{})
                    for name in ('prompt_time','completion_time','queue_time'):
                        if name in usage:usage_metrics['groq_'+name+'_ms']=round(usage[name]*1000)
                if not done:raise GroqError('Groq stream ended before completion.')
                from expression import EMOTIONS
                reply=json.loads(''.join(parts))
                if not isinstance(reply,dict) or reply.get('emotion') not in EMOTIONS or not isinstance(reply.get('text'),str) or not reply['text'].strip():
                    raise GroqError('Groq returned invalid speech JSON.')
                if metrics is not None:
                    metrics.update(usage_metrics,groq_attempts=attempt+1,llm_model=model,
                                   groq_recovered=attempt>0,groq_strict_json=strict)
                # Groq's short replies finish in a few hundred ms. Validate the
                # complete object before speech so a failed stream can be retried
                # without cancelling or duplicating a partly spoken answer.
                yield json.dumps({'emotion':reply['emotion'],'text':reply['text']},ensure_ascii=False)
                return
        except PermissionError as error:
            raise GroqError(str(error)) from None
        except (GroqError,httpx.HTTPError,ValueError) as error:
            last_error=str(error) if isinstance(error,GroqError) else 'Groq transport or JSON decoding failed.'
            if metrics is not None:metrics['groq_last_error']=last_error
            if attempt+1<len(models):await asyncio.sleep(delay)
    raise GroqError(last_error) from None


async def completion_lines(response,strict):
    """Normalize a complete constrained response into the existing SSE parser.

    The caller already buffers its short answer before speech. Strict schemas
    require non-streaming HTTP and avoid provider JSON-validation retries.
    """
    if not strict:
        async for line in response.aiter_lines():yield line
        return
    data=json.loads(await response.aread())
    if data.get('error'):
        yield 'data: '+json.dumps({'error':data['error']})
        return
    choices=data.get('choices',[])
    if not choices:raise GroqError('Groq returned no completion.')
    normalized={'choices':[{'delta':{'content':choice.get('message',{}).get('content')},
        'finish_reason':choice.get('finish_reason')} for choice in choices],
        'x_groq':{'usage':data.get('usage',{})}}
    yield 'data: '+json.dumps(normalized)
    yield 'data: [DONE]'
