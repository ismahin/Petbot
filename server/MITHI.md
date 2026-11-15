# Mithi v1 Edge

Mithi is installed and selected, with **Malini** on two CPU threads. The owner
preferred Malini over Charvi and Ahana. The first Charvi audition sounded clear
but robotic; a smaller model still trades expressiveness for efficiency.
Real Bangla/English synthesis, local-ASR screening and an authenticated
HTTPS/WebSocket ASR → Groq → Mithi → Opus exchange passed.

## Source and dependencies

[Oomni/mithi-v1-edge](https://huggingface.co/Oomni/mithi-v1-edge), pinned revision
`c211c7e6a3dbf57159318b83d2543204980bb905`. Its model card, configuration, embedded
Python pipeline, phonemizer, normalizer, Indic encoder, prosody writer, weight
decompressor and acoustic decoder were reviewed. `mithi-model-source.json` records
file hashes. Source `README.md` and Apache-2.0 `LICENSE` are retained alongside
the model; bundled components/packages retain their own licenses.

The author lists 47.6 million parameters, eleven languages including Bengali,
ten voices and 24 kHz mono output. Compressed INT8/INT4 weights expand to float32
in the Python loader, so file size is not RAM usage or native INT4 computation.
One warmed worker snapshot was about 938 MiB working set, including Python,
PyTorch, spaCy and the model.

The pipeline normalizes text, generates eSpeak/Misaki phonemes, computes
Indic-BERT word vectors, predicts duration/pitch/energy and synthesizes through
Kokoro/iSTFTNet. Latin English runs inside Bangla use English phonemization.
Romanized Bangla can be ambiguous; the LLM emits Bengali script for Bangla words
and Latin script for English words. Supplied ONNX files are browser assets;
this integration uses the reviewed Python API.

The isolated environment uses Python 3.12.10: Misaki 0.9.4 declares Python below
3.13. It includes CPU PyTorch 2.11.0, Transformers 5.23.0, eSpeak loader 0.2.4,
phonemizer-fork 3.3.2 and spaCy with `en_core_web_sm` 3.8.0. Installed versions are
in `mithi-requirements.lock.txt`. The gateway has its own smaller environment.

## Efficiency and validation

`mithi_cached_writer.py` reuses prior self-attention keys/values and projected
cross-attention memory instead of recomputing the causal prefix for every phoneme.
Weights, phonemes, sampling and the acoustic decoder are unchanged. Unsupported
layouts/padding or discontinuous prefixes fall back to the original method.
State resets at each sentence.

The real-weight test compared twelve incremental prefixes, reset and fallback
against the original decoder. All six two-thread Charvi audition WAVs were
byte-identical before/after caching. That validates these cases, not every sentence.

Warm synthesis, seconds, excluding first G2P initialization:

| Charvi sample | Stock, 2 threads | Cached, 2 threads | Audio duration |
|---|---:|---:|---:|
| Bangla congratulation | 2.336 | 2.087 | 4.725 |
| Bangla explanation | 2.424 | 2.165 | 4.575 |
| English greeting | 1.157 | 1.137 | 2.500 |
| Banglish | 1.700 | 1.475 | 3.300 |
| Longer Bangla | 4.203 | 3.583 | 7.225 |

One/four threads were also tested. Two generally won on short samples; four
helped the longest. Two were retained to leave room for ASR/gateway work.
CUDA was not benchmarked for Mithi. These are small trials, not general guarantees.

Three uncached live Charvi HTTP checks generated Bangla/English/Banglish in 1.041,
1.095 and 1.446 seconds for 2.425, 2.500 and 3.300 seconds of audio. A synthetic
gateway exchange sent first Opus 2.728 seconds after endpointing, including ASR
and Groq, with 1 ms measured transport starvation. Concurrent test traffic was
present. These are server measurements, not microphone-to-ear latency.

The selected Malini voice's uncached HTTP checks took 0.964 s for a 2.35 s
Bangla greeting, 1.000 s for 2.50 s English, 1.451 s for 3.425 s Banglish and
3.136 s for 6.90 s longer Bangla. Local ASR recovered most words; it misheard
“মন দিয়ে” in the longer sample and the English name Mahin. These limitations
are retained in `diagnostics/mithi/malini-asr.json`, not hidden as perfect scores.

The worker warms G2P and kernels before readiness. Existing bounded queues
overlap generation/playback; the opening chunk is capped at six words and later
chunks at twelve, preferring punctuation boundaries and preserving all words, with
no artificial initial synthesis reserve. One continuous Opus encoder retains
24 kHz mono, 48 kbps and 60 ms packets. The board's dedicated speaker task and
GPIOs are unchanged; no firmware upload was needed.

The owner confirmed Malini was clear and reasonably quick through the robot.
Seven observed sessions with the earlier sixteen-word cap had no measured
server-side transport gaps, but one long opening waited 7.462 seconds. That
motivated the shorter opening cap. The final four-chunk Bangla playback test
started Opus at 1.624 seconds without artificial reserve and recorded zero
transport starvation. This PC test excludes ASR/Groq and does not measure
device speaker underruns. Results are in `diagnostics/mithi/continuous/bn.json`.

Quiet outside padding is trimmed. Bounded loudness gain has a 3× limit and 0.9
peak cap, without time-stretching or pitch shifting. The worker has a bounded
32 MiB RAM cache and does not save conversations. Audition tools explicitly save
synthetic WAVs under `diagnostics/mithi`.

## Quality limits

Local ASR recovered Bangla with mostly correct words and minor spelling/inflection
differences. English recognition rendered Mahin as “Mahind”; English words in the
mixed sample were written phonetically in Bengali. Human listening remains needed.

The model card warns of flatter emotion, rare-name/loanword errors, normalizer
limits for numbers/dates and independent sentence prosody. It has no learned
happy/angry or reference-audio conditioning API. Tags are stripped from speech;
the LLM can still send expression events. Worker health reports
`emotion_control: false`. Mithi is the only retained speech backend.

## Run

Model: `%LOCALAPPDATA%\Deskter\models\mithi-v1-edge`.
Python: `%LOCALAPPDATA%\Deskter\venvs\mithi-py312\Scripts\python.exe`.
Worker: loopback `127.0.0.1:1925`, managed as a validated owned process.

```powershell
.\server\install_mithi.ps1
.\server\start.ps1 -Background
```

Installation needs Python 3.12, `uv` and internet. Speech runtime is local;
Groq conversation needs internet. Malini is saved in `private/config.json`.

Use Mithi Python for `check_mithi.py --cached --threads 2`,
`test_mithi_cached_writer.py` and `test_mithi_worker.py`. Use gateway Python for
`check_mithi_asr.py` and `test_mithi_speech.py`.

`check_gateway.py --sample mithi/malini_0.wav` checks recognition, Groq,
speech, Opus, TLS, authentication and local clock. Run while the robot is asleep.
