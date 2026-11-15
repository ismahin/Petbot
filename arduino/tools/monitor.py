"""Bounded Arduino CLI serial monitor; uses Python's standard library only."""
import argparse
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time


def main():
    # Windows terminals can default to cp1252; service diagnostics may be UTF-8.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM3")
    parser.add_argument("--seconds", type=float, default=25)
    parser.add_argument("--output", type=Path, default=Path("runtime.log"))
    args = parser.parse_args()
    if not 0 < args.seconds <= 60:
        parser.error("--seconds must be between 0 and 60")
    cli = shutil.which("arduino-cli") or str(Path(os.environ["LOCALAPPDATA"]) / "Programs/ArduinoCLI/arduino-cli.exe")
    process = subprocess.Popen([cli, "monitor", "--port", args.port, "--config", "baudrate=115200", "--quiet", "--no-color"],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    lines = queue.Queue()

    def reader():
        for line in iter(process.stdout.readline, b""):
            lines.put(line)

    threading.Thread(target=reader, daemon=True).start()
    started = time.monotonic()
    try:
        with args.output.open("wb") as output:
            while time.monotonic() - started < args.seconds:
                try:
                    line = lines.get(timeout=0.25)
                except queue.Empty:
                    if process.poll() is not None:
                        raise RuntimeError(f"Arduino monitor exited: {process.returncode}")
                    continue
                output.write(line)
                output.flush()
                print(line.decode(errors="replace").rstrip(), flush=True)
    finally:
        if process.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                process.terminate()
            process.wait(timeout=5)
    print(f"Saved {args.output.resolve()}; monitor closed.")


if __name__ == "__main__":
    main()
