"""Raw Opus packets matching the XIAO: mono 16 kHz in, 24 kHz out."""
from collections import deque
from fractions import Fraction
import struct
import av
import numpy as np
import webrtcvad


class OpusInput:
    def __init__(self):
        self.codec = av.CodecContext.create("opus", "r")
        self.codec.extradata = b"OpusHead" + struct.pack("<BBHIhB", 1, 1, 0, 16000, 0, 0)
        self.codec.open()
        self.resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)

    def decode(self, packet):
        frames = self.codec.decode(av.Packet(packet))
        return b"".join(f.to_ndarray().astype("<i2").tobytes()
                        for frame in frames for f in self.resampler.resample(frame))


class OpusOutput:
    def __init__(self, rate=24000, bitrate=48000):
        self.rate = rate
        self.pts = 0
        self.pending = np.empty(0,dtype='<i2')
        self.codec = av.CodecContext.create("libopus", "w")
        self.codec.sample_rate = rate
        self.codec.layout = "mono"
        self.codec.format = "s16"
        self.codec.bit_rate = bitrate
        self.codec.options = {"application": "audio", "frame_duration": "60", "compression_level": "5"}
        self.codec.open()

    def encode(self, pcm):
        pcm = np.asarray(pcm, dtype="<i2").reshape(-1)
        if self.pending.size:
            pcm=np.concatenate((self.pending,pcm))
        count = self.rate * 60 // 1000
        complete=len(pcm)//count*count
        self.pending=pcm[complete:].copy()
        for start in range(0,complete,count):
            yield from self._frame(pcm[start:start+count])

    def _frame(self, pcm):
        frame = av.AudioFrame.from_ndarray(pcm[None, :], format="s16", layout="mono")
        frame.sample_rate = self.rate
        frame.time_base = Fraction(1, self.rate)
        frame.pts = self.pts
        self.pts += len(pcm)
        for packet in self.codec.encode(frame):
            yield bytes(packet)

    def finish(self):
        result=[]
        if self.pending.size:
            count=self.rate*60//1000
            result.extend(self._frame(np.pad(self.pending,(0,count-len(self.pending)))))
            self.pending=np.empty(0,dtype='<i2')
        return result+[bytes(packet) for packet in self.codec.encode(None)]


class Utterances:
    """20 ms VAD; pre-roll, short-sound rejection and bounded utterances."""
    def __init__(self, config):
        self.vad = webrtcvad.Vad(config.get("vad_mode", 2))
        self.silence_frames = max(10, config.get("silence_ms", 500) // 20)
        self.limit = int(config.get("max_utterance_seconds", 12) * 50)
        self.reset()

    def reset(self):
        self.pending = bytearray()
        self.pre = deque(maxlen=10)
        self.votes = deque(maxlen=5)
        self.frames = []
        self.silent = self.voiced = 0

    def feed(self, pcm):
        self.pending.extend(pcm)
        while len(self.pending) >= 640:
            frame = bytes(self.pending[:640])
            del self.pending[:640]
            speech = self.vad.is_speech(frame, 16000)
            if not self.frames:
                self.pre.append(frame)
                self.votes.append(speech)
                if len(self.votes) == 5 and sum(self.votes) >= 3:
                    self.frames = list(self.pre)
                    self.voiced = sum(self.votes)
                continue
            self.frames.append(frame)
            self.voiced += int(speech)
            self.silent = 0 if speech else self.silent + 1
            if self.silent >= self.silence_frames or len(self.frames) >= self.limit:
                # Keep 100 ms of trailing silence rather than the entire hangover.
                keep = len(self.frames) - max(0, self.silent - 5)
                result = b"".join(self.frames[:keep]) if self.voiced >= 10 else None
                self.reset()
                if result:
                    return np.frombuffer(result, dtype="<i2").astype(np.float32) / 32768.0
        return None
