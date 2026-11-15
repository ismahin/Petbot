"""Arbitrary streamed PCM boundaries must not insert silence or lose samples."""
import unittest
import numpy as np
from audio import OpusOutput

class StreamCodecTests(unittest.TestCase):
    def test_streamed_chunks_match_whole_waveform_packets(self):
        time=np.arange(17321)/24000
        pcm=(np.sin(time*2*np.pi*317)*6000).astype('<i2')
        whole=OpusOutput(); expected=list(whole.encode(pcm))+whole.finish()
        for size in [1,137,1440,1600,5000]:
            stream=OpusOutput(); actual=[]
            for start in range(0,len(pcm),size):
                actual.extend(stream.encode(pcm[start:start+size]))
            actual.extend(stream.finish())
            self.assertEqual(actual,expected)

    def test_incomplete_frame_is_buffered_until_finish(self):
        stream=OpusOutput()
        self.assertEqual(list(stream.encode(np.zeros(100,dtype='<i2'))),[])
        self.assertTrue(stream.finish())

if __name__=='__main__': unittest.main()
