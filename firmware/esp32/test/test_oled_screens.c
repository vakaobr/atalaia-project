/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Reference-image tests for the on-board OLED's status view (oled_view.h)
 * and the USB radio modem's screens (modem_screen.h, the modem_* cases).
 * Each case draws one screen through the real LVGL 9.2.2 build on a
 * headless 128x64 display, packs it to one bit per pixel as the device does
 * (oled_pack), writes the result to <build>/screens/oled/ and compares it
 * with firmware/esp32/test/screens/oled/<name>.png.
 *
 * ATALAIA_UPDATE_SCREENS=1 rewrites the references, as for test_screens.c.
 * A case whose name ends in "_pt" is drawn in Portuguese, "_de" in German,
 * "_zh-tw" in Traditional Chinese (box_text.h), as there; and every letter of
 * every label must be in its own font (font_check.h).
 */
#define _POSIX_C_SOURCE 200809L

#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include "box_text.h"
#include "font_check.h"
#include "lvgl.h"
#include "modem/modem_screen.h"
#include "oled_view.h"
#include "png_io.h"

#define W HAL_OLED_WIDTH
#define H HAL_OLED_HEIGHT
/* The hold bar's inside (oled_view.c: 48 pixels less its border and padding). */
#define HOLD_INNER_W 42

typedef struct {
    const char *name; /* PNG file name without .png */
    const char *mode; /* the "@mode" message before it, or NULL */
    const char *template_name;
    const char *data;
} oled_case_t;

#define BOMB     "org.atalaia.bomb {\"attackers\":\"red\",\"defenders\":\"blue\",\"fuse_s\":300}"
#define DOM      "org.atalaia.domination {\"capture_hold_ms\":3000}"
#define MEDIC    "org.atalaia.medic {\"heal_hold_s\":10,\"charges\":5,\"lang\":\"en\"}"
#define MEDIC_DE "org.atalaia.medic {\"heal_hold_s\":10,\"charges\":5,\"lang\":\"de\"}"
#define MEDIC_ZH "org.atalaia.medic {\"heal_hold_s\":10,\"charges\":5,\"lang\":\"zh-tw\"}"
#define MONEY    "org.atalaia.money_factory {\"capacity\":50,\"capture_hold_ms\":3000}"
#define PROG     "org.atalaia.progressive_domination {\"capture_hold_ms\":3000,\"complete_min\":10}"
#define SAB      "org.atalaia.sabotage {\"attackers\":\"red\",\"defenders\":\"blue\",\"fuse_s\":300}"
#define KILL     "org.atalaia.kill_confirmed {\"turn_in_s\":20}"
#define RESPAWN  "org.atalaia.respawn {\"lives\":20,\"per_player\":false}"
#define CHECKIN  "org.atalaia.player_checkin {\"points\":1}"
#define HACK     "org.atalaia.hacking_terminal {\"puzzle\":\"code\",\"digits\":4}"
#define MASTER   "org.atalaia.master_satellites {\"capture_hold_ms\":3000}"
#define CODES    "org.atalaia.codes {\"codes\":\"\"}"

/* The splashes are drawn by oled_view_splash(), not by a screen update; data is the firmware's
 * version (FV-8): a release, a development build, one with a three-digit count and changes. */
