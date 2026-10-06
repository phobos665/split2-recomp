"""A minimal PNG writer (8-bit RGB or RGBA, no filtering)."""

import struct
import zlib


def write_png(path, width, height, pixels, channels=4):
    """`pixels`: rows top first, `channels` bytes per pixel (3 or 4)."""
    kind = {3: 2, 4: 6}[channels]
    stride = width * channels
    raw = b"".join(b"\0" + pixels[y * stride:(y + 1) * stride] for y in range(height))

    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, kind, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw, 9)))
        f.write(chunk(b"IEND", b""))
