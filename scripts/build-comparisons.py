#!/usr/bin/env python3
# Purpose: Builds equal-size reference-vs-native side-by-side comparison images with 40px label bands.
"""Regenerate Docs/Test_Results/Unreleased/visual/reference-vs-native-*.png.

Each output is the two unchanged 1280x800 screenshots side by side under a
40px label band (reference left, native right). No resampling of the source
captures: pixels are copied 1:1.
"""
import sys
from PIL import Image, ImageDraw, ImageFont

REPO = "/home/user/Archx-Agent"
VISUAL = f"{REPO}/Docs/Test_Results/Unreleased/visual"
REFERENCE = f"{REPO}/Docs/Test_Results/Unreleased/reference"

JOBS = [
    ("chat", f"{REFERENCE}/reference-chat-1280.png", f"{VISUAL}/linux-agent.png"),
    ("models", f"{REFERENCE}/reference-models-1280.png", f"{VISUAL}/linux-models.png"),
    ("import", f"{REFERENCE}/reference-import-fixture-1280.png", f"{VISUAL}/linux-import-verified.png"),
]

BAND = 40
FONT = ImageFont.truetype(f"{REPO}/assets/fonts/Manrope.ttf", 15)


def label_band(width: int, left: str, right: str) -> Image.Image:
    band = Image.new("RGB", (width, BAND), (16, 16, 16))
    draw = ImageDraw.Draw(band)
    draw.text((16, 11), left, fill=(244, 244, 244), font=FONT)
    draw.text((width // 2 + 16, 11), right, fill=(244, 244, 244), font=FONT)
    return band


def main() -> int:
    for name, ref_path, native_path in JOBS:
        ref = Image.open(ref_path).convert("RGB")
        native = Image.open(native_path).convert("RGB")
        if ref.size != native.size:
            print(f"WARN {name}: size mismatch {ref.size} vs {native.size} — stacking anyway")
        width = ref.width + native.width
        out = Image.new("RGB", (width, BAND + max(ref.height, native.height)), (0, 0, 0))
        band = label_band(width, f"Original web 1.9.0  |  {ref.width} x {ref.height}",
                          f"Native Iced  |  {native.width} x {native.height}")
        out.paste(band, (0, 0))
        out.paste(ref, (0, BAND))
        out.paste(native, (ref.width, BAND))
        dest = f"{VISUAL}/reference-vs-native-{name}.png"
        out.save(dest)
        print(f"wrote {dest} ({out.width}x{out.height})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
