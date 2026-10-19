# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Field and team branding (branding.py, images.py; decisions BR1-BR24).

    cd controller && python -m unittest discover -s tests

The image checks against real PNG, JPEG and WebP files (tests/fixtures/branding/, made by
make.py there with Pillow) and against hand-made broken ones; the endpoints through the whole
controller from main.build(): no token to read, the GM token to change, ETags and 304s,
persistence across a restart, team crests per game, team presets and the clean-up.
"""

from __future__ import annotations

import struct
import time
import unittest
import zlib
from pathlib import Path

from p3support import GM, READ, P3Case, bearer

from atalaia_controller import branding as brandmod
from atalaia_controller import images
from atalaia_controller.checkin import RateLimit

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "branding"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def chunk(ctype: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + ctype + body + struct.pack(">I", zlib.crc32(ctype + body) & 0xFFFFFFFF)


def png(width: int, height: int, rgb: tuple[int, int, int] = (200, 30, 40), *, extra: tuple[bytes, ...] = (),
        raw: bytes | None = None, ihdr: tuple[int, int] | None = None) -> bytes:
    """A truecolour PNG made by hand (no image library): extra chunks go before the image data."""
    w, h = ihdr or (width, height)
    if raw is None:
        raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    return (images.PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + b"".join(extra)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


SVG = (b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
       b'<script>alert(1)</script><rect width="64" height="64"/></svg>')


class ImageCheckTests(unittest.TestCase):
    def test_real_files_are_accepted_and_stripped(self):
        cases = [("logo.png", "image/png", images.LOGO, (256, 128), [b"tEXt", b"Someone Private"]),
                 ("logo.jpg", "image/jpeg", images.LOGO, (200, 200), [b"Exif\x00", b"private comment",
                                                                       b"PhoneMaker"]),
                 ("wallpaper.webp", "image/webp", images.WALLPAPER, (640, 400), [b"EXIF", b"PhoneMaker"]),
                 ("wallpaper.jpg", "image/jpeg", images.WALLPAPER, (800, 500), [b"Exif\x00", b"PhoneMaker"]),
                 ("crest-red.png", "image/png", images.CREST, (128, 128), []),
                 ("crest-blue.webp", "image/webp", images.CREST, (128, 128), [])]
        for name, ctype, limits, size, private in cases:
            with self.subTest(name):
                data = fixture(name)
                for marker in private:
                    self.assertIn(marker, data, "the fixture should carry metadata to strip")
                out = images.check(data, ctype, limits)
                self.assertEqual((out.content_type, out.width, out.height), (ctype, *size))
                for marker in private:
                    self.assertNotIn(marker, out.data)
                self.assertLessEqual(len(out.data), len(data))
                self.assertEqual(images.check(out.data, ctype, limits).data, out.data, "stripping is stable")

    def test_webp_extended_header_loses_its_metadata_flags(self):
        out = images.check(fixture("wallpaper.webp"), "image/webp", images.WALLPAPER).data
        self.assertEqual(out[12:16], b"VP8X")
        self.assertEqual(out[20] & (images.VP8X_EXIF | images.VP8X_XMP), 0)
        self.assertEqual(struct.unpack("<I", out[4:8])[0] + 8, len(out))

    def test_refused_types(self):
        cases = [
            (fixture("not-allowed.gif"), "image/gif", 415),     # GIF
            (SVG, "image/svg+xml", 415),                         # SVG: scripts
            (SVG, "image/png", 415),                             # SVG passed off as a PNG
            (b"<html><script>x</script></html>", "image/webp", 415),
            (fixture("logo.png"), "image/jpeg", 415),            # PNG declared as JPEG
            (fixture("logo.png"), "", 415),                      # no type
            (b"", "image/png", 422),
        ]
        for data, ctype, status in cases:
            with self.subTest(ctype=ctype, head=data[:8]):
                with self.assertRaises(images.ImageError) as cm:
                    images.check(data, ctype, images.LOGO)
                self.assertEqual(cm.exception.status, status)

    def test_size_dimension_and_animation_limits(self):
        def refused(data, ctype, limits, status=422):
            with self.assertRaises(images.ImageError) as cm:
                images.check(data, ctype, limits)
            self.assertEqual(cm.exception.status, status, str(cm.exception))
            return str(cm.exception)

        self.assertIn("1048576", refused(b"\x89PNG" + b"\x00" * images.LOGO.max_bytes, "image/png",
                                         images.LOGO, 413))
        self.assertIn("each side", refused(png(8, 8), "image/png", images.LOGO))          # too small
        self.assertIn("each side", refused(png(20, 20), "image/png", images.WALLPAPER))   # under 320
        # A header claiming 5000 pixels is refused before any inflating.
        self.assertIn("5000x20", refused(png(20, 20, ihdr=(5000, 20)), "image/png", images.LOGO))
        self.assertIn("times as long", refused(png(400, 40), "image/png", images.LOGO))   # 10:1
        self.assertIn("times as long", refused(png(100, 20), "image/png", images.CREST))  # 5:1 crest
        refused(fixture("animated.png"), "image/png", images.CREST)
        refused(fixture("animated.webp"), "image/webp", images.CREST)
        self.assertEqual(images.check(png(64, 64), "image/png", images.CREST).width, 64)

    def test_broken_files(self):
        good = png(32, 32)
        bad_crc = bytearray(good)
        bad_crc[29] ^= 0xFF  # inside IHDR's checksum
        truncated = good[:-20]
        # The header says 32x32 and the data inflates to more (a small decompression bomb) or less.
        bomb = png(32, 32, raw=b"\x00" * (33 * 97 * 50))
        short = png(32, 32, raw=b"\x00" * 100)
        unknown = png(32, 32, extra=(chunk(b"ZZZZ", b"x"),))
        jpeg = fixture("logo.jpg")
        for name, data, ctype in [("crc", bytes(bad_crc), "image/png"), ("truncated", truncated, "image/png"),
                                  ("bomb", bomb, "image/png"), ("short", short, "image/png"),
                                  ("unknown critical chunk", unknown, "image/png"),
                                  ("jpeg without end", jpeg[:len(jpeg) // 2].rstrip(b"\xff\xd9"), "image/jpeg"),
                                  ("jpeg header only", jpeg[:20], "image/jpeg"),
                                  ("webp size", fixture("crest-blue.webp")[:-10], "image/webp")]:
            with self.subTest(name):
                with self.assertRaises(images.ImageError) as cm:
                    images.check(data, ctype, images.LOGO)
                self.assertEqual(cm.exception.status, 422, str(cm.exception))

    def test_trailing_data_and_private_chunks_are_dropped(self):
        text = chunk(b"tEXt", b"Author\x00Someone")
        private = chunk(b"prVt", b"secret")
        data = png(40, 40, extra=(text, private)) + b"PK\x03\x04 appended zip"
        out = images.check(data, "image/png", images.LOGO).data
        self.assertNotIn(b"Someone", out)
        self.assertNotIn(b"secret", out)
        self.assertTrue(out.endswith(chunk(b"IEND", b"")))
        jpeg = fixture("logo.jpg") + b"trailing"
        self.assertTrue(images.check(jpeg, "image/jpeg", images.LOGO).data.endswith(b"\xff\xd9"))


class BrandingApiTests(P3Case):
    def put_image(self, slot, data, ctype, headers=GM, expect=200):
        r = self.client.put(f"/api/v1/field/branding/{slot}", content=data,
                            headers={**headers, "Content-Type": ctype})
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    def test_default_branding_needs_no_token(self):
        r = self.client.get("/api/v1/field/branding")
        self.assertEqual(r.status_code, 200, r.text)
        b = r.json()
        self.assertEqual((b["field_id"], b["field_name"], b["accent"], b["logo"], b["wallpaper"]),
                         ("field", "Atalaia", None, None, None))
        self.assertEqual(r.headers["etag"], b["etag"])
        self.assertEqual(r.headers["cache-control"], "no-cache")
        self.assertEqual(self.client.get("/api/v1/field/branding/logo").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/field/branding/banner").status_code, 404)

    def test_only_the_gm_changes_it(self):
        for headers, status in (({}, 401), (READ, 403)):
            self.assertEqual(self.client.put("/api/v1/field/branding", json={"accent": "#123456"},
                                             headers=headers).status_code, status)
            self.put_image("logo", fixture("logo.png"), "image/png", headers=headers, expect=status)
            self.assertEqual(self.client.delete("/api/v1/field/branding/logo", headers=headers).status_code,
                             status)
            self.assertEqual(self.client.post("/api/v1/crests", content=fixture("crest-red.png"),
                                              headers={**headers, "Content-Type": "image/png"}).status_code,
                             status)
        game = self.new_game()
        player = self.check_in(game["id"])
        self.assertEqual(self.client.put("/api/v1/field/branding", json={"accent": "#123456"},
                                         headers=bearer(player["token"])).status_code, 401)

    def test_upload_serve_etag_and_restart(self):
        r = self.client.get("/api/v1/field/branding")
        first_tag = r.headers["etag"]
        b = self.put_image("logo", fixture("logo.jpg"), "image/jpeg")
        self.assertEqual((b["logo"]["width"], b["logo"]["height"], b["logo"]["content_type"]),
                         (200, 200, "image/jpeg"))
        self.assertNotEqual(b["etag"], first_tag)
        self.put_image("wallpaper", fixture("wallpaper.webp"), "image/webp")
        out = self.client.put("/api/v1/field/branding", json={"accent": "#C0FFEE", "field_name": "Campo Norte"},
                              headers=GM).json()
        self.assertEqual((out["accent"], out["field_name"]), ("#c0ffee", "Campo Norte"))
        # One name: the poster and the check-in info follow it (decision BR4).
        self.assertEqual(self.client.get("/api/v1/checkin/poster", headers=GM).json()["field_name"], "Campo Norte")
        self.assertEqual(self.info()["field"]["name"], "Campo Norte")

        logo = self.client.get("/api/v1/field/branding/logo")
        self.assertEqual(logo.status_code, 200)
        self.assertEqual(logo.headers["content-type"], "image/jpeg")
        self.assertNotIn(b"Someone Private", logo.content)
        self.assertEqual(logo.headers["x-content-type-options"], "nosniff")
        self.assertIn("sandbox", logo.headers["content-security-policy"])
        tag = logo.headers["etag"]
        self.assertEqual(tag, out["logo"]["etag"])
        again = self.client.get("/api/v1/field/branding/logo", headers={"If-None-Match": tag})
        self.assertEqual((again.status_code, again.content), (304, b""))
        self.assertEqual(self.client.get("/api/v1/field/branding/logo",
                                         headers={"If-None-Match": '"other", W/' + tag}).status_code, 304)
        self.assertEqual(self.client.get("/api/v1/field/branding/logo",
                                         headers={"If-None-Match": '"other"'}).status_code, 200)
        info = self.client.get("/api/v1/field/branding")
        self.assertEqual(self.client.get("/api/v1/field/branding",
                                         headers={"If-None-Match": info.headers["etag"]}).status_code, 304)

        self.restart()
        after = self.client.get("/api/v1/field/branding").json()
        self.assertEqual(after, info.json())
        self.assertEqual(self.client.get("/api/v1/field/branding/wallpaper").status_code, 200)

    def test_replacing_and_removing_images(self):
        old = self.put_image("logo", fixture("logo.png"), "image/png")["logo"]["id"]
        new = self.put_image("logo", fixture("logo.jpg"), "image/jpeg")["logo"]["id"]
        self.assertNotEqual(old, new)
        self.assertIsNone(self.ctrl.store.image(old), "the replaced logo is deleted")
        out = self.client.delete("/api/v1/field/branding/logo", headers=GM).json()
        self.assertIsNone(out["logo"])
        self.assertIsNone(self.ctrl.store.image(new))
        self.assertEqual(self.client.get("/api/v1/field/branding/logo").status_code, 404)
        self.assertIsNone(self.client.put("/api/v1/field/branding", json={"accent": None},
                                          headers=GM).json()["accent"])

    def test_upload_refusals_over_http(self):
        self.put_image("logo", SVG, "image/svg+xml", expect=415)
        self.put_image("logo", SVG, "image/png", expect=415)
        self.put_image("logo", fixture("not-allowed.gif"), "image/gif", expect=415)
        self.put_image("logo", png(8, 8), "image/png", expect=422)
        self.put_image("logo", fixture("animated.webp"), "image/webp", expect=422)
        self.put_image("logo", b"\x89PNG" + b"\x00" * images.LOGO.max_bytes, "image/png", expect=413)
        self.put_image("wallpaper", fixture("wallpaper.jpg"), "image/jpeg")  # 36 KB is fine as a wallpaper
        self.put_image("banner", fixture("logo.png"), "image/png", expect=404)
        for spec in ({"accent": "red"}, {"accent": "#12345"}, {"field_name": ""}, {"field_name": "x" * 49},
                     {"logo": "abc"}):
            self.assertEqual(self.client.put("/api/v1/field/branding", json=spec, headers=GM).status_code, 400,
                             spec)

    def test_public_reads_are_rate_limited(self):
        self.ctrl.branding.rate = RateLimit(3)
        codes = [self.client.get("/api/v1/field/branding").status_code for _ in range(4)]
        self.assertEqual(codes, [200, 200, 200, 429])

    def test_stream_carries_branding(self):
        game = self.new_game()
        player = self.check_in(game["id"])
        with self.client.websocket_connect(f"/api/v1/stream?token={player['token']}") as ws:
            hello = ws.receive_json()
            self.assertEqual(hello["branding"]["field_id"], "field")
            self.client.put("/api/v1/field/branding", json={"accent": "#224466"}, headers=GM)
            for _ in range(20):
                msg = ws.receive_json()
                if msg["type"] == "branding":
                    break
            self.assertEqual(msg["branding"]["accent"], "#224466")


class TeamBrandingTests(P3Case):
    def crest(self, name="crest-red.png", ctype="image/png", expect=201):
        r = self.client.post("/api/v1/crests", content=fixture(name), headers={**GM, "Content-Type": ctype})
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    def test_crests_are_stored_once_and_cached_forever(self):
        red = self.crest()
        self.assertEqual(self.crest(expect=200)["crest_id"], red["crest_id"])
        r = self.client.get(red["url"])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["cache-control"], "public, max-age=31536000, immutable")
        self.assertEqual(self.client.get(red["url"], headers={"If-None-Match": r.headers["etag"]}).status_code, 304)
        self.assertEqual(self.client.get("/api/v1/crests/" + "0" * 64).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/crests/%2e%2e%2Ffield").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/crests/" + red["crest_id"].upper()).status_code, 404)
        r = self.client.post("/api/v1/crests", content=png(100, 20), headers={**GM, "Content-Type": "image/png"})
        self.assertEqual(r.status_code, 422, r.text)  # 5:1, a crest is at most 4:1
        r = self.client.post("/api/v1/crests", content=SVG, headers={**GM, "Content-Type": "image/svg+xml"})
        self.assertEqual(r.status_code, 415, r.text)
        r = self.client.post("/api/v1/crests", content=b"x" * (images.CREST.max_bytes + 1),
                             headers={**GM, "Content-Type": "image/png"})
        self.assertEqual(r.status_code, 413)

    def test_game_teams_with_display_names_and_crests(self):
        red = self.crest()["crest_id"]
        blue = self.crest("crest-blue.webp", "image/webp")["crest_id"]
        game = self.new_game(team_info={"red": {"display_name": "Lobos", "crest_id": red},
                                        "blue": {"display_name": " Águias "}})
        self.assertEqual(game["teams"], ["red", "blue"], "the colours stay the team names")
        self.assertEqual(game["team_info"], {"red": {"display_name": "Lobos", "crest_id": red},
                                             "blue": {"display_name": "Águias"}})
        teams = self.client.get(f"/api/v1/games/{game['id']}/teams").json()  # no token
        self.assertEqual([t["team"] for t in teams["teams"]], ["red", "blue"])
        self.assertEqual(teams["teams"][0]["crest_url"], f"/api/v1/crests/{red}")
        self.assertIsNone(teams["teams"][1]["crest_id"])
        out = self.client.put(f"/api/v1/games/{game['id']}/teams/blue", json={"crest_id": blue},
                              headers=GM).json()
        self.assertEqual(out["team_info"]["blue"], {"display_name": "Águias", "crest_id": blue})
        cleared = self.client.put(f"/api/v1/games/{game['id']}/teams/red", json={"display_name": None,
                                                                                "crest_id": None}, headers=GM)
        self.assertNotIn("red", cleared.json()["team_info"])
        # The players' view: the game (with its team_info) through a player token.
        player = self.check_in(game["id"])
        seen = self.client.get(f"/api/v1/games/{game['id']}", headers=bearer(player["token"])).json()
        self.assertEqual(seen["team_info"]["blue"]["display_name"], "Águias")
        # Survives a restart, and the game ending keeps it but locks it.
        self.restart()
        self.assertEqual(self.client.get(f"/api/v1/games/{game['id']}", headers=READ).json()["team_info"],
                         {"blue": {"display_name": "Águias", "crest_id": blue}})
        self.client.post(f"/api/v1/games/{game['id']}/start", headers=GM)
        self.client.post(f"/api/v1/games/{game['id']}/end", headers=GM, json={})
        self.assertEqual(self.client.put(f"/api/v1/games/{game['id']}/teams/blue", json={"display_name": "X"},
                                         headers=GM).status_code, 409)

    def test_team_info_refusals(self):
        bad = [{"green": {"display_name": "X"}}, {"red": {"display_name": "x" * 33}},
               {"red": {"crest_id": "f" * 64}}, {"red": {"crest_id": "../etc"}}, {"red": "Lobos"},
               {"red": {"colour": "green"}}, ["red"], {"red": {"display_name": "a\u0007b"}}]
        for info in bad:
            r = self.client.post("/api/v1/games", headers=GM,
                                 json={"name": "X", "mode_id": "org.atalaia.domination", "teams": ["red", "blue"],
                                       "team_info": info})
            self.assertEqual(r.status_code, 400, (info, r.text))
        r = self.client.post("/api/v1/games", headers=GM, json={
            "name": "X", "mode_id": "org.atalaia.domination", "teams": ["red", "blue"],
            "team_info": {"red": {"team_preset_id": 99}}})
        self.assertEqual(r.status_code, 404)
        game = self.new_game()
        self.assertEqual(self.client.put(f"/api/v1/games/{game['id']}/teams/green", json={},
                                         headers=GM).status_code, 404)
        self.assertEqual(self.client.put(f"/api/v1/games/{game['id']}/teams/red", json={"display_name": "L"},
                                         headers=READ).status_code, 403)
        self.assertEqual(self.client.get("/api/v1/games/9999/teams").status_code, 404)

    def test_team_presets(self):
        crest = self.crest()["crest_id"]
        r = self.client.post("/api/v1/team-presets", json={"name": "Lobos do Norte", "colour": "red",
                                                           "crest_id": crest}, headers=GM)
        self.assertEqual(r.status_code, 201, r.text)
        preset = r.json()
        self.assertEqual(preset["crest_url"], f"/api/v1/crests/{crest}")
        self.assertEqual(self.client.post("/api/v1/team-presets", json={"name": "Lobos do Norte"},
                                          headers=GM).status_code, 409)
        self.assertEqual(self.client.post("/api/v1/team-presets", json={"name": "A", "crest_id": "0" * 64},
                                          headers=GM).status_code, 400)
        self.assertEqual(self.client.post("/api/v1/team-presets", json={"name": "B"}, headers=READ).status_code,
                         403)
        self.assertEqual(len(self.client.get("/api/v1/team-presets", headers=READ).json()), 1)
        game = self.new_game(team_info={"red": {"team_preset_id": preset["id"]}})
        self.assertEqual(game["team_info"]["red"], {"display_name": "Lobos do Norte", "crest_id": crest,
                                                    "team_preset_id": preset["id"]})
        changed = self.client.put(f"/api/v1/team-presets/{preset['id']}", json={"name": "Lobos"}, headers=GM).json()
        self.assertEqual((changed["name"], changed["crest_id"], changed["colour"]), ("Lobos", crest, "red"))
        self.restart()
        self.assertEqual(self.client.get("/api/v1/team-presets", headers=GM).json()[0]["name"], "Lobos")
        self.assertEqual(self.client.delete(f"/api/v1/team-presets/{preset['id']}", headers=GM).status_code, 200)
        self.assertEqual(self.client.delete(f"/api/v1/team-presets/{preset['id']}", headers=GM).status_code, 404)
        self.assertIsNotNone(self.ctrl.store.image(crest), "the game still shows it")

    def test_unused_crests_are_purged_after_a_day(self):
        used = self.crest()["crest_id"]
        unused = self.crest("crest-blue.webp", "image/webp")["crest_id"]
        self.new_game(team_info={"red": {"crest_id": used}})
        svc = self.ctrl.branding
        self.assertEqual(svc.purge(force=True), 0, "a fresh upload is kept for a day")
        self.assertEqual(svc.purge(force=True, now=time.time() + brandmod.CREST_GRACE_S + 60), 1)
        self.assertIsNone(self.ctrl.store.image(unused))
        self.assertIsNotNone(self.ctrl.store.image(used))
        self.assertEqual(svc.purge(now=time.time() + 2 * brandmod.CREST_GRACE_S), 0, "throttled")

    def test_crest_cap(self):
        orig = brandmod.CREST_MAX
        brandmod.CREST_MAX = 1
        try:
            self.crest()
            self.crest(expect=200)  # the same crest again is fine
            self.crest("crest-blue.webp", "image/webp", expect=409)
        finally:
            brandmod.CREST_MAX = orig


if __name__ == "__main__":
    unittest.main()
