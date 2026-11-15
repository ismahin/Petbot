# Retained model sources

- Speech: [Oomni/mithi-v1-edge](https://huggingface.co/Oomni/mithi-v1-edge),
  revision `c211c7e6a3dbf57159318b83d2543204980bb905`, Apache-2.0. File hashes:
  `mithi-model-source.json`. Malini voice, local CPU runtime. Source and license
  notices remain beside the weights. See [implementation](MITHI.md).
- Bengali recognition: [Alpha Cephei streaming Zipformer](https://huggingface.co/alphacep/vosk-model-small-streaming-bn),
  Apache-2.0, official sherpa-onnx release export
  `sherpa-onnx-streaming-zipformer-bn-vosk-2026-02-09`.
  Checksums: `model-checksums.json`.
- English recognition and language routing:
  [Whisper Tiny CTranslate2 export](https://huggingface.co/Systran/faster-whisper-tiny),
  MIT, local INT8 CPU. Revision and hashes: `language-router-source.json`.
- Conversation: Groq `openai/gpt-oss-120b`, with configured API fallback.
  These weights are not downloaded into this project. See [Groq](GROQ.md).
- Face and wake models remain part of the existing Arduino firmware/toolchain;
  they are necessary for the robot and are unrelated to speech synthesis.

Other project speech models, experimental runtimes and their archived copies
were permanently removed. Shared system model caches outside this project were not targeted.
