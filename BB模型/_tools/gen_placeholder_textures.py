# -*- coding: utf-8 -*-
"""
Generate placeholder textures for the Blockbench project in this folder.

Output:  ../textures/axe.png   (16x16, pure flat color zones)

Layout of axe.png (16x16):
    x 0.. 2  dark wood   (handle, front/back faces)
    x 2.. 4  light wood  (handle, side faces)
    x 4.. 8  light iron  (axe blade)
    x 8..12  mid iron    (axe head socket / blade inner side)
    x12..16  dark iron   (top / bottom faces, shading)

Every zone is a single flat color, so any rectangle that stays inside a zone
gives a predictable, uniform result. Replace this file with real art whenever
you want - the model only cares about file names and rectangles.

No third party modules required (uses only zlib + struct).
"""

import os
import struct
import zlib

ZONES = {
    "dark_wood": (0x58, 0x3E, 0x26, 0xFF),
    "lite_wood": (0x7C, 0x5A, 0x38, 0xFF),
    "lite_iron": (0xE8, 0xE8, 0xE8, 0xFF),
    "mid_iron": (0xB0, 0xB0, 0xB0, 0xFF),
    "dark_iron": (0x78, 0x78, 0x78, 0xFF),
}


def zone_color(x):
    if x < 2:
        return ZONES["dark_wood"]
    if x < 4:
        return ZONES["lite_wood"]
    if x < 8:
        return ZONES["lite_iron"]
    if x < 12:
        return ZONES["mid_iron"]
    return ZONES["dark_iron"]


def write_png(path, width, height, rows):
    """rows: list of rows, each row is a list of (r, g, b, a) tuples."""
    raw = bytearray()
    for row in rows:
        raw.append(0)  # filter type 0 (None)
        for pixel in row:
            raw += bytes(pixel)

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8bit RGBA
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )
    with open(path, "wb") as handle:
        handle.write(png)


def build_axe_texture():
    size = 16
    rows = []
    for _y in range(size):
        rows.append([zone_color(x) for x in range(size)])
    return size, size, rows


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.normpath(os.path.join(here, "..", "textures"))
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    width, height, rows = build_axe_texture()
    out_file = os.path.join(out_dir, "axe.png")
    write_png(out_file, width, height, rows)
    print("wrote %s (%dx%d)" % (out_file, width, height))


if __name__ == "__main__":
    main()
