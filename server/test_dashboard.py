import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import httpx

from dashboard import create_dashboard


class DashboardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root/'private').mkdir()
        (self.root/'persona.txt').write_text('You are a helpful companion.', encoding='utf8')
        self.config = {'device_token':'do-not-expose', 'groq_api_key':'private-test-key',
                       'tts_backend':'mithi', 'mithi_voice':'malini'}
        (self.root/'private/config.json').write_text(json.dumps(self.config), encoding='utf8')
        self.model = SimpleNamespace(persona='', speech=SimpleNamespace(voice=SimpleNamespace(voice='malini', volume=100)))
        self.state = SimpleNamespace(CONFIG=self.config, MODEL=self.model,
            ACTIVE_CONVERSATION=None, DEVICE_LOCK=__import__('asyncio').Lock(),
            model_name=lambda config:'test-model')
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_dashboard(self.state,self.root)), base_url='http://127.0.0.1:8787')
        self.headers = {'X-Deskter-Panel':'1', 'Origin':'http://127.0.0.1:8787'}

    async def asyncTearDown(self):
        await self.client.aclose()
        self.tmp.cleanup()

    async def body(self):
        data = (await self.client.get('/api/settings')).json()
        return {key:data[key] for key in ('revision','settings')}

    async def test_read_redacts_credentials_and_lists_every_voice(self):
        response = await self.client.get('/api/settings')
        self.assertNotIn('do-not-expose',response.text)
        self.assertNotIn('private-test-key',response.text)
        self.assertEqual(len(response.json()['voices']),10)
        self.assertEqual(response.json()['settings']['mithi_voice'],'malini')

    async def test_save_persists_applies_and_preserves_private_fields(self):
        body = await self.body()
        body['settings'].update(system_prompt='Be a thoughtful Bangla companion.', mithi_voice='ahana', speech_volume=80)
        response = await self.client.put('/api/settings',json=body,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        disk=json.loads((self.root/'private/config.json').read_text(encoding='utf8'))
        self.assertEqual(disk['device_token'],'do-not-expose')
        self.assertEqual(disk['mithi_voice'],'ahana')
        self.assertEqual(self.model.speech.voice.volume,80)
        self.assertEqual(self.model.persona,body['settings']['system_prompt'])
        stale=await self.client.put('/api/settings',json=body,headers=self.headers)
        self.assertEqual(stale.status_code,409)

    async def test_rejects_cross_origin_and_dns_rebinding_and_missing_header(self):
        body=await self.body()
        for headers in ({'Origin':'https://evil.example','X-Deskter-Panel':'1'}, {'Host':'evil.example:8787'}, {}):
            response=await self.client.put('/api/settings',json=body,headers=headers)
            self.assertEqual(response.status_code,403)
        response=await self.client.get('/api/settings',headers={'Sec-Fetch-Site':'cross-site'})
        self.assertEqual(response.status_code,403)

    async def test_validates_ranges_unknown_keys_and_voice(self):
        for key,value in [('speech_volume',101), ('mithi_voice','fake'), ('device_token','overwrite'), ('silence_ms',201)]:
            body=await self.body();body['settings'][key]=value
            response=await self.client.put('/api/settings',json=body,headers=self.headers)
            self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(self.config['device_token'],'do-not-expose')

    async def test_busy_reply_blocks_settings_and_preview(self):
        self.state.ACTIVE_CONVERSATION=SimpleNamespace(busy=True)
        response=await self.client.put('/api/settings',json=await self.body(),headers=self.headers)
        self.assertEqual(response.status_code,409)
        response=await self.client.post('/api/preview',json={'voice':'malini','text':'Hello'},headers=self.headers)
        self.assertEqual(response.status_code,409)


if __name__=='__main__':
    unittest.main()
