"""Mithi is the sole local speech synthesis backend."""
from mithi_speech import MithiSpeech


class Speech:
    def __init__(self, config):
        if config.get('tts_backend', 'mithi') != 'mithi':
            raise ValueError('Only the Mithi speech backend is installed')
        self.backend = 'mithi'
        self.voice = MithiSpeech(config)

    def synthesize(self, text):
        return self.voice.synthesize(text)
