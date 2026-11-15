"""Fetch the reviewed Mithi Edge revision and verify all published LFS hashes."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import urllib.request

REVISION = 'c211c7e6a3dbf57159318b83d2543204980bb905'
REPO = 'Oomni/mithi-v1-edge'
DEST = Path(os.environ['LOCALAPPDATA']) / 'Deskter/models/mithi-v1-edge'
ROOT = Path(__file__).resolve().parent


def main():
    with urllib.request.urlopen(f'https://huggingface.co/api/models/{REPO}/revision/{REVISION}?blobs=true', timeout=30) as response:
        metadata = json.load(response)
    if metadata['sha'] != REVISION:
        raise ValueError('Unexpected Mithi revision')
    files = [f for f in metadata['siblings'] if not f['rfilename'].startswith('onnx/') and not f['rfilename'].startswith('.')]
    DEST.mkdir(parents=True, exist_ok=True)

    def fetch(item):
        name = item['rfilename']
        target = DEST / name
        target.parent.mkdir(parents=True, exist_ok=True)
        expected = item.get('lfs', {}).get('sha256')
        def valid(path):
            if not path.exists() or path.stat().st_size != item['size']:
                return False
            if expected:
                with path.open('rb') as handle:
                    return hashlib.file_digest(handle, 'sha256').hexdigest() == expected
            return True
        if not valid(target):
            partial = target.with_suffix(target.suffix + '.partial')
            with urllib.request.urlopen(f'https://huggingface.co/{REPO}/resolve/{REVISION}/{name}?download=true', timeout=60) as response, partial.open('wb') as output:
                while block := response.read(65536):
                    output.write(block)
            if not valid(partial):
                raise ValueError('Mithi size/hash mismatch: ' + name)
            partial.replace(target)
        with target.open('rb') as handle:
            digest = hashlib.file_digest(handle, 'sha256').hexdigest()
        print('Verified ' + name, flush=True)
        return {'file': name, 'size': target.stat().st_size, 'sha256': digest}

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        verified = list(pool.map(fetch, files))
    (ROOT / 'mithi-model-source.json').write_text(json.dumps({
        'repo': REPO, 'revision': REVISION, 'model_dir': str(DEST), 'files': verified,
    }, indent=2), encoding='utf8')


if __name__ == '__main__':
    main()
