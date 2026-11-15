import unittest
from text_chunks import SpokenChunks


class MithiChunkTests(unittest.TestCase):
    def test_short_opening_keeps_following_sentence_and_all_words(self):
        text=' '.join('word'+str(i) for i in range(25))+'.'
        chunks=SpokenChunks(sentence_mode=True,max_sentence_words=12,first_sentence_words=6)
        result=chunks.feed(text)+chunks.finish()
        self.assertEqual(len(result[0].split()),6)
        self.assertLessEqual(max(map(lambda s:len(s.split()),result)),12)
        self.assertEqual(' '.join(result),text)

    def test_short_complete_sentence_keeps_its_punctuation(self):
        chunks=SpokenChunks(sentence_mode=True,max_sentence_words=12,first_sentence_words=6)
        self.assertEqual(chunks.feed('Hello there, welcome back!'),['Hello there, welcome back!'])


if __name__=='__main__':unittest.main()
