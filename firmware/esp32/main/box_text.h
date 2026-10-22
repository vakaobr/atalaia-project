/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The box's own screen texts in the field's language (decision BN-14): English,
 * European Portuguese and German (P5H-4), one static table, looked up by id.
 * The language is the joined game's (join payload key 15, protocol/join.md);
 * between games, the last game's (kept in NVS by box_game.c), or English.
 *
 * Mode templates (modes/<mode>/assets/screens/, YAML) get the language as
 * "lang" in their data ("en", "pt" or "de") when a game gave one and the mode
 * does not set it, so a template can show its texts in that language
 * (screen_renderer.c); the built-in templates have no German and show English
 * for it ("{lang == 'pt' && ... || ...}", modes/README.md).
 *
 * Plain C, no LVGL: the renderer, the OLED view, the game and the lobby use it,
 * on the device and in the host tests. Set from the game task, read from the
 * display task: one int, written whole.
 */
#ifndef ATALAIA_BOX_TEXT_H
#define ATALAIA_BOX_TEXT_H

#include <stdbool.h>

typedef enum {
    BOX_LANG_EN = 0,
    BOX_LANG_PT = 1,
    BOX_LANG_DE = 2,
    BOX_LANG_COUNT,
} box_lang_t;

void box_lang_set(box_lang_t lang);
box_lang_t box_lang(void);

/* The language a game gave (join key 15, kept between games): "" or NULL when none did, so the
 * box's texts are English and the modes' templates keep their own default (box_lang_given()
 * false). */
void box_lang_set_code(const char *code);
bool box_lang_given(void);

/* "pt" or "pt-..." is Portuguese, "de" or "de-..." German; anything else (NULL, "", "en",
 * "fr") English. */
box_lang_t box_lang_from_code(const char *code);
const char *box_lang_code(box_lang_t lang); /* "en", "pt", "de" */