static const oled_case_t cases[] = {
    {"splash", NULL, NULL, "0.2.0"},
    {"splash_dev", NULL, NULL, "0.4.0-dev.12+gabc1234"},
    {"splash_dev_dirty", NULL, NULL, "0.4.0-dev.164+g8560d54.dirty"},
    {"pin_entry", NULL, "pin_entry", "{\"digits\":0,\"error\":false}"},
    {"pin_entry_typed", NULL, "pin_entry", "{\"digits\":3,\"error\":false}"},
    {"pin_entry_wrong", NULL, "pin_entry", "{\"digits\":0,\"error\":true}"},
    {"pin_entry_locked", NULL, "pin_entry", "{\"digits\":0,\"error\":false,\"locked_min\":60}"},
    {"pin_entry_locked_pt", NULL, "pin_entry", "{\"digits\":0,\"error\":false,\"locked_min\":60}"},
    {"pin_entry_no_pin", NULL, "pin_entry", "{\"digits\":0,\"error\":false,\"no_pin\":true}"},
    {"pin_entry_no_pin_pt", NULL, "pin_entry", "{\"digits\":0,\"error\":false,\"no_pin\":true}"},
    {"preset_select", NULL, "preset_select",
     "{\"presets\":[\"Bomb\",\"Domination\",\"Hold-All Domination\",\"Last Stand\",\"Codes\","
     "\"Kill Confirmed\",\"Respawn and Lives\",\"Player Check-in\",\"Medic Kit\"],"
     "\"selected\":3,\"page\":1,\"pages\":2}"},
    {"timer_adjust", NULL, "timer_adjust", "{\"timer_s\":600}"},
    {"start_confirm", NULL, "start_confirm", "{\"label\":\"Bomb\",\"timer_s\":600}"},
    {"start_confirm_setup", NULL, "start_confirm", "{\"setup\":true}"},
    {"start_confirm_adopt", NULL, "start_confirm", "{\"adopt\":true}"},
    {"status", NULL, "status", "{\"title\":\"Game on\",\"mode\":\"Bomb\",\"timer_s\":600}"},
    /* A game's life (decisions BN-10, BN-12, BN-13): invited or joined and waiting, started,
     * a zone nobody holds and one a team holds (BN-11), over, and ready for the next game. */
    {"waiting_invited", NULL, "waiting", "{\"game\":3073,\"role\":\"zone\",\"invited\":true}"},
    {"playing", DOM, "playing", "{\"game\":3073,\"role\":\"zone\"}"},
    {"neutral", DOM, "neutral", "{}"},
    {"captured", DOM, "captured", "{\"team\":\"red\",\"points\":12,\"since\":95}"},
    /* Another team holding its button: the bar, and that team below. */
    {"captured_taking", DOM, "captured",
     "{\"team\":\"red\",\"points\":12,\"since\":95,\"taker\":\"blue\",\"progress\":0.4}"},
    /* Domination sends no progress: the box's own bar from its held button (BN-26). A case
     * whose name ends in "_holding" is drawn while blue has held its button 1.5 s of the 3 s
     * capture hold. */
    {"neutral_holding", DOM, "neutral", "{}"},
    {"captured_holding", DOM, "captured", "{\"team\":\"red\",\"points\":12,\"since\":95}"},
    {"final_score", DOM, "final_score", "{\"owner\":\"red\",\"points\":12}"},
    {"ready_picker", NULL, "ready", "{\"picker\":true}"},
    {"waiting_invited_pt", NULL, "waiting", "{\"game\":3073,\"role\":\"zone\",\"invited\":true}"},
    {"playing_pt", DOM, "playing", "{\"game\":3073,\"role\":\"zone\"}"},
    {"neutral_pt", DOM, "neutral", "{}"},
    {"captured_pt", DOM, "captured", "{\"team\":\"red\",\"points\":12,\"since\":95}"},
    {"final_score_pt", DOM, "final_score", "{\"owner\":\"red\",\"points\":12}"},
    {"ready_picker_pt", NULL, "ready", "{\"picker\":true}"},
    {"standby_pt", BOMB, "standby", "{\"arm\":\"red\"}"},
    {"countdown_defusing_pt", BOMB, "countdown", "{\"left\":231,\"defuse\":0.4}"},
    {"pin_entry_wrong_pt", NULL, "pin_entry", "{\"digits\":0,\"error\":true}"},
    {"preset_select_pt", NULL, "preset_select",
     "{\"presets\":[\"Bomba\",\"Domínio\"],\"selected\":2,\"page\":1,\"pages\":2}"},
    {"start_confirm_pt", NULL, "start_confirm", "{\"label\":\"Bomba\",\"timer_s\":600}"},
    {"start_confirm_setup_pt", NULL, "start_confirm", "{\"setup\":true}"},
    {"start_confirm_adopt_pt", NULL, "start_confirm", "{\"adopt\":true}"},
    /* German (P5H-4). */
    {"pin_entry_locked_de", NULL, "pin_entry", "{\"digits\":0,\"error\":false,\"locked_min\":60}"},
    {"pin_entry_no_pin_de", NULL, "pin_entry", "{\"digits\":0,\"error\":false,\"no_pin\":true}"},
    {"pin_entry_wrong_de", NULL, "pin_entry", "{\"digits\":0,\"error\":true}"},
    {"waiting_invited_de", NULL, "waiting", "{\"game\":3073,\"role\":\"zone\",\"invited\":true}"},
    {"playing_de", DOM, "playing", "{\"game\":3073,\"role\":\"zone\"}"},
    {"neutral_de", DOM, "neutral", "{}"},
    {"captured_de", DOM, "captured", "{\"team\":\"red\",\"points\":12,\"since\":95}"},
    {"final_score_de", DOM, "final_score", "{\"owner\":\"red\",\"points\":12}"},
    {"ready_picker_de", NULL, "ready", "{\"picker\":true}"},
    {"standby_de", BOMB, "standby", "{\"arm\":\"red\"}"},
    {"standby_arming_de", BOMB, "standby", "{\"arm\":\"red\",\"progress\":0.6}"},
    {"countdown_defusing_de", BOMB, "countdown", "{\"left\":231,\"defuse\":0.4}"},
    {"preset_select_de", NULL, "preset_select",
     "{\"presets\":[\"Bombe\",\"Domination\"],\"selected\":2,\"page\":1,\"pages\":2}"},
    {"timer_adjust_de", NULL, "timer_adjust", "{\"timer_s\":600}"},
    {"start_confirm_de", NULL, "start_confirm", "{\"label\":\"Bombe\",\"timer_s\":600}"},
    {"start_confirm_setup_de", NULL, "start_confirm", "{\"setup\":true}"},
    {"start_confirm_adopt_de", NULL, "start_confirm", "{\"adopt\":true}"},
    /* Traditional Chinese (P5K-2): the box's preset names stay English (builtin_presets.c). */
    {"pin_entry_zh-tw", NULL, "pin_entry", "{\"digits\":2,\"error\":false}"},
    {"pin_entry_locked_zh-tw", NULL, "pin_entry",
     "{\"digits\":0,\"error\":false,\"locked_min\":60}"},
    {"pin_entry_no_pin_zh-tw", NULL, "pin_entry", "{\"digits\":0,\"error\":false,\"no_pin\":true}"},
    {"pin_entry_wrong_zh-tw", NULL, "pin_entry", "{\"digits\":0,\"error\":true}"},
    {"waiting_invited_zh-tw", NULL, "waiting",
     "{\"game\":3073,\"role\":\"zone\",\"invited\":true}"},
    {"playing_zh-tw", DOM, "playing", "{\"game\":3073,\"role\":\"zone\"}"},
    {"neutral_zh-tw", DOM, "neutral", "{}"},
    {"captured_zh-tw", DOM, "captured", "{\"team\":\"red\",\"points\":12,\"since\":95}"},
    {"final_score_zh-tw", DOM, "final_score", "{\"owner\":\"red\",\"points\":12}"},
    {"ready_picker_zh-tw", NULL, "ready", "{\"picker\":true}"},
    {"standby_zh-tw", BOMB, "standby", "{\"arm\":\"red\"}"},
    {"standby_arming_zh-tw", BOMB, "standby", "{\"arm\":\"red\",\"progress\":0.6}"},
    {"countdown_defusing_zh-tw", BOMB, "countdown", "{\"left\":231,\"defuse\":0.4}"},
    {"preset_select_zh-tw", NULL, "preset_select",
     "{\"presets\":[\"Bomb\",\"Domination\"],\"selected\":2,\"page\":1,\"pages\":2}"},
    {"preset_select_one_page_zh-tw", NULL, "preset_select",
     "{\"presets\":[\"Bomb\",\"Domination\"],\"selected\":1,\"page\":1,\"pages\":1}"},
    {"timer_adjust_zh-tw", NULL, "timer_adjust", "{\"timer_s\":600}"},
    {"start_confirm_zh-tw", NULL, "start_confirm", "{\"label\":\"Bomb\",\"timer_s\":600}"},
    {"start_confirm_setup_zh-tw", NULL, "start_confirm", "{\"setup\":true}"},
    {"start_confirm_adopt_zh-tw", NULL, "start_confirm", "{\"adopt\":true}"},
    {"wifi_setup_zh-tw", NULL, "wifi_setup", "{\"ssid\":\"atalaia-3F2A\"}"},
    {"paused_zh-tw", DOM, "paused", "{}"},
    {"status_pair_locked", NULL, "status",
     "{\"title\":\"Pair locked\",\"pairing\":\"restart the box\"}"},
    {"status_pair", NULL, "status",
     "{\"title\":\"Pair this box\",\"code\":\"042 137\",\"id\":\"b0c5\",\"field\":\"none\"}"},
    {"standby", BOMB, "standby", "{\"arm\":\"red\"}"},
    {"standby_arming", BOMB, "standby", "{\"arm\":\"red\",\"progress\":0.6}"},
    {"countdown", BOMB, "countdown", "{\"left\":299}"},
    {"countdown_defusing", BOMB, "countdown", "{\"left\":231,\"defuse\":0.4}"},
    {"defused", BOMB, "defused", "{\"team\":\"blue\"}"},
    {"exploded", BOMB, "exploded", "{\"team\":\"red\"}"},
    {"code_entry", BOMB, "code_entry",
     "{\"title\":\"DEFUSE\",\"digits\":2,\"left\":61,\"message\":\"Enter your team code\"}"},
    {"mode_template", MEDIC, "medic_refused",
     "{\"reason\":\"limit\",\"message\":\"Limit reached\",\"player\":\"r2\",\"team\":\"red\"}"},
    /* The modes' own screens on a German or Chinese box (P5H-12): the mode's words are the
     * TFT's; the OLED shows a countdown, a team or the script's message (the Medic Kit's
     * refusals are in the fonts, gen_box_fonts.py). */
    {"mode_template_de", MEDIC_DE, "medic_refused",
     "{\"reason\":\"limit\",\"message\":\"Du hast alle Behandlungen gehabt\"}"},
    {"mode_template_zh-tw", MEDIC_ZH, "medic_refused",
     "{\"reason\":\"limit\",\"message\":\"你的治療次數已用完\"}"},
    {"money_captured_de", MONEY, "captured", "{\"team\":\"red\",\"since\":95,\"stock\":35}"},
    {"money_captured_zh-tw", MONEY, "captured", "{\"team\":\"red\",\"since\":95,\"stock\":35}"},
    /* Progressive Domination: the OLED has no template of its own for a box that waits or is
     * completed (its screen's name, and the team); the active box is a free or held zone. */
    {"prog_inactive", PROG, "inactive", "{\"done\":1,\"of\":4}"},
    {"prog_neutral", PROG, "neutral", "{\"step\":2,\"of\":4,\"final\":false}"},
    {"prog_captured", PROG, "captured",
     "{\"team\":\"red\",\"since\":95,\"step\":2,\"of\":4,\"held_min\":1,\"points\":6}"},
    {"prog_completed", PROG, "completed", "{\"team\":\"blue\",\"step\":1,\"of\":4,\"done\":1}"},
    /* Sabotage: the standby with its score, the pause (a countdown) and the game's end (the
       winner). */
    {"sab_standby", SAB, "standby",
     "{\"arm\":\"red\",\"defend\":\"blue\",\"a_points\":2,\"d_points\":1,\"round\":4,\"game_left\":754}"},
    {"sab_pause", SAB, "pause",
     "{\"attackers\":\"red\",\"defenders\":\"blue\",\"a_points\":2,\"d_points\":1,\"left\":7,\"exploded\":true,\"game_left\":754}"},
    {"sab_game_over", SAB, "game_over",
     "{\"winner\":\"red\",\"attackers\":\"red\",\"defenders\":\"blue\",\"a_points\":3,\"d_points\":1}"},
    {"sab_standby_pt", SAB, "standby",
     "{\"arm\":\"red\",\"defend\":\"blue\",\"a_points\":2,\"d_points\":1,\"round\":4,\"game_left\":754}"},
    {"sab_pause_pt", SAB, "pause",
     "{\"attackers\":\"red\",\"defenders\":\"blue\",\"a_points\":2,\"d_points\":1,\"left\":7,\"exploded\":true,\"game_left\":754}"},
    {"sab_game_over_pt", SAB, "game_over",
     "{\"winner\":\"red\",\"attackers\":\"red\",\"defenders\":\"blue\",\"a_points\":3,\"d_points\":1}"},
    {"sab_standby_de", SAB, "standby",
     "{\"arm\":\"red\",\"defend\":\"blue\",\"a_points\":2,\"d_points\":1,\"round\":4,\"game_left\":754}"},
    {"sab_pause_de", SAB, "pause",
     "{\"attackers\":\"red\",\"defenders\":\"blue\",\"a_points\":2,\"d_points\":1,\"left\":7,\"exploded\":true,\"game_left\":754}"},
    {"sab_game_over_de", SAB, "game_over",
     "{\"winner\":\"red\",\"attackers\":\"red\",\"defenders\":\"blue\",\"a_points\":3,\"d_points\":1}"},
    {"sab_standby_zh-tw", SAB, "standby",
     "{\"arm\":\"red\",\"defend\":\"blue\",\"a_points\":2,\"d_points\":1,\"round\":4,\"game_left\":754}"},
    {"sab_pause_zh-tw", SAB, "pause",
     "{\"attackers\":\"red\",\"defenders\":\"blue\",\"a_points\":2,\"d_points\":1,\"left\":7,\"exploded\":true,\"game_left\":754}"},
    {"sab_game_over_zh-tw", SAB, "game_over",
     "{\"winner\":\"red\",\"attackers\":\"red\",\"defenders\":\"blue\",\"a_points\":3,\"d_points\":1}"},
    /* A built-in mode's end screens, its header and the keypad's titles in the box's language
     * (the template's name and the mode's were English whatever the language). */
    {"defused_pt", BOMB, "defused", "{\"team\":\"blue\"}"},
    {"exploded_pt", BOMB, "exploded", "{\"team\":\"red\"}"},
    {"code_entry_pt", BOMB, "code_entry", "{\"title\":\"ARM\",\"digits\":2}"},
    {"code_entry_defuse_pt", BOMB, "code_entry", "{\"title\":\"DEFUSE\",\"digits\":1,\"left\":61}"},
    {"code_entry_codes_pt", CODES, "code_entry", "{\"title\":\"CODE\",\"digits\":4}"},
    {"tags_pt", KILL, "tags", "{\"error\":false}"},
    {"respawn_pt", RESPAWN, "respawn", "{\"team\":\"blue\",\"lives\":17}"},
    {"checkin_pt", CHECKIN, "checkin", "{\"total\":5,\"team\":\"red\"}"},
    {"hack_solved_pt", HACK, "hack_solved", "{\"team\":\"red\"}"},
    {"master_status_pt", MASTER, "master_status", "{\"team\":\"red\",\"held\":2,\"of\":3}"},
    {"defused_de", BOMB, "defused", "{\"team\":\"blue\"}"},
    {"exploded_de", BOMB, "exploded", "{\"team\":\"red\"}"},
    {"code_entry_de", BOMB, "code_entry", "{\"title\":\"ARM\",\"digits\":2}"},
    {"code_entry_defuse_de", BOMB, "code_entry", "{\"title\":\"DEFUSE\",\"digits\":1,\"left\":61}"},
    {"code_entry_codes_de", CODES, "code_entry", "{\"title\":\"CODE\",\"digits\":4}"},
    {"tags_de", KILL, "tags", "{\"error\":false}"},
    {"respawn_de", RESPAWN, "respawn", "{\"team\":\"blue\",\"lives\":17}"},
    {"checkin_de", CHECKIN, "checkin", "{\"total\":5,\"team\":\"red\"}"},
    {"hack_solved_de", HACK, "hack_solved", "{\"team\":\"red\"}"},
    {"master_status_de", MASTER, "master_status", "{\"team\":\"red\",\"held\":2,\"of\":3}"},
    {"defused_zh-tw", BOMB, "defused", "{\"team\":\"blue\"}"},
    {"exploded_zh-tw", BOMB, "exploded", "{\"team\":\"red\"}"},
    {"code_entry_zh-tw", BOMB, "code_entry", "{\"title\":\"ARM\",\"digits\":2}"},
    {"code_entry_defuse_zh-tw", BOMB, "code_entry",
     "{\"title\":\"DEFUSE\",\"digits\":1,\"left\":61}"},
    {"code_entry_codes_zh-tw", CODES, "code_entry", "{\"title\":\"CODE\",\"digits\":4}"},
    {"tags_zh-tw", KILL, "tags", "{\"error\":false}"},
    {"respawn_zh-tw", RESPAWN, "respawn", "{\"team\":\"blue\",\"lives\":17}"},
    {"checkin_zh-tw", CHECKIN, "checkin", "{\"total\":5,\"team\":\"red\"}"},
    {"hack_solved_zh-tw", HACK, "hack_solved", "{\"team\":\"red\"}"},
    {"master_status_zh-tw", MASTER, "master_status", "{\"team\":\"red\",\"held\":2,\"of\":3}"},
    {"prog_inactive_pt", PROG, "inactive", "{\"done\":1,\"of\":4}"},
    {"prog_completed_pt", PROG, "completed", "{\"team\":\"blue\",\"step\":1,\"of\":4,\"done\":1}"},
    {"prog_inactive_de", PROG, "inactive", "{\"done\":1,\"of\":4}"},
    {"prog_completed_de", PROG, "completed", "{\"team\":\"blue\",\"step\":1,\"of\":4,\"done\":1}"},
    {"prog_inactive_zh-tw", PROG, "inactive", "{\"done\":1,\"of\":4}"},
    {"prog_completed_zh-tw", PROG, "completed",
     "{\"team\":\"blue\",\"step\":1,\"of\":4,\"done\":1}"},
    {"wifi_setup", NULL, "wifi_setup", "{\"ssid\":\"atalaia-7c4f\"}"},
};
#define CASE_COUNT ((int)(sizeof(cases) / sizeof(cases[0])))

