#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Browser tests of the live demo's own pages (decision DEMO-20); run by `python3 tools/docker_server.py preview-demo-unit`.

Headless Chromium (Playwright's image; no network) opens the demo's pages from server/preview/demo/field/ with
/player/data.json answered from stand-in data shaped as proxy.py's player_data() makes it:

 * every .js file of the demo parses (a duplicate `const` is a SyntaxError that otherwise shows only on screen, DEMO-18);
 * the player's view on the open field (no floors), in the three-storey building (floor buttons, the plan asked for per
   floor, the beacons of that floor), the three position kinds (beacon square, GPS circle, hollow ring for an unknown
   floor), team colours when a position's team is a number or a name, the waiting state, and the four languages
   (every text table has the same keys; the page's chrome changes with the language), with no script error.

Usage in the image: python3 demo_player_browser.py REPO_ROOT. Exit 0 when all pass.
"""

from __future__ import annotations

import http.server
import json
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360f8cf"
                    "f01f0005000100a5f645400000000049454e44ae426082")
RED, BLUE = "rgb(214, 69, 59)", "rgb(61, 116, 214)"
ME = "p-me"
CORNERS = {"top_left": {"lat": 0.002, "lon": 0.0}, "top_right": {"lat": 0.002, "lon": 0.002},
           "bottom_left": {"lat": 0.0, "lon": 0.0}, "bottom_right": {"lat": 0.0, "lon": 0.002}}
FAILS: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("ok   " if ok else "FAIL ") + what, flush=True)
    if not ok:
        FAILS.append(what)


def base_data() -> dict:
    return {
        "me": {"display_name": "Falcão", "team": "red", "team_name": "Vermelha", "role": "vip", "status": "checked_in",
               "squad": 2, "player_id": ME, "game_id": 7, "replicas": [{"class": "rifle", "type": "aeg", "state": "passed"}]},
        "game": {"id": 7, "name": "Domínio", "state": "running", "teams": ["red", "blue"], "game_time_ms": 61000},
        "score": {"game": 7, "teams": {"red": 12, "blue": 9}},
        "positions": [], "georef": {"georef": {"corners": CORNERS}},
        "log": [{"t": 1000, "type": "game.start", "data": {}},
                {"t": 65000, "type": "zone.captured", "node": 1, "team": "blue", "data": {}}],
        "nodes": [{"node_id": 1, "name": "alpha", "owner": "red", "link": "online"},
                  {"node_id": 2, "name": "bravo", "owner": "blue", "link": "online"}],
        "boxes": {"1": {"x": 0.2, "y": 0.3, "level": 0}, "2": {"x": 0.7, "y": 0.6, "level": 1}},
        "levels": {"enabled": False, "count": 1, "names": [], "stamps": []}, "beacons": [], "you": ME}


def open_field() -> dict:
    d = base_data()
    # team is the number in the game's list (1 red, 2 blue), a name only in older data; fixes are GPS or a beacon's x, y
    d["positions"] = [{"player_id": ME, "team": 1, "lat": 0.001, "lon": 0.001, "source": "gps"},
                      {"player_id": "p2", "team": 2, "lat": 0.0005, "lon": 0.0015, "source": "gps"},
                      {"player_id": "p3", "team": "blue", "x": 0.5, "y": 0.5, "source": "ble"}]
    return d


def building() -> dict:
    d = base_data()
    d["game"]["name"] = "Prédio"
    d["levels"] = {"enabled": True, "count": 3, "names": ["R/C", "1.º andar", "2.º andar"],
                   "stamps": ["s0", "s1", "s2"]}
    d["beacons"] = [{"major": 1, "minor": 1, "room": "Hall", "level": 0, "x": 0.1, "y": 0.1},
                    {"major": 2, "minor": 1, "room": "Sala B", "level": 1, "x": 0.4, "y": 0.4},
                    {"major": 2, "minor": 2, "room": "Sala B2", "level": 1, "x": 0.6, "y": 0.4},
                    {"major": 3, "minor": 1, "room": "Sala C", "level": 2, "x": 0.8, "y": 0.8}]
    d["positions"] = [
        {"player_id": ME, "team": 1, "lat": 0.001, "lon": 0.001, "source": "gps", "level": 1, "room": "Sala B"},
        {"player_id": "p2", "team": 2, "x": 0.4, "y": 0.4, "source": "ble", "level": 1},       # beacon: square, floor 1
        {"player_id": "p3", "team": 2, "x": 0.1, "y": 0.1, "source": "ble", "level": 0},       # beacon: square, floor 0
        {"player_id": "p4", "team": 1, "lat": 0.0015, "lon": 0.0005, "source": "gps", "level": 2},  # GPS circle, floor 2
        {"player_id": "p5", "team": 1, "lat": 0.0004, "lon": 0.0004, "source": "gps", "level": None}]  # unknown floor
    return d


def serve(field: Path) -> http.server.ThreadingHTTPServer:
    """The demo's player directory under /player/, as the proxy serves it (data.json and field.png come from routes)."""
    kinds = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def do_GET(self) -> None:
            path = self.path.split("?")[0]
            name = "index.html" if path == "/player/" else path.removeprefix("/player/") if path.startswith("/player/") else ""
            f = field / "player" / name
            if not name or "/" in name or not f.is_file():
                self.send_error(404)
                return
            body = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", kinds.get(f.suffix, "application/octet-stream") + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def page_for(browser, base: str, data: dict | None, lang: str = "en"):
    """A page on the player's view with data.json answered by `data` (None: 503, as without a game)."""
    ctx = browser.new_context(viewport={"width": 420, "height": 900})
    page = ctx.new_page()
    page.errors = []
    page.requested = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.on("console", lambda m: page.errors.append(m.text) if m.type == "error" else None)

    def data_json(route) -> None:
        if data is None:
            route.fulfill(status=503, content_type="application/json", body='{"waiting": true}')
        else:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

    def png(route) -> None:
        page.requested.append(route.request.url)
        route.fulfill(status=200, content_type="image/png", body=PNG)

    page.route("**/player/data.json", data_json)
    page.route("**/player/field.png*", png)
    page.goto(f"{base}/player/?lang={lang}")
    page.wait_for_selector("#view:not([hidden])" if data is not None else "#waiting:not([hidden])")
    return page


def people(page) -> list[dict]:
    return page.evaluate("""() => [...document.querySelectorAll('#plan-people > *')].map(e => ({
        tag: e.tagName.toLowerCase(), fill: e.getAttribute('fill'), r: e.getAttribute('r') || e.getAttribute('width')}))""")


def fills(page, selector: str) -> list[str]:
    return page.locator(selector).evaluate_all("els => els.map(e => getComputedStyle(e).fill)")


def test_parse(browser, root: Path, field: Path) -> None:
    page = browser.new_context().new_page()
    files = sorted(field.rglob("*.js"))
    check(len(files) >= 2, f"the demo has JavaScript files to parse ({len(files)})")
    for f in files:
        # new Function() parses the source without running it: a duplicate `const` or a stray brace throws here
        err = page.evaluate("(src) => { try { new Function(src); return ''; } catch (e) { return String(e); } }",
                            f.read_text(encoding="utf-8"))
        check(err == "", f"{f.relative_to(root)} parses" + (f": {err}" if err else ""))
    page.context.close()


def test_open_field(browser, base: str) -> None:
    page = page_for(browser, base, open_field())
    check(page.inner_text("#callsign") == "Falcão", "open field: the callsign")
    check(page.inner_text("#game-name") == "Domínio" and page.inner_text("#game-state") == "playing",
          "open field: the game and its state")
    check(page.inner_text("#clock") in ("01:01", "01:02"), "open field: the clock from game_time_ms")
    check(page.locator("#levels").is_hidden(), "open field: no floor buttons")
    check(page.locator("#plan-beacons > *").count() == 0, "open field: no beacon dots")
    ppl = people(page)
    check([p["tag"] for p in ppl] == ["circle", "circle", "rect"],
          f"open field: GPS fixes are circles, a beacon fix a square ({[p['tag'] for p in ppl]})")
    f = fills(page, "#plan-people > *")
    check(f == [RED, BLUE, BLUE], f"open field: team numbers 1 and 2, and a name, draw red and blue ({f}) (DEMO-18)")
    check(ppl[0]["r"] == "9" and ppl[1]["r"] == "6", "open field: the player's own dot is bigger")
    f = fills(page, "#plan-boxes circle")
    check(f == [RED, BLUE], f"open field: both boxes, in the colour of their owner ({f})")
    check(page.locator("#unsure-note").is_hidden() and page.locator("#where").is_hidden(),
          "open field: no unsure note, no room line")
    check(page.locator("#scores .score").count() == 2 and page.locator("#scores .you").count() == 1,
          "open field: two scores, mine marked")
    check(page.locator("#events li").count() == 2, "open field: the events list")
    check(page.locator("#chip").evaluate("e => getComputedStyle(e).backgroundColor") == RED,
          "open field: the chip is the team's colour")
    check(not page.errors, f"open field: no script or console errors {page.errors}")
    page.context.close()


def test_building(browser, base: str) -> None:
    page = page_for(browser, base, building())
    buttons = page.locator("#levels button")
    check(page.locator("#levels").is_visible() and buttons.count() == 3, "building: three floor buttons")
    check(buttons.all_inner_texts() == ["R/C", "1.º andar", "2.º andar"], "building: the floor names")
    pressed = buttons.evaluate_all("els => els.map(e => e.getAttribute('aria-pressed'))")
    check(pressed == ["false", "true", "false"], f"building: opens on the player's own floor ({pressed})")
    check(any("level=1" in u and "v=s1" in u for u in page.requested), "building: floor 1's plan is asked for, with its stamp")
    # floor 1: me (GPS circle), p2 (beacon square), p5 (unknown floor, hollow); p3 is on floor 0 and p4 on floor 2
    ppl = people(page)
    check(sorted(p["tag"] for p in ppl) == ["circle", "circle", "rect"], f"building floor 1: {[p['tag'] for p in ppl]}")
    hollow = [p for p in ppl if p["fill"] == "none"]
    check(len(hollow) == 1 and hollow[0]["tag"] == "circle", "building floor 1: the unknown-floor person is a hollow ring")
    check(page.locator("#unsure-note").is_visible(), "building floor 1: the unsure note shows")
    check(page.locator("#plan-beacons circle").count() == 2, "building floor 1: its two beacons")
    check(page.locator("#plan-boxes circle").count() == 1, "building floor 1: only that floor's box")
    where = page.inner_text("#where")
    check("Sala B" in where and "1.º andar" in where, f"building: the player's room and floor ({where})")
    buttons.nth(0).click()
    check(buttons.nth(0).get_attribute("aria-pressed") == "true", "building: a click selects the floor")
    ppl = people(page)
    check(sorted(p["tag"] for p in ppl) == ["circle", "rect"] and sum(p["fill"] == "none" for p in ppl) == 1,
          f"building floor 0: the beacon square of floor 0 and the hollow ring, on every floor ({ppl})")
    check(page.locator("#plan-beacons circle").count() == 1, "building floor 0: its one beacon")
    check(any("level=0" in u and "v=s0" in u for u in page.requested), "building floor 0: that floor's plan is asked for")
    buttons.nth(2).click()
    ppl = people(page)
    check(sorted(p["tag"] for p in ppl) == ["circle", "circle"] and sum(p["fill"] == "none" for p in ppl) == 1,
          f"building floor 2: the GPS circle of floor 2 and the hollow ring ({ppl})")
    check(page.locator("#plan-boxes circle").count() == 0, "building floor 2: no box")
    check("level=2" in page.requested[-1], "building floor 2: that floor's plan is asked for")
    check(not page.errors, f"building: no script or console errors {page.errors}")
    page.context.close()


EXPECT = {  # per language: title, floor label, position line, the first row's label, the running state, <html lang>
    "pt": ("Vista de quem joga", "Piso", "A minha posição: Sala B, 1.º andar", "Equipa", "a decorrer", "pt"),
    "en": ("Player’s view", "Floor", "My position: Sala B, 1.º andar", "Team", "playing", "en"),
    "de": ("Sicht der Spielenden", "Etage", "Meine Position: Sala B, 1.º andar", "Team", "läuft", "de"),
    "zh-tw": ("玩家視角", "樓層", "我的位置：Sala B, 1.º andar", "隊伍", "進行中", "zh-TW"),
}


def test_languages(browser, base: str) -> None:
    page = page_for(browser, base, building(), "pt")
    keys = page.evaluate("""() => { const walk = (o) => Object.entries(o).flatMap(([k, v]) =>
        typeof v === 'object' ? walk(v).map((s) => k + '.' + s) : [k]);
        return Object.fromEntries(Object.entries(TEXTS).map(([l, t]) => [l, walk(t).sort()])); }""")
    check(set(keys) == set(EXPECT), f"languages: the text tables are {sorted(keys)}")
    check(all(keys[k] == keys["pt"] for k in keys), "languages: every text table has the same keys")
    check(page.locator("#langs button").count() == 4, "languages: four language buttons")
    for code, (title, floor, where, team, state, htmllang) in EXPECT.items():
        page.locator(f"#langs button[lang='{htmllang}']").click()
        check(page.inner_text("#title") == title and page.evaluate("document.documentElement.lang") == htmllang,
              f"languages: {code} title and lang attribute")
        check(page.get_attribute("#levels", "aria-label") == floor, f"languages: {code} floor label")
        check(page.inner_text("#where") == where, f"languages: {code} position line")
        check(page.inner_text("#me-list dt") == team and page.inner_text("#game-state") == state,
              f"languages: {code} labels and state")
        check(page.locator("#unsure-note").inner_text().strip() != "", f"languages: {code} unsure note")
        check(page.inner_text("#events li:first-child span") != "", f"languages: {code} event text")
    check(not page.errors, f"languages: no script or console errors {page.errors}")
    page.context.close()
    page = page_for(browser, base, None, "de")
    check(page.inner_text("#waiting").startswith("Warte"), "waiting: no game gives the waiting line, in the language asked")
    check(page.locator("#view").is_hidden(), "waiting: the view is hidden")
    page.context.close()


def main(argv: list[str]) -> int:
    root = Path(argv[0]).resolve()
    field = root / "server" / "preview" / "demo" / "field"
    srv = serve(field)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            test_parse(browser, root, field)
            test_open_field(browser, base)
            test_building(browser, base)
            test_languages(browser, base)
        finally:
            browser.close()
    srv.shutdown()
    print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["."]))
