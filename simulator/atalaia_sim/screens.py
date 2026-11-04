# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A mode's screen templates (assets/screens/*.yaml, ADR-P3-4): the checks CI runs.

Each file is parsed by the core's own parser (core/src/screen_template.c,
through ctypes), the one the Field Box renders with, so a template the
simulator accepts is one every box accepts. On top of that the file's name
must be its `template:` name, which is how ui.screen() finds it.
"""

from __future__ import annotations

import ctypes
import json
import re
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

import yaml

from .core import Core, _Scope

SOURCE_MAX = 4096  # ATALAIA_TPL_SOURCE_MAX
LITERALS_MAX = 256  # ATALAIA_TPL_LITERALS_MAX: the 'text' literals of one expression (decision TPL-1)
LITERALS_WARN = 230  # a warning from here: about 90 % of the limit


def screen_files(mode_dir: Path) -> list[Path]:
    folder = mode_dir / "assets" / "screens"
    return sorted(folder.glob("*.yaml")) if folder.is_dir() else []


def _split_filter(inner: str) -> str:
    """The expression of "{expr|filter}" ("||" is an operator, a '|' in a 'text' is text)."""
    quoted = False
    i = 0
    while i < len(inner):
        c = inner[i]
        if c == "'":
            quoted = not quoted
        elif c == "|" and not quoted:
            if inner[i + 1:i + 2] == "|":
                i += 2
                continue
            return inner[:i]
        i += 1
    return inner


def _expressions(text: str) -> Iterator[str]:
    """Every {expression} of a template text, as the core finds them."""
    i = 0
    while i < len(text):
        c = text[i]
        if c in "{}" and text[i + 1:i + 2] == c:
            i += 2
            continue
        if c != "{":
            i += 1
            continue
        close = text.find("}", i + 1)
        if close < 0:
            return
        yield _split_filter(text[i + 1:close])
        i = close + 1


def _widgets(node: Any, where: str) -> Iterator[tuple[str, dict[str, Any]]]:
    """Every widget (a mapping with a `type`), named by where it is: layout[1].children[0]."""
    if isinstance(node, list):
        for n, child in enumerate(node):
            yield from _widgets(child, f"{where}[{n}]")
    elif isinstance(node, dict):
        if "type" in node:
            yield where, node
        for key in ("children", "layout"):
            if key in node:
                yield from _widgets(node[key], f"{where}.{key}" if where else key)


def _strings(node: Any, field: str) -> Iterator[tuple[str, str]]:
    if isinstance(node, str):
        yield field, node
    elif isinstance(node, dict):
        for key, value in node.items():
            if key not in ("children", "layout"):
                yield from _strings(value, f"{field}.{key}" if field else str(key))


def literal_budget(core: Core, path: Path) -> list[tuple[str, str, int]]:
    """The 'text' literal bytes of every expression in a template, biggest first: (where, the
    expression, bytes). `where` names the widget and field ("layout[2] label text"). Every language
    is in the one expression (a chain of lang == ... branches), and the core counts them all,
    reached or not, so this is the exact size the evaluator needs, whatever the data."""
    try:
        doc = yaml.safe_load(path.read_bytes()) or {}
    except yaml.YAMLError:
        return []  # the core's parser has already said so
    found: list[tuple[str, str, int]] = []
    for where, widget in _widgets(doc.get("layout", []), "layout"):
        for field, value in _strings(widget, ""):
            for expr in _expressions(value):
                size = core.expression_literal_bytes(expr)
                if size:
                    found.append((f"{where} {widget.get('type')} {field}", expr, size))
    found.sort(key=lambda row: -row[2])
    return found


def _echo(expr: str) -> str:
    expr = " ".join(expr.split())
    return expr if len(expr) <= 60 else expr[:57] + "..."


def check_screen(core: Core, path: Path, mode: str = "") -> list[str]:
    """Problems with one template file (empty when it is fine). `mode` names the mode in the
    message of an expression whose 'text' literals are over the limit."""
    source = path.read_bytes()
    if len(source) > SOURCE_MAX:
        return [f"{path.name}: larger than {SOURCE_MAX} bytes"]
    try:
        source.decode("utf-8")
    except UnicodeDecodeError:
        return [f"{path.name}: not UTF-8"]
    try:
        over = [row for row in literal_budget(core, path) if row[2] > LITERALS_MAX]
    except AttributeError:  # a core from before the limit was checked
        over = []
    if over:
        # The Field Box would show an empty text for these (it refuses them at load), so say which.
        prefix = f"{mode} / " if mode else ""
        return [f"{prefix}{path.stem} / {where}: the expression {{{_echo(expr)}}} has 'text' "
                f"literals of {size} bytes in all (each its length + 1, every language's branch "
                f"counted); the limit is {LITERALS_MAX}. Shorten the texts or split the label "
                f"in two widgets with a visible: each" for where, expr, size in over]
    why = core.check_screen(source)
    if why is not None:
        return [f"{path.name}: {why}"]
    name = (yaml.safe_load(source) or {}).get("template")
    if name != path.stem:
        return [f"{path.name}: its template: name is {name!r}; it must be {path.stem!r}"]
    return []


def check_screens(core: Core, mode_dir: Path) -> list[str]:
    problems: list[str] = []
    for path in screen_files(mode_dir):
        problems += check_screen(core, path, mode_dir.name)
    return problems


def screen_warnings(core: Core, mode_dir: Path) -> list[str]:
    """Expressions that are close to the limit (from LITERALS_WARN bytes): one more translated
    word would tip them over."""
    warnings: list[str] = []
    for path in screen_files(mode_dir):
        try:
            rows = literal_budget(core, path)
        except AttributeError:
            return []
        for where, expr, size in rows:
            if LITERALS_WARN <= size <= LITERALS_MAX:
                warnings.append(f"{mode_dir.name} / {path.stem} / {where}: {{{_echo(expr)}}} uses "
                                f"{size} of {LITERALS_MAX} literal bytes")
    return warnings


# ---- drawing a template: the render model the web view draws ----
#
# The Field Box draws a template with LVGL (firmware/esp32/main/screen_template.c) and the app with
# Flutter (app/lib/ui/template/template_view.dart); both follow the same rules, and so does this.
# The template is parsed by the core's parser into its own struct (atalaia_tpl_t, read here through
# ctypes), and every expression, visible:, progress value and colour is evaluated by the core, so
# what the view draws is what a box draws with the same data. What is left to the view is the
# layout itself (web/app.js), with the box's numbers: 320x240, a centred column 4 px apart, rows
# 6 px apart, "fill" as flex grow, a 200x12 bar.

SCREEN_W, SCREEN_H = 320, 240
FONT_SIZES = (14, 20, 28, 48)  # the Field Box's fonts; font_size picks the nearest, 20 by default
COLOR_BG = 0x101418  # the screen's background when the template sets none
COLOR_TEXT = 0xFFFFFF  # a label's colour when it sets none
COLOR_DARK = 0x101418  # "contrast" on a light background
COLOR_TRACK = 0x222B35  # a progress bar's track
COLOR_BAR = 0xFFB300  # its filled part when it sets no colour
COLOR_UNKNOWN = 0x78909C  # a team without a colour
BAR_W, BAR_H = 200, 12
QR_FONT = 14  # a QR code is drawn as its text on the Field Box (the QR library is left out)
LANGS = ("en", "pt", "de", "zh-tw")  # the box languages a template knows (data `lang`)

_TPL_WIDGETS_MAX = 32  # ATALAIA_TPL_WIDGETS_MAX
_TPL_POOL_MAX = 3072  # ATALAIA_TPL_POOL_MAX
_TPL_YAML_MAX = 192  # ATALAIA_TPL_YAML_MAX
_TPL_AUTO, _TPL_FILL = -1, -2
_TYPES = {1: "label", 2: "progress_bar", 3: "icon", 4: "qr_code", 5: "spacer", 6: "row", 7: "column"}
_ALIGNS = {1: "left", 2: "center", 3: "right"}  # 0, the default, is centre too


class _TplWidget(ctypes.Structure):
    # atalaia_tpl_widget_t (core/include/atalaia/screen_template.h).
    _fields_ = [("type", ctypes.c_uint8), ("align", ctypes.c_uint8), ("parent", ctypes.c_int8),
                ("depth", ctypes.c_uint8), ("font_size", ctypes.c_int16), ("width", ctypes.c_int16),
                ("height", ctypes.c_int16), ("pad", ctypes.c_int16 * 4), ("id", ctypes.c_uint16),
                ("content", ctypes.c_uint16), ("color", ctypes.c_uint16),
                ("background", ctypes.c_uint16), ("visible", ctypes.c_uint16)]


class _TplYaml(ctypes.Structure):
    # atalaia_tpl_yaml_t: parsing scratch, here only for the struct's size.
    _fields_ = [("kind", ctypes.c_uint8), ("style", ctypes.c_uint8), ("line", ctypes.c_uint16),
                ("key", ctypes.c_uint16), ("key_len", ctypes.c_uint8), ("val", ctypes.c_uint16),
                ("val_len", ctypes.c_uint16), ("child", ctypes.c_int16), ("next", ctypes.c_int16)]


class _Tpl(ctypes.Structure):
    # atalaia_tpl_t. Its size is checked against atalaia_tpl_sizeof() before it is read.
    _fields_ = [("name", ctypes.c_uint16), ("background", ctypes.c_uint16), ("count", ctypes.c_uint8),
                ("w", _TplWidget * _TPL_WIDGETS_MAX), ("pool_used", ctypes.c_uint16),
                ("pool", ctypes.c_char * _TPL_POOL_MAX), ("yaml_count", ctypes.c_uint16),
                ("yaml", _TplYaml * _TPL_YAML_MAX)]


class ScreenError(Exception):
    """A template the core refuses, or a core whose atalaia_tpl_t is not the one mirrored here."""


def _bind(core: Core) -> Any:
    """The core's template functions, their types declared once per library."""
    lib = core.lib
    if getattr(lib, "_atalaia_tpl_bound", False):
        return lib
    scope = ctypes.POINTER(_Scope)
    for name, args, res in (
        ("atalaia_tpl_str", [ctypes.c_void_p, ctypes.c_uint16], ctypes.c_char_p),
        ("atalaia_tpl_truthy", [ctypes.c_char_p, scope], ctypes.c_bool),
        ("atalaia_tpl_fraction", [ctypes.c_char_p, scope], ctypes.c_double),
        ("atalaia_tpl_color", [ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32)], ctypes.c_bool),
    ):
        fn = getattr(lib, name)
        fn.argtypes = args
        fn.restype = res
    if ctypes.sizeof(_Tpl) != lib.atalaia_tpl_sizeof():
        raise ScreenError(f"this core's atalaia_tpl_t is {lib.atalaia_tpl_sizeof()} bytes, the "
                          f"simulator reads {ctypes.sizeof(_Tpl)}: update screens.py")
    lib._atalaia_tpl_bound = True
    return lib


