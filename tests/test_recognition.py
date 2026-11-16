import unittest
from unittest.mock import patch
import numpy as np
from cloud.recognition import prepare
from audio import Utterances


class RecognitionTests(unittest.TestCase):
    def test_quiet_speech_gain_is_bounded_and_does_not_clip(self):
        audio=(np.sin(np.arange(16000)*.15)*.005+.08).astype(np.float32)
        pcm,metrics=prepare(audio)
        result=np.frombuffer(pcm,dtype='<i2')/32768
        self.assertEqual(len(result),16000)
        self.assertAlmostEqual(float(np.mean(result)),0,places=3)
        self.assertLessEqual(metrics['gain'],6)
        self.assertLess(float(np.max(np.abs(result))),.99)
        self.assertGreater(float(np.std(result)),float(np.std(audio)))

    def test_invalid_samples_are_rejected(self):
        for values in ([],[float('nan')],[float('inf')]):
            with self.assertRaises(ValueError):prepare(values)

    def test_a_half_second_pause_does_not_split_a_question(self):
        class VAD:
            def __init__(self,*args):pass
            def is_speech(self,frame,rate):return frame[0]!=0
        speech=(np.ones(320,dtype='<i2')*257).tobytes()
        quiet=np.zeros(320,dtype='<i2').tobytes()
        with patch('audio.webrtcvad.Vad',VAD):
            endpoint=Utterances({})
            self.assertIsNone(endpoint.feed(speech*20+quiet*25))
            self.assertIsNone(endpoint.feed(speech*20))
            result=endpoint.feed(quiet*35)
            self.assertIsNotNone(result)
            self.assertGreater(len(result),320*60)

    def test_short_yes_no_sized_answer_is_kept(self):
        class VAD:
            def __init__(self,*args):pass
            def is_speech(self,frame,rate):return frame[0]!=0
        speech=(np.ones(320,dtype='<i2')*257).tobytes()
        quiet=np.zeros(320,dtype='<i2').tobytes()
        with patch('audio.webrtcvad.Vad',VAD):
            self.assertIsNotNone(Utterances({}).feed(speech*7+quiet*35))
