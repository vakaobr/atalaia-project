#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Checks the Field Box wiring diagrams against the firmware's pin defaults.

    python3 tools/check_wiring.py                 run the check
    python3 tools/check_wiring.py --resolve FILE  print FILE with its GPIO
                                                  placeholders filled in

The WireViz sources (hardware/field-box/wiring/*.yml) name board pins as
GPIO<SYMBOL>, the default of that Kconfig symbol in
firmware/esp32/main/Kconfig.projbuild; tools/docker_hw.py render fills them in
with --resolve before drawing. The check fails when:

- a GPIO placeholder names an unknown symbol, a disabled pin (-1), or two
  placeholders land on the same GPIO;
- a Kconfig pin does not go where it should (buttons, display, LED data, I2C
  bus, I2S audio), or the diagrams wire a GPIO no Kconfig pin claims;
- a wired GPIO is board-internal (the list in Kconfig.projbuild's header, plus
  the Heltec V4 front-end-module pins below), on the board's GNSS connector
  (its module keeps those pins: decision PIN-1) or a boot strapping pin (GPIO 45
  only for the optional piezo buzzer or, without it, a second simple output,
  whose circuits hold it low at reset: STRAP_TOLERANT below); or a board pin the
  Field Box shares on purpose (GPIO 1, 35, 44: SHARED below) is used for anything
  else than what it is shared for;
- the optional simple output (an RC relay switch on a spare gate; draft RFC "The
  expansion port", EXP-34) is not on the front-end-module pin the board revision
  leaves free (GPIO 46 on a V4.3, 5 on a V4.2: REVISION_FREE below), or shares a
  pin with another part on that revision; or, in an I/O pod's build, is not on
  GPIO 33 (its second on GPIO 1: POD_SIMPLE_OUT below) or shares a pin with
  another part the pod has;
- the keypad is not on the PCF8574 the way hal_esp_keypad.c scans it (rows on
  P0-P3, columns on P4-P6), the team button of ATALAIA_KP_P7_BUTTON is not on
  its P7, the expander address differs from the Kconfig default, or its INT
  pin is wired while the firmware polls;
- the pin table in hardware/field-box/README.md disagrees with Kconfig;
- a pin table of another node's build guide (the Satellite's and the I/O
  pod's BUILD.md, GUIDES below) or of the project page's build page
  (site/src/build.html, its cells marked data-kconfig) gives a GPIO that is
  not its Kconfig default, a pin no part may use, or leaves out a pin it must
  list (phase 5 plan phase 12);
- the expansion port's pin table (hardware/expansion-port/BUILD.md and its
  Portuguese BUILD.pt.md, the table after the marker PORT_MARKER) does not give
  the M12 pin-out of decision EXP-1 (pin, wire colour and signal; SDA and SCL on
  the box's I2C bus GPIOs and Kconfig options, nothing on pins 1, 3 and 5's GPIO
  and option cells, pin 5 not connected), or the keypad expander's Kconfig
  address falls in the expansion modules' range 0x58-0x5F (EXP-7: PORT_PINOUT,
  EXPANSION_ADDRESSES below);
- the I2C output module's pin table (hardware/output-module/BUILD.md and
  BUILD.pt.md, the table after the marker OUTPUT_MARKER) does not give each pin
  of firmware/output-module/src/board.h exactly once, on its GP number; or
  board.h itself puts two pins on one GPIO, a pin outside GP0-GP29, SDA and SCL
  off an i2c0 pair, or the supply sense off an ADC pin (OUTPUT_BOARD below);
- a rendered SVG or PNG is missing, or an SVG was not rendered from the
  current source and Kconfig defaults (the render writes the SHA-256 of the
  resolved source into it).

Needs only Python 3 and PyYAML. Exit code 0 = no errors.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
WIRING = REPO / "hardware" / "field-box" / "wiring"
DIAGRAMS = [WIRING / "field-box-wiring.yml", WIRING / "field-box-power.yml"]
KCONFIG = REPO / "firmware" / "esp32" / "main" / "Kconfig.projbuild"
README = REPO / "hardware" / "field-box" / "README.md"
SITE_BUILD = REPO / "site" / "src" / "build.html"

# The build guides of the other node types (phase 5 plan phase 12): each uses the Field Box's
# pins for the parts it has, in a table whose rows name their Kconfig symbol in backticks
# ("| Button 1 | 4 | `ATALAIA_BTN1_PIN` | ..."); these symbols must each have a row.
GUIDES: dict[Path, tuple[str, ...]] = {
    REPO / "hardware" / "field-box" / "BUILD.md": (
        "ATALAIA_BTN1_PIN", "ATALAIA_BTN2_PIN", "ATALAIA_BTN3_PIN", "ATALAIA_KP_P7_BUTTON",
        "ATALAIA_NFC_SDA_PIN", "ATALAIA_NFC_SCL_PIN", "ATALAIA_LED_PIN", "ATALAIA_DISP_CS_PIN",
        "ATALAIA_DISP_DC_PIN", "ATALAIA_DISP_MOSI_PIN", "ATALAIA_DISP_CLK_PIN",
        "ATALAIA_AUDIO_BCLK_PIN", "ATALAIA_AUDIO_LRCLK_PIN", "ATALAIA_AUDIO_DOUT_PIN",
        "ATALAIA_BUZZER_PIN"),
    REPO / "hardware" / "satellite" / "BUILD.md": (
        "ATALAIA_BTN1_PIN", "ATALAIA_BTN2_PIN", "ATALAIA_BTN3_PIN", "ATALAIA_LED_PIN",
        "ATALAIA_BATT_SDA_PIN", "ATALAIA_BATT_SCL_PIN", "ATALAIA_AUDIO_BCLK_PIN",
        "ATALAIA_AUDIO_LRCLK_PIN", "ATALAIA_AUDIO_DOUT_PIN", "ATALAIA_BUZZER_PIN"),
    REPO / "hardware" / "io-pod" / "BUILD.md": (
        "ATALAIA_BTN1_PIN", "ATALAIA_BTN2_PIN", "ATALAIA_BTN3_PIN", "ATALAIA_KP_P7_BUTTON",
        "ATALAIA_LED_PIN", "ATALAIA_NFC_SDA_PIN", "ATALAIA_NFC_SCL_PIN", "ATALAIA_AUDIO_BCLK_PIN",
        "ATALAIA_AUDIO_LRCLK_PIN", "ATALAIA_AUDIO_DOUT_PIN", "ATALAIA_POD_TAMPER_PIN"),
}
# The expansion port's build guide (draft RFC "The expansion port", increment 10): the port uses no
# GPIO of its own, so its only pins are the I2C bus's, behind the port board's buffer. Both languages
# are checked: the table is the same in each, and only the colour and signal words differ.
PORT_GUIDES = [REPO / "hardware" / "expansion-port" / "BUILD.md",
               REPO / "hardware" / "expansion-port" / "BUILD.pt.md"]
for _port_guide in PORT_GUIDES:
    GUIDES[_port_guide] = ("ATALAIA_NFC_SDA_PIN", "ATALAIA_NFC_SCL_PIN")
PORT_MARKER = "<!-- check_wiring: expansion-port-pins -->"
# M12 pin -> (its wire colour in English and Portuguese, the signal cell's accepted words (None: not
# connected), the Kconfig pin of its bus GPIO or None). Decision EXP-1 (P5J-20): 1 brown 3.3 V,
# 2 white SDA, 3 blue GND, 4 black SCL, 5 grey reserved, not connected.
PORT_PINOUT: dict[int, tuple[tuple[str, ...], tuple[str, ...] | None, str | None]] = {
    1: (("brown", "castanho"), ("3.3 V", "3,3 V"), None),
    2: (("white", "branco"), ("SDA",), "ATALAIA_NFC_SDA_PIN"),
    3: (("blue", "azul"), ("GND",), None),
    4: (("black", "preto"), ("SCL",), "ATALAIA_NFC_SCL_PIN"),
    5: (("grey", "cinzento"), None, None),
}
# The I2C output module's build guide (draft RFC "The expansion port", increment 11): its RP2040 pins
# are the firmware's own (board.h's OUT_PIN_* defines), not the box's Kconfig; each language's table
# names each define in backticks next to its GP number ("| GP6 | `OUT_PIN_CH0` | ...").
OUTPUT_BOARD = REPO / "firmware" / "output-module" / "src" / "board.h"
OUTPUT_GUIDES = [REPO / "hardware" / "output-module" / "BUILD.md",
                 REPO / "hardware" / "output-module" / "BUILD.pt.md"]
OUTPUT_MARKER = "<!-- check_wiring: output-module-pins -->"
OUTPUT_DEFINE = re.compile(r"^#define\s+(OUT_PIN_\w+)\s+(\d+)\b", re.MULTILINE)
OUTPUT_SYMBOL = re.compile(r"`(OUT_PIN_\w+)`")
RP2040_ADC_PINS = range(26, 30)
# Expansion modules answer at 0x58-0x5F (EXP-7); the box's own parts and the keypad search stay out.
EXPANSION_ADDRESSES = range(0x58, 0x60)
BOX_ADDRESSES = {0x24: "the PN532", 0x36: "the battery gauge", 0x3C: "the board's OLED"}
KEYPAD_SEARCH = (range(0x20, 0x28), range(0x38, 0x40))
# A guide whose pins are those of another firmware variant: its table is checked against that
# build's Kconfig defaults (the I/O pod's simple outputs: GPIO 33 and 1, not the Field Box's 46).
GUIDE_CHOICE: dict[Path, frozenset[str]] = {
    REPO / "hardware" / "io-pod" / "BUILD.md": frozenset({"ATALAIA_POD_MODE"}),
}
GUIDE_SYMBOL = re.compile(r"`(ATALAIA_\w+)`")
# The project page's build page: <td data-kconfig="ATALAIA_BTN1_PIN">4</td>.
SITE_CELL = re.compile(r'data-kconfig="(ATALAIA_\w+)"[^>]*>([^<]*)<')

BOARD = "BOARD"
HASH_MARK = "atalaia-wiring-source-sha256:"
PLACEHOLDER = re.compile(r"GPIO<(ATALAIA_\w+)>")

# Kconfig pin symbol -> the connector pin its GPIO must be wired to.
EXPECTED: dict[str, tuple[str, str]] = {
    "ATALAIA_BTN1_PIN": ("BTN1", "N/O"),
    "ATALAIA_BTN2_PIN": ("BTN2", "N/O"),
    "ATALAIA_BTN3_PIN": ("BTN3", "N/O"),
    "ATALAIA_BTN4_PIN": ("BTN4", "N/O"),
    "ATALAIA_LED_PIN": ("HUB", "LED data in (3.3 V)"),
    "ATALAIA_DISP_MOSI_PIN": ("TFT", "SDI (MOSI)"),
    "ATALAIA_DISP_CLK_PIN": ("TFT", "SCK"),
    "ATALAIA_DISP_CS_PIN": ("TFT", "CS"),
    "ATALAIA_DISP_DC_PIN": ("TFT", "DC"),
    "ATALAIA_DISP_RST_PIN": ("TFT", "RESET"),
    "ATALAIA_DISP_BL_PIN": ("TFT", "LED"),
    "ATALAIA_NFC_SDA_PIN": ("HUB", "SDA in"),
    "ATALAIA_NFC_SCL_PIN": ("HUB", "SCL in"),
    "ATALAIA_BATT_SDA_PIN": ("HUB", "SDA in"),
    "ATALAIA_BATT_SCL_PIN": ("HUB", "SCL in"),
    "ATALAIA_AUDIO_BCLK_PIN": ("AMP", "BCLK"),
    "ATALAIA_AUDIO_LRCLK_PIN": ("AMP", "LRC"),
    "ATALAIA_AUDIO_DOUT_PIN": ("AMP", "DIN"),
}

# The I2C devices hang off the hub; each must reach the bus's SDA and SCL rails.
I2C_DEVICES: dict[str, tuple[str, str]] = {
    "PCF8574": ("SDA to PCF8574", "SCL to PCF8574"),
    "PN532": ("SDA to PN532", "SCL to PN532"),
    "GAUGE": ("SDA to gauge", "SCL to gauge"),
}

# hal_esp_keypad.c: rows on P0-P3 (driven low in turn), columns on P4-P6.
KEYPAD_ON_PCF = {
    "R1": "P0", "R2": "P1", "R3": "P2", "R4": "P3",
    "C1": "P4", "C2": "P5", "C3": "P6",
}

# hardware/field-box/README.md "Peripheral Pins" rows -> Kconfig symbol.
README_ROWS = {
    "Button 1": "ATALAIA_BTN1_PIN",
    "Button 2": "ATALAIA_BTN2_PIN",
    "Button 3": "ATALAIA_BTN3_PIN",
    "Button 4": "ATALAIA_BTN4_PIN",
    "LED Data": "ATALAIA_LED_PIN",
    "Display MOSI": "ATALAIA_DISP_MOSI_PIN",
    "Display CLK": "ATALAIA_DISP_CLK_PIN",
    "Display CS": "ATALAIA_DISP_CS_PIN",
    "Display DC": "ATALAIA_DISP_DC_PIN",
    "Display RST": "ATALAIA_DISP_RST_PIN",
    "Display BL": "ATALAIA_DISP_BL_PIN",
    "I2C SDA": "ATALAIA_NFC_SDA_PIN",
    "I2C SCL": "ATALAIA_NFC_SCL_PIN",
    "I2S BCLK": "ATALAIA_AUDIO_BCLK_PIN",
    "I2S LRCLK": "ATALAIA_AUDIO_LRCLK_PIN",
    "I2S DOUT": "ATALAIA_AUDIO_DOUT_PIN",
    "GNSS power": "ATALAIA_GNSS_PWR_PIN",
    "GNSS TX": "ATALAIA_GNSS_TX_PIN",
    "GNSS RX": "ATALAIA_GNSS_RX_PIN",
    "GNSS wake-up": "ATALAIA_GNSS_WAKE_PIN",
    "GNSS PPS": "ATALAIA_GNSS_PPS_PIN",
    "GNSS reset": "ATALAIA_GNSS_RST_PIN",
}
# The README names the button on the keypad expander's P7 this way.
README_P7 = "PCF8574 P7"

STRAPPING_FORBIDDEN = {0, 45, 46}  # GPIO 3 is a strapping pin the pin map uses on purpose
# Strapping pins one optional part may take, because its circuit keeps the pin's reset level
# (decision BZR-1): GPIO -> (the Kconfig pins allowed on it, why). GPIO 45 selects the flash
# voltage at reset (low = 3.3 V, its internal pull-down): a piezo through a series resistor, or a
# transistor's base with 10 kohm to GND, never pulls it up. The diagrams do not show the buzzer.
STRAP_TOLERANT: dict[int, tuple[set[str], str]] = {
    45: ({"ATALAIA_BUZZER_PIN", "ATALAIA_SIMPLE_OUT2_PIN"},
         "the VDD_SPI strap: only the piezo buzzer or a second simple output, whose circuits "
         "hold it low at reset"),
}
# The board revision's free front-end-module pin (decision EXP-34): the V4.3 and the V4.2 swap
# GPIO 5 and 46, each being the other revision's front-end line, so the build's revision choice
# (Radio > Board revision) knows which one is free. Kconfig pin -> {revision: the GPIO it may take}.
# GPIO 46 is a strapping pin read low at reset: the simple output's 10 kohm pull-down keeps it so.
REVISION_FREE: dict[str, dict[str, int]] = {
    "ATALAIA_SIMPLE_OUT_PIN": {"ATALAIA_BOARD_HELTEC_V4_3": 46, "ATALAIA_BOARD_HELTEC_V4_2": 5},
}
# Each revision's own front-end pins: the other revision's Kconfig pin does not exist in its build.
REVISION_FEM: dict[str, tuple[int, str]] = {
    "ATALAIA_BOARD_HELTEC_V4_3": (5, "ATALAIA_RADIO_FEM_PA_PIN"),
    "ATALAIA_BOARD_HELTEC_V4_2": (46, "ATALAIA_RADIO_FEM_CTX_PIN"),
}
DEFAULT_REVISION = "ATALAIA_BOARD_HELTEC_V4_3"
# The I/O pod's simple outputs (EXP-34, increment 9): the pod has no display, so its pins 33, 1 and
# 3 are free; output 1 on GPIO 33, output 2 on GPIO 1. The display's and the on-board OLED's
# symbols keep their Field Box defaults in a pod build but drive nothing there, and the keypad's
# GPIO matrix is the Wokwi emulator's (a pod has the PCF8574; the firmware refuses a clash in a
# matrix build at compile time).
POD_SIMPLE_OUT = {"ATALAIA_SIMPLE_OUT_PIN": 33, "ATALAIA_SIMPLE_OUT2_PIN": 1}
POD_UNUSED_PREFIXES = ("ATALAIA_DISP_", "ATALAIA_OLED_", "ATALAIA_KP_ROW", "ATALAIA_KP_COL")
# Optional parts Kconfig never builds together (`depends on !...`): their pins may share a GPIO.
EXCLUSIVE = {frozenset({"ATALAIA_BUZZER_PIN", "ATALAIA_SIMPLE_OUT2_PIN"})}
SHARED_BUS = {17, 18}  # board-internal, but the shared I2C bus is meant to be wired

# Heltec WiFi LoRa 32 V4 pins that the Kconfig header does not list (yet).
# Either board revision may be fitted, so both revisions' pins are reserved.
V4_RESERVED = {
    5: "front-end module CTX (LNA/bypass) line on the V4.3",
    46: "front-end module PA-mode line on the V4.2",
}
# The board's GNSS connector: its module keeps these pins (decision PIN-1).
# They are in the Kconfig header's board-internal list too; this names them.
V4_GNSS = {
    34: "GNSS connector's power control (VGNSS_Ctrl)",
    38: "GNSS module's RX line", 39: "GNSS module's TX line", 40: "GNSS module's wake-up line",
    41: "GNSS module's PPS line", 42: "GNSS module's reset line",
}
# Board pins with a part of their own that the Field Box uses for one thing
# that part tolerates (Kconfig.projbuild's header; decisions PIN-3, PIN-5):
# GPIO -> (the Kconfig pins allowed on it, why only those).
SHARED: dict[int, tuple[set[str], str]] = {
    1: ({"ATALAIA_DISP_CS_PIN", "ATALAIA_DISP_DC_PIN", "ATALAIA_DISP_RST_PIN",
         "ATALAIA_SIMPLE_OUT2_PIN"},
        "the battery-voltage ADC input, 100 kohm to GND: a low-speed output only (a display "
        "line, or an I/O pod's second simple output)"),
    35: ({"ATALAIA_LED_PIN"}, "the board's white LED: the LED ring's data only"),
    44: ({"ATALAIA_BTN1_PIN", "ATALAIA_BTN2_PIN", "ATALAIA_BTN3_PIN", "ATALAIA_BTN4_PIN"},
         "UART0's RX line: a team button only (the box then takes no console input there)"),
}


def _truth(expr: str, bools: dict[str, bool]) -> bool:
    """Evaluates a Kconfig condition made of SYM, !SYM, && and || (no parentheses)."""
    def term(t: str) -> bool:
        t = t.strip()
        if t.startswith("!"):
            return not term(t[1:])
        return bools.get(t, False)
    return any(all(term(t) for t in part.split("&&")) for part in expr.split("||"))


def read_kconfig_defaults(text: str, choose: frozenset[str] = frozenset()) -> dict[str, int]:
    """Returns the default of every numeric `config` symbol.

    Handles conditional defaults (`default 6 if SYM`, the first true one wins)
    and choices (`default SYM` selects that choice member; a member in `choose`
    is selected instead, as a build that picks it).
    """
    numeric: dict[str, list[tuple[str, str | None]]] = {}
    bool_defaults: dict[str, list[tuple[str, str | None]]] = {}
    choice_members: list[list[str]] = []
    choice_default: list[str | None] = []
    symbol = None
    in_choice = False
    help_indent = None  # inside a help text: its keyword's indentation
    for line in text.splitlines():
        indent = len(line) - len(line.lstrip())
        if help_indent is not None:
            if not line.strip() or indent > help_indent:
                continue
            help_indent = None
        stripped = line.split("#", 1)[0].strip()
        if stripped in ("help", "---help---"):
            help_indent = indent
            continue
        m = re.match(r"(?:menu)?config\s+(\w+)$", stripped)
        if m:
            symbol = m.group(1)
            if in_choice:
                choice_members[-1].append(symbol)
            continue
        if re.match(r"choice\b", stripped):
            in_choice, symbol = True, None
            choice_members.append([])
            choice_default.append(None)
            continue
        if stripped == "endchoice":
            in_choice, symbol = False, None
            continue
        if re.match(r"(menu|endmenu|if|endif|comment)\b", stripped):
            symbol = None
            continue
        m = re.match(r"default\s+(\S+)(?:\s+if\s+(.+))?$", stripped)
        if not m:
            continue
        value, cond = m.group(1), m.group(2)
        if symbol is None and in_choice:
            if choice_default[-1] is None and cond is None:
                choice_default[-1] = value
        elif symbol is not None:
            if re.fullmatch(r"-?\d+|0x[0-9a-fA-F]+", value):
                numeric.setdefault(symbol, []).append((value, cond))
            elif value in ("y", "n"):
                bool_defaults.setdefault(symbol, []).append((value, cond))
    bools: dict[str, bool] = {}
    for members, default in zip(choice_members, choice_default):
        chosen = default or (members[0] if members else None)
        picked = [m for m in members if m in choose]
        if picked:
            chosen = picked[0]
        for member in members:
            bools[member] = member == chosen
    for name, options in bool_defaults.items():
        for value, cond in options:
            if cond is None or _truth(cond, bools):
                bools[name] = value == "y"
                break
    defaults: dict[str, int] = {}
    for name, options in numeric.items():
        for value, cond in options:
            if cond is None or _truth(cond, bools):
                defaults[name] = int(value, 0)
                break
    return defaults


def read_board_internal(text: str) -> set[int]:
    """Parses the 'Board-internal pins -- DO NOT reassign' list in the Kconfig header."""
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if "Board-internal pins" in line)
    except StopIteration:
        return set()
    block = []
    for line in lines[start + 1:]:
        body = line.lstrip("#").strip()
        if not body:
            break
        block.append(body)
    pins: set[int] = set()
    # Drop the "(...)" descriptions, then read numbers and ranges.
    for item in re.sub(r"\([^)]*\)", "", " ".join(block)).replace(".", "").split(","):
        # "8-14", "21", or "5 on the V4.3" (a revision-specific pin counts too)
        m = re.match(r"(\d+)(?:\s*-\s*(\d+))?\b", item.strip())
        if m:
            pins.update(range(int(m.group(1)), int(m.group(2) or m.group(1)) + 1))
    return pins


def resolve(text: str, defaults: dict[str, int]) -> tuple[str, list[str]]:
    """Fills in GPIO<SYMBOL> placeholders with the Kconfig defaults."""
    errors: list[str] = []

    def fill(m: re.Match) -> str:
        symbol = m.group(1)
        if symbol not in defaults:
            errors.append(f"GPIO<{symbol}>: no numeric Kconfig default for {symbol}")
            return m.group(0)
        if defaults[symbol] < 0:
            errors.append(f"GPIO<{symbol}>: {symbol} is -1 (not wired) by default; "
                          "take its wire out of the diagram")
            return m.group(0)
        return f"GPIO{defaults[symbol]}"

    return PLACEHOLDER.sub(fill, text), sorted(set(errors))


def pin_names(connector: dict) -> list[str]:
    """A connector's pin labels, or its pin IDs when it names pins that way (the board)."""
    return [str(p) for p in connector.get("pinlabels") or connector.get("pins") or []]


def pin_label(connector: dict, pin: object, name: str) -> str:
    """Resolves a pin reference (label, string ID or 1-based number) to its name."""
    labels = pin_names(connector)
    if isinstance(pin, str) and pin in labels:
        return pin
    if isinstance(pin, int) and 1 <= pin <= len(labels):
        return labels[pin - 1]
    raise ValueError(f"{name}: unknown pin {pin!r}")


def read_links(diagram: dict) -> list[tuple[tuple[str, str], tuple[str, str]]]:
    """Returns every wire as ((connector, pin label), (connector, pin label))."""
    connectors = diagram.get("connectors", {})
    cables = diagram.get("cables", {})
    links = []
    for index, conn_set in enumerate(diagram.get("connections", [])):
        items = []
        for item in conn_set:
            if isinstance(item, str) and re.fullmatch(r"<?[-=]{2}>?", item):
                continue  # an arrow: a direct wire between the connectors either side
            if not isinstance(item, dict) or len(item) != 1:
                raise ValueError(f"connection set {index + 1}: expected one designator per item")
            (name, pins), = item.items()
            items.append((name, pins if isinstance(pins, list) else [pins]))
        lengths = {len(pins) for _, pins in items}
        if len(lengths) != 1:
            raise ValueError(f"connection set {index + 1}: pin lists of different lengths")
        for i in range(lengths.pop()):
            chain = []
            for name, pins in items:
                if name in connectors:
                    chain.append((name, pin_label(connectors[name], pins[i], name)))
                elif name not in cables:
                    raise ValueError(f"connection set {index + 1}: unknown designator {name!r}")
            for a, b in zip(chain, chain[1:]):
                links.append((a, b))
    return links


def board_wiring(links) -> dict[int, set[tuple[str, str]]]:
    """GPIO number -> the connector pins it is wired to."""
    wired: dict[int, set[tuple[str, str]]] = {}
    for a, b in links:
        for end, other in ((a, b), (b, a)):
            if end[0] == BOARD:
                m = re.fullmatch(r"GPIO(\d+)", end[1])
                if m:
                    wired.setdefault(int(m.group(1)), set()).add(other)
    return wired


def connected(links, a: tuple[str, str], b: tuple[str, str]) -> bool:
    return (a, b) in links or (b, a) in links


def check_simple_outputs(kconfig_text: str, internal: set[int]) -> list[str]:
    """The optional simple outputs (not in the diagrams; decision EXP-34), on each board revision:
    output 1 on the revision's free front-end pin, output 2 on GPIO 45 and only without the buzzer,
    neither on another part's default pin."""
    errors: list[str] = []
    block = re.search(r"config ATALAIA_SIMPLE_OUT2\n(.*?)\n\n", kconfig_text, re.S)
    if block is None or not re.search(r"depends on [^\n]*!ATALAIA_BUZZER\b", block.group(1)):
        errors.append("Kconfig: ATALAIA_SIMPLE_OUT2 must depend on !ATALAIA_BUZZER (GPIO 45 is the "
                      "buzzer's or a second simple output)")
    for revision, (fem, other_fem_symbol) in REVISION_FEM.items():
        defaults = read_kconfig_defaults(kconfig_text, frozenset({revision}))
        name = revision.removeprefix("ATALAIA_BOARD_HELTEC_").replace("_", ".")
        for symbol, wanted in REVISION_FREE.items():
            gpio = defaults.get(symbol)
            if gpio != wanted[revision]:
                errors.append(f"Kconfig: {symbol} defaults to {gpio} on a {name}, not GPIO "
                              f"{wanted[revision]}, the pin that revision leaves free")
            if gpio == fem:
                errors.append(f"Kconfig: {symbol} = {gpio} on a {name}, its front-end-module line")
        second = defaults.get("ATALAIA_SIMPLE_OUT2_PIN")
        if second is None or second not in STRAP_TOLERANT or \
                "ATALAIA_SIMPLE_OUT2_PIN" not in STRAP_TOLERANT[second][0]:
            errors.append(f"Kconfig: ATALAIA_SIMPLE_OUT2_PIN defaults to {second}, not GPIO 45")
        for out in ("ATALAIA_SIMPLE_OUT_PIN", "ATALAIA_SIMPLE_OUT2_PIN"):
            gpio = defaults.get(out, -1)
            if gpio < 0:
                continue
            if gpio in V4_GNSS or gpio in SHARED or (gpio in internal and gpio not in (5, 46)):
                errors.append(f"Kconfig: {out} = {gpio}, a pin the board or another part keeps")
            for symbol, other in sorted(defaults.items()):
                if (symbol == out or not symbol.endswith("_PIN") or other != gpio
                        or symbol == other_fem_symbol
                        or frozenset({symbol, out}) in EXCLUSIVE):
                    continue
                errors.append(f"Kconfig: {out} = {gpio} on a {name}, the default of {symbol} too")
    # The I/O pod's build: its own pins for them, clear of every part a pod drives.
    for revision, (fem, other_fem_symbol) in REVISION_FEM.items():
        defaults = read_kconfig_defaults(kconfig_text, frozenset({revision, "ATALAIA_POD_MODE"}))
        name = revision.removeprefix("ATALAIA_BOARD_HELTEC_").replace("_", ".")
        for out, wanted in POD_SIMPLE_OUT.items():
            gpio = defaults.get(out)
            if gpio != wanted:
                errors.append(f"Kconfig: {out} defaults to {gpio} in an I/O pod build on a {name}, "
                              f"not GPIO {wanted}")
                continue
            if gpio in V4_GNSS or gpio == fem or (gpio in internal and gpio not in (5, 46)):
                errors.append(f"Kconfig: {out} = {gpio} in an I/O pod build, a pin the board keeps")
            if gpio in SHARED and out not in SHARED[gpio][0]:
                errors.append(f"Kconfig: {out} = {gpio} in an I/O pod build, which is "
                              f"{SHARED[gpio][1]}")
            for symbol, other in sorted(defaults.items()):
                if (symbol == out or not symbol.endswith("_PIN") or other != gpio
                        or symbol == other_fem_symbol or symbol.startswith(POD_UNUSED_PREFIXES)):
                    continue
                errors.append(f"Kconfig: {out} = {gpio} in an I/O pod build on a {name}, the "
                              f"default of {symbol} too")
    return errors


def check_readme(text: str, defaults: dict[str, int]) -> list[str]:
    """Each row's GPIO cell starts with the Kconfig default (-1: not a GPIO).

    The button on the keypad expander's P7 says README_P7 instead.
    """
    errors = []
    p7_row = f"Button {defaults.get('ATALAIA_KP_P7_BUTTON', 0)}"
    section = text.split("### Peripheral Pins", 1)
    if len(section) != 2:
        return ["README.md: no 'Peripheral Pins' table"]
    seen = set()
    for line in section[1].splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or cells[0] not in README_ROWS:
            continue
        symbol = README_ROWS[cells[0]]
        seen.add(cells[0])
        if cells[0] == p7_row:
            if cells[1] != README_P7:
                errors.append(f"README.md: {cells[0]} is on the keypad expander's P7 "
                              f"(ATALAIA_KP_P7_BUTTON), the row says {cells[1]!r}, not "
                              f"{README_P7!r}")
            continue
        m = re.match(r"-?\d+\b", cells[1])
        if not m:
            errors.append(f"README.md: '{cells[0]}' row has no GPIO number ({cells[1]!r})")
        elif int(m.group(0)) != defaults.get(symbol):
            errors.append(f"README.md: {cells[0]} is GPIO {m.group(0)}, Kconfig {symbol} "
                          f"defaults to {defaults.get(symbol)}")
    for row in README_ROWS:
        if row not in seen:
            errors.append(f"README.md: the pin table has no '{row}' row")
    return errors


def check_pin(where: str, symbol: str, cell: str, defaults: dict[str, int],
              internal: set[int]) -> list[str]:
    """One pin of a build guide's table: its cell against the Kconfig default and the board."""
    if symbol == "ATALAIA_KP_P7_BUTTON":
        if defaults.get(symbol, 0) <= 0:
            return [f"{where}: {symbol} is 0 by default: no button on the keypad expander's P7"]
        if cell != README_P7:
            return [f"{where}: the button of {symbol} is on the keypad expander's P7, the table "
                    f"says {cell!r}, not {README_P7!r}"]
        return []
    if symbol not in defaults:
        return [f"{where}: {symbol} is not a Kconfig symbol with a numeric default"]
    m = re.match(r"-?\d+\b", cell)
    if not m:
        return [f"{where}: {symbol}'s row has no GPIO number ({cell!r})"]
    gpio = int(m.group(0))
    if gpio != defaults[symbol]:
        return [f"{where}: {symbol} is GPIO {gpio} in the table, Kconfig defaults to "
                f"{defaults[symbol]}"]
    if gpio < 0:
        return [f"{where}: {symbol} is disabled by default (-1): a guide lists wired pins only"]
    if gpio in STRAP_TOLERANT and symbol in STRAP_TOLERANT[gpio][0]:
        return []
    if POD_SIMPLE_OUT.get(symbol) == gpio:
        return []  # the I/O pod's guide, read with its build's defaults (GUIDE_CHOICE)
    if symbol in REVISION_FREE:
        # A guide's tables are for the default revision (a V4.3); its cell names both.
        if gpio == REVISION_FREE[symbol][DEFAULT_REVISION]:
            return []
        return [f"{where}: {symbol} = GPIO {gpio}, not the pin the board revision leaves free"]
    if gpio in STRAPPING_FORBIDDEN:
        return [f"{where}: {symbol} = GPIO {gpio}, a boot strapping pin"]
    if gpio in V4_GNSS:
        return [f"{where}: {symbol} = GPIO {gpio}, the {V4_GNSS[gpio]}"]
    if gpio in V4_RESERVED:
        return [f"{where}: {symbol} = GPIO {gpio}, the {V4_RESERVED[gpio]}"]
    if gpio in SHARED:
        allowed, why = SHARED[gpio]
        if symbol not in allowed:
            return [f"{where}: {symbol} = GPIO {gpio}, which is {why}"]
    elif gpio in internal and gpio not in SHARED_BUS:
        return [f"{where}: {symbol} = GPIO {gpio}, a board-internal pin"]
    return []


def check_guide(name: str, text: str, required: tuple[str, ...], defaults: dict[str, int],
                internal: set[int]) -> list[str]:
    """A build guide's pin table: each row whose cell is a backticked Kconfig symbol has the
    GPIO (or "PCF8574 P7") in the cell before it; every required symbol has a row."""
    errors: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        for i, cell in enumerate(cells):
            m = GUIDE_SYMBOL.fullmatch(cell)
            if not m or i == 0:
                continue
            seen.add(m.group(1))
            errors += check_pin(name, m.group(1), cells[i - 1], defaults, internal)
    errors += [f"{name}: the pin table has no row for {s}" for s in required if s not in seen]
    return errors


def check_port_table(name: str, text: str, defaults: dict[str, int]) -> list[str]:
    """The expansion port's pin table: the M12 pin-out of EXP-1, the bus's GPIOs and options on SDA
    and SCL, and nothing in the GPIO and option cells of pins 1, 3 and 5 (the GPIO cells themselves
    are checked against Kconfig by check_guide, as every guide's are)."""
    if PORT_MARKER not in text:
        return [f"{name}: no pin table after the marker {PORT_MARKER!r}"]
    errors: list[str] = []
    seen: dict[int, int] = {}
    in_table = False
    for line in text.split(PORT_MARKER, 1)[1].splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            if in_table:
                break
            continue
        in_table = True
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not re.fullmatch(r"\d+", cells[0]):
            continue  # the header and its rule
        pin = int(cells[0])
        if pin not in PORT_PINOUT:
            errors.append(f"{name}: the port table has an M12 pin {pin}; the socket has pins 1-5")
            continue
        seen[pin] = seen.get(pin, 0) + 1
        if len(cells) < 5:
            errors.append(f"{name}: M12 pin {pin}'s row has fewer than 5 cells (pin, colour, signal, "
                          "GPIO, firmware option)")
            continue
        colours, signals, symbol = PORT_PINOUT[pin]
        colour, signal, gpio_cell, option = cells[1].lower(), cells[2], cells[3], cells[4]
        if colour not in colours:
            errors.append(f"{name}: M12 pin {pin} is {cells[1]!r}, EXP-1 gives {colours[0]}")
        if signals is None:
            if re.search(r"\d\s*V\b|SDA|SCL|GND", signal):
                errors.append(f"{name}: M12 pin 5 is reserved and not connected (EXP-1), the table "
                              f"says {signal!r}")
        elif not any(word in signal for word in signals):
            errors.append(f"{name}: M12 pin {pin}'s signal is {signal!r}, EXP-1 gives {signals[0]}")
        found = GUIDE_SYMBOL.fullmatch(option)
        if symbol is None:
            if re.search(r"\d", gpio_cell) or GUIDE_SYMBOL.search(option):
                errors.append(f"{name}: M12 pin {pin} is not a GPIO signal: its GPIO and firmware "
                              f"option cells must be '--', not {gpio_cell!r} and {option!r}")
        elif found is None or found.group(1) != symbol:
            errors.append(f"{name}: M12 pin {pin} ({signals[0] if signals else ''}) is the box's I2C "
                          f"bus: its firmware option must be `{symbol}`, not {option!r}")
    for pin in PORT_PINOUT:
        if pin not in seen:
            errors.append(f"{name}: the port table has no row for M12 pin {pin}")
        elif seen[pin] > 1:
            errors.append(f"{name}: the port table has {seen[pin]} rows for M12 pin {pin}")
    if defaults.get("ATALAIA_NFC_SDA_PIN") == defaults.get("ATALAIA_NFC_SCL_PIN"):
        errors.append(f"{name}: SDA and SCL default to the same GPIO")
    return errors


def check_port_addresses(defaults: dict[str, int]) -> list[str]:
    """The expansion modules' addresses (EXP-7) are clear of the box's parts and its keypad search."""
    errors: list[str] = []
    for address in EXPANSION_ADDRESSES:
        if address in BOX_ADDRESSES:
            errors.append(f"expansion modules' address 0x{address:02x} is {BOX_ADDRESSES[address]}'s")
        if any(address in search for search in KEYPAD_SEARCH):
            errors.append(f"expansion modules' address 0x{address:02x} is in the keypad search")
        if address < 0x08 or address > 0x77:
            errors.append(f"expansion modules' address 0x{address:02x} is an I2C reserved address")
    keypad = defaults.get("ATALAIA_KP_I2C_ADDR")
    if keypad is not None and keypad in EXPANSION_ADDRESSES:
        errors.append(f"Kconfig: ATALAIA_KP_I2C_ADDR = 0x{keypad:02x}, in the expansion modules' range "
                      "0x58-0x5F (EXP-7)")
    return errors


def check_site_build(text: str, required: set[str], defaults: dict[str, int],
                     internal: set[int]) -> list[str]:
    """The project page's build page: each cell marked data-kconfig holds that pin's GPIO."""
    errors: list[str] = []
    seen: set[str] = set()
    for symbol, cell in SITE_CELL.findall(text):
        seen.add(symbol)
        errors += check_pin(SITE_BUILD.name, symbol, cell.strip(), defaults, internal)
    errors += [f"{SITE_BUILD.name}: no data-kconfig cell for {s}" for s in sorted(required)
               if s not in seen]
    return errors


def read_output_board(text: str) -> dict[str, int]:
    """board.h's OUT_PIN_* defines: symbol -> GP number."""
    return {name: int(gp) for name, gp in OUTPUT_DEFINE.findall(text)}


def check_output_board(pins: dict[str, int]) -> list[str]:
    """The output module's pins themselves: one GPIO each, on the RP2040, the bus on an i2c0 pair,
    the supply sense on an ADC pin."""
    name = OUTPUT_BOARD.relative_to(REPO).as_posix()
    errors: list[str] = []
    if not pins:
        return [f"{name}: no OUT_PIN_* define"]
    for symbol in ("OUT_PIN_SDA", "OUT_PIN_SCL", "OUT_PIN_SUPPLY_SENSE", "OUT_PIN_LED",
                   "OUT_PIN_JUMPER_A0", "OUT_PIN_JUMPER_A1", "OUT_PIN_CH0"):
        if symbol not in pins:
            errors.append(f"{name}: no {symbol}")
    by_gp: dict[int, list[str]] = {}
    for symbol, gp in pins.items():
        by_gp.setdefault(gp, []).append(symbol)
        if gp > 29:
            errors.append(f"{name}: {symbol} is GP{gp}; the RP2040 has GP0-GP29")
    for gp, symbols in sorted(by_gp.items()):
        if len(symbols) > 1:
            errors.append(f"{name}: {' and '.join(sorted(symbols))} are both GP{gp}")
    sda, scl = pins.get("OUT_PIN_SDA"), pins.get("OUT_PIN_SCL")
    if sda is not None and scl is not None and (sda % 4 != 0 or scl != sda + 1):
        errors.append(f"{name}: SDA GP{sda} and SCL GP{scl} are not an i2c0 pair (GP0/1, GP4/5, ...)")
    sense = pins.get("OUT_PIN_SUPPLY_SENSE")
    if sense is not None and sense not in RP2040_ADC_PINS:
        errors.append(f"{name}: OUT_PIN_SUPPLY_SENSE is GP{sense}, not an ADC pin (GP26-GP29)")
    return errors


def check_output_table(name: str, text: str, pins: dict[str, int]) -> list[str]:
    """The output module's pin table: each board.h pin exactly once, its GP number in the cell
    before its backticked name."""
    if OUTPUT_MARKER not in text:
        return [f"{name}: no pin table after the marker {OUTPUT_MARKER!r}"]
    errors: list[str] = []
    seen: dict[str, int] = {}
    in_table = False
    for line in text.split(OUTPUT_MARKER, 1)[1].splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            if in_table:
                break
            continue
        in_table = True
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        for i, cell in enumerate(cells):
            m = OUTPUT_SYMBOL.fullmatch(cell)
            if not m:
                continue
            symbol = m.group(1)
            seen[symbol] = seen.get(symbol, 0) + 1
            if symbol not in pins:
                errors.append(f"{name}: the pin table names {symbol}, which board.h does not have")
                continue
            gp = re.fullmatch(r"GP(\d+)", cells[i - 1]) if i > 0 else None
            if gp is None or int(gp.group(1)) != pins[symbol]:
                errors.append(f"{name}: {symbol} is GP{pins[symbol]} in board.h, the table says "
                              f"{cells[i - 1] if i > 0 else 'nothing'!r}")
    for symbol in pins:
        if symbol not in seen:
            errors.append(f"{name}: the pin table has no row for {symbol}")
        elif seen[symbol] > 1:
            errors.append(f"{name}: the pin table has {seen[symbol]} rows for {symbol}")
    return errors


def check_guides(kconfig_path: Path) -> list[str]:
    """The pin tables of the other nodes' build guides and of the project page's build page."""
    kconfig_text = kconfig_path.read_text(encoding="utf-8")
    defaults = read_kconfig_defaults(kconfig_text)
    internal = read_board_internal(kconfig_text)
    errors: list[str] = []
    for path, required in GUIDES.items():
        name = path.relative_to(REPO).as_posix()
        choice = GUIDE_CHOICE.get(path)
        guide_defaults = read_kconfig_defaults(kconfig_text, choice) if choice else defaults
        errors += check_guide(name, path.read_text(encoding="utf-8"), required, guide_defaults,
                              internal)
    for path in PORT_GUIDES:
        errors += check_port_table(path.relative_to(REPO).as_posix(),
                                   path.read_text(encoding="utf-8"), defaults)
    errors += check_port_addresses(defaults)
    output_pins = read_output_board(OUTPUT_BOARD.read_text(encoding="utf-8"))
    errors += check_output_board(output_pins)
    for path in OUTPUT_GUIDES:
        errors += check_output_table(path.relative_to(REPO).as_posix(),
                                     path.read_text(encoding="utf-8"), output_pins)
    required_all = {s for symbols in GUIDES.values() for s in symbols}
    errors += check_site_build(SITE_BUILD.read_text(encoding="utf-8"), required_all, defaults,
                               internal)
    return errors


def text_hash(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def check(diagram_paths: list[Path], kconfig_path: Path, readme_path: Path | None,
          render_check: bool = True) -> tuple[list[str], list[str]]:
    """Returns (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    kconfig_text = kconfig_path.read_text(encoding="utf-8")
    defaults = read_kconfig_defaults(kconfig_text)
    internal = read_board_internal(kconfig_text)
    if not internal:
        errors.append("Kconfig.projbuild: the board-internal pin list was not found")

    # The diagrams are read together: a part may appear in several of them,
    # each time with the pins that diagram shows.
    links: list[tuple[tuple[str, str], tuple[str, str]]] = []
    board_labels: list[str] = []
    pcf_text = ""
    for path in diagram_paths:
        resolved, resolve_errors = resolve(path.read_text(encoding="utf-8"), defaults)
        errors += [f"{path.name}: {e}" for e in resolve_errors]
        diagram = yaml.safe_load(resolved)
        connectors = diagram.get("connectors", {})
        labels = pin_names(connectors.get(BOARD, {}))
        for label in sorted({x for x in labels if labels.count(x) > 1}):
            errors.append(f"{path.name}: two board pins resolve to {label}: two Kconfig pins "
                          "share one GPIO")
        board_labels += labels
        pcf_text += " " + str(connectors.get("PCF8574", {}).get("subtype", ""))
        try:
            links += read_links(diagram)
        except ValueError as e:
            errors.append(f"{path.name}: {e}")
        if render_check:
            svg_path, png_path = path.with_suffix(".svg"), path.with_suffix(".png")
            for image in (svg_path, png_path):
                if not image.exists():
                    errors.append(f"{image.name} is missing: run python tools/docker_hw.py render")
            if svg_path.exists():
                svg = svg_path.read_text(encoding="utf-8")
                if f"{HASH_MARK} {text_hash(resolved)}" not in svg:
                    errors.append(f"{svg_path.name} was not rendered from the current "
                                  f"{path.name} and Kconfig defaults: run "
                                  "python tools/docker_hw.py render")
    wired = board_wiring(links)

    # Every Kconfig pin goes where it should.
    claimed: set[int] = set()
    for symbol, target in EXPECTED.items():
        if symbol not in defaults:
            errors.append(f"Kconfig: {symbol} has no numeric default")
            continue
        gpio = defaults[symbol]
        if gpio < 0:
            continue  # the peripheral is off by default; nothing to wire
        claimed.add(gpio)
        if target not in wired.get(gpio, set()):
            got = ", ".join(f"{c}.{p}" for c, p in sorted(wired.get(gpio, set()))) or "nothing"
            errors.append(f"{symbol} = {gpio}: the diagram must wire GPIO{gpio} to "
                          f"{target[0]}.{target[1]}, it goes to {got}")
        for other_gpio, ends in wired.items():
            if other_gpio != gpio and target in ends:
                errors.append(f"{target[0]}.{target[1]} is wired to GPIO{other_gpio}, "
                              f"but {symbol} = {gpio}")
    owners: dict[int, list[str]] = {}
    for symbol in EXPECTED:
        if defaults.get(symbol, -1) >= 0:
            owners.setdefault(defaults[symbol], []).append(symbol)

    # No stray, internal, front-end-module or strapping GPIOs.
    for gpio, ends in sorted(wired.items()):
        who = ", ".join(owners.get(gpio, [])) or "no Kconfig pin"
        if gpio not in claimed:
            errors.append(f"GPIO{gpio} is wired in the diagram but no Kconfig pin uses it")
        if gpio in STRAPPING_FORBIDDEN:
            errors.append(f"GPIO{gpio} ({who}) is a boot strapping pin and must not be wired")
        if gpio in V4_GNSS:
            errors.append(f"GPIO{gpio} ({who}) is the {V4_GNSS[gpio]}: the GNSS module keeps "
                          "it, wire nothing else to it")
        elif gpio in SHARED:
            allowed, why = SHARED[gpio]
            wrong = [s for s in owners.get(gpio, []) if s not in allowed]
            if wrong:
                errors.append(f"GPIO{gpio} ({', '.join(wrong)}) is {why} "
                              f"(allowed: {', '.join(sorted(allowed))})")
        elif gpio in internal and gpio not in SHARED_BUS:
            errors.append(f"GPIO{gpio} ({who}) is board-internal (Kconfig.projbuild) "
                          "and must not be wired")
        if gpio in V4_RESERVED:
            errors.append(f"GPIO{gpio} ({who}) is the {V4_RESERVED[gpio]} and must not "
                          "be wired on a Heltec V4")
        if gpio not in SHARED_BUS and len(ends) > 1:
            errors.append(f"GPIO{gpio} is wired to more than one place: {sorted(ends)}")
    # The GNSS pins are the connector's, as Heltec wires it.
    for symbol, gpio in (("ATALAIA_GNSS_PWR_PIN", 34), ("ATALAIA_GNSS_TX_PIN", 38),
                         ("ATALAIA_GNSS_RX_PIN", 39), ("ATALAIA_GNSS_WAKE_PIN", 40),
                         ("ATALAIA_GNSS_PPS_PIN", 41), ("ATALAIA_GNSS_RST_PIN", 42)):
        if defaults.get(symbol) not in (gpio, -1):
            errors.append(f"Kconfig: {symbol} = {defaults.get(symbol)}, but the Heltec V4 "
                          f"wires that line of its GNSS connector to GPIO {gpio}")
    # The optional buzzer (not in the diagrams) has a pin of its own: no other part's default.
    buzzer = defaults.get("ATALAIA_BUZZER_PIN")
    if buzzer is None:
        errors.append("Kconfig: ATALAIA_BUZZER_PIN has no numeric default")
    else:
        for symbol, gpio in sorted(defaults.items()):
            if (symbol != "ATALAIA_BUZZER_PIN" and symbol.endswith("_PIN") and gpio == buzzer
                    and buzzer >= 0 and frozenset({symbol, "ATALAIA_BUZZER_PIN"}) not in EXCLUSIVE):
                errors.append(f"Kconfig: ATALAIA_BUZZER_PIN = {buzzer}, the default of {symbol} too")
        if buzzer in internal or buzzer in V4_GNSS or buzzer in V4_RESERVED or buzzer in SHARED:
            errors.append(f"Kconfig: ATALAIA_BUZZER_PIN = {buzzer}, a pin the board or another "
                          "part keeps")
        elif buzzer in STRAPPING_FORBIDDEN and buzzer not in STRAP_TOLERANT:
            errors.append(f"Kconfig: ATALAIA_BUZZER_PIN = {buzzer}, a boot strapping pin")
    errors += check_simple_outputs(kconfig_text, internal)
    for label in board_labels:
        m = re.fullmatch(r"GPIO(\d+)", label)
        if m and int(m.group(1)) not in wired:
            errors.append(f"BOARD lists GPIO{m.group(1)} but nothing is wired to it")
    for a, b in (("ATALAIA_NFC_SDA_PIN", "ATALAIA_BATT_SDA_PIN"),
                 ("ATALAIA_NFC_SCL_PIN", "ATALAIA_BATT_SCL_PIN")):
        if defaults.get(a) != defaults.get(b):
            errors.append(f"Kconfig: {a} and {b} differ, but the NFC reader and the gauge share "
                          "one I2C bus (hal_esp_i2c.c)")

    # The I2C devices are on the bus.
    for device, (sda, scl) in I2C_DEVICES.items():
        if not connected(links, ("HUB", sda), (device, "SDA")):
            errors.append(f"{device}.SDA is not wired to HUB.{sda}")
        if not connected(links, ("HUB", scl), (device, "SCL")):
            errors.append(f"{device}.SCL is not wired to HUB.{scl}")

    # Keypad on the expander, as the driver scans it.
    for key_pin, pcf_pin in KEYPAD_ON_PCF.items():
        if not connected(links, ("KEYPAD", key_pin), ("PCF8574", pcf_pin)):
            errors.append(f"KEYPAD.{key_pin} must go to PCF8574.{pcf_pin} (hal_esp_keypad.c)")
    p7 = defaults.get("ATALAIA_KP_P7_BUTTON", 0)
    for n in range(1, 5):
        on_p7 = connected(links, (f"BTN{n}", "N/O"), ("PCF8574", "P7"))
        if n == p7 and not on_p7:
            errors.append(f"ATALAIA_KP_P7_BUTTON = {p7}: BTN{n}.N/O must go to PCF8574.P7")
        elif n != p7 and on_p7:
            errors.append(f"BTN{n}.N/O is wired to PCF8574.P7, but ATALAIA_KP_P7_BUTTON = {p7}")
        if n == p7 and defaults.get(f"ATALAIA_BTN{n}_PIN", -1) >= 0:
            errors.append(f"ATALAIA_KP_P7_BUTTON = {p7}, but ATALAIA_BTN{n}_PIN is a GPIO too "
                          "(hal_esp_buttons.c refuses to build)")
    address = defaults.get("ATALAIA_KP_I2C_ADDR")
    if address is None or not re.search(rf"\b0x{address:02x}\b", pcf_text, re.IGNORECASE):
        errors.append("PCF8574 subtype must give the Kconfig address (ATALAIA_KP_I2C_ADDR = "
                      f"{'none' if address is None else hex(address)})")
    if defaults.get("ATALAIA_KP_INT_PIN", -1) < 0:
        for a, b in links:
            if ("PCF8574", "INT") in (a, b):
                errors.append("PCF8574.INT is wired, but ATALAIA_KP_INT_PIN = -1 (polling)")

    if readme_path is not None:
        errors += check_readme(readme_path.read_text(encoding="utf-8"), defaults)
    return errors, warnings


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--diagram", type=Path, action="append",
                        help="WireViz source (repeatable; default: the Field Box diagrams)")
    parser.add_argument("--kconfig", type=Path, default=KCONFIG)
    parser.add_argument("--readme", type=Path, default=README)
    parser.add_argument("--no-render-check", action="store_true",
                        help="skip the check that the SVG/PNG match their source")
    parser.add_argument("--resolve", type=Path, metavar="FILE",
                        help="print FILE with its GPIO<SYMBOL> placeholders filled in, and exit")
    args = parser.parse_args(argv)
    defaults = read_kconfig_defaults(args.kconfig.read_text(encoding="utf-8"))
    if args.resolve:
        resolved, errors = resolve(args.resolve.read_text(encoding="utf-8"), defaults)
        for error in errors:
            print(f"check_wiring: {args.resolve.name}: {error}", file=sys.stderr)
        if errors:
            return 1
        sys.stdout.write(resolved)
        return 0
    errors, warnings = check(args.diagram or DIAGRAMS, args.kconfig, args.readme,
                             render_check=not args.no_render_check)
    errors += check_guides(args.kconfig)
    for warning in warnings:
        print(f"check_wiring: warning: {warning}", file=sys.stderr)
    for error in errors:
        print(f"check_wiring: {error}", file=sys.stderr)
    if errors:
        print(f"check_wiring: {len(errors)} problem(s)", file=sys.stderr)
        return 1
    print("check_wiring: the wiring diagrams, the pin tables (Field Box, build guides, the "
          "expansion port, the output module, project page) and the Kconfig defaults agree")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
