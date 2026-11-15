import asyncio
import unittest
from unittest.mock import AsyncMock
from conversation_activity import keep_session_active


class ActivityTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_speech_refreshes_session_without_starting_playback(self):
        send=AsyncMock();done=asyncio.Event()
        task=asyncio.create_task(keep_session_active(send,done,interval=.01))
        await asyncio.sleep(.035)
        done.set();await asyncio.wait_for(task,1)
        self.assertGreaterEqual(send.await_count,1)
        for call in send.await_args_list:
            self.assertEqual(call.args,('tts',))
            self.assertEqual(call.kwargs,{'state':'preparing'})
        count=send.await_count
        await asyncio.sleep(.02)
        self.assertEqual(send.await_count,count)

    async def test_finished_turn_emits_no_heartbeat(self):
        send=AsyncMock();done=asyncio.Event();done.set()
        await keep_session_active(send,done,interval=.01)
        send.assert_not_awaited()


if __name__=='__main__':unittest.main()
