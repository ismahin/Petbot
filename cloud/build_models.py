"""Fetch only pinned Mithi assets at build time, never during a request."""
import hashlib
import json
import os
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent


def main():
    if os.getenv('MITHI_ENABLED', '1') == '0':
        return
    source = json.loads((ROOT/'model-source.json').read_text(encoding='utf8'))
    folder = ROOT/'models/mithi-v1-edge'
    for entry in source['files']:
        target = (folder/entry['file']).resolve()
        if not target.is_relative_to(folder.resolve()):
            raise ValueError('Unsafe asset path')
        target.parent.mkdir(parents=True, exist_ok=True)
        valid = target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == entry['sha256']
        if not valid:
            url = f"https://huggingface.co/{source['repo']}/resolve/{source['revision']}/{entry['file']}?download=true"
            digest = hashlib.sha256()
            with urllib.request.urlopen(url, timeout=120) as incoming, target.open('wb') as output:
                while block := incoming.read(65536):
                    output.write(block); digest.update(block)
            if digest.hexdigest() != entry['sha256']:
                target.unlink()
                raise ValueError('Asset checksum mismatch: '+entry['file'])
        print('Verified '+entry['file'], flush=True)


if __name__ == '__main__':
    main()
