#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Makes the project page's animated game-mode pictures from the firmware's own screen code.

    python3 tools/gen_mode_gifs.py                 write site/img/modes/*.gif (needs Docker)
    python3 tools/gen_mode_gifs.py --check         fail if a file differs from what the code draws
    python3 tools/gen_mode_gifs.py --only domination --lang de      some pictures only
    python3 tools/gen_mode_gifs.py --frames-exe PATH    use the built host program (CI) instead of Docker
    python3 tools/gen_mode_gifs.py --list          the pictures and their sizes, no drawing

tools/mode_gifs.yaml scripts each picture: the screens a Field Box shows as a game of a mode goes
on (the data each mode's script sends). The host program firmware/esp32/test/mode_gif_frames.c
draws them, on the TFT (320x240) and the OLED (128x64), with the LVGL build, the screen renderer
and the screen templates of modes/ that the device runs; this script frames them in the Field Box's
body (plain drawing, no photograph) and writes each picture as a GIF with a palette of at most 64
colours, each frame holding only what changed. A picture is made for each language the page has
(the box draws the game's language), and a still picture of one frame (<id>-<lang>-still.gif)
that the page shows to someone who asked for less motion (decisions GIF-1 to GIF-12).

The GIF writer is plain Python (the standard library only), so that the same frames always give
the same bytes: --check compares them, byte for byte, with the files in the repository, and CI
runs it in the firmware-test job. Without --frames-exe the frames are drawn in Docker, in
the atalaia-dev image like `tools/docker_fw.py test` (ATALAIA_VOLUME_SUFFIX keeps the build
cache of two checkouts apart). Needs PyYAML.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "tools" / "mode_gifs.yaml"
OUT = REPO / "site" / "img" / "modes"
LANGUAGES = ("pt", "en", "de", "zh-tw")

# The picture: the Field Box's body with its TFT above and its OLED (shown twice as large)
# below, 360 x 444 pixels.
TFT_W, TFT_H = 320, 240
OLED_W, OLED_H = 128, 64
OLED_SCALE = 2
WIDTH = 360
TFT_X, TFT_Y = 20, 20
OLED_X = (WIDTH - OLED_W * OLED_SCALE) // 2
OLED_Y = TFT_Y + TFT_H + 28
HEIGHT = OLED_Y + OLED_H * OLED_SCALE + 28
MAX_COLOURS = 63  # and one transparent entry: 64 in the table, 6-bit codes

BODY = (0x23, 0x2A, 0x31)
BODY_EDGE = (0x3C, 0x46, 0x50)
BEZEL = (0x07, 0x09, 0x0B)
SCREW = (0x4A, 0x55, 0x60)
OLED_LIT = (0xEE, 0xF6, 0xFF)  # the panel's white, as the page's other screens
OLED_DARK = (0x00, 0x00, 0x00)
KEY = (255, 0, 255)  # outside the body: transparent


def fail(message: str) -> int:
    print(f"gen_mode_gifs: {message}", file=sys.stderr)
    return 1


# ---- the scripts -> a list of frames -----------------------------------------------------


def localise(value: Any, lang: str) -> Any:
    """A text the mode's script writes in the game's language is {pt:, en:, de:, zh-tw:}."""
    if isinstance(value, dict):
        if "en" in value and set(value) <= set(LANGUAGES):
            return value[lang]
        return {k: localise(v, lang) for k, v in value.items()}
    if isinstance(value, list):
        return [localise(v, lang) for v in value]
    return value


def lerp(a: float, b: float, i: int, n: int) -> float | int:
    t = i / (n - 1) if n > 1 else 1.0
    v = a + (b - a) * t
    return int(round(v)) if isinstance(a, int) and isinstance(b, int) else round(v, 3)


def expand(name: str, entry: dict, lang: str, default_frame_s: float) -> tuple[list[dict], int]:
    """The frames of a picture in a language, and the frame its still picture shows."""
    frames: list[dict] = []
    poster = -1
    game_s = 0
    for index, step in enumerate(entry["steps"]):
        data = localise(step.get("data", {}), lang)
        oled = step.get("oled")
        game_s = step.get("game_s", game_s)
        tween = step.get("tween")
        count = tween["n"] if tween else 1
        for i in range(count):
            d = dict(data)
            clock = game_s
            hold = step.get("hold")
            seconds = step.get("s", 2.0)
            if tween:
                for key, (a, b) in tween.get("set", {}).items():
                    d[key] = lerp(a, b, i, count)
                if "game_s" in tween:
                    clock = lerp(tween["game_s"][0], tween["game_s"][1], i, count)
                if "hold_ms" in tween:
                    hold = {"team": tween["hold_team"], "ms": lerp(*tween["hold_ms"], i, count)}
                seconds = seconds if i == count - 1 else tween.get("frame_s", default_frame_s)
            frames.append({
                "screen": step["screen"],
                "data": d,
                "oled": (oled["screen"], localise(oled.get("data", d), lang)) if oled else None,
                "game_ms": int(clock * 1000),
                "hold": hold,
                "cs": max(2, int(round(seconds * 100))),
            })
        if index == entry.get("poster", len(entry["steps"]) - 1):
            poster = len(frames) - 1
    return frames, poster


def script_text(name: str, entry: dict, lang: str, frames: list[dict]) -> str:
    """The lines mode_gif_frames reads (its header comment)."""
    import json

    params = dict(entry.get("params", {}))
    if entry.get("lang_param"):
        params["lang"] = lang
    mode = f"{entry['mode']} {json.dumps(params, separators=(',', ':'), ensure_ascii=False)}"
    lines = ["RESET"]
    for f in frames:
        o_screen, o_data = f["oled"] or (f["screen"], f["data"])
        hold = f["hold"]
        lines.append("\t".join([
            lang, mode, f["screen"], json.dumps(f["data"], separators=(",", ":"), ensure_ascii=False),
            o_screen, json.dumps(o_data, separators=(",", ":"), ensure_ascii=False),
            str(f["game_ms"]), hold["team"] if hold else "-", str(hold["ms"]) if hold else "0",
        ]))
    return "\n".join(lines) + "\n"


def pictures(config: dict, only: set[str] | None, langs: set[str] | None):
    """(id, language, frame list, poster index, script lines) for every file to make."""
    out = []
    for name, entry in config["scripts"].items():
        if only and name not in only:
            continue
        languages = LANGUAGES if entry.get("languages", "all") == "all" else tuple(entry["languages"])
        for lang in languages:
            if langs and lang not in langs:
                continue
            frames, poster = expand(name, entry, lang, config.get("frame_s", 0.15))
            out.append((name, lang, frames, poster, script_text(name, entry, lang, frames)))
    return out


# ---- drawing the frames: the host program ---------------------------------------------------


def run_frames(text: str, frames_exe: str | None) -> bytes:
    """The raw frames of a script: TFT RGB (230400 bytes) and OLED bytes (8192) for each line."""
    with tempfile.TemporaryDirectory() as tmp:
        script, frames = Path(tmp) / "script.txt", Path(tmp) / "frames.bin"
        script.write_text(text, encoding="utf-8")
        if frames_exe:
            done = subprocess.run([frames_exe, str(script), str(frames)], capture_output=True, text=True)
            if done.returncode != 0:
                raise RuntimeError(f"mode_gif_frames failed: {done.stderr or done.stdout}")
        else:
            raise RuntimeError("no frames program")
        return frames.read_bytes()


def run_in_docker(texts: dict[str, str]) -> dict[str, bytes]:
    """Builds the host program in the dev image, as docker_fw.py test does, and draws every script."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import docker_fw

    if not docker_fw.ensure_dev_image():
        raise RuntimeError("building the image failed")
    work = REPO / "firmware" / "esp32" / "build-test" / "gifs"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    for key, text in texts.items():
        (work / f"{key}.txt").write_text(text, encoding="utf-8")
    keys = " ".join(texts)
    uid, gid = os.getuid(), os.getgid()
    script = (
        "cmake -S firmware/esp32/test -B /build/fw-test -DCMAKE_BUILD_TYPE=Debug >/dev/null && "
        "cmake --build /build/fw-test --target mode_gif_frames >/dev/null && "
        f"cd firmware/esp32/build-test/gifs && for k in {keys}; do "
        '/build/fw-test/mode_gif_frames "$k.txt" "$k.bin" >/dev/null || exit 1; done; '
        f"code=$?; chown -R {uid}:{gid} /src/firmware/esp32/build-test; exit $code"
    )
    code = docker_fw.docker("run", "--rm", "-v", f"{REPO}:/src", "-v", f"{docker_fw.TEST_VOLUME}:/build",
                            docker_fw.DEV_IMAGE, "sh", "-c", script)
    if code != 0:
        raise RuntimeError("drawing the frames in Docker failed")
    frames = {key: (work / f"{key}.bin").read_bytes() for key in texts}
    shutil.rmtree(work)
    return frames


# ---- framing: the Field Box's body ------------------------------------------------------


def rounded(x: int, y: int, x0: int, y0: int, x1: int, y1: int, r: int) -> bool:
    """Is (x, y) inside the rectangle [x0, x1) x [y0, y1) with corners of radius r?"""
    if not (x0 <= x < x1 and y0 <= y < y1):
        return False
    cx = x0 + r if x < x0 + r else x1 - 1 - r if x >= x1 - r else x
    cy = y0 + r if y < y0 + r else y1 - 1 - r if y >= y1 - r else y
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r + r


def body_rows() -> list[bytearray]:
    """The Field Box's body as RGB rows: rounded, a bezel round each screen, four screws."""
    rows = []
    screws = [(11, 11), (WIDTH - 12, 11), (11, HEIGHT - 12), (WIDTH - 12, HEIGHT - 12)]
    for y in range(HEIGHT):
        row = bytearray()
        for x in range(WIDTH):
            if not rounded(x, y, 0, 0, WIDTH, HEIGHT, 22):
                c = KEY
            elif not rounded(x, y, 1, 1, WIDTH - 1, HEIGHT - 1, 21):
                c = BODY_EDGE
            elif any((x - sx) ** 2 + (y - sy) ** 2 <= 9 for sx, sy in screws):
                c = SCREW
            elif rounded(x, y, TFT_X - 7, TFT_Y - 7, TFT_X + TFT_W + 7, TFT_Y + TFT_H + 7, 8):
                c = BEZEL
            elif rounded(x, y, OLED_X - 7, OLED_Y - 7, OLED_X + OLED_W * OLED_SCALE + 7,
                         OLED_Y + OLED_H * OLED_SCALE + 7, 6):
                c = BEZEL
            else:
                c = BODY
            row += bytes(c)
        rows.append(row)
    return rows


def compose(base: list[bytearray], tft: bytes, oled: bytes) -> list[bytes]:
    """One frame: the body with the TFT's pixels and the OLED's (twice as large) in it."""
    rows = [bytes(r) for r in base]
    for y in range(TFT_H):
        r = bytearray(rows[TFT_Y + y])
        r[TFT_X * 3:(TFT_X + TFT_W) * 3] = tft[y * TFT_W * 3:(y + 1) * TFT_W * 3]
        rows[TFT_Y + y] = bytes(r)
    lit, dark = bytes(OLED_LIT), bytes(OLED_DARK)
    for y in range(OLED_H):
        line = oled[y * OLED_W:(y + 1) * OLED_W]
        px = b"".join((lit if v else dark) * OLED_SCALE for v in line)
        for k in range(OLED_SCALE):
            r = bytearray(rows[OLED_Y + y * OLED_SCALE + k])
            r[OLED_X * 3:(OLED_X + OLED_W * OLED_SCALE) * 3] = px
            rows[OLED_Y + y * OLED_SCALE + k] = bytes(r)
    return rows


# ---- the GIF writer (plain Python, deterministic) -----------------------------------------


def quantise(histogram: Counter, limit: int) -> list[tuple[int, int, int]]:
    """A palette of at most limit colours: median cut, weighted by how many pixels have each."""
    boxes = [list(histogram.items())]
    while len(boxes) < limit:
        best, best_score = None, 0
        for i, box in enumerate(boxes):
            if len(box) < 2:
                continue
            span = max(max(c[ch] for c, _ in box) - min(c[ch] for c, _ in box) for ch in range(3))
            score = span * sum(n for _, n in box) ** 0.5
            if score > best_score:
                best, best_score = i, score
        if best is None:
            break
        box = boxes.pop(best)
        ch = max(range(3), key=lambda k: (max(c[k] for c, _ in box) - min(c[k] for c, _ in box), -k))
        box.sort(key=lambda item: (item[0][ch], item[0]))
        half, acc = sum(n for _, n in box) / 2, 0
        cut = 1
        for j, (_, n) in enumerate(box):
            acc += n
            if acc >= half:
                cut = min(max(j + 1, 1), len(box) - 1)
                break
        boxes.append(box[:cut])
        boxes.append(box[cut:])
    palette = []
    for box in boxes:
        total = sum(n for _, n in box)
        palette.append(tuple(int(round(sum(c[k] * n for c, n in box) / total)) for k in range(3)))
    return sorted(set(palette))


def lzw(data: bytes, min_size: int) -> bytes:
    clear, end = 1 << min_size, (1 << min_size) + 1
    out = bytearray()
    acc = bits = 0
    size = min_size + 1
    nxt = end + 1
    table: dict[int, int] = {}

    def emit(code: int, width: int) -> None:
        nonlocal acc, bits
        acc |= code << bits
        bits += width
        while bits >= 8:
            out.append(acc & 255)
            acc >>= 8
            bits -= 8

    emit(clear, size)
    prefix = data[0]
    get = table.get
    for byte in data[1:]:
        key = (prefix << 8) | byte
        code = get(key)
        if code is not None:
            prefix = code
            continue
        emit(prefix, size)
        table[key] = nxt
        nxt += 1
        if nxt - 1 == (1 << size):
            size += 1
        if nxt > 4095:
            emit(clear, size)
            table.clear()
            nxt = end + 1
            size = min_size + 1
        prefix = byte
    emit(prefix, size)
    emit(end, size)
    if bits:
        out.append(acc & 255)
    return bytes(out)


def sub_blocks(data: bytes) -> bytes:
    out = bytearray()
    for i in range(0, len(data), 255):
        chunk = data[i:i + 255]
        out.append(len(chunk))
        out += chunk
    out.append(0)
    return bytes(out)


def encode_gif(frames: list[list[bytes]], durations: list[int], loop: bool) -> bytes:
    """frames: each frame's RGB rows (WIDTH x HEIGHT); durations in hundredths of a second.
    A frame after the first holds, in the box round what changed, the pixels that did; the others
    are transparent. The palette is shared; its last entry is the transparent one."""
    histogram: Counter = Counter()
    seen: set[bytes] = set()
    for rows in frames:
        for row in rows:
            if row in seen:
                continue
            seen.add(row)
            histogram.update(zip(row[0::3], row[1::3], row[2::3]))
    histogram.pop(KEY, None)
    palette = quantise(histogram, MAX_COLOURS)
    transparent = len(palette)
    bits = max(2, (transparent).bit_length())  # entries 0..transparent
    table = palette + [KEY] + [(0, 0, 0)] * ((1 << bits) - transparent - 1)

    lut: dict[tuple[int, int, int], int] = {KEY: transparent}

    def index_of(colour: tuple[int, int, int]) -> int:
        if colour not in lut:
            lut[colour] = min(range(len(palette)), key=lambda i: (
                (palette[i][0] - colour[0]) ** 2 + (palette[i][1] - colour[1]) ** 2 +
                (palette[i][2] - colour[2]) ** 2, i))
        return lut[colour]

    cache: dict[bytes, bytes] = {}

    def indices(row: bytes) -> bytes:
        got = cache.get(row)
        if got is None:
            got = bytes(index_of(c) for c in zip(row[0::3], row[1::3], row[2::3]))
            cache[row] = got
        return got

    out = bytearray(b"GIF89a")
    out += WIDTH.to_bytes(2, "little") + HEIGHT.to_bytes(2, "little")
    out += bytes([0x80 | 0x70 | (bits - 1), transparent, 0])
    for c in table:
        out += bytes(c)
    if loop:
        out += b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"
    previous: list[bytes] | None = None
    for rows, cs in zip(frames, durations):
        if previous is None:
            top, left, right, bottom = 0, 0, WIDTH - 1, HEIGHT - 1
            pixels = [indices(r) for r in rows]
        else:
            changed = [y for y in range(HEIGHT) if rows[y] != previous[y]]
            idx = {y: (indices(rows[y]), indices(previous[y])) for y in changed}
            cols = [x for y in changed for x in range(WIDTH) if idx[y][0][x] != idx[y][1][x]]
            if not cols:  # the same after the palette: the frame still takes its time
                top = bottom = left = right = 0
                pixels = [bytes([transparent])]
            else:
                top, bottom = changed[0], changed[-1]
                left, right = min(cols), max(cols)
                pixels = []
                for y in range(top, bottom + 1):
                    if y in idx:
                        now, before = idx[y]
                        pixels.append(bytes(transparent if now[x] == before[x] else now[x]
                                            for x in range(left, right + 1)))
                    else:
                        pixels.append(bytes([transparent]) * (right - left + 1))
        w, h = right - left + 1, bottom - top + 1
        flat = b"".join(pixels)
        out += b"\x21\xf9\x04" + bytes([0x04 | 0x01, cs & 255, cs >> 8, transparent, 0])
        out += b"\x2c" + left.to_bytes(2, "little") + top.to_bytes(2, "little")
        out += w.to_bytes(2, "little") + h.to_bytes(2, "little") + b"\x00"
        out += bytes([bits]) + sub_blocks(lzw(flat, bits))
        previous = rows
    out += b"\x3b"
    return bytes(out)


# ---- one picture --------------------------------------------------------------------------


def make_files(job: tuple[str, str, list[dict], int, bytes]) -> dict[str, bytes]:
    name, lang, frames, poster, raw = job
    per = TFT_W * TFT_H * 3 + OLED_W * OLED_H
    if len(raw) != per * len(frames):
        raise RuntimeError(f"{name}-{lang}: {len(raw) // per} frames drawn, {len(frames)} scripted")
    base = body_rows()
    composed: list[list[bytes]] = []
    durations: list[int] = []
    poster_at = -1
    last = None
    for i, f in enumerate(frames):
        chunk = raw[i * per:(i + 1) * per]
        key = chunk  # two frames that draw the same pixels are one, for both their times
        if key == last:
            durations[-1] += f["cs"]
        else:
            composed.append(compose(base, chunk[:TFT_W * TFT_H * 3], chunk[TFT_W * TFT_H * 3:]))
            durations.append(f["cs"])
            last = key
        if i == poster:
            poster_at = len(composed) - 1
    return {
        f"{name}-{lang}.gif": encode_gif(composed, durations, loop=True),
        f"{name}-{lang}-still.gif": encode_gif([composed[poster_at]], [100], loop=False),
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="fail if a file is not what the code draws")
    ap.add_argument("--only", action="append", help="a picture's id (repeatable)")
    ap.add_argument("--lang", action="append", help="a language (repeatable)")
    ap.add_argument("--frames-exe", help="the built mode_gif_frames, instead of Docker")
    ap.add_argument("--list", action="store_true", help="list the pictures and the sizes on disk")
    args = ap.parse_args(argv)

    config = yaml.safe_load(SCRIPTS.read_text(encoding="utf-8"))
    jobs = pictures(config, set(args.only or []), set(args.lang or []))
    if args.list:
        total = 0
        for name, lang, frames, poster, _ in jobs:
            for suffix in ("", "-still"):
                p = OUT / f"{name}-{lang}{suffix}.gif"
                size = p.stat().st_size if p.exists() else 0
                total += size
                print(f"{p.relative_to(REPO)}  {size} bytes" + (f"  {len(frames)} steps" if not suffix else ""))
        print(f"total {total} bytes")
        return 0

    keys = {f"{name}-{lang}": text for name, lang, _, _, text in jobs}
    try:
        if args.frames_exe:
            raws = {k: run_frames(t, args.frames_exe) for k, t in keys.items()}
        else:
            raws = run_in_docker(keys)
        with ProcessPoolExecutor() as pool:
            results = list(pool.map(make_files, [(n, l, f, p, raws[f"{n}-{l}"]) for n, l, f, p, _ in jobs]))
    except RuntimeError as error:
        return fail(str(error))

    files: dict[str, bytes] = {}
    for r in results:
        files.update(r)
    if args.check:
        bad = 0
        for name, data in sorted(files.items()):
            path = OUT / name
            if not path.exists():
                print(f"gen_mode_gifs: {path.relative_to(REPO)} is missing", file=sys.stderr)
                bad += 1
            elif path.read_bytes() != data:
                print(f"gen_mode_gifs: {path.relative_to(REPO)} is not what the code draws now", file=sys.stderr)
                bad += 1
        if not (args.only or args.lang):
            stale = sorted(p.name for p in OUT.glob("*.gif") if p.name not in files)
            for name in stale:
                print(f"gen_mode_gifs: {name} belongs to no script", file=sys.stderr)
            bad += len(stale)
        if bad:
            print("gen_mode_gifs: run python3 tools/gen_mode_gifs.py and look at the pictures (git status)",
                  file=sys.stderr)
            return 1
        print(f"gen_mode_gifs: {len(files)} pictures match what the firmware's screens draw")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    for name, data in sorted(files.items()):
        (OUT / name).write_bytes(data)
        total += len(data)
        print(f"{name}  {len(data)} bytes")
    if not (args.only or args.lang):
        for p in OUT.glob("*.gif"):
            if p.name not in files:
                p.unlink()
                print(f"removed {p.name}")
    print(f"{len(files)} files, {total} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
