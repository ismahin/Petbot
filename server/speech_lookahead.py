"""Bounded initial look-ahead while the independent synthesizer keeps running."""
import asyncio
from collections import deque
import time

def initial_reserve(planned_words,first_timing,minimum=.65,maximum=6.0):
    """Estimate cumulative production deficit, rather than adding silence later.

    This cannot make a slow model real-time. It moves a bounded amount of its
    unavoidable wait before speech, while generation and playback still overlap.
    """
    if len(planned_words)<2 or not first_timing:return 0
    first_words=max(1,first_timing['words'])
    duration=first_timing['audio_ms']/1000
    generated=first_timing['generation_ms']/1000
    if duration<=0:return minimum
    audio_per_word=duration/first_words
    # Cached first phrases say nothing about the cost of the next new phrase.
    rtf=max(1.25,generated/duration) if generated<.1 else generated/duration
    overhead=min(.6,generated*.2) if generated>=.1 else .6
    production=0;playback=duration;deficit=0
    for words in planned_words[1:]:
        audio=words*audio_per_word
        production+=overhead+max(0,rtf-overhead/duration)*audio
        deficit=max(deficit,production-playback)
        playback+=audio
    return min(maximum,max(minimum,deficit+.25))

async def lookahead_audio(queue,lead_seconds=0,metrics=None):
    item=await queue.get()
    if item is None:return
    pending=deque([item]);finished=False
    began=time.perf_counter()
    lead_seconds=lead_seconds() if callable(lead_seconds) else lead_seconds
    # Short reserve before the first audio, not a pause at every chunk. A
    # single-chunk reply ends the reserve immediately when its sentinel arrives.
    if lead_seconds>0:
        try:
            async with asyncio.timeout(lead_seconds):
                while True:
                    item=await queue.get()
                    if item is None:finished=True;break
                    pending.append(item)
                    if len(pending)>=4:break
        except TimeoutError:pass
    if metrics is not None:
        metrics['tts_lookahead_target_ms']=round(lead_seconds*1000)
        metrics['tts_lookahead_wait_ms']=round((time.perf_counter()-began)*1000)
    while pending:
        yield pending.popleft()
    if not finished:
        while (item:=await queue.get()) is not None:yield item
