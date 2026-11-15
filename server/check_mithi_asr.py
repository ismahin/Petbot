"""Local intelligibility screening of Mithi audition files, not a MOS score."""
import asyncio
import json
from pathlib import Path
import re
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from engine import Engine

ROOT = Path(__file__).resolve().parent


async def main():
    engine = Engine(json.loads((ROOT/'private/config.json').read_text()))
    results = []
    try:
        reports = sorted((ROOT/'diagnostics/mithi').glob('*_cached/results.json'))
        reports.append(ROOT/'diagnostics/mithi/malini-live.json')
        for report_path in reports:
            report = json.loads(report_path.read_text(encoding='utf8'))
            cases = report if isinstance(report, list) else report['cases']
            for case in cases:
                filename = case.get('file', f"malini_{case.get('index', 0)}.wav")
                wave, rate = sf.read(report_path.parent/filename, dtype='float32')
                audio = resample_poly(wave, 16000, rate).astype(np.float32)
                if case['language'] == 'bn':
                    heard = engine._bangla(audio)
                else:
                    segments, _ = engine.language_router.transcribe(audio, language='en',
                        beam_size=3, condition_on_previous_text=False, temperature=0)
                    heard = ' '.join(s.text.strip() for s in segments)
                record = {'profile': report_path.parent.name, 'expected': case['text'],
                          'heard': heard, 'language': case['language'],
                          'mixed_script': bool(re.search('[A-Za-z]',case['text'])) and case['language']=='bn'}
                results.append(record)
                print(json.dumps(record, ensure_ascii=True), flush=True)
        (ROOT/'diagnostics/mithi/asr-screening.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf8')
    finally:
        await engine.close()


if __name__=='__main__':
    asyncio.run(main())
