/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Declarative screen templates (ADR-P3-4, modes/README.md "Screens").
 *
 * A mode ships its screens as YAML files in assets/screens/<name>.yaml.
 * When the script calls ui.screen(name, data), a renderer that has the
 * template builds its widgets once and then patches the data in; without
 * one it falls back to its built-in screens. This module is the
 * platform-free half: a parser for the small YAML subset the templates use
 * (block mappings and sequences, one-line flow mappings, plain and quoted
 * scalars, comments; no anchors, tags, block scalars, flow sequences or
 * multiple documents), the checks on the template itself, and the
 * expressions inside {braces}. The ESP32's LVGL renderer
 * (firmware/esp32/main/screen_template.c) and the simulator's checker
 * (simulator/atalaia_sim/screens.py) follow the same rules.
 *
 *   template: countdown
 *   style: { background: "#101418" }      optional: the screen's background
 *   layout:
 *     - type: label
 *       text: "{left|clock}"
 *       style: { font_size: 48, color: "{left <= 10 && 'danger' || 'white'}" }
 *     - type: progress_bar
 *       value: "{left / params.fuse_s}"
 *       style: { width: 240, height: 10, color: team }
 *
 * Widgets: label (text), progress_bar (value 0-1), icon (icon), qr_code
 * (data), spacer (height), row and column (children). Style: font_size,
 * align, color, background, padding, width, height (pixels or "fill"),
 * visible. See modes/README.md for every property.
 *
 * Expressions: numbers, 'text', names from the screen's data (dots reach
 * into objects; params.<name> reads the game's parameters), + - * /,
 * comparisons (< <= > >= == !=), ! && || and parentheses. && and || give
 * the deciding operand, as in Lua. A missing name is nil (0 in arithmetic,
 * "" in text, false in tests); division by zero gives 0. In text, {expr}
 * may end with a filter: |clock (seconds as M:SS or H:MM:SS), |upper,
 * |int. {{ and }} are literal braces.
 *
 * Nothing here allocates: a template lives in its atalaia_tpl_t.
 */
#ifndef ATALAIA_SCREEN_TEMPLATE_H
#define ATALAIA_SCREEN_TEMPLATE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define ATALAIA_TPL_SOURCE_MAX  4096 /* bytes of YAML */
#define ATALAIA_TPL_WIDGETS_MAX 32
#define ATALAIA_TPL_YAML_MAX    192  /* YAML nodes while parsing */
#define ATALAIA_TPL_POOL_MAX    3072 /* the texts, every language's (P5H-12) */
#define ATALAIA_TPL_NAME_MAX    31
#define ATALAIA_TPL_DEPTH_MAX   4   /* rows and columns inside each other */
#define ATALAIA_TPL_TEXT_MAX    160 /* a widget's text after interpolation, NUL included */

/* Widget sizes besides pixels. */
#define ATALAIA_TPL_AUTO (-1) /* fit the content */
#define ATALAIA_TPL_FILL (-2) /* take the room left in the parent */

typedef enum {
    ATALAIA_TPL_LABEL = 1,
    ATALAIA_TPL_PROGRESS_BAR,
    ATALAIA_TPL_ICON,
    ATALAIA_TPL_QR_CODE,
    ATALAIA_TPL_SPACER,
    ATALAIA_TPL_ROW,
    ATALAIA_TPL_COLUMN,
} atalaia_tpl_type_t;

typedef enum {
    ATALAIA_TPL_ALIGN_DEFAULT = 0, /* centre */
    ATALAIA_TPL_ALIGN_LEFT,
    ATALAIA_TPL_ALIGN_CENTER,
    ATALAIA_TPL_ALIGN_RIGHT,
} atalaia_tpl_align_t;