/* The USB radio modem's screens: the modem_splash* cases are modem_screen_splash(); a case whose
 * name ends in "_pt", "_de" or "_zh-tw" is in that language (decision MOD-1). */
typedef struct {
    const char *name;
    const char *version; /* the splashes': the firmware's version; NULL a status screen */
    modem_screen_state_t state;
} modem_case_t;

#define MODEM_COUNTS .tx = 1234, .tx_fail = 3, .rx = 56789, .rx_auth_fail = 1
static const modem_case_t modem_cases[] = {
    {"modem_splash", "0.2.0", {0}},
    {"modem_splash_dev", "0.4.0-dev.12+gabc1234", {0}},
    {"modem_splash_dev_dirty", "0.4.0-dev.164+g8560d54.dirty", {0}},
    {"modem_waiting",
     NULL,
     {.link = MODEM_LINK_WAITING, .channel_hz = 869525000u, .radio_ok = true, .duty_ms = 360000}},
    {"modem_game",
     NULL,
     {.link = MODEM_LINK_UP,
      .configured = true,
      .game_id = 4660,
      .channel_hz = 869525000u,
      MODEM_COUNTS,
      .radio_ok = true,
      .duty_ms = 341200}},
    {"modem_link_down",
     NULL,
     {.link = MODEM_LINK_DOWN,
      .configured = true,
      .game_id = 4660,
      .channel_hz = 869525000u,
      MODEM_COUNTS,
      .radio_ok = true,
      .duty_ms = 341200}},
    {"modem_no_duty",
     NULL,
     {.link = MODEM_LINK_UP,
      .configured = true,
      .game_id = 4660,
      .channel_hz = 868100000u,
      MODEM_COUNTS,
      .radio_ok = true,
      .duty_ms = 0}},
    {"modem_radio_fault",
     NULL,
     {.link = MODEM_LINK_UP,
      .channel_hz = 869525000u,
      .radio_ok = false,
      .fault = "SX1262 errors 0x0020 (TCXO)"}},
    /* The same screens in the other languages (the state's lang is set from the name). */
    {"modem_splash_pt", "0.2.0", {0}},
    {"modem_splash_de", "0.2.0", {0}},
    {"modem_splash_zh-tw", "0.2.0", {0}},
    {"modem_splash_dev_zh-tw", "0.4.0-dev.12+gabc1234", {0}},
    {"modem_splash_dev_dirty_zh-tw", "0.4.0-dev.164+g8560d54.dirty", {0}},
    {"modem_waiting_pt",
     NULL,
     {.link = MODEM_LINK_WAITING, .channel_hz = 869525000u, .radio_ok = true, .duty_ms = 360000}},
    {"modem_game_pt",
     NULL,
     {.link = MODEM_LINK_UP,
      .configured = true,
      .game_id = 4660,
      .channel_hz = 869525000u,
      MODEM_COUNTS,
      .radio_ok = true,
      .duty_ms = 341200}},
    {"modem_link_down_pt",
     NULL,
     {.link = MODEM_LINK_DOWN,
      .configured = true,
      .game_id = 4660,
      .channel_hz = 869525000u,
      MODEM_COUNTS,
      .radio_ok = true,
      .duty_ms = 341200}},
    {"modem_radio_fault_pt",
     NULL,
     {.link = MODEM_LINK_UP,
      .channel_hz = 869525000u,
      .radio_ok = false,
      .fault = "SX1262 errors 0x0020 (TCXO)"}},
    {"modem_waiting_de",
     NULL,
     {.link = MODEM_LINK_WAITING, .channel_hz = 869525000u, .radio_ok = true, .duty_ms = 360000}},
    {"modem_game_de",
     NULL,
     {.link = MODEM_LINK_UP,
      .configured = true,
      .game_id = 4660,
      .channel_hz = 869525000u,
      MODEM_COUNTS,
      .radio_ok = true,
      .duty_ms = 341200}},
    {"modem_link_down_de",
     NULL,
     {.link = MODEM_LINK_DOWN,
      .measuring = true,
      .channel_hz = 869525000u,
      MODEM_COUNTS,
      .radio_ok = true,
      .duty_ms = 341200}},
    {"modem_radio_fault_de",
     NULL,
     {.link = MODEM_LINK_UP,
      .channel_hz = 869525000u,
      .radio_ok = false,
      .fault = "SX1262 errors 0x0020 (TCXO)"}},
    {"modem_waiting_zh-tw",
     NULL,
     {.link = MODEM_LINK_WAITING, .channel_hz = 869525000u, .radio_ok = true, .duty_ms = 360000}},
    {"modem_game_zh-tw",
     NULL,
     {.link = MODEM_LINK_UP,
      .configured = true,
      .game_id = 4660,
      .channel_hz = 869525000u,
      MODEM_COUNTS,
      .radio_ok = true,
      .duty_ms = 341200}},
    {"modem_link_down_zh-tw",
     NULL,
     {.link = MODEM_LINK_DOWN,
      .measuring = true,
      .channel_hz = 869525000u,
      MODEM_COUNTS,
      .radio_ok = true,
      .duty_ms = 341200}},
    {"modem_no_duty_zh-tw",
     NULL,
     {.link = MODEM_LINK_UP,
      .configured = true,
      .game_id = 4660,
      .channel_hz = 868100000u,
      MODEM_COUNTS,
      .radio_ok = true,
      .duty_ms = 0}},
    {"modem_radio_fault_zh-tw",
     NULL,
     {.link = MODEM_LINK_UP,
      .channel_hz = 869525000u,
      .radio_ok = false,
      .fault = "SX1262 errors 0x0020 (TCXO)"}},
};
#define MODEM_CASE_COUNT ((int)(sizeof(modem_cases) / sizeof(modem_cases[0])))

