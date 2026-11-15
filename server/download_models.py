"""One-time downloads. Runtime loads these directories with networking disabled."""
from pathlib import Path
import tarfile
import urllib.request
ROOT = Path(__file__).resolve().parent
MODELS = ROOT / "models"

def main():
    name = 'sherpa-onnx-streaming-zipformer-bn-vosk-2026-02-09'
    if not (MODELS / name / 'encoder.onnx').exists():
        archive = MODELS / 'bn-zipformer.tar.bz2'
        urllib.request.urlretrieve('https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/' + name + '.tar.bz2', archive)
        with tarfile.open(archive) as package:
            package.extractall(MODELS, filter='data')
    print('Bengali streaming ASR ready', flush=True)

if __name__ == "__main__":
    main()
