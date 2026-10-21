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
  (its module keeps those pins: decision PIN-1) or a boot strapping pin; or a
  board pin the Field Box shares on purpose (GPIO 1, 35, 44: SHARED below) is
  used for anything else than what it is shared for;
- the keypad is not on the PCF8574 the way hal_esp_keypad.c scans it (rows on
  P0-P3, columns on P4-P6), the team button of ATALAIA_KP_P7_BUTTON is not on
  its P7, the expander address differs from the Kconfig default, or its INT
  pin is wired while the firmware polls;
- the pin table in hardware/field-box/README.md disagrees with Kconfig;
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
    1: ({"ATALAIA_DISP_CS_PIN", "ATALAIA_DISP_DC_PIN", "ATALAIA_DISP_RST_PIN"},
        "the battery-voltage ADC input, 100 kohm to GND: a low-speed output only"),
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


def read_kconfig_defaults(text: str) -> dict[str, int]:
    """Returns the default of every numeric `config` symbol.

    Handles conditional defaults (`default 6 if SYM`, the first true one wins)
    and choices (`default SYM` selects that choice member).
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
    for warning in warnings:
        print(f"check_wiring: warning: {warning}", file=sys.stderr)
    for error in errors:
        print(f"check_wiring: {error}", file=sys.stderr)
    if errors:
        print(f"check_wiring: {len(errors)} problem(s)", file=sys.stderr)
        return 1
    print("check_wiring: the wiring diagrams, the Field Box pin table and the Kconfig defaults agree")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