def _hex(rgb: int) -> str:
    return f"#{rgb:06x}"


def _contrast_on(bg: int) -> int:
    """Dark text on light backgrounds (yellow), white text on the rest: the box's rule."""
    r, g, b = (bg >> 16) & 0xFF, (bg >> 8) & 0xFF, bg & 0xFF
    return COLOR_DARK if (r * 299 + g * 587 + b * 114) // 1000 > 160 else COLOR_TEXT


def nearest_font(size: int) -> int:
    """The Field Box's font for a font_size (0: its default, 20), as font_for() picks it."""
    if size <= 0:
        size = 20
    return 14 if size <= 16 else 20 if size <= 24 else 28 if size <= 38 else 48


def box_data(data: dict[str, Any], lang: str = "", game_s: Optional[int] = None) -> dict[str, Any]:
    """The data a box hands its template (screen_renderer.c add_extras): its language as `lang`
    unless the mode gives one (only when the box has a language set), and with the data's `since`
    and the game's clock, `age` and `held` (unless the data has its own) and `live`."""
    extra: dict[str, Any] = {}
    if lang and "lang" not in data:
        extra["lang"] = lang
    since = data.get("since")
    if game_s is not None and isinstance(since, int) and not isinstance(since, bool) and since >= 0:
        age = max(game_s - since, 0)
        if "held" not in data:
            extra["held"] = age
        extra["age"] = age
        extra["live"] = 1
    return {**extra, **data} if extra else data


