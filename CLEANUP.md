# Mithi-only cleanup

Mithi v1 Edge / Malini is the only retained speech backend. Alternative speech
weights, experimental runtimes/environments, old voice launchers, comparison
scripts, obsolete model manifests and previous project archives were permanently
removed at the owner's request.

Retained: Arduino source/build/upload tools, the working camera/face/wake/audio
firmware, Mithi source and pinned dependencies, active speech recognition models,
gateway and regression tests, provisioning tools, private credentials and TLS
certificates. Selected Malini diagnostics remain for repeatable verification.

The original flash recovery ZIP was copied and SHA256-verified before archive
removal: `arduino/recovery/original_flash.zip`. The old archives are no longer
rollback locations. No board flash or Wi-Fi credentials were erased.

Model and runtime locations:

- `%LOCALAPPDATA%\Deskter\models\mithi-v1-edge`
- `%LOCALAPPDATA%\Deskter\venvs\mithi-py312`
- `server/models/`: necessary Bengali/English recognition models
- `server/.venv/`: gateway and recognition dependencies

Shared system caches and independent Ollama installations were outside the
cleanup scope.

Automatic approval review blocked removal of four obsolete private files:
`config.before-speed.json`, `config.before-zonos.json`, `mio-trial.pid`, and
`omnivoice-native-server.json`. They remain unused in `server/private`; no
alternative speech weights or runtime depend on them. The review returned
"blocked by policy" without a more specific reason.
