# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Adopting boxes (protocol/adoption.md, decisions AD-*): the NFC field card and the USB cable.

The field card through the API (GM only, never cached, the bytes decoding to the
field join key); the USB adoption against the C host box (the firmware's own
main/adoption.c) reached through a TCP bridge as ``socket://`` (as a COM-to-TCP
bridge on the Docker host would be): the scan, the MAC the GM confirmed, an
unadopted box, a box of another field with and without its admin PIN, the modem's
port never touched, the records; a box adopted by USB joins a game of this field;
``join-key --rotate``.
"""

from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout

from fastapi.testclient import TestClient

from support import BOX_HOST, CORE, REPO, config, unittest_skip, wait_for
from atalaia_controller.adoption import PREVIOUS_SETTING, BoxLink, _same_port
from atalaia_controller.main import build, join_key_command
from atalaia_controller.store import Store
from atalaia_sim import field_card, join

GM = {"Authorization": "Bearer gm-secret"}
READ = {"Authorization": "Bearer read-secret"}
KEY = bytes(range(32))
OTHER = bytes(range(1, 33))


class BridgedBox:
    """The C host box with its console on a TCP port, as a COM-to-TCP bridge serves a box's port."""

    def __init__(self, state_dir: str, *, join_key: bytes = b"", mac: str = "02:00:00:00:00:01",
                 name: str = "box-a", admin_pin: str = "1234") -> None:
        if not BOX_HOST:
            raise unittest_skip("host box not built")
        args = [BOX_HOST, "--state-dir", state_dir, "--modes", str(REPO / "modes"), "--name", name,
                "--mac", mac, "--admin-pin", admin_pin]
        if join_key:
            args += ["--join-key", join_key.hex()]
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.lines: list[str] = []
        first = self.proc.stdout.readline().decode()
        if not first.startswith("READY "):
            raise RuntimeError(f"host box did not start: {first!r} {self.proc.stderr.read()!r}")
        self.server = socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(4)
        self.url = f"socket://127.0.0.1:{self.server.getsockname()[1]}"
        self.client: "socket.socket | None" = None
        self.conns: list[socket.socket] = []
        self._lock = threading.Lock()
        threading.Thread(target=self._accept, daemon=True).start()
        threading.Thread(target=self._stdout, daemon=True).start()

    def _accept(self) -> None:
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with self._lock:
                self.client = conn
                self.conns.append(conn)
            threading.Thread(target=self._stdin, args=(conn,), daemon=True).start()

    def _stdin(self, conn: socket.socket) -> None:
        while True:
            try:
                data = conn.recv(1024)
            except OSError:
                return
            if not data:
                return
            self.send_raw(data)

    def _stdout(self) -> None:
        for raw in self.proc.stdout:
            self.lines.append(raw.decode(errors="replace").rstrip("\n"))
            with self._lock:
                conn = self.client
            if conn is not None:
                try:
                    conn.sendall(raw)
                except OSError:
                    pass

    def send_raw(self, data: bytes) -> None:
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def logged(self, needle: str) -> bool:
        return any(needle in line for line in list(self.lines))

    def close(self) -> None:
        self.server.close()
        for conn in self.conns:
            conn.close()
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        self.proc.kill()
        self.proc.wait(timeout=5)
        self.proc.stdout.close()
        self.proc.stderr.close()


class Field:
    def __init__(self, ports: list[str], lister=lambda: [], **cfg) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        c = config(self.tmp.name, join_key=KEY.hex(), adopt_usb_ports=ports, **cfg)
        self.bundle = build(c, core=CORE, load_core_lib=False)
        self.adoption = self.bundle.controller.adoption
        self.adoption.lister = lister
        self.http = TestClient(self.bundle.app, base_url="https://testserver")  # tokens go over HTTPS (guard.py)
        self.http.__enter__()

    def close(self) -> None:
        self.http.__exit__(None, None, None)
        self.bundle.store.close()
        self.tmp.cleanup()


class FieldCardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.field = Field([])
        self.addCleanup(self.field.close)

    def test_card_is_the_join_key_for_the_gm_only(self) -> None:
        http = self.field.http
        self.assertEqual(http.post("/api/v1/adopt/card").status_code, 401)
        self.assertEqual(http.post("/api/v1/adopt/card", headers=READ).status_code, 403)
        self.assertEqual(http.get("/api/v1/adopt", headers=READ).status_code, 403)
        r = http.post("/api/v1/adopt/card", headers=GM)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.headers["cache-control"], "no-store")
        card = r.json()
        self.assertEqual(card["fingerprint"], "604A-0A95")  # protocol/vectors/field_card.json
        self.assertEqual(card["field_name"], "Atalaia")
        payload = field_card.from_ndef_tag(bytes.fromhex(card["ndef_tag_hex"]))
        decoded = field_card.decode(payload)
        self.assertEqual(decoded["join_key"], KEY)
        self.assertEqual(decoded["name"], "Atalaia")
        self.assertEqual(card["bytes"], len(payload))
        self.assertLessEqual(len(bytes.fromhex(card["ndef_tag_hex"])), 504)  # an NTAG215's user memory
        self.assertIsNone(join.from_ndef_tag(bytes.fromhex(card["ndef_tag_hex"])))
        info = http.get("/api/v1/adopt", headers=GM).json()
        self.assertEqual(info["fingerprint"], "604A-0A95")
        self.assertEqual(info["log"][0]["method"], "card")
        self.assertEqual(info["log"][0]["result"], "card_made")
        self.assertNotIn(KEY.hex(), json.dumps(info))

    def test_the_branding_name_goes_on_the_card(self) -> None:
        http = self.field.http
        self.assertEqual(http.put("/api/v1/field/branding", headers=GM,
                                  json={"field_name": 'Clube "Ão" de Évora'}).status_code, 200)
        card = http.post("/api/v1/adopt/card", headers=GM).json()
        self.assertEqual(card["field_name"], "Clube Ão de Évora")  # '"' cannot go on a card

    def test_usb_off(self) -> None:
        field = Field([], adopt_usb=False)
        self.addCleanup(field.close)
        self.assertEqual(field.http.post("/api/v1/adopt/usb/scan", headers=GM).status_code, 503)


class BoxLinkTests(unittest.TestCase):
    def test_reply_lines_among_log_lines(self) -> None:
        class Port:
            def __init__(self, data: bytes) -> None:
                self.data = io.BytesIO(data)
                self.written = b""

            def read(self, n: int) -> bytes:
                return self.data.read(n)

            def write(self, b: bytes) -> None:
                self.written += b

            def flush(self) -> None:
                pass

        info = '{"v":1,"kind":"info","name":"b","mac":"AA:BB:CC:DD:EE:FF","state":"unadopted"}'
        port = Port(("\x1b[0;32mI (812) atalaia: field: hello\x1b[0m\r\n"
                     "ATALAIA-ADOPT {not json}\r\n"
                     'ATALAIA-ADOPT {"v":2,"kind":"info"}\r\n'
                     f"noise ATALAIA-ADOPT {info}\r\n").encode())
        link = BoxLink(port)
        link.send("adopt-info")
        self.assertEqual(port.written, b"\n@adopt-info\n")
        msg = link.reply("info", 0.5)
        self.assertEqual(msg["mac"], "AA:BB:CC:DD:EE:FF")
        self.assertIsNone(link.reply("result", 0.05))

    def test_same_port(self) -> None:
        self.assertTrue(_same_port("/dev/ttyACM0", "/dev/ttyACM0"))
        self.assertFalse(_same_port("/dev/ttyACM0", ""))
        self.assertFalse(_same_port("socket://a:1", "socket://a:2"))


class UsbAdoptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def box(self, sub: str, **kw) -> BridgedBox:
        os.makedirs(os.path.join(self.tmp.name, sub))
        b = BridgedBox(os.path.join(self.tmp.name, sub), **kw)
        self.addCleanup(b.close)
        return b

    def test_an_unadopted_box_then_a_box_of_another_field(self) -> None:
        new = self.box("new", mac="02:00:00:00:00:0A", name="porta-norte")
        stranger = self.box("stranger", join_key=OTHER, mac="02:00:00:00:00:0B", name="vizinho")
        field = Field([new.url, stranger.url])
        self.addCleanup(field.close)
        http = field.http
        self.assertEqual(http.post("/api/v1/adopt/usb/scan", headers=READ).status_code, 403)
        scan = http.post("/api/v1/adopt/usb/scan", headers=GM).json()
        self.assertEqual(scan["silent"], [])
        boxes = {b["mac"]: b for b in scan["boxes"]}
        self.assertEqual(boxes["02:00:00:00:00:0A"]["state"], "unadopted")
        self.assertEqual(boxes["02:00:00:00:00:0A"]["name"], "porta-norte")
        self.assertEqual(boxes["02:00:00:00:00:0A"]["relation"], "none")
        self.assertEqual(boxes["02:00:00:00:00:0B"]["relation"], "other_field")
        self.assertEqual(boxes["02:00:00:00:00:0B"]["field"], field_card.fingerprint(OTHER))

        # The GM confirmed another box than the one on that port: nothing is written.
        r = http.post("/api/v1/adopt/usb", headers=GM, json={"port": new.url, "mac": "02:00:00:00:00:0B"})
        self.assertEqual(r.status_code, 409, r.text)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "new", "join_key")))
        r = http.post("/api/v1/adopt/usb", headers=GM, json={"port": "socket://127.0.0.1:1", "mac": "02:00:00:00:00:0A"})
        self.assertEqual(r.status_code, 404)
        r = http.post("/api/v1/adopt/usb", headers=GM, json={"port": new.url, "mac": "02:00:00:00:00:0A",
                                                             "pin": "12ab"})
        self.assertEqual(r.status_code, 400)

        r = http.post("/api/v1/adopt/usb", headers=GM, json={"port": new.url, "mac": "02:00:00:00:00:0a"})
        self.assertEqual(r.status_code, 200, r.text)
        out = r.json()
        self.assertEqual(out["result"], "adopted")
        self.assertTrue(out["ok"])
        self.assertEqual(out["box"]["relation"], "this_field")
        self.assertEqual(out["box"]["field_name"], "Atalaia")
        with open(os.path.join(self.tmp.name, "new", "join_key"), "rb") as f:
            self.assertEqual(f.read(), KEY)
        self.assertTrue(new.logged("adoption (usb): adopted, field 604A-0A95"))
        # Again: the same field, nothing changes.
        r = http.post("/api/v1/adopt/usb", headers=GM, json={"port": new.url, "mac": "02:00:00:00:00:0A"})
        self.assertEqual(r.json()["result"], "same")

        # Another field's box: only with its admin PIN.
        r = http.post("/api/v1/adopt/usb", headers=GM, json={"port": stranger.url, "mac": "02:00:00:00:00:0B"})
        self.assertEqual(r.json()["result"], "need_pin")
        self.assertFalse(r.json()["ok"])
        r = http.post("/api/v1/adopt/usb", headers=GM, json={"port": stranger.url, "mac": "02:00:00:00:00:0B",
                                                             "pin": "9999"})
        self.assertEqual(r.json()["result"], "bad_pin")
        with open(os.path.join(self.tmp.name, "stranger", "join_key"), "rb") as f:
            self.assertEqual(f.read(), OTHER)
        r = http.post("/api/v1/adopt/usb", headers=GM, json={"port": stranger.url, "mac": "02:00:00:00:00:0B",
                                                             "pin": "1234"})
        self.assertEqual(r.json()["result"], "readopted")
        with open(os.path.join(self.tmp.name, "stranger", "join_key"), "rb") as f:
            self.assertEqual(f.read(), KEY)

        records = http.get("/api/v1/adopt", headers=GM).json()["log"]
        self.assertEqual([x["result"] for x in records[:4]], ["readopted", "bad_pin", "need_pin", "same"])
        self.assertEqual(records[0]["mac"], "02:00:00:00:00:0B")
        self.assertTrue(records[0]["pin_given"])
        text = json.dumps(records)
        self.assertNotIn(KEY.hex(), text)
        self.assertNotIn("1234", text)

    def test_the_adopted_box_joins_this_fields_game(self) -> None:
        new = self.box("new", mac="02:00:00:00:00:0C")
        field = Field([new.url])
        self.addCleanup(field.close)
        http = field.http
        r = http.post("/api/v1/adopt/usb", headers=GM, json={"port": new.url, "mac": "02:00:00:00:00:0C"})
        self.assertEqual(r.json()["result"], "adopted", r.text)
        game = http.post("/api/v1/games", headers=GM, json={"name": "g", "mode_id": "org.atalaia.domination",
                                                            "teams": ["red", "blue"]})
        self.assertEqual(game.status_code, 201, game.text)
        text = http.post("/api/v1/join", headers=GM, json={"kind": "node", "role": "zone"}).json()["text"]
        new.send_raw(f"@join {text}\n".encode())
        self.assertTrue(wait_for(lambda: new.logged("join: joined"), 5), new.lines[-5:])
        # With the game joined the box refuses to be adopted (it says it is busy).
        scan = http.post("/api/v1/adopt/usb/scan", headers=GM).json()
        self.assertTrue(scan["boxes"][0]["busy"])

    def test_the_modem_port_is_never_touched(self) -> None:
        opened: list[str] = []

        def opener(url: str):
            opened.append(url)
            raise OSError("no such port")

        field = Field([], lister=lambda: [{"port": "/dev/ttyACM0", "serial": "AA"},
                                          {"port": "/dev/ttyACM1", "serial": "BB"}],
                      port="", adopt_usb=True)
        self.addCleanup(field.close)
        field.adoption.cfg.port = "/dev/ttyACM0"  # the modem's port (no modem started in this test)
        field.adoption.opener = opener
        scan = field.http.post("/api/v1/adopt/usb/scan", headers=GM).json()
        self.assertEqual(opened, ["/dev/ttyACM1"])
        self.assertEqual(scan["boxes"], [])
        self.assertEqual(scan["silent"], [{"port": "/dev/ttyACM1", "error": "no such port"}])
        r = field.http.post("/api/v1/adopt/usb", headers=GM, json={"port": "/dev/ttyACM0", "mac": "02:00:00:00:00:01"})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(opened, ["/dev/ttyACM1"])

    def test_a_port_that_does_not_answer(self) -> None:
        silent = socket.socket()
        silent.bind(("127.0.0.1", 0))
        silent.listen(1)
        self.addCleanup(silent.close)
        field = Field([f"socket://127.0.0.1:{silent.getsockname()[1]}"])
        self.addCleanup(field.close)
        field.adoption.probe_timeout_s = 0.3
        scan = field.http.post("/api/v1/adopt/usb/scan", headers=GM).json()
        self.assertEqual(scan["boxes"], [])
        self.assertIn("no answer", scan["silent"][0]["error"])


