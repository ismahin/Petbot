"""Provider outages must produce a spoken notice and release the listen gate."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import gateway
from groq_llm import GroqError

class Socket:
    def __init__(self):self.messages=[];self.audio=[]
    async def send_json(self,message):self.messages.append(message)
    async def send_bytes(self,packet):self.audio.append(packet)

class GatewayRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_exhausted_groq_attempts_are_explained_in_the_heard_language(self):
        for route in ('english','bangla'):
            with self.subTest(route=route):
                socket=Socket();spoken=[]
                async def reply(*args,**kwargs):
                    raise GroqError('Groq generation failed (json_validate_failed).')
                    yield
                async def chunks(phrase):
                    spoken.append(phrase)
                    yield np.zeros(1440,dtype='<i2')
                model=SimpleNamespace(transcribe=lambda audio:'Test question',last_asr_route={'asr_route':route},
                    heard_message=lambda text:text,reply_phrases=reply,synthesize_chunks=chunks,
                    speech=SimpleNamespace(backend='mithi'))
                conversation=gateway.Conversation(socket);conversation.busy=True
                with patch.object(gateway,'MODEL',model),patch.object(gateway.LOGGER,'warning'),\
                     patch.object(gateway.LOGGER,'info'),patch('pathlib.Path.open'):
                    await conversation.respond(np.zeros(1600,np.float32))
                self.assertFalse(conversation.busy)
                self.assertTrue(socket.audio)
                self.assertEqual(len(spoken),1)
                self.assertEqual(spoken[0].emotion,'neutral')
                self.assertIn('Could you ask' if route=='english' else 'আর একবার',spoken[0].text)
                self.assertEqual(socket.messages[-1]['state'],'stop')
                self.assertFalse(any(message['type']=='error' for message in socket.messages))

if __name__=='__main__':unittest.main()
