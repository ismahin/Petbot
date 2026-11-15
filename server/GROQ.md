# Groq-only conversation

Deskter uses Groq for text generation. Ollama is no longer a project dependency;
startup does not contact it and the engine has no local-LLM branch.

The local LAN server reads `private/groq.key` or `GROQ_API_KEY`. The cloud app
uses Vercel's `GROQ_API_KEY` environment variable. Never commit private files.

Default conversation model: `openai/gpt-oss-120b`, with structured JSON containing
`emotion` and `text`. The local configuration can retain a bounded API-model
fallback; cloud fallback is opt-in with `GROQ_FALLBACK_MODEL`.

The local server retains local recognition. The memory-saving cloud app instead
sends microphone utterances to Groq Whisper (`whisper-large-v3-turbo`) for ASR.
Both text conversation and cloud ASR require internet, model permissions, and
sufficient account quotas. Mithi speech stays in the selected deployment.

Change the local Groq model from Studio or:

```powershell
.\server\select_llm.ps1 -GroqModel openai/gpt-oss-120b
```

Provider failures are bounded and sanitized; keys and error response bodies are
not logged. Real synthetic checks verify the integration, not dialect accuracy
or a guaranteed response time. Cloud setup: [DEPLOY.md](../DEPLOY.md).