class RotationTests(unittest.TestCase):
    def test_rotate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config(tmp)
            store = Store(cfg.db_path)
            try:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    self.assertEqual(join_key_command(cfg, store, "show"), 0)
                old = bytes.fromhex(buf.getvalue().strip())
                buf = io.StringIO()
                with redirect_stdout(buf):
                    self.assertEqual(join_key_command(cfg, store, "rotate"), 0)
                new = bytes.fromhex(store.get_setting("join_key"))
                self.assertNotEqual(new, old)
                self.assertEqual(store.get_setting(PREVIOUS_SETTING), field_card.fingerprint(old))
                self.assertIn(field_card.fingerprint(new), buf.getvalue())
                self.assertNotIn(new.hex(), buf.getvalue())
                buf = io.StringIO()
                with redirect_stdout(buf):
                    join_key_command(cfg, store, "fingerprint")
                self.assertEqual(buf.getvalue().strip(), field_card.fingerprint(new))
            finally:
                store.close()
            # A key set in the settings is not rotated here.
            cfg2 = config(tmp, join_key=KEY.hex())
            store = Store(cfg2.db_path)
            try:
                with redirect_stderr(io.StringIO()):
                    self.assertEqual(join_key_command(cfg2, store, "rotate"), 2)
            finally:
                store.close()

    def test_previous_key_boxes(self) -> None:
        """A box still on the field's previous key (after a rotation) is told apart from a stranger's."""
        field = Field([])
        self.addCleanup(field.close)
        field.bundle.store.set_setting(PREVIOUS_SETTING, field_card.fingerprint(OTHER))
        box = field.adoption._box("p", {"state": "adopted", "field": field_card.fingerprint(OTHER)})
        self.assertEqual(box["relation"], "previous_key")
        self.assertEqual(field.http.get("/api/v1/adopt", headers=GM).json()["previous_fingerprint"],
                         field_card.fingerprint(OTHER))


if __name__ == "__main__":
    unittest.main()
