# Deploy Petbot to Vercel (experimental direct Mithi)

This deployment runs **Groq recognition + Groq conversation + Mithi speech**.
Ollama, sherpa-onnx, and local Whisper are not loaded by the cloud app. Your
existing LAN/Arduino firmware remains available under `server/` and `arduino/`.

The owner chose to test Mithi directly on Vercel, accepting cold starts and
free-tier limits. This is not a promise of continuous free hosting or Xiaozhi
latency. Vercel Hobby currently provides 2 GB / 1 vCPU and a 300-second maximum
function lifetime. CPU/memory usage allowances still apply. Large Python
functions require Fluid compute and large-function support.

## Import and deploy

1. Import `ismahin/Petbot` into Vercel. Keep **Root Directory at the repository
   root**. Select the **FastAPI** framework. The entrypoint is `app.py`.
2. Keep the build command `python cloud/build_models.py` from `vercel.json`.
   Python 3.12 is selected by `.python-version`. Enable Fluid compute and set
   `VERCEL_SUPPORT_LARGE_FUNCTIONS=1`.
   The repository also declares `fluid: true` and the non-secret flag in
   `build.env` because the dashboard may show its system entry as read-only.
   The model build prints whether the flag reaches the build process. Vercel
   account/project eligibility still applies; repository configuration cannot
   bypass a platform restriction. Prefer Project Settings when editable.
3. Add these environment variables **before deploying**:

   | Variable | Purpose |
   |---|---|
   | `GROQ_API_KEY` | Your Groq credential; used for both ASR and conversation |
   | `DESKTER_ADMIN_KEY` | Random secret of at least 32 characters for Studio login |
   | `DESKTER_DEVICE_KEY` | Different random secret of at least 32 characters; bootstrap ESP API key |
   | `KV_REST_API_URL` | HTTPS endpoint for Redis-compatible REST storage |
   | `KV_REST_API_TOKEN` | Server-only Redis REST credential |
   | `VERCEL_SUPPORT_LARGE_FUNCTIONS` | `1` |
   | `MITHI_THREADS` | `1` |
   | `MITHI_CACHE_MB` | `4` |

   Fresh admin/device keys were generated locally in **`cloud/private/vercel.env`**;
   the file also contains your existing Groq key for copying into Vercel. It is
   excluded from Git and deployment bundles. Never put it in the repository.
   On a fresh clone, `python cloud/make_keys.py` creates new admin/device keys;
   add your own Groq key separately.

4. Add a Redis REST database (for example an Upstash integration). Its URL/token
   provide durable settings, hashed device keys, global request limits and
   short-lived WebSocket history. Without it, the bootstrap device API and
   default settings work, but **saving settings / creating extra keys is disabled**;
   throttling is only per instance and reconnect history is not durable.
5. Deploy. The build downloads only pinned, checksum-verified Mithi assets from
   Hugging Face. No model download is attempted inside a live request.
6. Visit `https://YOUR_PROJECT.vercel.app/health`, then open `/` and sign in with
   `DESKTER_ADMIN_KEY`. Choose a voice and preview it. The first preview is cold
   and can take substantially longer than subsequent requests.
7. Open **Devices & API**, create a key for each ESP, and copy its key immediately.
   The full key is shown once. Revoke keys from the same page. The environment
   bootstrap key must be rotated in Vercel rather than through the device list.

No Vercel deployment was performed automatically: importing the repository and
setting your Vercel/Redis environment variables are still required.

## Memory and latency design

- CPU-only PyTorch; no CUDA, Ollama, local recognition models, separate TTS
  process, or model loading during health checks and text-only requests.
- One lazy Mithi model per instance, one speech generation at a time, one CPU
  thread by default, existing prosody KV caching and a 4 MiB PCM cache.
- Maximum two active WebSocket sessions per instance; no unbounded task queues.
  Speech production/playback overlap through a two-item queue.
- REST audio is bounded to 30 seconds of mono 16 kHz PCM16. Input bodies are
  capped at 1.1 MB. Speech requests allow 300 characters; conversation history
  holds at most eight messages. No base64 audio expansion in JSON responses.
- WebSockets close by 240 seconds so clients can reconnect before Vercel's
  300-second function deadline. Redis history expires after one hour. Active
  inference cannot survive instance termination; requests may need retrying.
- No conversation transcripts are logged by the cloud app. The transcript toggle
  in the shared local UI is hidden on cloud deployments.

