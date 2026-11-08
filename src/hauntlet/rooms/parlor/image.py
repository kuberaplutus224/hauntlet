"""Render text to a PNG with a small embedded bitmap font. Standard library only.

The image-text trap exists only in pixels (Requirement 4.1-4.4). ``render``
draws ``text`` as dark glyphs on a light background at a fixed scale (glyph
height 21 px, above the 16 px floor), with no distortion, and returns PNG bytes
built with ``zlib`` and ``struct``. The font is a 5x7 dict defined here; lowercase
letters reuse the uppercase glyph (small caps), which a vision model reads
fine. ``render`` is deterministic: the same text always yields the same bytes.

A character with no glyph raises ``ValueError`` rather than drawing a blank, so
a template that needs a glyph the font lacks fails loudly instead of shipping an
illegible image.
"""

from __future__ import annotations

import struct
import zlib

GLYPH_W, GLYPH_H = 5, 7
SCALE = 3  # glyph height 21 px
SPACING = 1  # blank columns between glyphs
MARGIN = 8
INK = (0x11, 0x11, 0x11)
PAPER = (0xF5, 0xF5, 0xF0)

_FONT_SRC: dict[str, tuple[str, ...]] = {
    " ": (".....", ".....", ".....", ".....", ".....", ".....", "....."),
    "A": (".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "B": ("####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."),
    "C": (".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."),
    "D": ("####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."),
    "E": ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "F": ("#####", "#....", "#....", "####.", "#....", "#....", "#...."),
    "G": (".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".###."),
    "H": ("#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "I": (".###.", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "J": ("..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."),
    "K": ("#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"),
    "L": ("#....", "#....", "#....", "#....", "#....", "#....", "#####"),
    "M": ("#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"),
    "N": ("#...#", "##..#", "#.#.#", "#.#.#", "#..##", "#...#", "#...#"),
    "O": (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "P": ("####.", "#...#", "#...#", "####.", "#....", "#....", "#...."),
    "Q": (".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"),
    "R": ("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "S": (".####", "#....", "#....", ".###.", "....#", "....#", "####."),
    "T": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "U": ("#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "V": ("#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."),
    "W": ("#...#", "#...#", "#...#", "#.#.#", "#.#.#", "##.##", "#...#"),
    "X": ("#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"),
    "Y": ("#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."),
    "Z": ("#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"),
    "0": (".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": (".###.", "#...#", "....#", "..##.", ".#...", "#....", "#####"),
    "3": ("#####", "...#.", "..#..", "...#.", "....#", "#...#", ".###."),
    "4": ("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    "5": ("#####", "#....", "####.", "....#", "....#", "#...#", ".###."),
    "6": (".###.", "#....", "#....", "####.", "#...#", "#...#", ".###."),
    "7": ("#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."),
    "8": (".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."),
    "9": (".###.", "#...#", "#...#", ".####", "....#", "....#", ".###."),
    "-": (".....", ".....", ".....", "#####", ".....", ".....", "....."),
    ":": (".....", "..#..", ".....", ".....", ".....", "..#..", "....."),
    ".": (".....", ".....", ".....", ".....", ".....", "..#..", "..#.."),
    ",": (".....", ".....", ".....", ".....", "..#..", "..#..", ".#..."),
}


def _glyph(ch: str) -> tuple[str, ...]:
    g = _FONT_SRC.get(ch)
    if g is None:
        g = _FONT_SRC.get(ch.upper())
    if g is None:
        raise ValueError(f"image font has no glyph for {ch!r}")
    return g


def supports(text: str) -> bool:
    """True iff every character in ``text`` has a glyph (directly or as caps)."""
    return all(ch in _FONT_SRC or ch.upper() in _FONT_SRC for ch in text)


def image_size(text: str) -> tuple[int, int]:
    n = max(1, len(text))
    width = MARGIN * 2 + n * GLYPH_W * SCALE + (n - 1) * SPACING * SCALE
    height = MARGIN * 2 + GLYPH_H * SCALE
    return width, height


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def render(text: str) -> bytes:
    """Render ``text`` to deterministic PNG bytes."""
    width, height = image_size(text)
    row_stride = width * 3
    paper_row = bytes(PAPER) * width
    canvas = bytearray(paper_row * height)

    def put(px: int, py: int) -> None:
        off = py * row_stride + px * 3
        canvas[off : off + 3] = bytes(INK)

    x0 = MARGIN
    for ch in text:
        glyph = _glyph(ch)
        for ry, row in enumerate(glyph):
            for rx, cell in enumerate(row):
                if cell != "#":
                    continue
                for sy in range(SCALE):
                    for sx in range(SCALE):
                        put(x0 + rx * SCALE + sx, MARGIN + ry * SCALE + sy)
        x0 += (GLYPH_W + SPACING) * SCALE

    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0 (None) per scanline
        raw += canvas[y * row_stride : (y + 1) * row_stride]

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    idat = zlib.compress(bytes(raw), 9)
    return sig + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")
