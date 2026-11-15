import unittest
from expression import ExpressiveChunks, JsonSpeechChunks


class EmotionStreamTests(unittest.TestCase):
    def test_tags_split_across_any_token_boundary(self):
        text='<happy>তুমি এসেছো! <neutral>How was your day?'
        for width in (1,2,5,100):
            parser=ExpressiveChunks(first_words=30)
            phrases=[]
            for start in range(0,len(text),width):
                phrases.extend(parser.feed(text[start:start+width]))
            phrases.extend(parser.finish())
            self.assertEqual([(p.text,p.emotion) for p in phrases],
                             [('তুমি এসেছো!','happy'),('How was your day?','neutral')])

    def test_emotion_is_optional_and_resets_per_reply(self):
        parser=ExpressiveChunks()
        phrases=parser.feed('হুম, আজ একটু বিশ্রাম নাও।')+parser.finish()
        self.assertTrue(phrases)
        self.assertTrue(all(p.emotion=='neutral' for p in phrases))

    def test_unknown_and_unfinished_tags_never_reach_speech(self):
        parser=ExpressiveChunks()
        phrases=parser.feed('<nonsense>Hi there. <happy')+parser.finish()
        self.assertEqual(' '.join(p.text for p in phrases),'Hi there.')

    def test_style_changes_flush_the_preceding_text_with_its_original_style(self):
        parser=ExpressiveChunks(first_words=30)
        phrases=parser.feed('<sad>খারাপ লাগছে <caring>আমি তোমার পাশে আছি।')+parser.finish()
        self.assertEqual([p.emotion for p in phrases],['sad','caring'])

    def test_json_fragments_and_escaped_quotes_never_leak_syntax(self):
        import json
        for ascii_only in (False,True):
            text='হুম, তুমি "ভালো" আছো? How was work?'
            raw=json.dumps({'emotion':'caring','text':text},ensure_ascii=ascii_only)
            for width in (1,2,7,100):
                parser=JsonSpeechChunks(first_words=30);phrases=[]
                for start in range(0,len(raw),width):phrases.extend(parser.feed(raw[start:start+width]))
                phrases.extend(parser.finish())
                self.assertEqual(' '.join(p.text for p in phrases),text)
                self.assertTrue(all(p.emotion=='caring' for p in phrases))

    def test_text_before_emotion_is_buffered_until_style_known(self):
        parser=JsonSpeechChunks()
        self.assertEqual(parser.feed('{"text":"Hello there!",'),[])
        phrases=parser.feed('"emotion":"happy"}')+parser.finish()
        self.assertEqual([(p.text,p.emotion) for p in phrases],[('Hello there!','happy')])


if __name__=='__main__':unittest.main()
