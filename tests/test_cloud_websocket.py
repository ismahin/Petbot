import asyncio
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import numpy as np
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from cloud.app import app
from cloud.security import LOCAL_RATES


class CloudWebSocketTests(unittest.TestCase):
    def setUp(self):
        LOCAL_RATES.clear()
        self.env=patch.dict(os.environ,{'DESKTER_DEVICE_KEY':'test-device-'+'x'*40})
        self.env.start()
        self.storage=SimpleNamespace(ready=False)
        self.patches=[patch('cloud.websocket.store',self.storage),patch('cloud.security.store',self.storage),patch('cloud.app.store',self.storage)]
        for p in self.patches:p.start()

    def tearDown(self):
        for p in self.patches:p.stop()
        self.env.stop()

    def test_unauthenticated_websocket_is_rejected(self):
        with TestClient(app) as client:
            with self.assertRaises(WebSocketDisconnect) as error:
                with client.websocket_connect('/xiaozhi/v1/'):
                    pass
            self.assertEqual(error.exception.code,1008)

    def test_hello_real_opus_transport_and_reply_completion(self):
        from audio import OpusOutput
        class Segmenter:
            def __init__(self,*args): pass
            def reset(self): pass
            def feed(self,pcm): return np.zeros(16000,np.float32)
        packet=next(iter(OpusOutput(rate=16000).encode(np.zeros(960,dtype='<i2'))))
        headers={'Authorization':'Bearer '+os.environ['DESKTER_DEVICE_KEY']}
        with patch('cloud.provider.recognize',AsyncMock(return_value={'text':'A test question','metadata':{'model':'whisper-large-v3'}})),\
             patch('cloud.provider.chat',AsyncMock(return_value={'text':'A test reply.','emotion':'neutral'})),\
             patch('cloud.runtime.pcm',AsyncMock(return_value=np.zeros(2400,dtype='<i2').tobytes())),\
             patch('audio.Utterances',Segmenter),TestClient(app) as client:
            with client.websocket_connect('/xiaozhi/v1/',headers=headers) as socket:
                socket.send_json({'type':'hello','audio_params':{'format':'opus','sample_rate':16000,'channels':1}})
                hello=socket.receive_json()
                self.assertEqual(hello['audio_params']['sample_rate'],24000)
                socket.send_json({'type':'listen','state':'start'})
                socket.send_bytes(packet)
                messages=[];audio=[]
                for _ in range(16):
                    event=socket.receive()
                    if event.get('bytes'):
                        audio.append(event['bytes'])
                    elif event.get('text'):
                        import json
                        message=json.loads(event['text']);messages.append(message)
                        if message.get('type')=='tts' and message.get('state')=='stop':break
                self.assertTrue(audio)
                self.assertEqual((messages[0]['type'],messages[0]['state']),('tts','preparing'))
                self.assertTrue(any(m.get('type')=='stt' for m in messages))
                self.assertEqual(messages[-1]['state'],'stop')


if __name__=='__main__':unittest.main()
