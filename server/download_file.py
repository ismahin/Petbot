"""Checked parallel HTTP ranges for model downloads on slow single connections."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import urllib.request
import time

def download(url, target, size, digest, workers=6):
    target = Path(target)
    if target.exists() and target.stat().st_size == size:
        with target.open('rb') as existing:
            verified = hashlib.file_digest(existing, 'sha256').hexdigest() == digest
        if verified:
            print('SHA256 verified:',target.name,flush=True)
            return
    parts = target.parent/(target.name+'.parts')
    parts.mkdir(parents=True,exist_ok=True)
    block = 4*1024*1024
    ranges = [(i,start,min(size,start+block)-1) for i,start in enumerate(range(0,size,block))]
    def fetch_once(item):
        index,start,end = item
        path = parts/str(index)
        if path.exists() and path.stat().st_size==end-start+1:
            return path
        request = urllib.request.Request(url,headers={'Range':f'bytes={start}-{end}'})
        with urllib.request.urlopen(request,timeout=60) as response:
            if response.status != 206 or response.headers.get('Content-Range') != f'bytes {start}-{end}/{size}':
                raise RuntimeError('Server did not honor the requested byte range')
            with path.open('wb') as out:
                while data := response.read(256*1024):
                    out.write(data)
        if path.stat().st_size != end-start+1:
            raise RuntimeError('Incomplete download part')
        print('Downloaded part',index+1,'of',len(ranges),flush=True)
        return path
    def fetch(item):
        for attempt in range(4):
            try:
                return fetch_once(item)
            except OSError:
                if attempt==3:
                    raise
                time.sleep(2**attempt)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        completed = list(pool.map(fetch,ranges))
    temporary = target.with_suffix(target.suffix+'.verified-download')
    hasher = hashlib.sha256()
    with temporary.open('wb') as out:
        for path in completed:
            with path.open('rb') as part:
                while data := part.read(1024*1024):
                    hasher.update(data); out.write(data)
    if temporary.stat().st_size != size or hasher.hexdigest() != digest:
        raise RuntimeError('Downloaded file failed SHA256 verification')
    temporary.replace(target)
    # Only delete the exact numbered parts generated above, after verified assembly.
    for path in completed:
        path.unlink()
    parts.rmdir()
    print('SHA256 verified:',target.name,flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url'); parser.add_argument('target'); parser.add_argument('size',type=int); parser.add_argument('sha256')
    args=parser.parse_args()
    download(args.url,args.target,args.size,args.sha256)