_Alignas(64) static uint8_t framebuffer[W * H * 2];
static lv_display_t *display;
static uint32_t fake_ms;
/* The game's clock (oled_view_set_game_clock): 3:50 into the game, so a zone taken at 1:35
 * ("since":95) has been held for 2:15. */
static uint32_t fake_game_ms = 230000;

static uint32_t game_clock(void)
{
    return fake_game_ms;
}
/* The box's team buttons (oled_view_set_hold_reader): none held unless a case says so. */
static oled_hold_t fake_holds[OLED_HOLDS_MAX];
static int fake_hold_count;

static int hold_reader(oled_hold_t *holds, int max)
{
    int n = fake_hold_count < max ? fake_hold_count : max;
    memcpy(holds, fake_holds, (size_t)n * sizeof(*holds));
    return n;
}

static void hold_button(const char *team, uint32_t ms)
{
    fake_hold_count = team ? 1 : 0;
    if (team) {
        snprintf(fake_holds[0].team, sizeof(fake_holds[0].team), "%s", team);
        fake_holds[0].ms = ms;
    }
}
static int failures;
static uint8_t rendered[W * H * 3];

static uint32_t tick_cb(void)
{
    return fake_ms;
}

static void flush_cb(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map)
{
    (void)area;
    (void)px_map;
    lv_display_flush_ready(disp);
}

