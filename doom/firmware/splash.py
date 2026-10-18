#!/usr/bin/env python3
"""The 128x64 test card for the NEK-100 framebuffer (used by fbtest.py), and how a frame is packed.

Step 1 (fb_splash, confirmed on the device): VOL+/VOL- on the main screen copied this card into the
framebuffer and set the "refresh LCD" flag; the firmware's tick sent all 8 pages to the display.

Framebuffer (from the firmware map / our analysis, not yet confirmed on the device for a full frame):
    RAM 0x662a, 1024 words, byte i = page*128 + x, bit b of it = row page*8 + b (bit 0 = top), one byte per word.
    RAM 0x6a50 bit 0 = "send the framebuffer to the LCD" (cleared by the tick after sending).
The image is stored packed, two framebuffer bytes per program word (low byte first), and unpacked by the copy loop.

The test card is chosen to make mistakes visible: a filled square marks the top-left corner (mirroring,
rotation), the border shows the edges (off-by-one, missing pages), the 1-px checkerboard shows bit order
within a page, and the stripes at the bottom show page order.

Usage: python3 firmware/splash.py   (preview; nek100-mod's pixel font)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))   # nek100-mod
from nuxdsp import pixfont  # noqa: E402

W, H = 128, 64


def blit(canvas, rows, x0, y0, scale=1):
    for y, row in enumerate(rows):
        for x, c in enumerate(row):
            if c == "#":
                for dy in range(scale):
                    for dx in range(scale):
                        canvas[y0 + y * scale + dy][x0 + x * scale + dx] = 1


def centred(canvas, text, y0, font, scale):
    rows, w = pixfont.render(text, font)
    blit(canvas, rows, (W - w * scale) // 2, y0, scale)


def test_card():
    c = [[0] * W for _ in range(H)]
    for x in range(W):
        c[0][x] = c[H - 1][x] = 1
    for y in range(H):
        c[y][0] = c[y][W - 1] = 1
    for y in range(2, 8):                       # top-left marker
        for x in range(2, 8):
            c[y][x] = 1
    centred(c, "DOOM", 0, "small", 4)           # 5 px letters x4 = 20 px (rows 4..23)
    centred(c, "PIANO", 22, "small", 2)         # rows 24..33
    centred(c, "NEK-100 FRAMEBUFFER", 35, "small", 1)  # rows 36..40
    for y in range(44, 52):                     # 1-px checkerboard
        for x in range(8, 120):
            c[y][x] = (x + y) & 1
    for y in range(54, 62):                     # vertical stripes of growing width
        x, w = 4, 1
        while x + w < W - 4:
            for i in range(w):
                c[y][x + i] = 1
            x += 2 * w
            w += 1
    return c


def pack(canvas):
    fb = []
    for page in range(H // 8):
        for x in range(W):
            fb.append(sum(canvas[page * 8 + b][x] << b for b in range(8)))
    return [fb[i] | fb[i + 1] << 8 for i in range(0, len(fb), 2)]


def preview(canvas):
    return "\n".join("".join("#" if v else "." for v in row) for row in canvas)


if __name__ == "__main__":
    print(preview(test_card()))
