#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Makes the branding test images in this folder (test_branding.py, the console and app tests).

Run once with Pillow, outside the controller (which has no image library, decision BR7):
    docker run --rm -v "$PWD:/out" python:3.12-slim sh -c "pip install pillow==11.0.0 && python /out/make.py"
The logo, wallpaper and JPEG files carry made-up metadata (an author, EXIF fields, a comment) for the
controller to strip; the animated and GIF files are there to be refused. Drawn here, no third-party art.
"""
import os

from PIL import Image, ImageDraw, PngImagePlugin

OUT = os.path.dirname(os.path.abspath(__file__)) + "/"

def shield(size, fill, accent):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    w = size
    d.polygon([(w*0.1, w*0.08), (w*0.9, w*0.08), (w*0.9, w*0.5), (w*0.5, w*0.94), (w*0.1, w*0.5)], fill=fill, outline=accent, width=max(2, w//24))
    d.rectangle([w*0.44, w*0.2, w*0.56, w*0.7], fill=accent)
    d.rectangle([w*0.28, w*0.32, w*0.72, w*0.44], fill=accent)
    return im

# Logo PNG 256x128 with a text chunk (stripped by the controller)
logo = Image.new("RGBA", (256, 128), (0, 0, 0, 0))
d = ImageDraw.Draw(logo)
d.ellipse([8, 8, 120, 120], fill=(31, 58, 43, 255), outline=(255, 179, 0, 255), width=8)
d.polygon([(64, 24), (100, 100), (28, 100)], fill=(255, 179, 0, 255))
d.rectangle([136, 40, 248, 56], fill=(31, 58, 43, 255))
d.rectangle([136, 72, 220, 88], fill=(255, 179, 0, 255))
info = PngImagePlugin.PngInfo()
info.add_text("Author", "Someone Private")
info.add_text("Comment", "GPS 38.7,-9.1")
logo.save(OUT + "logo.png", pnginfo=info)

# Logo JPEG with EXIF and a comment
exif = Image.Exif()
exif[0x010F] = "PhoneMaker"
exif[0x013B] = "Someone Private"
lj = Image.new("RGB", (200, 200), (31, 58, 43))
ImageDraw.Draw(lj).ellipse([20, 20, 180, 180], fill=(255, 179, 0))
lj.save(OUT + "logo.jpg", quality=85, exif=exif.tobytes(), comment=b"private comment")

# Wallpaper WebP (lossy, extended with EXIF) and progressive JPEG
wp = Image.new("RGB", (640, 400), (40, 70, 50))
d = ImageDraw.Draw(wp)
for i in range(0, 640, 40):
    d.line([(i, 0), (i + 200, 400)], fill=(60 + i // 8, 100, 60), width=12)
wp.save(OUT + "wallpaper.webp", quality=70, exif=exif.tobytes())
wp.resize((800, 500)).save(OUT + "wallpaper.jpg", quality=80, progressive=True, exif=exif.tobytes())

# Crests
shield(128, (215, 38, 61, 255), (255, 255, 255, 255)).save(OUT + "crest-red.png")
shield(128, (27, 110, 224, 255), (255, 255, 255, 255)).save(OUT + "crest-blue.webp", lossless=True)

# Refused: animated WebP and PNG, a tiny logo, a GIF
frames = [Image.new("RGB", (64, 64), c) for c in ((255, 0, 0), (0, 0, 255))]
frames[0].save(OUT + "animated.webp", save_all=True, append_images=frames[1:], duration=200, loop=0)
frames[0].save(OUT + "animated.png", save_all=True, append_images=frames[1:], duration=200, loop=0)
frames[0].save(OUT + "not-allowed.gif")
