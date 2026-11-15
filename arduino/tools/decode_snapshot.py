"""Decode diagnostic SNAPROW records and compare RGB565 byte/channel orders.

Requires Pillow on the development computer only; not a firmware dependency.
"""
import argparse
from pathlib import Path
import re
from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--output", type=Path, default=Path("diagnostics"))
    args = parser.parse_args()
    frames = {}
    for frame, y, payload in re.findall(r"SNAPROW (\d+) (\d+) ([0-9a-f]{640})", args.log.read_text(errors="replace")):
        frames.setdefault(int(frame), {})[int(y)] = bytes.fromhex(payload)
    complete = [frame for frame, rows in frames.items() if set(rows) == set(range(120))]
    if not complete:
        parser.error(f"No complete snapshot; row counts: {[(f, len(r)) for f, r in frames.items()]}")
    frame = max(complete)
    raw = b"".join(frames[frame][y] for y in range(120))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / f"frame_{frame}.rgb565").write_bytes(raw)
    grid = Image.new("RGB", (640, 520), "#222222")
    draw = ImageDraw.Draw(grid)
    for index, (endian, swap) in enumerate((("big", False), ("little", False), ("big", True), ("little", True))):
        pixels = bytearray()
        for i in range(0, len(raw), 2):
            value = int.from_bytes(raw[i:i+2], endian)
            r = ((value >> 11) & 31) * 255 // 31
            g = ((value >> 5) & 63) * 255 // 63
            b = (value & 31) * 255 // 31
            pixels.extend((b, g, r) if swap else (r, g, b))
        label = ("BGR565" if swap else "RGB565") + ("BE" if endian == "big" else "LE")
        image = Image.frombytes("RGB", (160, 120), bytes(pixels))
        image.save(args.output / f"frame_{frame}_{label}.png")
        x, y = (index % 2) * 320, (index // 2) * 260
        draw.text((x + 5, y + 4), label, fill="white")
        grid.paste(image.resize((320, 240), Image.Resampling.NEAREST), (x, y + 20))
    output = args.output / f"frame_{frame}_comparison.png"
    grid.save(output)
    print(f"Decoded frame {frame}, {len(raw)} raw bytes: {output.resolve()}")


if __name__ == "__main__":
    main()
