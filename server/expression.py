"""Parse optional model-chosen emotion tags before clause splitting or playback."""
from dataclasses import dataclass
import json
import re
from text_chunks import SpokenChunks

EMOTIONS = {'neutral','happy','sad','angry','caring','excited','playful','curious','surprised'}
SPEECH_SCHEMA = {'type':'object','properties':{
    'emotion':{'type':'string','enum':sorted(EMOTIONS)},'text':{'type':'string'}},
    'required':['emotion','text'],'additionalProperties':False}


@dataclass(frozen=True)
class SpokenPhrase:
    text: str
    emotion: str = 'neutral'


class ExpressiveChunks:
    def __init__(self, **options):
        self.chunks = SpokenChunks(**options)
        self.emotion = 'neutral'
        self.tag = None

    def feed(self, token):
        result = []
        plain = ''
        for char in token:
            if self.tag is not None:
                if char == '>':
                    tag = self.tag.strip().lower()
                    self.tag = None
                    if tag.startswith('/'):
                        tag = 'neutral'
                    if tag == 'haapy':
                        tag = 'happy'
                    if tag in EMOTIONS:
                        result.extend(SpokenPhrase(p, self.emotion) for p in self.chunks.finish())
                        self.emotion = tag
                elif len(self.tag) < 64:
                    self.tag += char
                continue
            if char == '<':
                if plain:
                    result.extend(SpokenPhrase(p,self.emotion) for p in self.chunks.feed(plain))
                    plain = ''
                self.tag = ''
            else:
                plain += char
        if plain:
            result.extend(SpokenPhrase(p,self.emotion) for p in self.chunks.feed(plain))
        return result

    def finish(self):
        self.tag = None  # Never pronounce an incomplete/unknown tag.
        return [SpokenPhrase(p,self.emotion) for p in self.chunks.finish()]


class JsonSpeechChunks:
    """Extract only safe spoken text from incrementally generated structured output.

    The LLM chooses a delivery, including neutral, on every turn. Neutral applies
    no emotional steering. The choice becomes the same silent tag understood by
    ExpressiveChunks; JSON syntax is never sent to the speaker or display.
    """
    def __init__(self, **options):
        self.chunks=ExpressiveChunks(**options)
        self.raw=''
        self.started=False
        self.emitted=0

    def feed(self, token):
        self.raw+=token
        if not self.started:
            match=re.search(r'"emotion"\s*:\s*("(?:[^"\\]|\\.)*")',self.raw)
            if not match:
                return []
            emotion=json.loads(match[1])
            self.chunks.feed('<'+(emotion if emotion in EMOTIONS else 'neutral')+'>')
            self.started=True
        match=re.search(r'"text"\s*:\s*"',self.raw)
        if not match:
            return []
        prefix=re.match(r'(?:[^"\\]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*',self.raw[match.end():])[0]
        text=json.loads('"'+prefix+'"')
        if text and 0xD800 <= ord(text[-1]) <= 0xDBFF:
            text=text[:-1]
        delta=text[self.emitted:]
        self.emitted=len(text)
        return self.chunks.feed(delta)

    def finish(self):
        return self.chunks.finish()
