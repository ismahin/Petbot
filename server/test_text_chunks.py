import unittest
from text_chunks import SpokenChunks


class StreamingSpeechTests(unittest.TestCase):
    def test_speech_word_cap_does_not_leave_an_unstable_tiny_tail(self):
        text='one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen.'
        stream=SpokenChunks(sentence_mode=True,split_commas=True,max_sentence_words=14,
                            min_sentence_words=6,min_clause_words=6)
        phrases=stream.feed(text,now=0)+stream.finish()
        self.assertEqual([len(p.split()) for p in phrases],[12,6])
        self.assertEqual(' '.join(phrases),text)

    def test_speech_chunks_at_a_natural_clause_before_oversized_sentence(self):
        text='আজ সারাদিন কাজ করে তুমি অনেক ক্লান্ত হয়েছো, তাই একটু পানি খেয়ে বিশ্রাম নাও এবং আরাম করো।'
        stream=SpokenChunks(sentence_mode=True,split_commas=True,max_sentence_words=14,
                            min_sentence_words=6,min_clause_words=6)
        phrases=stream.feed(text,now=0)+stream.finish()
        self.assertEqual(len(phrases),2)
        self.assertTrue(phrases[0].endswith(','))
        self.assertTrue(all(len(phrase.split())<=14 for phrase in phrases))
        self.assertEqual(' '.join(phrases),text)

    def test_speech_keeps_short_acknowledgment_with_following_content(self):
        stream=SpokenChunks(sentence_mode=True,split_commas=True,max_sentence_words=14,
                            min_sentence_words=6,min_clause_words=6)
        self.assertEqual(stream.feed('I feel good today. ',now=0),[])
        self.assertEqual(stream.feed('Tell me about your day.',now=0),
                         ['I feel good today. Tell me about your day.'])

    def test_bangla_is_preserved_across_token_boundaries(self):
        text='হ্যালো মাহিন, তোমার সঙ্গে কথা বলতে ভালো লাগছে। তুমি আজ কী করেছো?'
        for width in [1,2,7,100]:
            stream=SpokenChunks(); phrases=[]
            for start in range(0,len(text),width):
                phrases.extend(stream.feed(text[start:start+width],now=0))
            phrases.extend(stream.finish())
            self.assertEqual(''.join(''.join(phrases).split()),''.join(text.split()))

    def test_speaks_before_a_long_sentence_finishes(self):
        stream=SpokenChunks()
        output=[]
        for token in ['আমি ','আজ ','তোমার ','সঙ্গে ','অনেক ','সুন্দর ','একটি ','গল্প ']:
            output.extend(stream.feed(token,now=0))
        self.assertTrue(output)
        self.assertLess(len(output[0].split()),9)

    def test_numbers_are_not_spoken_as_separate_sentences(self):
        stream=SpokenChunks()
        self.assertEqual(stream.feed('মান হলো 3.',now=0),[])
        self.assertEqual(stream.feed('14 এবং ঠিক আছে।',now=0),['মান হলো 3.14 এবং ঠিক আছে।'])

    def test_punctuation_only_output_does_not_trigger_tts(self):
        stream=SpokenChunks()
        self.assertEqual(stream.feed('!\n'),[])
        self.assertEqual(stream.finish(),[])

    def test_native_voice_keeps_comma_clauses_together(self):
        stream=SpokenChunks(split_commas=False,first_words=20)
        self.assertEqual(stream.feed('My day was good, ',now=0),[])
        self.assertEqual(stream.feed('thanks for asking.',now=0),['My day was good, thanks for asking.'])

    def test_sentence_mode_does_not_cut_on_timer_or_short_word_budget(self):
        stream=SpokenChunks(sentence_mode=True,split_commas=False,first_words=3,first_wait=.1)
        self.assertEqual(stream.feed('আজ অফিসে অনেক কাজ ছিল, ',now=0),[])
        self.assertEqual(stream.feed('তাই একটু বিশ্রাম নাও',now=10),[])
        self.assertEqual(stream.feed('।',now=11),['আজ অফিসে অনেক কাজ ছিল, তাই একটু বিশ্রাম নাও।'])

    def test_short_backchannel_stays_with_its_response(self):
        for width in (1,3,100):
            stream=SpokenChunks(sentence_mode=True,split_commas=False)
            text='ওহ! তোমার জন্য খুব খুশি।'
            phrases=[]
            for start in range(0,len(text),width):
                phrases+=stream.feed(text[start:start+width],now=0)
            phrases+=stream.finish()
            self.assertEqual(phrases,[text])

    def test_short_complete_reply_and_long_unpunctuated_reply_are_not_lost(self):
        stream=SpokenChunks(sentence_mode=True,max_sentence_words=5)
        self.assertEqual(stream.feed('আমি ডেস্কটার।',now=0),[])
        self.assertEqual(stream.finish(),['আমি ডেস্কটার।'])
        self.assertTrue(stream.feed('one two three four five six seven ',now=0))

if __name__=='__main__': unittest.main()