/* Strings are offsets into the template's pool; 0 means "not set". */
typedef struct {
    uint8_t type;      /* atalaia_tpl_type_t */
    uint8_t align;     /* atalaia_tpl_align_t */
    int8_t parent;     /* index of the row or column it is in; -1 for the screen */
    uint8_t depth;     /* 0 on the screen */
    int16_t font_size; /* 0: the renderer's default */
    int16_t width;     /* pixels, ATALAIA_TPL_AUTO or ATALAIA_TPL_FILL */
    int16_t height;    /* pixels, ATALAIA_TPL_AUTO or ATALAIA_TPL_FILL */
    int16_t pad[4];    /* top, right, bottom, left */
    uint16_t id;       /* the template's id for the widget */
    uint16_t content;  /* label text, progress value, icon name or QR data */
    uint16_t color;    /* "team", "contrast", a colour name, #RRGGBB or {expr} */
    uint16_t background;
    uint16_t visible; /* "{expr}" or "false"; 0: always visible */
} atalaia_tpl_widget_t;

/* A YAML node while parsing (kept here so parsing needs no stack or heap). */
typedef struct {
    uint8_t kind;  /* scalar, mapping, sequence */
    uint8_t style; /* plain, single- or double-quoted, null */
    uint16_t line;
    uint16_t key;     /* source offset of the key (in a mapping) */
    uint8_t key_len;  /* 0: no key */
    uint16_t val;     /* source offset of a scalar */
    uint16_t val_len; /* its length in the source, quotes included */
    int16_t child;    /* first entry of a mapping or sequence; -1 none */
    int16_t next;     /* next entry in the parent; -1 none */
} atalaia_tpl_yaml_t;

typedef struct {
    uint16_t name;       /* the template: field */
    uint16_t background; /* the screen's background, or 0 */
    uint8_t count;       /* widgets, parents before their children */
    atalaia_tpl_widget_t w[ATALAIA_TPL_WIDGETS_MAX];
    uint16_t pool_used;
    char pool[ATALAIA_TPL_POOL_MAX];
    /* Parsing scratch. */
    uint16_t yaml_count;
    atalaia_tpl_yaml_t yaml[ATALAIA_TPL_YAML_MAX];
} atalaia_tpl_t;

/*
 * Parses and checks a template. On failure returns false and writes
 * "line N: why" into err (when err is not NULL); *t is then unusable.
 */
bool atalaia_tpl_parse(atalaia_tpl_t *t, const char *src, size_t len, char *err, size_t err_cap);

/* sizeof(atalaia_tpl_t), for hosts that allocate one through an FFI (the simulator, Dart). */
size_t atalaia_tpl_sizeof(void);

/* A string of the template, or NULL for offset 0. */
const char *atalaia_tpl_str(const atalaia_tpl_t *t, uint16_t off);

/* The name of a widget type ("label", ...), or "?". */
const char *atalaia_tpl_type_name(uint8_t type);

/* What expressions read: the screen's data and the game's parameters (JSON objects; NULL = {}). */
typedef struct {
    const char *data;
    const char *params;
} atalaia_tpl_scope_t;

/*
 * Text with {expressions} replaced (a label's text, a QR code's data).
 * Returns the length written to out (always NUL-terminated, cut to fit).
 */
size_t atalaia_tpl_text(const char *text, const atalaia_tpl_scope_t *scope, char *out, size_t cap);

/* A visible: property: NULL or "true" is true, "false" false, "{expr}" its truth. */
bool atalaia_tpl_truthy(const char *value, const atalaia_tpl_scope_t *scope);

/* A progress_bar value: a number literal or "{expr}", clamped to 0-1. */
double atalaia_tpl_fraction(const char *value, const atalaia_tpl_scope_t *scope);

/*
 * A colour: "#RRGGBB", a palette name (see modes/README.md), or a team
 * name with a colour. Returns false for anything else (an unknown team).
 * The renderer resolves "team", "contrast" and {expr} first.
 */
bool atalaia_tpl_color(const char *name, uint32_t *rgb);

/* Checks one expression (without braces). err gets the reason. */
bool atalaia_tpl_expr_ok(const char *expr, size_t len, char *err, size_t err_cap);

#endif /* ATALAIA_SCREEN_TEMPLATE_H */
