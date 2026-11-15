"""Durable REST Redis; no mutable settings or API keys in ephemeral files."""
import os
import httpx
from fastapi import HTTPException


class Store:
    def __init__(self):
        self.client = None
    @property
    def ready(self):
        return bool(os.getenv('KV_REST_API_URL') and os.getenv('KV_REST_API_TOKEN'))

    async def command(self, *args):
        if not self.ready:
            raise HTTPException(503, 'Configure KV_REST_API_URL and KV_REST_API_TOKEN for durable settings and device management.')
        url = os.environ['KV_REST_API_URL']
        if not url.startswith('https://'):
            raise HTTPException(503, 'Redis REST storage must use HTTPS.')
        try:
            if self.client is None:
                self.client = httpx.AsyncClient(trust_env=False, timeout=5,
                    limits=httpx.Limits(max_connections=8,max_keepalive_connections=4))
            response = await self.client.post(url, json=list(args), headers={
                'Authorization':'Bearer '+os.environ['KV_REST_API_TOKEN']})
            response.raise_for_status()
            data = response.json()
            if data.get('error'):
                raise ValueError('Storage command failed')
            return data.get('result')
        except (httpx.HTTPError, ValueError):
            raise HTTPException(503, 'Persistent storage is unavailable.') from None


store = Store()
