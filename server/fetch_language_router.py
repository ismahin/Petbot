"""Pin/download Whisper Tiny for local English recognition and language routing."""
import hashlib
import json
from pathlib import Path
import urllib.request
from download_file import download

ROOT=Path(__file__).resolve().parent
repo='Systran/faster-whisper-tiny'
manifest=ROOT/'language-router-source.json'
if manifest.exists():
    source=json.loads(manifest.read_text())
else:
    with urllib.request.urlopen('https://huggingface.co/api/models/'+repo+'?blobs=true') as response:
        metadata=json.load(response)
    selected=['model.bin','config.json','tokenizer.json','vocabulary.txt']
    source={'repo':repo,'revision':metadata['sha'],'original':'openai/whisper-tiny','license':'MIT',
            'files':[{'path':x['rfilename'],'size':x['size'],'sha256':x.get('lfs',{}).get('sha256')}
                     for x in metadata['siblings'] if x['rfilename'] in selected]}
    manifest.write_text(json.dumps(source,indent=2),encoding='utf-8')
root=ROOT/'models/whisper-tiny-router';root.mkdir(parents=True,exist_ok=True)
for item in source['files']:
    url=f"https://huggingface.co/{repo}/resolve/{source['revision']}/{item['path']}"
    path=root/item['path']
    if item['size']>4*1024*1024:
        download(url,path,item['size'],item['sha256'])
    else:
        data=urllib.request.urlopen(url,timeout=30).read()
        if len(data)!=item['size']:raise ValueError('Model asset size mismatch')
        if item['sha256'] and hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('Model asset checksum mismatch')
        path.write_bytes(data)
    print('Ready:',path.name,flush=True)