static void fail(const char *name, const char *msg)
{
    fprintf(stderr, "FAIL oled %s: %s\n", name, msg);
    failures++;
}

static bool update_mode(void)
{
    const char *v = getenv("ATALAIA_UPDATE_SCREENS");
    return v && v[0] == '1';
}

/* What the panel shows: lit pixels white, the rest black. */
static void capture(lv_obj_t *scr)
{
    lv_obj_invalidate(scr);
    lv_refr_now(display);

    static uint8_t fb[HAL_OLED_FB_SIZE];
    oled_pack((const uint16_t *)framebuffer, fb);
    for (int y = 0; y < H; y++) {
        for (int x = 0; x < W; x++) {
            uint8_t v = (fb[(y / 8) * W + x] >> (y % 8)) & 1 ? 255 : 0;
            memset(&rendered[3 * (y * W + x)], v, 3);
        }
    }
}

/* Draws the case, then captures it. */
static void render(const oled_case_t *c)
{
    size_t n = strlen(c->name);
    const char *suffix = n > 3 ? c->name + n - 3 : "";
    bool zh = n > 6 && strcmp(c->name + n - 6, "_zh-tw") == 0;
    box_lang_set_code(zh                           ? "zh-tw"
                      : strcmp(suffix, "_pt") == 0 ? "pt"
                      : strcmp(suffix, "_de") == 0 ? "de"
                                                   : "");
    lv_obj_t *scr = lv_screen_active();
    fake_ms += 10000;
    if (!c->template_name) {
        oled_view_splash(scr, c->data, fake_ms, 0);
    } else {
        if (c->mode) oled_view_handle(scr, "@mode", c->mode, fake_ms);
        oled_view_handle(scr, c->template_name, c->data, fake_ms);
        if (n > 8 && strcmp(c->name + n - 8, "_holding") == 0) {
            hold_button("blue", 1500);
            oled_view_poll(scr, fake_ms);
            hold_button(NULL, 0);
        }
    }
    capture(scr);
}

