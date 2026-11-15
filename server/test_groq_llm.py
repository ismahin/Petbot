import json
import unittest
from unittest.mock import patch,AsyncMock
import httpx
from groq_llm import tokens,GroqError


def stream(*events,done=True):
    data=''.join('data: '+json.dumps(event)+'\n\n' for event in events)
    return data+('data: [DONE]\n\n' if done else '')


class GroqTests(unittest.IsolatedAsyncioTestCase):
    async def test_strict_nonstreaming_completion_obeys_schema_and_hides_reasoning(self):
        def handler(request):
            body=json.loads(request.content)
            self.assertFalse(body['stream'])
            schema=body['response_format']['json_schema']
            self.assertTrue(schema['strict'])
            self.assertFalse(schema['schema']['additionalProperties'])
            return httpx.Response(200,json={'choices':[{'message':{
                'reasoning':'PRIVATE','content':'{"text":"Hello!","emotion":"happy"}'},'finish_reason':'stop'}],
                'usage':{'completion_time':.1}})
        metrics={}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with patch('groq_llm.api_key',return_value='test-credential'):
                parts=[p async for p in tokens(client,{'groq_strict_json':True},
                    [{'role':'user','content':'Hi'}],metrics)]
        self.assertEqual(json.loads(''.join(parts)),{'emotion':'happy','text':'Hello!'})
        self.assertNotIn('PRIVATE',''.join(parts))
        self.assertTrue(metrics['groq_strict_json'])
        self.assertEqual(metrics['groq_completion_time_ms'],100)

    async def collect(self,handler):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with patch('groq_llm.api_key',return_value='test-credential'):
                return ''.join([p async for p in tokens(client,{},[{'role':'user','content':'Hi'}])])

    async def test_stream_uses_groq_auth_and_never_speaks_reasoning(self):
        def handler(request):
            self.assertEqual(request.url.host,'api.groq.com')
            self.assertEqual(request.headers['authorization'],'Bearer test-credential')
            body=json.loads(request.content)
            self.assertEqual(body['reasoning_effort'],'none')
            self.assertEqual(body['response_format'],{'type':'json_object'})
            return httpx.Response(200,text=stream(
                {'choices':[{'delta':{'reasoning':'INTERNAL ONLY','content':'{"emotion":"happy",'}}]},
                {'choices':[{'delta':{'content':'"text":"Hello!"}'}}]}))
        result=await self.collect(handler)
        self.assertNotIn('INTERNAL',result)
        self.assertEqual(json.loads(result)['emotion'],'happy')

    async def test_rate_limit_retries_before_text_only(self):
        count=0
        def handler(request):
            nonlocal count
            count+=1
            if count==1:return httpx.Response(429,headers={'retry-after':'1'})
            return httpx.Response(200,text=stream({'choices':[{'delta':{
                'content':'{"emotion":"neutral","text":"Hello."}'}}]}))
        with patch('groq_llm.asyncio.sleep',new_callable=AsyncMock):await self.collect(handler)
        self.assertEqual(count,2)

    async def test_provider_errors_are_redacted(self):
        def handler(request):return httpx.Response(401,text='provider echoed test-credential')
        with self.assertRaises(GroqError) as error:await self.collect(handler)
        self.assertNotIn('test-credential',str(error.exception))
        self.assertIn('401',str(error.exception))

    async def test_interrupted_reply_is_buffered_and_retried_without_duplicate_speech(self):
        count=0
        def handler(request):
            nonlocal count
            count+=1
            if count==1:
                return httpx.Response(200,text=stream({'choices':[{'delta':{'content':'{"emotion":"happy",'}}]},done=False))
            return httpx.Response(200,text=stream({'choices':[{'delta':{
                'content':'{"emotion":"happy","text":"Hello!"}'}}]}))
        with patch('groq_llm.asyncio.sleep',new_callable=AsyncMock):
            result=await self.collect(handler)
        self.assertEqual(json.loads(result)['text'],'Hello!')
        self.assertEqual(count,2)

    async def test_invalid_emotion_is_rejected(self):
        def handler(request):return httpx.Response(200,text=stream({'choices':[{'delta':{
            'content':'{"emotion":"unsupported","text":"Hello."}'}}]}))
        with patch('groq_llm.asyncio.sleep',new_callable=AsyncMock):
            with self.assertRaises(GroqError):await self.collect(handler)

    async def test_stream_generation_error_uses_fallback_after_bounded_retries(self):
        models=[]
        def handler(request):
            model=json.loads(request.content)['model'];models.append(model)
            if len(models)<3:
                return httpx.Response(200,text=stream({'error':{'code':'json_validate_failed',
                    'message':'private failed generation test-credential'}}))
            return httpx.Response(200,text=stream({'choices':[{'delta':{
                'content':'{"emotion":"neutral","text":"Recovered."}'}}]}))
        with patch('groq_llm.asyncio.sleep',new_callable=AsyncMock):
            result=await self.collect(handler)
        self.assertEqual(models,['qwen/qwen3.8-27b','qwen/qwen3.8-27b','openai/gpt-oss-120b'])
        self.assertEqual(json.loads(result)['text'],'Recovered.')
        self.assertNotIn('test-credential',result)

    async def test_failed_attempt_never_emits_partial_text(self):
        def handler(request):
            return httpx.Response(200,text=stream(
                {'choices':[{'delta':{'content':'{"emotion":"happy","text":"WRONG PARTIAL'}}]},
                {'error':{'code':'json_validate_failed','message':'private text'}}))
        emitted=[]
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with patch('groq_llm.api_key',return_value='test-credential'),patch('groq_llm.asyncio.sleep',new_callable=AsyncMock):
                with self.assertRaises(GroqError):
                    async for part in tokens(client,{},[{'role':'user','content':'Hi'}]):emitted.append(part)
        self.assertEqual(emitted,[])

    async def test_emotion_is_always_delivered_before_spoken_text(self):
        def handler(request):
            return httpx.Response(200,text=stream({'choices':[{'delta':{
                'content':'{"text":"Great news!","emotion":"happy"}'}}]}))
        result=await self.collect(handler)
        self.assertLess(result.index('emotion'),result.index('text'))


if __name__=='__main__':unittest.main()