typedef enum {
    /* The Bomb's standby (no YAML of its own) */
    TX_READY_UP, /* header: the box is ready (the bomb is not armed) */
    TX_HOLD_TO_ARM,
    TX_WAITING,
    TX_BOMB_NOT_ARMED,
    /* countdown, results, game over, pause */
    TX_ARMED_UP,
    TX_UNTIL_DETONATION,
    TX_ARMED_BY,  /* %s: the team */
    TX_TEAM_WINS, /* %s: the team */
    TX_DEFUSED_UP,
    TX_EXPLODED_UP,
    TX_GAME_OVER_UP,
    TX_SCORES_FINAL,
    TX_ZONE_HELD_BY,
    TX_NO_TEAM_HELD,
    TX_PAUSED_UP,
    TX_WAIT_GM,
    /* a zone: neutral and held (decision BN-11) */
    TX_ZONE_UP,
    TX_NEUTRAL_UP,
    TX_HOLD_TO_CAPTURE,
    TX_HOLD_FOR_S, /* %ld: seconds */
    TX_TO_CAPTURE, /* the same without the seconds ("" in English: nothing more to say) */
    TX_NOBODY_HOLDS,
    TX_ZONE_HELD_UP,
    TX_HOLD_TO_TAKE_OVER,
    TX_HELD_SINCE, /* %s: the time */
    /* joined, waiting for the start; a game on; ready for the next game (BN-10, BN-12, BN-13) */
    TX_WAITING_UP,
    TX_GAME_N, /* %u: the game id */
    TX_NOT_STARTED,
    TX_INVITED_AS, /* %s: the role */
    TX_JOINED_AS,  /* %s: the role */
    TX_GAME_ON_UP,
    TX_NEXT_GAME,
    TX_KEY_FOR_PICKER,
    /* status rows */
    TX_ROW_GAME,
    TX_ROW_CODE,
    TX_ROW_ID,
    TX_ROW_PAIRING,
    TX_ROW_FIELD,
    TX_ROW_KEY,
    TX_ROW_TIMER,
    TX_ROW_BATTERY,
    TX_ROW_FIRMWARE,
    TX_STATUS_UP,
    /* the shell's screens */
    TX_GAME_MASTER_UP,
    TX_ENTER_ADMIN_PIN,
    TX_WRONG_PIN_AGAIN,
    TX_KEYS_ENTER_DELETE,
    TX_CODE_UP,
    TX_CHOOSE_GAME_UP,
    TX_NO_GAMES,
    TX_KEYS_CHOOSE,
    TX_KEYS_CHOOSE_PAGES,
    TX_GAME_TIMER_UP,
    TX_KEYS_TIMER,
    TX_THEN_GAME_ENDS,
    TX_GM_ENDS_IT,
    TX_START_GAME_UP,
    TX_GAME,
    TX_TIMER_IS, /* %s: the time */
    TX_KEYS_START,
    TX_FIRST_SETUP_UP,
    TX_JOIN_WIFI,
    TX_THEN_OPEN,
    TX_PHONES_OPEN,
    TX_NO_LIMIT,
    /* adoption and pairing (status titles, the PIN prompt) */
    TX_ADOPTED,
    TX_ALREADY_ADOPTED,
    TX_WRONG_PIN,
    TX_ADOPTION_LOCKED,
    TX_GAME_JOINED,
    TX_NOT_ADOPTED,
    TX_BAD_FIELD_CARD,
    TX_NOT_STORED,
    TX_ADMIN_PIN_NEEDED,
    TX_ADOPTION,
    TX_PIN_TO_CHANGE_FIELD,
    TX_FIELD_NONE,
    TX_PAIR_THIS_BOX,
    TX_PAIR_LOCKED,
    TX_RESTART_THE_BOX,
    TX_PAIR_PAUSED,
    TX_FOR_ONE_MINUTE,
    TX_TRY_AGAIN,
    /* firmware updates (fw_update_esp.c) */
    TX_UPDATING,
    TX_RESTARTING,
    TX_UPDATE_FAILED,
    TX_UPDATE_REFUSED,
    /* mode packages fetched for a game (mode_fetch.h) */
    TX_MODES_FETCHING,
    TX_MODES_FAILED,
    TX_PIN_LOCKED,    /* the admin PIN's wait (decision AD-28) */
    TX_TRY_IN_MIN,    /* "%lu": minutes */
    TX_NO_ADMIN_PIN,  /* a Field Box with no admin PIN set (AD-29) */
    TX_SET_ADMIN_PIN, /* how to set one */
    /* the on-board OLED (16 characters a line) */
    TXO_ADMIN_PIN,
    TXO_WRONG_PIN,
    TXO_ENTER_DELETE,
    TXO_GAMES,
    TXO_NO_GAMES,
    TXO_PICK_PAGES,
    TXO_PICK,
    TXO_GAME_TIME,
    TXO_TIMER_KEYS,
    TXO_START_Q,
    TXO_START_BACK,
    TXO_CONSOLE_ADOPT,
    TXO_WIFI_SETUP,
    TXO_OPEN_PORTAL,
    TXO_ARMING,
    TXO_HOLD_TO_ARM, /* %s: the team */
    TXO_WAIT_GM,
    TXO_DEFUSE,
    TXO_KEY_PICKER,
    TXO_NOT_STARTED,
    TXO_HOLD_TO_CAPTURE,
    TXO_PIN_LOCKED,
    TXO_AGAIN_IN_MIN, /* "%lu": minutes */
    TXO_NO_PIN,
    TXO_SET_PIN,
    TX_COUNT,
} box_text_id_t;

/* The text for id in the current language (never NULL). */
const char *box_text(box_text_id_t id);

/* The same in a given language (the tests). */
const char *box_text_in(box_lang_t lang, box_text_id_t id);

#endif /* ATALAIA_BOX_TEXT_H */