/* The language a modem case is in, from its name's ending. */
static box_lang_t modem_case_lang(const modem_case_t *c)
{
    size_t n = strlen(c->name);
    if (n > 6 && strcmp(c->name + n - 6, "_zh-tw") == 0) return BOX_LANG_ZH_TW;
    if (n > 3 && strcmp(c->name + n - 3, "_pt") == 0) return BOX_LANG_PT;
    if (n > 3 && strcmp(c->name + n - 3, "_de") == 0) return BOX_LANG_DE;
    return BOX_LANG_EN;
}

static int32_t text_w(const char *s, const lv_font_t *font)
{
    return lv_text_get_width(s, (uint32_t)strlen(s), font, 0);
}

/* The 16-pixel rows' two texts and the header's two do not meet (modem_screen.c: 2 pixels in,
 * the right text 2 in from the edge; the bar's title starts at 14, its state ends 3 in). */
static void check_modem_rows(const modem_case_t *c, const modem_screen_text_t *t)
{
    extern const lv_font_t lv_font_atalaia_14;
    for (int i = 0; i < t->rows; i++) {
        if (!t->tall[i]) continue;
        if (2 + text_w(t->line[i], &lv_font_atalaia_14) + 4 +
                text_w(t->right[i], &lv_font_atalaia_14) + 2 >
            W)
            fail(c->name, "the two texts of a tall row meet");
    }
    /* The title (from 14) ends before the state, or before the bar's edge. */
    int32_t title_end = 14 + text_w(t->title, &lv_font_atalaia_14);
    int32_t limit =
        t->head_right[0] ? W - 3 - text_w(t->head_right, &lv_font_atalaia_14) - 4 : W - 2;
    if (title_end > limit) fail(c->name, "the header's title and the link state meet");
}

static void render_modem(const modem_case_t *c)
{
    lv_obj_t *scr = lv_screen_active();
    box_lang_t lang = modem_case_lang(c);
    if (c->version) {
        modem_screen_splash(scr, c->version, lang);
    } else {
        modem_screen_state_t state = c->state;
        state.lang = lang;
        modem_screen_text_t t;
        modem_screen_text(&state, &t);
        modem_screen_draw(scr, &t);
        check_modem_rows(c, &t);
    }
    capture(scr);
}

static void compare_with_reference(const char *name)
{
    char path[512];
    snprintf(path, sizeof(path), "%s/%s.png", OLED_OUT_DIR, name);
    if (!png_write_rgb(path, W, H, rendered)) fail(name, "cannot write the rendered PNG");

    snprintf(path, sizeof(path), "%s/%s.png", OLED_REF_DIR, name);
    if (update_mode()) {
        if (!png_write_rgb(path, W, H, rendered)) fail(name, "cannot update the reference");
        printf("updated %s\n", path);
        return;
    }
    int rw = 0, rh = 0;
    uint8_t *ref = png_read_rgb(path, &rw, &rh);
    if (!ref) {
        fail(name, "no reference PNG; run with ATALAIA_UPDATE_SCREENS=1 to create it");
        return;
    }
    if (rw != W || rh != H) {
        fail(name, "the reference PNG is not 128x64");
    } else if (memcmp(ref, rendered, sizeof(rendered)) != 0) {
        int diff = 0;
        for (int i = 0; i < W * H; i++) diff += memcmp(&ref[3 * i], &rendered[3 * i], 3) != 0;
        fprintf(stderr, "  %d pixels differ; rendered: %s/%s.png\n", diff, OLED_OUT_DIR, name);
        fail(name, "differs from its reference; if intended, run with ATALAIA_UPDATE_SCREENS=1");
    }
    png_free(ref);
}

/* Every reference PNG must belong to a case, so stale images do not linger. */
static void check_no_stale_references(void)
{
    DIR *dir = opendir(OLED_REF_DIR);
    if (!dir) {
        fail("(all)", "cannot open the reference folder " OLED_REF_DIR);
        return;
    }
    struct dirent *e;
    while ((e = readdir(dir)) != NULL) {
        size_t len = strlen(e->d_name);
        if (len < 5 || strcmp(e->d_name + len - 4, ".png") != 0) continue;
        bool known = false;
        for (int i = 0; i < CASE_COUNT; i++) {
            if (strlen(cases[i].name) == len - 4 && strncmp(cases[i].name, e->d_name, len - 4) == 0)
                known = true;
        }
        for (int i = 0; i < MODEM_CASE_COUNT; i++) {
            const char *n = modem_cases[i].name;
            if (strlen(n) == len - 4 && strncmp(n, e->d_name, len - 4) == 0) known = true;
        }
        if (!known) fail(e->d_name, "reference PNG without a test case; delete it or add a case");
    }
    closedir(dir);
}

