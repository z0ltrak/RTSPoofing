#!/usr/bin/env python3
"""Convert PNG/JPEG/etc. to a 240x120 BMP and a numeric RGB565 flash array."""
import argparse
from pathlib import Path

from PIL import Image, ImageOps

BACKGROUND = (0x05, 0x12, 0x49)
SIZE = (240, 120)


def prepare_image(source, crop=False, round_display=False, white=False,
                  clear_top_row=False):
    with Image.open(source) as original:
        image = ImageOps.exif_transpose(original).convert("RGBA")
    if clear_top_row:
        # Supplied RDT file has a detached 1px horizontal artifact on row 0.
        # Preserve the original file and clear just this row before resampling.
        image.paste((0, 0, 0, 0), (0, 0, image.width, 1))
    if white:
        # Recolor the actual silhouette while preserving its alpha/edge coverage.
        silhouette = Image.new("RGBA", image.size, (255, 255, 255, 0))
        silhouette.putalpha(image.getchannel("A"))
        image = silhouette
    # Composite alpha before resizing to avoid fringes around transparent edges.
    backing = Image.new("RGBA", image.size, BACKGROUND + (255,))
    image = Image.alpha_composite(backing, image).convert("RGB")
    if crop:
        # Exactly 120px tall artwork; crop its left/right edges if over 240px wide.
        width = max(1, round(image.width * SIZE[1] / image.height))
        image = image.resize((width, SIZE[1]), Image.Resampling.LANCZOS)
        if width > SIZE[0]:
            left = (width - SIZE[0]) // 2
            image = image.crop((left, 0, left + SIZE[0], SIZE[1]))
    elif round_display:
        # RDT layout: narrower artwork, bottom aligned in the top semicircle.
        image = ImageOps.contain(image, (200, 120), Image.Resampling.LANCZOS)
    else:
        # Preserve the whole logo. Wide artwork is fit within a 240x120 canvas.
        image = ImageOps.contain(image, SIZE, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", SIZE, BACKGROUND)
    y = SIZE[1] - image.height if round_display else (SIZE[1] - image.height) // 2
    canvas.paste(image, ((SIZE[0] - image.width) // 2, y))
    return canvas


def write_header(image, output):
    pixels = image.load()
    values = []
    for y in range(image.height):
        for x in range(image.width):
            r, g, b = pixels[x, y]
            values.append(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3))
    lines = ["#pragma once", "#include <Arduino.h>", "",
             "// Generated RGB565 values in row-major order. Do not byte-swap.",
             "constexpr bool LOGO_AVAILABLE = true;",
             "constexpr int16_t LOGO_WIDTH = 240;",
             "constexpr int16_t LOGO_HEIGHT = 120;",
             "const uint16_t LOGO_RGB565[240 * 120] PROGMEM = {"]
    for offset in range(0, len(values), 12):
        lines.append("  " + ", ".join(f"0x{value:04X}"
                                      for value in values[offset:offset + 12]) + ",")
    lines.extend(["};", ""])
    output.write_text("\n".join(lines), encoding="utf-8")


def main():
    default_header = Path(__file__).resolve().parents[1] / "arduino/HackingButton/Logo.h"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="Source PNG, JPEG, BMP, etc.")
    parser.add_argument("--output", type=Path, default=default_header,
                        help="Header destination (default: project's Logo.h)")
    parser.add_argument("--crop", action="store_true",
                        help="Scale artwork to 120px high, center-crop if too wide")
    parser.add_argument("--round", action="store_true", dest="round_display",
                        help="Fit the supplied RDT logo within the round top half")
    parser.add_argument("--white", action="store_true",
                        help="Recolor the silhouette white, preserving alpha")
    parser.add_argument("--clear-top-row", action="store_true",
                        help="Remove the supplied RDT file's stray row-0 line")
    args = parser.parse_args()
    if args.crop and args.round_display:
        parser.error("Choose --crop or --round, not both")
    if not args.image.is_file():
        parser.error(f"Image does not exist: {args.image}")
    if args.output.suffix.lower() != ".h":
        parser.error("--output must end in .h")
    destinations = [args.output, args.output.with_suffix(".bmp"),
                    args.output.with_name("logo_preview.png")]
    if args.image.resolve() in [path.resolve() for path in destinations]:
        parser.error("Choose output paths that do not overwrite the source image")
    image = prepare_image(args.image, crop=args.crop, round_display=args.round_display,
                          white=args.white, clear_top_row=args.clear_top_row)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_header(image, args.output)
    image.save(destinations[1], "BMP")
    image.save(destinations[2], "PNG")
    print(f"Created {args.output} (240x120, 57,600 RGB565 bytes in flash)")
    print(f"Created {destinations[1]} and {destinations[2]}")


if __name__ == "__main__":
    main()
