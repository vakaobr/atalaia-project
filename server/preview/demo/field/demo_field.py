# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The preview's live demo field (decisions DEMO-*; docs/runbooks/preview-server.md, "The live demo").

One container, one supervisor: this process starts a simulated radio (a UDP "air", the Field Box firmware's own game
and radio code built for Linux as "host modem" and "host boxes"), a field controller that talks to it through the
host modem, a read-only proxy in front of the controller, and the director that plays a game after another through
the controller's API. If any of them stops, everything is stopped and the container exits, so the restart policy
brings the whole field back clean; a game that was running is ended when it does.

    DEMO_DATA          the data folder (default /data): the controller's database, the join key, the box state
    DEMO_READ_TOKEN    the public read token of the demo (default "atalaia-demo")
    DEMO_SYNC_KEY_FILE a field API key of the site server's live demo field (default /secrets/sync-key);
                       with it the controller syncs its games to the site server, which shows them on its public
                       pages; without it (after DEMO_SYNC_WAIT_S seconds) the demo runs on its own
    DEMO_SYNC_TARGET   the site server as this container reaches it (default server:8000)
    DEMO_LOBBY_S, DEMO_GAME_S, DEMO_PAUSE_S   the game's pace in seconds (25, 240, 60)

The only way in is the proxy's port (8001). The controller's own port is on 127.0.0.1 inside the container, its GM
token is made here for this run and never leaves the process and its environment.
"""

from __future__ import annotations

import logging
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from air import AirHub, HostBox, HostModem
from director import BOX_NAMES, Api, Director, Restart

log = logging.getLogger("demo")

DATA = Path(os.environ.get("DEMO_DATA", "/data"))
READ_TOKEN = os.environ.get("DEMO_READ_TOKEN", "atalaia-demo")
KEY_FILE = Path(os.environ.get("DEMO_SYNC_KEY_FILE", "/secrets/sync-key"))
SYNC_TARGET = os.environ.get("DEMO_SYNC_TARGET", "server:8000")
SYNC_WAIT_S = float(os.environ.get("DEMO_SYNC_WAIT_S", "180"))
CONTROLLER_PORT = 8080
PROXY_PORT = int(os.environ.get("DEMO_PROXY_PORT", "8001"))
FORWARD_PORT = 18000
MODES = os.environ.get("DEMO_MODES", "/app/modes")


def forwarder(listen_port: int, target: str) -> None:
    """127.0.0.1:listen_port -> target. The controller sends its sync over plain http only to the loopback; the site
    server is another container, so this carries the bytes across (nothing is read or changed)."""
    host, _, port = target.rpartition(":")
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", listen_port))
    srv.listen(16)

    def pipe(a: socket.socket, b: socket.socket) -> None:
        try:
            while data := a.recv(65536):
                b.sendall(data)
        except OSError:
            pass
        finally:
            for s in (a, b):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def serve() -> None:
        while True:
            client, _ = srv.accept()
            try:
                upstream = socket.create_connection((host, int(port)), timeout=10)
            except OSError:
                client.close()
                continue
            threading.Thread(target=pipe, args=(client, upstream), daemon=True).start()
            threading.Thread(target=pipe, args=(upstream, client), daemon=True).start()

    threading.Thread(target=serve, daemon=True, name="sync-forward").start()


def wait_port(port: int, timeout: float) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return True
        except OSError:
            time.sleep(0.3)
    return False


def sync_key() -> str:
    """The site server's API key for the live demo field, once its demo-refresh service has made it."""
    end = time.monotonic() + SYNC_WAIT_S
    while time.monotonic() < end:
        try:
            key = KEY_FILE.read_text().strip()
            if key:
                return key
        except OSError:
            pass
        time.sleep(2)
    return ""


def write_config(path: Path, modem_url: str, syncing: bool) -> None:
    path.write_text(f"""\
# Made by demo_field.py at every start; nothing secret in it (the tokens and the sync key come by environment).
[controller]
node_id = 0
db_path = "{DATA}/controller.db"
persist_game_key = false

[modem]
port = "{modem_url}"
ping_interval_s = 2.0

[api]
host = "127.0.0.1"
port = {CONTROLLER_PORT}
tls_port = 0

[mqtt]
enabled = false

[adopt]
usb = false

[checkin]
field_id = "demo-ao-vivo"
field_name = "Campo Demo ao Vivo"
operator = "Demonstração do Atalaia (dados inventados)"
confirm = "auto"
country = "PT"
rate_per_minute = 600
max_players = 40
retention_days = 1
limit_template = "portugal"

[sync]
enabled = {"true" if syncing else "false"}
url = "http://127.0.0.1:{FORWARD_PORT}"
interval_game_s = 10.0
interval_idle_s = 20.0
library = false
remote_gm = false

[atak]
enabled = false
""")


