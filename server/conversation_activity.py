"""Keep the existing XIAO session alive while a slow local voice computes."""
import asyncio


async def keep_session_active(send, finished, interval=15):
    while not finished.is_set():
        try:
            await asyncio.wait_for(finished.wait(),timeout=interval)
        except asyncio.TimeoutError:
            # Current firmware touches its inactivity timer on every TTS event.
            # 'preparing' does not start playback or resend a transcription.
            await send('tts',state='preparing')