def render_screen(core: Core, source: bytes, data: Optional[dict[str, Any]] = None,
                  params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """The render model of a template with its data, as the Field Box would draw it:

        {"template": name, "width": 320, "height": 240, "background": "#101418",
         "widgets": [{"type": "label", "visible": True, "text": "1:30", "font": 48,
                      "color": "#ffffff", "background": None, "align": "center",
                      "width": None, "height": None, "padding": [0, 0, 0, 0]}, ...]}

    A width or height is pixels, "fill" or None (fit the content). A label has `text` and `font`;
    an icon `icon` and `font`; a progress bar `value` (0-100, rounded as the box rounds it) and
    `track`; a QR code `text` (its data) and `font`; a row or column `children`. Every colour is
    resolved ("team", "contrast", palette names, {expressions}), `background` None meaning
    transparent. A hidden widget stays in the model with `visible` False. ScreenError for a
    template the core refuses."""
    lib = _bind(core)
    tpl = _Tpl()
    err = ctypes.create_string_buffer(256)
    if not lib.atalaia_tpl_parse(ctypes.byref(tpl), source, len(source), err, len(err)):
        raise ScreenError(err.value.decode(errors="replace"))
    scope = _Scope(json.dumps(data or {}).encode(), json.dumps(params or {}).encode())

    def string(off: int) -> Optional[str]:
        raw = lib.atalaia_tpl_str(ctypes.byref(tpl), off)
        return None if raw is None else raw.decode("utf-8", errors="replace")

    def text(value: Optional[str]) -> str:
        return core.screen_text(value or "", data or {}, params or {}) if value else ""

    def resolve(value: Optional[str], under: int) -> Optional[int]:
        """screen_template.c resolve(): None when not set (or empty), else the colour."""
        if value is None:
            return None
        if value == "contrast":
            return _contrast_on(under)
        name = text("{team}") if value == "team" else text(value) if value.startswith("{") else value
        if not name:
            return None
        if name == "contrast":
            return _contrast_on(under)
        rgb = ctypes.c_uint32()
        return rgb.value if lib.atalaia_tpl_color(name.encode(), ctypes.byref(rgb)) else COLOR_UNKNOWN

    def size(v: int) -> Any:
        return "fill" if v == _TPL_FILL else None if v == _TPL_AUTO else v

    screen_bg = resolve(string(tpl.background), COLOR_BG)
    screen_bg = COLOR_BG if screen_bg is None else screen_bg
    model: dict[str, Any] = {"template": string(tpl.name), "width": SCREEN_W, "height": SCREEN_H,
                             "background": _hex(screen_bg), "widgets": []}
    nodes: list[dict[str, Any]] = []
    under: list[int] = []  # the colour each widget is drawn on
    for i in range(tpl.count):
        w = tpl.w[i]
        kind = _TYPES.get(w.type, "?")
        parent_bg = under[w.parent] if w.parent >= 0 else screen_bg
        bg = resolve(string(w.background), parent_bg)
        under.append(parent_bg if bg is None else bg)
        fg = resolve(string(w.color), under[i])
        visible = bool(lib.atalaia_tpl_truthy(string(w.visible).encode() if w.visible else None,
                                              ctypes.byref(scope)))
        node: dict[str, Any] = {"type": kind, "visible": visible,
                                "align": _ALIGNS.get(w.align, "center"),
                                "width": size(w.width), "height": size(w.height),
                                "padding": list(w.pad),
                                "background": None if bg is None or kind == "progress_bar" else _hex(bg)}
        if w.id:
            node["id"] = string(w.id)
        content = string(w.content)
        if kind == "label":
            node.update(text=text(content), font=nearest_font(w.font_size),
                        color=_hex(COLOR_TEXT if fg is None else fg))
        elif kind == "icon":
            node.update(icon=content, font=nearest_font(w.font_size),
                        color=_hex(COLOR_TEXT if fg is None else fg))
        elif kind == "progress_bar":
            fraction = lib.atalaia_tpl_fraction(content.encode() if content else None,
                                                ctypes.byref(scope))
            node.update(value=int(fraction * 100.0 + 0.5), color=_hex(COLOR_BAR if fg is None else fg),
                        track=_hex(COLOR_TRACK))
            if node["width"] is None:
                node["width"] = BAR_W
            if node["height"] is None:
                node["height"] = BAR_H
        elif kind == "qr_code":
            node.update(text=text(content), font=nearest_font(w.font_size or QR_FONT),
                        color=_hex(COLOR_TEXT if fg is None else fg))
        elif kind == "spacer":
            if node["width"] is None:
                node["width"] = 1
            if node["height"] is None:
                node["height"] = 1
        else:
            node["children"] = []
        nodes.append(node)
        (nodes[w.parent]["children"] if w.parent >= 0 else model["widgets"]).append(node)
    return model


def find_screen(folders: Iterable[Path], name: str) -> Optional[Path]:
    """The template file a box finds for ui.screen(name): the main mode's first, then its
    modifiers' (screen_template_find); None when no part has one (a built-in C screen)."""
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,31}", name):
        return None
    for folder in folders:
        path = folder / "assets" / "screens" / f"{name}.yaml"
        if path.is_file():
            return path
    return None
