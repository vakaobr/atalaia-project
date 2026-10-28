# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field's logo for a Field Box (box_logo.py, decision PKG-1).

    cd controller && python -m unittest discover -s tests

The conversion against protocol/vectors/box_logo.json (the Dart controller holds the same file), and the
two endpoints a box uses through the whole controller: no token, 404 for no logo or a JPEG, a new id when the
logo is replaced, and the bytes the release text promises.
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import unittest
from pathlib import Path

from p3support import GM, P3Case

from atalaia_controller import box_logo
from test_branding import fixture

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "protocol" / "vectors" / "box_logo.json").read_text())


class ConvertTests(unittest.TestCase):
    def test_vectors(self):
        self.assertEqual((VECTORS["side"], VECTORS["bytes"]), (box_logo.SIDE, box_logo.SIZE))
        self.assertEqual(VECTORS["background"], "%02x%02x%02x" % box_logo.BG)
        for case in VECTORS["cases"]:
            with self.subTest(case["name"]):
                png = base64.b64decode(case["png_b64"])
                self.assertEqual(hashlib.sha256(png).hexdigest(), case["png_sha256"])
                out = box_logo.convert(png)
                self.assertEqual(len(out), case["box_bytes"])
                self.assertEqual(out[:16].hex(), case["box_head"])
                self.assertEqual(hashlib.sha256(out).hexdigest(), case["box_sha256"])

    def test_release_text_matches_the_vector(self):
        self.assertEqual(box_logo.release_text("ab" * 32, b"\x01\x02\x03"), VECTORS["release_text"])

    def test_format_and_letterbox(self):
        wide = next(c for c in VECTORS["cases"] if c["name"] == "palette4_trns_wide")
        out = box_logo.convert(base64.b64decode(wide["png_b64"]))
        self.assertEqual(out[:4], b"ALG1")
        self.assertEqual(struct.unpack_from("<HH", out, 4), (96, 96))
        px = lambda x, y: struct.unpack_from("<H", out, 8 + 2 * (y * 96 + x))[0]
        bg = ((0x10 >> 3) << 11) | ((0x14 >> 2) << 5) | (0x18 >> 3)
        self.assertEqual(px(0, 0), bg)           # the letterbox above a 3:1 logo is the screen colour
        self.assertEqual(px(95, 95), bg)
        self.assertNotEqual(px(48, 48), bg)

    def test_transparent_pixels_become_the_screen_colour(self):
        graya = next(c for c in VECTORS["cases"] if c["name"] == "graya8_adam7")
        out = box_logo.convert(base64.b64decode(graya["png_b64"]))
        self.assertEqual(len(out), box_logo.SIZE)

    def test_not_png_and_too_big(self):
        with self.assertRaises(box_logo.BoxLogoError):
            box_logo.convert(fixture("logo.jpg"))
        big = base64.b64decode(VECTORS["cases"][0]["png_b64"])
        head = bytearray(big)
        head[16:24] = struct.pack(">II", 2000, 2000)  # IHDR claims 4 Mpixels (its CRC no longer holds: not read)
        with self.assertRaises(box_logo.BoxLogoError):
            box_logo.convert(bytes(head))
        with self.assertRaises(box_logo.BoxLogoError):
            box_logo.convert(big[:60])


