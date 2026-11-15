"""Check the selected HTTPS gateway using its local CA, without printing secrets."""
import argparse
import json
from pathlib import Path
import ssl
import time
import httpx

ROOT=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wait',type=int,default=0)
    args=parser.parse_args()
    config=json.loads((ROOT/'private/config.json').read_text(encoding='utf-8-sig'))
    deadline=time.monotonic()+args.wait
    with httpx.Client(verify=ssl.create_default_context(cafile=str(ROOT/'private/ca.crt')),
                      trust_env=False,timeout=3) as client:
        while True:
            try:
                response=client.get(f"https://{config['host']}:{config['port']}/health")
                response.raise_for_status()
                health=response.json()
                if health.get('ready') and health.get('tts')==config['tts_backend']:
                    print(json.dumps({key:health.get(key) for key in
                        ('ready','llm_provider','llm','tts','tts_device','device_connected','offline','emotion_tags')}))
                    return
            except (httpx.HTTPError,ValueError):
                pass
            if time.monotonic()>=deadline:
                raise SystemExit('Selected voice gateway is not ready; inspect server/logs/server.err.log.')
            time.sleep(1)


if __name__=='__main__':main()
