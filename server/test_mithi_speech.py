import unittest
from unittest.mock import patch
import httpx
import numpy as np
from mithi_speech import MithiSpeech


class MithiClientTests(unittest.IsolatedAsyncioTestCase):
    def test_rejects_remote_worker_and_unknown_voice(self):
        for config in ({'mithi_url':'https://example.com'}, {'mithi_voice':'unknown'}):
            with self.assertRaises(ValueError):
                MithiSpeech(config)

    def test_mixed_script_and_tags_do_not_become_emotion_instructions(self):
        speech = MithiSpeech({})
        body = speech.request('<happy>আজ office-এ কাজ ছিল।\ue000', 'happy')
        self.assertEqual(body, {'text':'আজ office-এ কাজ ছিল।','voice':'malini','language':'bn'})
        self.assertEqual(speech.request('Hello there')['language'], 'en')

    async def test_float_audio_transports_as_contiguous_pcm(self):
        speech = MithiSpeech({})
        def respond(request):
            return httpx.Response(200, headers={'x-sample-rate':'24000'},
                                  content=np.array([-.25,0,.25],dtype='<f4').tobytes())
        speech.client=httpx.AsyncClient(transport=httpx.MockTransport(respond),base_url=speech.url)
        try:
            audio=[chunk async for chunk in speech.stream('Hello')]
            np.testing.assert_array_equal(np.frombuffer(audio[0],dtype='<i2'),[-8191,0,8191])
        finally:
            await speech.close()

    async def test_nonfinite_audio_is_rejected(self):
        speech=MithiSpeech({})
        speech.client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request:
            httpx.Response(200,headers={'x-sample-rate':'24000'},content=np.array([np.nan],dtype='<f4').tobytes())),base_url=speech.url)
        try:
            with self.assertRaises(ValueError):
                _=[chunk async for chunk in speech.stream('Hello')]
        finally:
            await speech.close()


if __name__=='__main__':
    unittest.main()
