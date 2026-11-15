"""Uncached Bangla/English Mithi audition and complete synthesis timings."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import time

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
import numpy as np
import torch
import soundfile as sf

ROOT = Path(__file__).resolve().parent
CASES = [
    ('bn', 'হ্যালো মাহিন, আজ তুমি কেমন আছো?'),
    ('bn', 'বাহ, দারুণ খবর! নতুন চাকরির জন্য তোমাকে অনেক অভিনন্দন।'),
    ('bn', 'বাংলাদেশের রাজধানী ঢাকা। আমি তোমার সঙ্গে বাংলায় কথা বলতে পারি।'),
    ('en', 'Hello Mahin, how are you feeling today?'),
    ('bn', 'আজ office-এ অনেক কাজ ছিল, তাই একটু rest নাও।'),
    ('bn', 'তোমার মন খারাপ হলে আমাকে বলতে পারো। আমি মন দিয়ে শুনব, তারপর আমরা একসঙ্গে একটা সমাধান খুঁজে দেখব।'),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--voice', default='malini')
    parser.add_argument('--threads', type=int, default=2)
    parser.add_argument('--cached', action='store_true')
    args = parser.parse_args()
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    source = json.loads((ROOT / 'mithi-model-source.json').read_text())
    folder = Path(source['model_dir'])
    spec = importlib.util.spec_from_file_location('mithi_run', folder / 'run.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    started = time.perf_counter()
    model = module.Mithi(str(folder), device='cpu')
    if args.cached:
        from mithi_cached_writer import enable_cached_writer
        enable_cached_writer(model)
    loaded = time.perf_counter() - started
    out = ROOT / 'diagnostics/mithi' / f'{args.voice}_threads{args.threads}{"_cached" if args.cached else ""}'
    out.mkdir(parents=True, exist_ok=True)
    report = {'voice': args.voice, 'threads': args.threads, 'device': 'cpu',
              'load_seconds': round(loaded, 3), 'cached_writer': args.cached, 'cases': []}
    for index, (language, text) in enumerate(CASES):
        started = time.perf_counter()
        wave = model.synthesize(text, lang=language, voice=args.voice, seed=0)
        elapsed = time.perf_counter() - started
        if not len(wave) or not np.isfinite(wave).all():
            raise RuntimeError('Invalid Mithi waveform')
        name = f'{index}_{language}.wav'
        sf.write(out / name, wave, 24000, subtype='PCM_16')
        case = {'text': text, 'language': language, 'file': name,
                'seconds': round(elapsed, 3), 'audio_seconds': round(len(wave) / 24000, 3),
                'rtf': round(elapsed / (len(wave) / 24000), 3),
                'peak': float(np.max(np.abs(wave)))}
        report['cases'].append(case)
        print(json.dumps(case, ensure_ascii=True), flush=True)
        (out / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')


if __name__ == '__main__':
    main()