/* The captured screen's held time follows the game's clock, once a second. */
static const char *foot_text(lv_obj_t *scr)
{
    return lv_label_get_text(
        lv_obj_get_child(scr, 2)); /* the header bar, the big line, the footer */
}

static void check_held_tick(void)
{
    box_lang_set_code("");
    lv_obj_t *scr = lv_screen_active();
    fake_game_ms = 230000;
    oled_view_handle(scr, "captured", "{\"team\":\"red\",\"points\":3,\"since\":95}", 1);
    if (strcmp(foot_text(scr), "held for 2:15") != 0)
        fail("captured", "the held time is not drawn");
    fake_game_ms = 230999;
    oled_view_poll(scr, 2);
    if (strcmp(foot_text(scr), "held for 2:15") != 0)
        fail("captured", "the held time changed within its second");
    fake_game_ms = 231000;
    oled_view_poll(scr, 3);
    if (strcmp(foot_text(scr), "held for 2:16") != 0)
        fail("captured", "the held time does not tick");
    fake_game_ms = 3600000 + 95000 + 5000;
    oled_view_poll(scr, 4);
    if (strcmp(foot_text(scr), "held for 1:00:05") != 0) fail("captured", "an hour's hold");
    /* While another team takes it, the taker stays; no tick. */
    oled_view_handle(scr, "captured",
                     "{\"team\":\"red\",\"since\":95,\"taker\":\"blue\",\"progress\":0.5}", 5);
    fake_game_ms += 1000;
    oled_view_poll(scr, 6);
    if (strcmp(foot_text(scr), "BLUE") != 0)
        fail("captured", "the taker gave way to the held time");
    /* Another screen: nothing ticks over it. */
    oled_view_handle(scr, "paused", "{}", 7);
    fake_game_ms += 1000;
    oled_view_poll(scr, 8);
    if (strcmp(foot_text(scr), box_text(TXO_WAIT_GM)) != 0)
        fail("paused", "the held time ticked over another screen");
    fake_game_ms = 230000;
    /* The longest held time, 9:59:59, fits the footer in every language (no "..."). */
    extern const lv_font_t lv_font_atalaia_14;
    for (int lang = 0; lang < BOX_LANG_COUNT; lang++) {
        char line[64];
        snprintf(line, sizeof(line), box_text_in((box_lang_t)lang, TXO_HELD_FOR), "9:59:59");
        int32_t w = lv_text_get_width(line, (uint32_t)strlen(line), &lv_font_atalaia_14, 0);
        if (w > W - 4) fail("captured", "the held time does not fit the footer");
    }
}

/* A Domination box while a team holds its button (BN-26): the mode sends no progress, so the
 * bar comes from the box's own button, on neutral and captured, and goes when it is let go. */
static bool hold_bar_shows(lv_obj_t *scr, int32_t *fill_w)
{
    /* The header bar, the big line, the footer, the hold bar. */
    lv_obj_t *box = lv_obj_get_child(scr, 3);
    lv_obj_update_layout(scr);
    if (fill_w) *fill_w = lv_obj_get_width(lv_obj_get_child(box, 0));
    return !lv_obj_has_flag(box, LV_OBJ_FLAG_HIDDEN);
}

static void check_button_hold(void)
{
    box_lang_set_code("");
    lv_obj_t *scr = lv_screen_active();
    int32_t fill = -1;
    fake_game_ms = 230000;
    oled_view_handle(scr, "@mode", DOM, 1);
    oled_view_handle(scr, "captured", "{\"team\":\"red\",\"points\":3,\"since\":95}", 1);
    if (hold_bar_shows(scr, NULL)) fail("captured", "a bar with no button held");
    /* Blue presses: an empty bar and BLUE at once; then it fills with the hold. */
    hold_button("blue", 0);
    oled_view_poll(scr, 2);
    if (!hold_bar_shows(scr, &fill) || fill != 0) fail("captured", "no bar when blue presses");
    if (strcmp(foot_text(scr), "BLUE") != 0) fail("captured", "the taker is not shown");
    hold_button("blue", 1500);
    fake_game_ms += 1000; /* the game's clock goes on: the bar keeps the footer */
    oled_view_poll(scr, 3);
    if (!hold_bar_shows(scr, &fill) || fill != (HOLD_INNER_W * 50) / 100)
        fail("captured", "the bar does not fill while blue holds");
    if (strcmp(foot_text(scr), "BLUE") != 0) fail("captured", "the held time over the bar");
    /* Let go: the bar goes, the held time comes back (on the clock that went on). */
    hold_button(NULL, 0);
    oled_view_poll(scr, 4);
    if (hold_bar_shows(scr, NULL)) fail("captured", "the bar stays after the button is let go");
    if (strcmp(foot_text(scr), "held for 2:16") != 0)
        fail("captured", "the held time does not come back");
    /* The owner's own button: nothing (Domination ignores it). */
    hold_button("red", 2000);
    oled_view_poll(scr, 5);
    if (hold_bar_shows(scr, NULL)) fail("captured", "a bar for the team that holds the zone");
    /* Neutral: the same bar, and back to "Hold to capture". */
    hold_button(NULL, 0);
    oled_view_handle(scr, "neutral", "{}", 6);
    hold_button("blue", 750);
    oled_view_poll(scr, 7);
    if (!hold_bar_shows(scr, &fill) || fill != (HOLD_INNER_W * 25) / 100)
        fail("neutral", "no bar while blue holds");
    if (strcmp(foot_text(scr), "BLUE") != 0) fail("neutral", "the taker is not shown");
    hold_button(NULL, 0);
    oled_view_poll(scr, 8);
    if (hold_bar_shows(scr, NULL) || strcmp(foot_text(scr), box_text(TXO_HOLD_TO_CAPTURE)) != 0)
        fail("neutral", "the bar stays after the button is let go");
    /* Not on another screen. */
    oled_view_handle(scr, "playing", "{\"role\":\"zone\"}", 9);
    hold_button("blue", 750);
    oled_view_poll(scr, 10);
    if (hold_bar_shows(scr, NULL)) fail("playing", "a hold bar over another screen");
    hold_button(NULL, 0);
    fake_game_ms = 230000;
}