class BoxLogoApiTests(P3Case):
    def put_logo(self, name, ctype):
        r = self.client.put("/api/v1/field/branding/logo", content=fixture(name),
                            headers={**GM, "Content-Type": ctype})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["logo"]["id"]

    def test_no_logo_and_a_jpeg_logo_are_not_offered(self):
        for path in ("/api/v1/field/box-logo/release", "/api/v1/field/box-logo"):
            self.assertEqual(self.client.get(path).status_code, 404)
        self.put_logo("logo.jpg", "image/jpeg")
        for path in ("/api/v1/field/box-logo/release", "/api/v1/field/box-logo"):
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_a_png_logo_is_served_to_boxes_without_a_token(self):
        image_id = self.put_logo("logo.png", "image/png")
        rel = self.client.get("/api/v1/field/box-logo/release")
        self.assertEqual(rel.status_code, 200, rel.text)
        self.assertEqual(rel.headers["content-type"], "text/plain; charset=utf-8")
        lines = rel.text.splitlines()
        self.assertEqual(lines[0], "atalaia-box-logo-v1")
        self.assertEqual(lines[1], f"id={image_id}")
        data = self.client.get("/api/v1/field/box-logo")
        self.assertEqual(data.status_code, 200)
        self.assertEqual(len(data.content), box_logo.SIZE)
        self.assertEqual(lines[2], f"sha256={hashlib.sha256(data.content).hexdigest()}")
        self.assertEqual(lines[3], f"bytes={box_logo.SIZE}")
        self.assertEqual(data.headers["etag"], f'"{image_id}"')
        # A new logo, a new id; no logo, nothing to draw.
        again = self.client.get("/api/v1/field/box-logo/release").text
        self.assertEqual(again, rel.text)
        self.client.delete("/api/v1/field/branding/logo", headers=GM)
        self.assertEqual(self.client.get("/api/v1/field/box-logo/release").status_code, 404)

    # --- a JPEG or WebP logo, converted by the GM console (decision LOGO-1) ---------------------------------

    def put_box(self, image_id, data, headers=GM):
        return self.client.put(f"/api/v1/field/branding/logo/box?id={image_id}", content=data,
                               headers={**headers, "Content-Type": "application/octet-stream"})

    def test_a_jpeg_logo_is_served_from_the_consoles_bytes(self):
        ready = box_logo.convert(fixture("logo.png"))  # stands for what the console makes in the browser
        image_id = self.put_logo("logo.jpg", "image/jpeg")
        r = self.put_box(image_id, ready)
        self.assertEqual(r.status_code, 200, r.text)
        data = self.client.get("/api/v1/field/box-logo")
        self.assertEqual((data.status_code, data.content), (200, ready))
        self.assertEqual(data.headers["etag"], f'"{image_id}"')
        rel = self.client.get("/api/v1/field/box-logo/release").text.splitlines()
        self.assertEqual(rel[1], f"id={image_id}")
        self.assertEqual(rel[2], f"sha256={hashlib.sha256(ready).hexdigest()}")
        # A new logo makes the bytes stale: nothing is served until the console uploads new ones.
        self.put_logo("wallpaper.jpg", "image/jpeg")
        self.assertEqual(self.client.get("/api/v1/field/box-logo").status_code, 404)

    def test_the_controller_checks_the_uploaded_bytes(self):
        ready = box_logo.convert(fixture("logo.png"))
        image_id = self.put_logo("logo.jpg", "image/jpeg")
        bad = [ready[:-1], b"", b"XXXX" + ready[4:], ready[:4] + struct.pack("<HH", 95, 96) + ready[8:]]
        for data in bad:
            self.assertEqual(self.put_box(image_id, data).status_code, 400, len(data))
        self.assertEqual(self.put_box(image_id, b"\0" * (box_logo.SIZE + 1)).status_code, 413)
        self.assertEqual(self.client.get("/api/v1/field/box-logo").status_code, 404)
        self.assertEqual(self.put_box(image_id, ready, headers={}).status_code, 401)
        self.assertEqual(self.put_box("0" * 64, ready).status_code, 409)  # not the field's logo
        self.assertEqual(self.client.get("/api/v1/field/box-logo").status_code, 404)

    def test_a_png_logo_is_never_replaced_by_uploaded_bytes(self):
        image_id = self.put_logo("logo.png", "image/png")
        self.assertEqual(self.put_box(image_id, box_logo.convert(fixture("logo.png"))).status_code, 409)

    def test_no_logo_no_box_logo(self):
        self.assertEqual(self.put_box("0" * 64, box_logo.convert(fixture("logo.png"))).status_code, 409)


if __name__ == "__main__":
    unittest.main()
