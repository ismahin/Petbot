# Deskter Bangla voice server

The sole speech backend is **Mithi v1 Edge / Malini**, running locally on two
CPU threads. Bengali Zipformer and Whisper Tiny provide local recognition;
Groq provides the conversation LLM. Groq needs internet. The XIAO retains its
Arduino wake phrase, camera preview, face detection, microphone and speaker.

## Run

From the project root:

```powershell
.\server\start.ps1 -Background
.\server\.venv\Scripts\python.exe server/voice_status.py --wait 30
.\server\stop.ps1
```

`Use-Mithi.cmd` starts the same server. Startup warms Mithi and recognition.
Wait for readiness, then say Hey Deskter and wait for Listening. This is
half-duplex: allow the robot to finish its reply before speaking again.

Configuration and credentials: `server/private/`. Persona: `server/persona.txt`.
Logs: `server/logs/`; microphone audio and transcripts are not saved by default.
Mithi exposes loopback port 1925. The robot uses authenticated HTTPS/WSS on
port 8443 and LAN time on UDP 8123. Keep these ports on the trusted LAN.

## Reinstall

Installation and model downloads require internet. The gateway environment uses
Python 3.13; the separate Mithi environment uses Python 3.12 because of Misaki.

```powershell
python -m venv server/.venv
.\server\.venv\Scripts\python.exe -m pip install -r server/requirements.lock.txt
.\server\.venv\Scripts\python.exe server/download_models.py
.\server\.venv\Scripts\python.exe server/fetch_language_router.py
.\server\install_mithi.ps1
```

Preserve the private settings, key and certificates. To provision a new address:

```powershell
.\server\.venv\Scripts\python.exe server/setup_local.py --host 192.168.0.131 --device-mac 7c:4f:ad:1c:d4:80
.\server\.venv\Scripts\python.exe server/provision.py --port COM3
```

## Validation and limits

With the server ready and robot asleep, test the real authenticated recognition,
Groq, Mithi and Opus path (only one conversation connection is accepted):

```powershell
.\server\.venv\Scripts\python.exe server/check_gateway.py --sample mithi/malini_0.wav
```

`check_mithi.py` benchmarks synthesis; `check_mithi_asr.py` screens pronunciation.
The owner confirmed Malini is clear and reasonably quick on the robot. Names,
dialects and mixed-language pronunciation can still be wrong. Mithi has no
learned emotion conditioning; expression labels are never spoken.

See [Mithi](MITHI.md), [model sources](MODELS.md), [Groq configuration](GROQ.md)
and [hardware voice setup](../arduino/VOICE.md). Conversation is Groq-only. `select_llm.ps1 -GroqModel MODEL_ID` can change the
configured Groq model. No alternative speech backend is retained.

For the separate Vercel deployment, see [DEPLOY.md](../DEPLOY.md).