A local Windows rehearsal passed actual Groq ASR -> Groq LLM -> lazy Mithi ->
24 kHz WAV: ASR 1.145 s, LLM 0.605 s, cold TTS 11.741 s, about 949 MiB working
set (966 MiB peak), 1,701 MiB private committed memory. The 0.003-second repeated
request was a **cache hit**, not normal uncached generation speed. These values
are not measurements of Linux/Vercel memory, concurrency, or end-to-end speaker
delay. Memory is close enough to the free limit that an actual deployment test
is necessary. Free quotas may stop the service even if an individual request fits.

## API for any ESP

All device endpoints require:

```http
Authorization: Bearer YOUR_DEVICE_API_KEY
```

| Method/path | Request | Result |
|---|---|---|
| `GET /health` | None | Lightweight configuration/model status; no model warmup |
| `GET /api/v1/voices` | Device authorization | Ten voice IDs and format |
| `POST /api/v1/chat` | JSON `text`, optional `history` | JSON `text` and `emotion` |
| `POST /api/v1/transcribe` | Raw WAV body; mono PCM16, 16 kHz, <=30 s | JSON `text` |
| `POST /api/v1/speech` | JSON `text`, optional `voice` | Mono PCM16 WAV at 24 kHz |
| `POST /xiaozhi/ota/` | Device authorization | Authenticated WSS configuration |
| `WS /xiaozhi/v1/` | Device authorization in upgrade headers | Xiaozhi hello/listen/Opus exchange |

REST conversation example:

```json
{"text":"তুমি কেমন আছো?","history":[]}
```

Keep REST history on the client and send the latest four user/assistant pairs.
For voice, call transcribe -> chat -> speech, streaming the WAV response into
your board's playback buffer. Strip the WAV container before PCM I2S playback;
do not send WAV header bytes to the speaker. Text longer than 300 characters
must be split into phrases by the REST client. The WebSocket route handles
phrase chunking, Opus encoding, VAD, bounded history and playback pacing itself.

The existing XIAO firmware already uses the Xiaozhi protocol, but **it has not
been switched to a deployed cloud URL**. Its current LAN CA/clock settings are
not suitable for public hosting as-is: provision the deployed HTTPS URL, a
trusted certificate chain, the device API key and a working clock source. Never
disable TLS verification. The generic [ESP example](examples/esp_rest/esp_rest.ino)
shows a certificate-verified REST request; microphone/speaker wiring remains
board-specific. Do not expect an arbitrary ESP without suitable RAM/audio
hardware and protocol code to run the existing full robot firmware.

Use `/api/docs` for request schemas. Error handling: 401 invalid key, 409 edit
conflict, 413 oversized body, 422 invalid input, 429 busy/rate limit, 502 Groq
failure, 503 missing model/storage/configuration. Respect `Retry-After`; avoid
blind retries after receiving part of an audio reply.

## Validation

```powershell
.\server\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

Real local rehearsal (requires the Mithi environment and private secrets):

```powershell
& "$env:LOCALAPPDATA\Deskter\venvs\mithi-py312\Scripts\python.exe" cloud/check_live.py --model-dir "$env:LOCALAPPDATA\Deskter\models\mithi-v1-edge"
```

Dependencies are pinned in a **flat root `requirements.txt`** for Vercel's
requirements parser. The resolver reference is `cloud/requirements-linux.lock.txt`;
the deployment manifest does not include it with `-r`.
CPU PyTorch uses its official, SHA256-pinned Linux wheel directly. The remaining
packages resolve from PyPI; no PyTorch extra index or unsafe index strategy is
needed. This avoids `uv` selecting outdated non-Torch dependencies from the
PyTorch index.

A full GitHub Actions Linux build installed the production dependencies, fetched
verified assets, and generated real Bangla and English audio with a peak resident
set of **1,017 MiB**. [Linux smoke-test run](https://github.com/ismahin/Petbot/actions/runs/43758430903).
Vercel deployment still needs verification; runner measurements do not establish
Vercel performance or memory usage.

References: [Vercel FastAPI](https://vercel.com/docs/frameworks/backend/fastapi),
[function limits](https://vercel.com/docs/functions/limitations),
[WebSockets](https://vercel.com/docs/functions/websockets),
[Groq ASR](https://console.groq.com/docs/speech-to-text),
[Mithi](https://huggingface.co/Oomni/mithi-v1-edge).
