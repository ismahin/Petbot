import unittest
from unittest.mock import Mock, patch
import numpy as np
import mithi_worker as worker


class MithiWorkerTests(unittest.TestCase):
    def setUp(self):
        worker.CACHE.clear()
        self.model=Mock()
        self.model.synthesize.return_value=np.tile(np.array([.05,-.05],dtype=np.float32),2400)
        self.patch=patch.object(worker,'MODEL',self.model)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        worker.CACHE.clear()

    def test_voice_language_and_bypass_do_not_share_wrong_audio(self):
        request=worker.SpeechRequest(text='Hello',language='en')
        worker.synthesize(request)
        self.assertEqual(worker.synthesize(request).headers['x-cache'],'hit')
        worker.synthesize(request.model_copy(update={'language':'bn'}))
        worker.synthesize(request.model_copy(update={'voice':'ahana'}))
        worker.synthesize(request.model_copy(update={'cache_audio':False}))
        self.assertEqual(self.model.synthesize.call_count,4)

    def test_invalid_audio_never_enters_cache(self):
        for wave in (np.array([],dtype=np.float32),np.array([np.nan],dtype=np.float32)):
            self.model.synthesize.return_value=wave
            with self.assertRaises(ValueError):
                worker.synthesize(worker.SpeechRequest(text='Test'))
            self.assertFalse(worker.CACHE)

    def test_loudness_is_bounded_and_emotion_support_is_honest(self):
        self.model.synthesize.return_value=np.tile(np.array([1.,-1.],dtype=np.float32),2400)
        response=worker.synthesize(worker.SpeechRequest(text='Test'))
        self.assertLessEqual(float(np.max(np.abs(np.frombuffer(response.body,dtype='<f4')))),.90001)
        self.assertEqual(response.headers['x-emotion-control'],'none')


if __name__=='__main__':
    unittest.main()