/* Every line of a splash shows whole (FV-8): no label's text is wider than the label, and no
 * label leaves the screen. */
static void check_labels_fit(const char *name)
{
    lv_obj_t *scr = lv_screen_active();
    lv_obj_update_layout(scr);
    for (uint32_t i = 0; i < lv_obj_get_child_count(scr); i++) {
        lv_obj_t *l = lv_obj_get_child(scr, (int32_t)i);
        if (!lv_obj_check_type(l, &lv_label_class)) continue;
        const char *s = lv_label_get_text(l);
        if (s[0] == '\0') continue; /* a modem line with nothing in it */
        const lv_font_t *font = lv_obj_get_style_text_font(l, LV_PART_MAIN);
        int32_t tw = lv_text_get_width(s, (uint32_t)strlen(s), font, 0);
        lv_area_t a;
        lv_obj_get_coords(l, &a);
        /* unscii 8 says its line is 9 pixels; its glyphs are 8 (the modem's six lines fill 48). */
        const int32_t lh = font == &lv_font_unscii_8 ? 8 : lv_font_get_line_height(font);
        if (tw > lv_area_get_width(&a)) fail(name, "a line of the splash is clipped");
        if (a.x1 < 0 || a.y1 < 0 || a.x1 + tw > W || a.y1 + lh > H)
            fail(name, "a line of the splash leaves the screen");
    }
}

/* A development build's version line fits the splash whole up to a count of 199 (FV-8): with
 * its "v" while that fits (every count up to 39, most up to 99), else without it. Past that
 * some end in "...", the commit's line still whole. */
static void check_version_widths(void)
{
    extern const lv_font_t lv_font_atalaia_14;
    const int32_t max_w = W - OLED_SPLASH_TEXT_X;
    for (int n = 0; n <= 199; n++) {
        char version[40], l1[40], l2[24];
        snprintf(version, sizeof(version), "0.4.0-dev.%d+gabc1234.dirty", n);
        oled_version_lines(version, l1, sizeof(l1), l2, sizeof(l2));
        const char *shown = oled_version_fit(l1, &lv_font_atalaia_14, max_w);
        if (lv_text_get_width(shown, (uint32_t)strlen(shown), &lv_font_atalaia_14, 0) > max_w)
            fail("splash", "a development build's version up to dev.199 does not fit");
        if (n <= 39 && shown != l1) fail("splash", "a count up to 39 lost its v");
    }
}

/* The splash holds later screens until its time is over. */
static void check_splash_hold(void)
{
    lv_obj_t *scr = lv_screen_active();
    oled_view_splash(scr, "0.2.0", 1000, 2000);
    oled_view_handle(scr, "pin_entry", "{\"digits\":0}", 1500);
    lv_obj_t *first = lv_obj_get_child(scr, 0);
    if (!first || !lv_obj_check_type(first, &lv_image_class))
        fail("splash", "a screen replaced it early");
    oled_view_poll(scr, 2999);
    first = lv_obj_get_child(scr, 0);
    if (!first || !lv_obj_check_type(first, &lv_image_class))
        fail("splash", "gone before its time");
    oled_view_poll(scr, 3000);
    first = lv_obj_get_child(scr, 0);
    if (first && lv_obj_check_type(first, &lv_image_class))
        fail("splash", "the held screen never came");
}

int main(void)
{
    char parent[512];
    snprintf(parent, sizeof(parent), "%s", OLED_OUT_DIR);
    char *slash = strrchr(parent, '/');
    if (slash) *slash = '\0';
    mkdir(parent, 0755);
    mkdir(OLED_OUT_DIR, 0755);
    lv_init();
    lv_tick_set_cb(tick_cb);
    display = lv_display_create(W, H);
    lv_display_set_color_format(display, LV_COLOR_FORMAT_RGB565);
    lv_display_set_buffers(display, framebuffer, NULL, sizeof(framebuffer),
                           LV_DISPLAY_RENDER_MODE_FULL);
    lv_display_set_flush_cb(display, flush_cb);
    oled_view_set_game_clock(game_clock);
    oled_view_set_hold_reader(hold_reader);

    for (int i = 0; i < CASE_COUNT; i++) {
        render(&cases[i]);
        char msg[200] = "";
        if (font_check_labels(lv_screen_active(), msg, sizeof(msg)) > 0) fail(cases[i].name, msg);
        if (!cases[i].template_name) check_labels_fit(cases[i].name);
        compare_with_reference(cases[i].name);
    }
    check_held_tick(); /* on the OLED view's own objects, before the modem's screens replace them */
    check_button_hold();
    for (int i = 0; i < MODEM_CASE_COUNT; i++) {
        render_modem(&modem_cases[i]);
        /* Every letter in its own label's font (the header bar's included), and every line whole
         * and on the screen. */
        char msg[200] = "";
        if (font_check_labels(lv_screen_active(), msg, sizeof(msg)) > 0)
            fail(modem_cases[i].name, msg);
        check_labels_fit(modem_cases[i].name);
        compare_with_reference(modem_cases[i].name);
    }
    check_splash_hold();
    check_version_widths();
    if (!update_mode()) check_no_stale_references();

    if (failures) {
        fprintf(stderr, "oled screens: %d failure(s)\n", failures);
        return 1;
    }
    printf("oled screens: %d renders match their reference images (%s)\n",
           CASE_COUNT + MODEM_CASE_COUNT, OLED_OUT_DIR);
    return 0;
}
