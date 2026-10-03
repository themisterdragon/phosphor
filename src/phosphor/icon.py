"""Phosphor's icon: a little green-screen monitor showing the ] prompt, as 16x16 pixel art.

png(scale) makes a PNG with no libraries (for the window, the app menu, and app bundles)."""

import struct
import zlib

COLORS = {".": None, "k": (0x1A, 0x1D, 0x1A), "c": (0x9A, 0x98, 0x8C), "l": (0xC9, 0xC6, 0xB8),
          "s": (0x06, 0x14, 0x08), "g": (0x33, 0xFF, 0x66), "d": (0x1F, 0x8A, 0x3F)}

PIXELS = [
    "................",
    ".kkkkkkkkkkkkkk.",
    ".kllllllllllllk.",
    ".klsssssssssslk.",
    ".klsggssssssslk.",
    ".klssgssssssslk.",
    ".klssgsggsssslk.",
    ".klssgsggsssslk.",
    ".klssgsggsssslk.",
    ".klsggsggsssslk.",
    ".klsssssssssslk.",
    ".klsddddddssslk.",
    ".kllllllllllllk.",
    ".kkkkkkkkkkkkkk.",
    "......kcck......",
    "...kkkkkkkkkk...",
]
assert len(PIXELS) == 16 and all(len(r) == 16 for r in PIXELS)


def png(scale=4):
    """The icon as PNG bytes, each pixel drawn scale x scale."""
    size = 16 * scale
    rows = []
    for line in PIXELS:
        row = bytearray([0])  # filter type: none
        for ch in line:
            c = COLORS.get(ch)
            row += bytes((*c, 255)) * scale if c else bytes(4) * scale
        rows.extend([bytes(row)] * scale)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))
