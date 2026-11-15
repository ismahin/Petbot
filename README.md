# Petbot / Deskter

Bangla, English and Banglish companion robot for XIAO ESP32S3 Sense, with a
settings dashboard and authenticated device APIs.

## Vercel deployment (experimental)

The cloud app uses **Groq for recognition and conversation** and **Mithi v1 Edge
for speech**. Ollama is not a dependency. Mithi loads lazily into one CPU worker
inside the function, with bounded requests, generation queues and audio caching.

**Read [DEPLOY.md](DEPLOY.md) before importing this repo into Vercel.** It covers
required environment variables, private API keys, persistent Redis settings,
ESP examples, measured local memory/latency, and free-tier limitations.

Import this repository with the repository root as Root Directory and FastAPI
as the framework. Never upload `cloud/private` or `server/private`.

- `/`: authenticated Studio, prompt editor, ten Mithi voices, audio previews,
  conversation/audio settings and device key management.
- `/api/v1/chat`, `/api/v1/transcribe`, `/api/v1/speech`: device-key-authenticated
  REST APIs. WAV audio avoids base64 overhead.
- `/xiaozhi/ota/`, `/xiaozhi/v1/`: Xiaozhi-compatible configuration and Opus WSS.
- `/health`: lightweight status. `/api/docs`: request schemas.

Vercel deployment has **not** been verified. Local rehearsal passed actual Groq
ASR, Groq reply generation and Mithi WAV synthesis. Cold starts and free-tier
CPU/memory limits can cause delays or failures. This is an experiment, not an
always-on service guarantee.

## Existing local robot

The existing Arduino firmware and LAN deployment remain available:

```powershell
.\server\start.ps1 -Background
.\server\stop.ps1
```

Open `http://127.0.0.1:8787` or `Open-Deskter-Studio.cmd` for the local dashboard.
Local speech/recognition use the PC; Groq supplies conversation. The uploaded
robot is still configured for this LAN server, not a new cloud URL.

See [Arduino build/upload](arduino/README.md), [server setup](server/README.md),
[Mithi implementation](server/MITHI.md) and [hardware](HARDWARE.md).
The camera/ST7789 wiring and full-screen preview are preserved.

## Secrets and models

Private credentials, generated keys, TLS files, model downloads, diagnostic audio,
virtual environments and firmware binaries are excluded from Git. Mithi assets
are downloaded from a pinned revision and SHA256-verified at build time.
Third-party weights/code retain their licenses; see [model attribution](server/MODELS.md).
