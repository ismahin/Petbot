import asyncio
import time
import unittest
from speech_lookahead import lookahead_audio,initial_reserve

class LookaheadTests(unittest.IsolatedAsyncioTestCase):
    def test_reserve_covers_cumulative_slow_model_deficit_but_is_bounded(self):
        first={'words':10,'generation_ms':4000,'audio_ms':3000}
        self.assertGreater(initial_reserve([10,10,10],first),2)
        self.assertEqual(initial_reserve([10]*30,first),6)
        self.assertEqual(initial_reserve([10],first),0)
        self.assertEqual(initial_reserve([10,10],{'words':10,'generation_ms':2000,'audio_ms':3000}),.65)

    async def test_single_chunk_has_no_artificial_start_delay(self):
        queue=asyncio.Queue();await queue.put('only');await queue.put(None)
        began=time.perf_counter()
        items=[item async for item in lookahead_audio(queue,1.5)]
        self.assertEqual(items,['only'])
        self.assertLess(time.perf_counter()-began,.1)

    async def test_next_chunk_generates_during_playback_in_order(self):
        queue=asyncio.Queue(4);events=[]
        async def synthesize():
            await queue.put('first')
            events.append('generating second')
            await asyncio.sleep(.04)
            events.append('second ready');await queue.put('second');await queue.put(None)
        task=asyncio.create_task(synthesize());items=[]
        async for item in lookahead_audio(queue,.01):
            items.append(item)
            events.append('playing '+item)
            if item=='first':
                await asyncio.sleep(.08)
                events.append('first finished')
        await task
        self.assertEqual(items,['first','second'])
        self.assertLess(events.index('second ready'),events.index('first finished'))

    async def test_short_reserve_covers_predictable_synthesis_gap(self):
        queue=asyncio.Queue(4)
        async def synthesize():
            await queue.put(1)
            await asyncio.sleep(.10)
            await queue.put(2);await queue.put(None)
        task=asyncio.create_task(synthesize());items=[];starvation=[];deadline=None
        async for item in lookahead_audio(queue,.05):
            now=time.perf_counter()
            if deadline is not None:starvation.append(max(0,now-deadline))
            items.append(item);deadline=now+.08
            await asyncio.sleep(.08)
        await task
        self.assertEqual(items,[1,2]);self.assertLess(max(starvation),.04)

    async def test_cancelled_consumer_does_not_eat_a_future_chunk(self):
        queue=asyncio.Queue();await queue.put('first')
        async def consume():return [item async for item in lookahead_audio(queue,1)]
        task=asyncio.create_task(consume());await asyncio.sleep(.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        await queue.put('second');self.assertEqual(await queue.get(),'second')

if __name__=='__main__':unittest.main()
