import unittest
import numpy as np
from speech_audio import trim_padding

class PaddingTests(unittest.TestCase):
    def test_edge_padding_is_shortened_without_removing_internal_pause(self):
        speech=np.r_[np.full(2400,.1,np.float32),np.zeros(2400,np.float32),np.full(2400,-.1,np.float32)]
        wave=np.r_[np.zeros(4800,np.float32),speech,np.zeros(4800,np.float32)]
        result=trim_padding(wave)
        self.assertLess(len(result),len(wave))
        np.testing.assert_array_equal(result[1200:1200+len(speech)],speech)
        self.assertEqual(len(result),len(speech)+1200+1920)

    def test_quiet_onsets_are_preserved(self):
        quiet=np.full(2400,.0004,np.float32)
        speech=np.r_[quiet,np.full(4800,.1,np.float32)]
        result=trim_padding(np.r_[np.zeros(4800,np.float32),speech,np.zeros(4800,np.float32)])
        np.testing.assert_array_equal(result[1200:1200+len(speech)],speech)

    def test_silence_short_clips_and_maximum_trim_are_bounded(self):
        for wave in (np.zeros(24000,np.float32),np.ones(24,np.float32)*.1):
            np.testing.assert_array_equal(trim_padding(wave),wave)
        wave=np.r_[np.zeros(24000,np.float32),np.full(2400,.1,np.float32),np.zeros(24000,np.float32)]
        result=trim_padding(wave)
        self.assertGreaterEqual(len(result),len(wave)-int(24000*.95))
        self.assertTrue(np.isfinite(result).all())

if __name__=='__main__':unittest.main()
