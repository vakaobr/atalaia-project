/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Declarative screen templates on the Field Box (ADR-P3-4): the LVGL
 * renderer for the YAML templates of the running mode. The core parses them
 * (atalaia/screen_template.h); this file builds LVGL widgets from the parsed
 * tree once and then patches the data in, only into widgets that changed.
 * screen_renderer.c calls it first and falls back to its C screens when the
 * mode has no template of that name.
 *
 * Which templates apply: those of the running mode (and of its modifiers,
 * main mode first), built into the image from modes/<mode>/assets/screens/
 * (builtin_screens.h). The node runner announces the mode with a "@mode"
 * screen message (screen_template_set_mode), in order with the screens,
 * so the LVGL task always draws with the right mode.
 *
 * A built-in mode's templates come from the image only (decision K10); a mode
 * package the box fetched and checked for a game (phase 5 plan phase 13,
 * mode_store.h) brings its own, read from LittleFS through the function the
 * shell sets with screen_template_set_fetched.
 */
#ifndef ATALAIA_FW_SCREEN_TEMPLATE_H
#define ATALAIA_FW_SCREEN_TEMPLATE_H

#include <stdbool.h>

#include "builtin_screens.h"

/* The template name of the mode message (internal to the shell and the renderer). */
#define SCREEN_MODE_MESSAGE "@mode"

/*
 * Data of a SCREEN_MODE_MESSAGE: "<mode id> <params JSON>" (mode ids have
 * no spaces). An empty mode id means no templates (only the C screens).
 */
void screen_template_set_mode(const char *data);

/* The running mode's id ("" when none) and its parameters as JSON ("{}"). */
const char *screen_template_mode(void);
const char *screen_template_params(void);

/* The running mode's template of this name, or NULL. */
const builtin_screen_t *screen_template_find(const char *name);

/* Where a fetched mode part's templates are found (part: n bytes of the "a+b" mode id); the
 * shell sets mode_store_screen. NULL (the default): only the image's. */
typedef const builtin_screen_t *(*screen_template_fetched_fn)(const char *part, size_t n,
                                                              const char *name);
void screen_template_set_fetched(screen_template_fetched_fn fn);

/* Forgets the mode and the widgets (tests). */
void screen_template_reset(void);

/*
 * The Field Box's fonts are Montserrat with ASCII and the letters of
 * Portuguese (main/fonts, decision BN-14), so a label's text is folded in
 * place before it is drawn: those letters, ª º ° · and the bullet stay
 * ("Lê a tua etiqueta"), other accented Latin letters lose the accent
 * ("Ñ" -> "N"), dashes, quotes and the ellipsis become their ASCII forms,
 * LVGL's own symbols stay, and anything else becomes '?'. The text never
 * gets longer.
 * Phones draw the same templates with every character (app/lib/ui/template/).
 */
void screen_template_fold_text(char *s);

#if ATALAIA_SCREEN_LVGL
#include "lvgl.h"

/*
 * Builds the template's widgets on scr (already cleaned) and draws data.
 * Returns false (and builds nothing) if the template does not parse; the
 * caller then falls back to its C screen.
 */
bool screen_template_build(lv_obj_t *scr, const builtin_screen_t *s, const char *data_json);

/* Patches new data into the widgets built last. */
void screen_template_update(const char *data_json);

/* The screen was cleaned: the widgets built last are gone. */
void screen_template_forget(void);

/* Test inspection: widgets on screen (0 when a C screen is shown), widgets the
 * last build or update changed, and a widget by its id. */
int screen_template_widget_count(void);
int screen_template_changed(void);
lv_obj_t *screen_template_widget(const char *id);
const char *screen_template_last_error(void);
#endif

#endif /* ATALAIA_FW_SCREEN_TEMPLATE_H */
