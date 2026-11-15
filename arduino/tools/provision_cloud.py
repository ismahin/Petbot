"""Verify the selected cloud endpoint, then provision its device key over USB.

Secrets are read from an ignored env file, never passed on the command line or
printed. Public HTTPS/WSS uses the board's CA bundle and public SNTP.
"""
import argparse
import json
from pathlib import Path
import time
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='COM3')
    parser.add_argument('--url', default='https://robotpetbot.vercel.app')
    parser.add_argument('--env-file', type=Path, default=ROOT/'cloud/private/vercel.env')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    origin = args.url.rstrip('/')
    url = urlparse(origin)
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.path or url.query or url.fragment:
        parser.error('--url must be a public HTTPS origin without a path or credentials')
    values = {}
    for line in args.env_file.read_text(encoding='utf-8-sig').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip()
    token = values.get('DESKTER_DEVICE_KEY', '')
    if not 32 <= len(token) <= 256:
        raise RuntimeError('Private env file needs DESKTER_DEVICE_KEY (32..256 characters)')
    import httpx
    with httpx.Client(timeout=120, follow_redirects=False) as client:
        health = client.get(origin+'/health')
        health.raise_for_status()
        if health.json().get('deployment') != 'vercel-experimental' or not health.json().get('ready'):
            raise RuntimeError('Selected endpoint is not a configured Deskter cloud service')
        response = client.post(origin+'/xiaozhi/ota/', headers={'Authorization':'Bearer '+token}, json={})
        if response.status_code != 200:
            raise RuntimeError(f'Cloud device authentication failed (HTTP {response.status_code}); check the device key in Vercel')
        config = response.json().get('websocket', {})
        if config.get('url') != 'wss://'+url.netloc+'/xiaozhi/v1/' or config.get('token') != token:
            raise RuntimeError('Unexpected cloud WebSocket configuration')
    print('Cloud health, device authentication and secure WebSocket configuration verified.')
    if args.check_only:
        return
    import serial
    payload = {'cmd':'server', 'public':True, 'url':origin+'/xiaozhi/ota/',
               'ca':'', 'ntp':'', 'token':token, 'utc':int(time.time())}
    with serial.Serial(args.port, 115200, timeout=.25, write_timeout=3) as port:
        time.sleep(2)
        port.reset_input_buffer()
        data = (json.dumps(payload)+'\n').encode()
        for offset in range(0, len(data), 64):
            port.write(data[offset:offset+64]); port.flush(); time.sleep(.08)
        acknowledged = False
        connected = False
        end = time.monotonic()+45
        while time.monotonic() < end:
            line = port.readline().decode(errors='replace').strip()
            if 'selected server settings saved' in line:
                acknowledged = True
                print('Board saved cloud settings; device key hidden.')
            if 'configuration HTTP=' in line or 'cloud settings ready' in line or 'Wi-Fi connected;' in line:
                print(line, flush=True)
            if 'cloud settings ready' in line:
                connected = True
        if not acknowledged:
            raise RuntimeError('Board did not acknowledge cloud provisioning')
        if not connected:
            print('Settings saved; cloud connection not confirmed within this capture.')
        else:
            print('Board authenticated to the cloud service successfully.')


if __name__ == '__main__':
    main()