class Supervisor:
    def __init__(self) -> None:
        self.procs: list[tuple[str, subprocess.Popen]] = []
        self.stopping = threading.Event()

    def spawn(self, name: str, argv: list[str], env: dict[str, str] | None = None) -> subprocess.Popen:
        proc = subprocess.Popen(argv, env={**os.environ, **(env or {})})
        self.procs.append((name, proc))
        log.info("started %s (pid %d)", name, proc.pid)
        return proc

    def watch(self, boxes: list[HostBox], modem: HostModem) -> str:
        """Blocks until something stops; returns its name."""
        while not self.stopping.is_set():
            for name, proc in self.procs:
                if proc.poll() is not None:
                    return f"{name} (exit {proc.returncode})"
            if modem.proc.poll() is not None:
                return "the host modem"
            for box in boxes:
                if not box.alive():
                    return f"the simulated box {box.name}"
            time.sleep(1.0)
        return "a stop request"

    def stop_all(self) -> None:
        for _, proc in self.procs:
            if proc.poll() is None:
                proc.terminate()
        end = time.monotonic() + 8
        for _, proc in self.procs:
            try:
                proc.wait(timeout=max(0.1, end - time.monotonic()))
            except subprocess.TimeoutExpired:
                proc.kill()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    DATA.mkdir(parents=True, exist_ok=True)
    # A clean start: the boxes forget what they were playing and the controller starts a new database (a restart is
    # how the demo forgets its old games: the console lists every game a controller has). The join key and the
    # marshal's identity are kept.
    for leftover in DATA.glob("controller.db*"):
        leftover.unlink()
    boxes_dir = DATA / "boxes"
    shutil.rmtree(boxes_dir, ignore_errors=True)
    boxes_dir.mkdir(mode=0o700)
    join_key = DATA / "join.key"
    if not join_key.exists():
        join_key.write_text(secrets.token_hex(32))
        join_key.chmod(0o600)
    gm_token = secrets.token_urlsafe(24)

    key = sync_key()
    if key:
        forwarder(FORWARD_PORT, SYNC_TARGET)
    else:
        log.warning("no sync key at %s: the demo runs without the site server's pages", KEY_FILE)

    sup = Supervisor()
    hub = AirHub()
    modem = HostModem(os.environ.get("ATALAIA_MODEM_HOST", "/opt/atalaia/modem_host"), hub)
    boxes = [HostBox(os.environ.get("ATALAIA_BOX_HOST", "/opt/atalaia/box_host"), hub,
                     str(boxes_dir / name), MODES, join_key.read_text().strip(), name) for name in BOX_NAMES]
    config = DATA / "controller.toml"
    write_config(config, modem.url, bool(key))
    env = {"ATALAIA_API_GM_TOKEN": gm_token, "ATALAIA_API_READ_TOKEN": READ_TOKEN,
           "ATALAIA_JOIN_KEY": join_key.read_text().strip()}
    if key:
        env["ATALAIA_SYNC_API_KEY"] = key
    sup.spawn("controller", [sys.executable, "-m", "atalaia_controller", "run", "--config", str(config)], env)
    if not wait_port(CONTROLLER_PORT, 60):
        log.error("the controller did not come up")
        sup.stop_all()
        return 1
    sup.spawn("proxy", [sys.executable, "-m", "uvicorn", "proxy:app", "--host", "0.0.0.0", "--port", str(PROXY_PORT),
                        "--no-server-header", "--log-level", "warning", "--app-dir", str(Path(__file__).parent)],
              {"DEMO_READ_TOKEN": READ_TOKEN, "DEMO_CONTROLLER": f"http://127.0.0.1:{CONTROLLER_PORT}",
               "DEMO_DATA": str(DATA)})

    signal.signal(signal.SIGTERM, lambda *_: sup.stopping.set())
    signal.signal(signal.SIGINT, lambda *_: sup.stopping.set())
    director = Director(Api(f"http://127.0.0.1:{CONTROLLER_PORT}", gm_token), boxes, DATA)
    crashed = threading.Event()

    def run_director() -> None:
        try:
            director.run_forever()
        except Restart as why:
            log.info("starting over: %s", why)
            sup.stopping.set()
        except Exception:  # noqa: BLE001
            log.exception("the director stopped")
            crashed.set()
            sup.stopping.set()

    threading.Thread(target=run_director, daemon=True, name="director").start()
    why = sup.watch(boxes, modem)
    log.warning("stopping: %s", why)
    for box in boxes:
        if box.alive():
            box.proc.terminate()
    if modem.proc.poll() is None:
        modem.proc.terminate()
    sup.stop_all()
    hub.close()
    return 0 if why == "a stop request" and not crashed.is_set() else 1


if __name__ == "__main__":
    sys.exit(main())
