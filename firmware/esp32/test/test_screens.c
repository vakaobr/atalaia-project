/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Reference-image tests for the screen templates. Each case renders one
 * template with representative data through the real LVGL 9.2.2 build
 * (headless, 320x240 RGB565), writes the result to <build>/screens/ and
 * compares it pixel by pixel with firmware/esp32/test/screens/<name>.png.
 *
 * A case whose name ends in "_pt" is drawn in Portuguese, as a box whose game's
 * join carried "pt" (box_text.h, decision BN-14), one ending in "_de" in
 * German (P5H-4), one ending in "_zh-tw" in Traditional Chinese (P5K-2); the
 * others as a box no game gave a language to (English, and the modes'
 * templates in their default). Every letter of every label must be in that
 * label's own font (font_check.h), never an empty box or a fallback.
 *
 * To accept new renders on purpose, run with ATALAIA_UPDATE_SCREENS=1:
 *   ATALAIA_UPDATE_SCREENS=1 ctest --test-dir <build> -R screens
 * (or `python tools/docker_fw.py test --update-screens`), then look at
 * every changed PNG before committing it.
 */
#define _POSIX_C_SOURCE 200809L

#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include "lvgl.h"
#include "box_logo.h"
#include "box_text.h"
#include "font_check.h"
#include "png_io.h"
#include "screen_renderer.h"
#include "screen_template.h"
#include "test_display.h"

#define W TEST_DISPLAY_W
#define H TEST_DISPLAY_H

typedef struct {
    const char *name; /* PNG file name without .png */
    const char *template_name;
    const char *data;
    /* For a mode's YAML template (modes/<mode>/assets/screens/): the "@mode"
     * message, "<mode id> <params>"; NULL for the C screens. */
    const char *mode;
} screen_case_t;

/* Cases drawn with the game timer's bar (screen_timer_bar): seconds left of the game's seconds. */
typedef struct {
    const char *name;
    long left, total;
} timer_bar_case_t;

static const timer_bar_case_t timer_bars[] = {
    {"timer_bar_status", 400, 600},
    {"timer_bar_neutral", 3600, 7200},
    {"timer_bar_yaml_domination", 3600, 7200},
    {"timer_bar_last_minute", 47, 1800},
};

#define BOMB     "org.atalaia.bomb {\"attackers\":\"red\",\"defenders\":\"blue\",\"fuse_s\":300}"
#define DOM      "org.atalaia.domination {\"capture_hold_ms\":3000,\"tick_s\":10}"
#define KILL     "org.atalaia.kill_confirmed {\"turn_in_s\":20}"
#define RESPAWN  "org.atalaia.respawn {\"lives\":20,\"per_player\":false}"
#define CHECKIN  "org.atalaia.player_checkin {\"points\":1}"
#define MEDIC    "org.atalaia.medic {\"heal_hold_s\":10,\"charges\":5,\"lang\":\"pt\"}"
#define MEDIC_EN "org.atalaia.medic {\"heal_hold_s\":10,\"charges\":5,\"lang\":\"en\"}"
#define MEDIC_DE "org.atalaia.medic {\"heal_hold_s\":10,\"charges\":5,\"lang\":\"de\"}"
#define MEDIC_ZH "org.atalaia.medic {\"heal_hold_s\":10,\"charges\":5,\"lang\":\"zh-tw\"}"
#define MASTER   "org.atalaia.master_satellites {\"capture_hold_ms\":3000,\"tick_s\":10}"
#define TARGET   "org.atalaia.target_windows {\"interval_s\":20,\"window_s\":5}"
#define HACK     "org.atalaia.hacking_terminal {\"digits\":4,\"lockout_s\":10,\"lang\":\"pt\"}"
#define HACK_EN  "org.atalaia.hacking_terminal {\"digits\":4,\"lockout_s\":10,\"lang\":\"en\"}"
#define HACK_DE  "org.atalaia.hacking_terminal {\"digits\":4,\"lockout_s\":10,\"lang\":\"de\"}"
#define HACK_ZH  "org.atalaia.hacking_terminal {\"digits\":4,\"lockout_s\":10,\"lang\":\"zh-tw\"}"
#define VIP      "org.atalaia.vip_payload {\"capture_hold_ms\":3000,\"lang\":\"pt\"}"
#define VIP_EN   "org.atalaia.vip_payload {\"capture_hold_ms\":3000,\"lang\":\"en\"}"
#define VIP_DE   "org.atalaia.vip_payload {\"capture_hold_ms\":3000,\"lang\":\"de\"}"
#define VIP_ZH   "org.atalaia.vip_payload {\"capture_hold_ms\":3000,\"lang\":\"zh-tw\"}"
#define OBJ      "org.atalaia.objectives {}"
#define MONEY    "org.atalaia.money_factory {\"capacity\":50,\"capture_hold_ms\":3000}"
#define PROG     "org.atalaia.progressive_domination {\"capture_hold_ms\":3000,\"complete_min\":10}"

/* Data as the modes (modes/bomb, modes/domination, modes/codes) and the shell send it. */
static const screen_case_t cases[] = {
    {"standby", "standby", "{\"arm\":\"red\"}", NULL},
    {"countdown", "countdown", "{\"left\":299}", NULL},
    {"countdown_last_seconds", "countdown", "{\"left\":7}", NULL},
    {"countdown_long", "countdown", "{\"left\":5400,\"team\":\"red\"}", NULL},
    {"defused", "defused", "{\"team\":\"blue\"}", NULL},
    {"defused_yellow", "defused", "{\"team\":\"yellow\"}", NULL},
    {"exploded", "exploded", "{\"team\":\"red\"}", NULL},
    {"final_score", "final_score", "{\"owner\":\"red\"}", NULL},
    {"final_score_no_owner", "final_score", "{}", NULL},
    {"paused", "paused", "{}", NULL},
    {"code_entry", "code_entry",
     "{\"title\":\"ARM\",\"digits\":0,\"message\":\"Enter your team code\"}", NULL},
    {"code_entry_defuse", "code_entry", "{\"title\":\"DEFUSE\",\"digits\":3,\"left\":154}", NULL},
    {"code_entry_wrong", "code_entry",
     "{\"title\":\"CODE\",\"digits\":0,\"message\":\"Wrong code\",\"error\":true}", NULL},
    {"code_entry_points", "code_entry",
     "{\"title\":\"CODE\",\"digits\":4,\"message\":\"+50 points for RED\",\"error\":false}", NULL},
    {"code_entry_pt", "code_entry", "{\"title\":\"ARM\",\"digits\":0}", NULL},
    {"code_entry_defuse_pt", "code_entry", "{\"title\":\"DEFUSE\",\"digits\":3,\"left\":154}",
     NULL},
    {"code_entry_code_pt", "code_entry", "{\"title\":\"CODE\",\"digits\":2}", NULL},
    {"code_entry_de", "code_entry", "{\"title\":\"ARM\",\"digits\":0}", NULL},
    {"code_entry_defuse_de", "code_entry", "{\"title\":\"DEFUSE\",\"digits\":3,\"left\":154}",
     NULL},
    {"code_entry_code_de", "code_entry", "{\"title\":\"CODE\",\"digits\":2}", NULL},
    {"code_entry_zh-tw", "code_entry", "{\"title\":\"ARM\",\"digits\":0}", NULL},
    {"code_entry_defuse_zh-tw", "code_entry", "{\"title\":\"DEFUSE\",\"digits\":3,\"left\":154}",
     NULL},
    {"code_entry_code_zh-tw", "code_entry", "{\"title\":\"CODE\",\"digits\":2}", NULL},
    {"status", "status",
     "{\"title\":\"Game on\",\"mode\":\"Domination\",\"timer_s\":600,\"battery\":85,"
     "\"version\":\"0.1.0\"}",
     NULL},
    /* A game's life on a box (decisions BN-10, BN-12, BN-13): joined or invited, waiting for the
     * start; started (before the mode draws); ready for the next game (with the picker's hint on a
     * box that has one). */
    {"waiting", "waiting", "{\"game\":3073,\"role\":\"zone\",\"invited\":false}", NULL},
    {"waiting_invited", "waiting", "{\"game\":3073,\"role\":\"zone\",\"invited\":true}", NULL},
    {"playing", "playing", "{\"game\":3073,\"role\":\"zone\"}", NULL},
    {"ready", "ready", "{}", NULL},
    /* The field's logo (box_logo.h, PKG-1): cases named field_logo_* have a kept logo (a test one);
     * the others show the Atalaia towers in its place. */
    {"field_logo_ready", "ready", "{}", NULL},
    {"field_logo_ready_picker_pt", "ready", "{\"picker\":true}", NULL},
    {"field_logo_standby", "standby", "{}", NULL},
    {"field_logo_standby_armed", "standby", "{\"arm\":\"red\"}", NULL},
    {"standby_waiting", "standby", "{}", NULL},
    {"ready_picker", "ready", "{\"picker\":true}", NULL},
    /* A zone nobody holds and a zone a team holds, for the modes without their own (BN-11). */
    {"neutral", "neutral", "{\"hold_s\":3}", NULL},
    {"captured", "captured", "{\"team\":\"red\",\"since\":95}", NULL},
    /* The same in Portuguese (BN-14). */
    {"waiting_invited_pt", "waiting", "{\"game\":3073,\"role\":\"zone\",\"invited\":true}", NULL},
    {"playing_pt", "playing", "{\"game\":3073,\"role\":\"zone\"}", NULL},
    {"ready_picker_pt", "ready", "{\"picker\":true}", NULL},
    {"neutral_pt", "neutral", "{\"hold_s\":3}", NULL},
    {"captured_pt", "captured", "{\"team\":\"red\",\"since\":95}", NULL},
    {"standby_pt", "standby", "{\"arm\":\"red\"}", NULL},
    {"countdown_pt", "countdown", "{\"left\":299,\"team\":\"red\"}", NULL},
    {"defused_pt", "defused", "{\"team\":\"blue\"}", NULL},
    {"final_score_pt", "final_score", "{\"owner\":\"red\"}", NULL},
    {"paused_pt", "paused", "{}", NULL},
    {"pin_entry_pt", "pin_entry", "{\"digits\":2,\"error\":true}", NULL},
    {"preset_select_pt", "preset_select",
     "{\"presets\":[\"Bomba\",\"Domínio\"],\"selected\":1,\"page\":1,\"pages\":2}", NULL},
    {"timer_adjust_pt", "timer_adjust", "{\"timer_s\":0}", NULL},
    {"start_confirm_pt", "start_confirm", "{\"label\":\"Bomba\",\"timer_s\":600}", NULL},
    {"start_confirm_setup_pt", "start_confirm", "{\"setup\":true}", NULL},
    {"start_confirm_adopt_pt", "start_confirm", "{\"adopt\":true}", NULL},
    {"preset_select_setup_pt", "preset_select",
     "{\"presets\":[\"Bomba\",\"Configurar o Wi-Fi\"],\"selected\":2}", NULL},
    {"wifi_setup_pt", "wifi_setup", "{\"ssid\":\"atalaia-3F2A\"}", NULL},
    {"status_adopted_pt", "status",
     "{\"title\":\"Adotada\",\"field\":\"Campo da Atalaia\",\"fingerprint\":\"604A-0A95\"}", NULL},
    /* The same in German (P5H-4); the modes' templates in German too (P5H-12). */
    {"waiting_invited_de", "waiting", "{\"game\":3073,\"role\":\"zone\",\"invited\":true}", NULL},
    {"playing_de", "playing", "{\"game\":3073,\"role\":\"zone\"}", NULL},
    {"ready_picker_de", "ready", "{\"picker\":true}", NULL},
    {"neutral_de", "neutral", "{\"hold_s\":3}", NULL},
    {"neutral_no_hold_de", "neutral", "{}", NULL},
    {"captured_de", "captured", "{\"team\":\"red\",\"since\":95}", NULL},
    {"standby_de", "standby", "{\"arm\":\"red\"}", NULL},
    {"countdown_de", "countdown", "{\"left\":299,\"team\":\"red\"}", NULL},
    {"defused_de", "defused", "{\"team\":\"blue\"}", NULL},
    {"exploded_de", "exploded", "{\"team\":\"red\"}", NULL},
    {"final_score_de", "final_score", "{\"owner\":\"red\"}", NULL},
    {"final_score_no_owner_de", "final_score", "{}", NULL},
    {"paused_de", "paused", "{}", NULL},
    {"pin_entry_de", "pin_entry", "{\"digits\":2,\"error\":true}", NULL},
    {"preset_select_de", "preset_select",
     "{\"presets\":[\"Bombe\",\"Domination\"],\"selected\":1,\"page\":1,\"pages\":2}", NULL},
    {"timer_adjust_de", "timer_adjust", "{\"timer_s\":0}", NULL},
    {"start_confirm_de", "start_confirm", "{\"label\":\"Bombe\",\"timer_s\":600}", NULL},
    {"start_confirm_setup_de", "start_confirm", "{\"setup\":true}", NULL},
    {"start_confirm_adopt_de", "start_confirm", "{\"adopt\":true}", NULL},
    {"wifi_setup_de", "wifi_setup", "{\"ssid\":\"atalaia-3F2A\"}", NULL},
    {"status_adopted_de", "status",
     "{\"title\":\"Aufgenommen\",\"field\":\"Campo da Atalaia\",\"fingerprint\":\"604A-0A95\"}",
     NULL},
    {"status_pair_de", "status",
     "{\"title\":\"Box koppeln\",\"code\":\"042 137\",\"id\":\"b0c5\",\"field\":\"keins\"}", NULL},
    {"pin_entry_locked_de", "pin_entry", "{\"digits\":0,\"error\":false,\"locked_min\":8}", NULL},
    {"pin_entry_no_pin_de", "pin_entry", "{\"digits\":0,\"error\":false,\"no_pin\":true}", NULL},
    {"yaml_domination_neutral_de", "neutral", "{}", DOM},
    /* The same in Traditional Chinese (P5K-2). The box's preset names stay English
     * (builtin_presets.c); the modes' templates are Chinese too (P5H-12). */
    {"waiting_invited_zh-tw", "waiting", "{\"game\":3073,\"role\":\"zone\",\"invited\":true}",
     NULL},
    {"playing_zh-tw", "playing", "{\"game\":3073,\"role\":\"zone\"}", NULL},
    {"ready_picker_zh-tw", "ready", "{\"picker\":true}", NULL},
    {"neutral_zh-tw", "neutral", "{\"hold_s\":3}", NULL},
    {"neutral_no_hold_zh-tw", "neutral", "{}", NULL},
    {"captured_zh-tw", "captured", "{\"team\":\"red\",\"since\":95}", NULL},
    {"standby_zh-tw", "standby", "{\"arm\":\"red\"}", NULL},
    {"countdown_zh-tw", "countdown", "{\"left\":299,\"team\":\"red\"}", NULL},
    {"defused_zh-tw", "defused", "{\"team\":\"blue\"}", NULL},
    {"exploded_zh-tw", "exploded", "{\"team\":\"red\"}", NULL},
    {"final_score_zh-tw", "final_score", "{\"owner\":\"red\"}", NULL},
    {"final_score_no_owner_zh-tw", "final_score", "{}", NULL},
    {"paused_zh-tw", "paused", "{}", NULL},
    {"pin_entry_zh-tw", "pin_entry", "{\"digits\":2,\"error\":true}", NULL},
    {"preset_select_zh-tw", "preset_select",
     "{\"presets\":[\"Bomb\",\"Domination\"],\"selected\":1,\"page\":1,\"pages\":2}", NULL},
    {"timer_adjust_zh-tw", "timer_adjust", "{\"timer_s\":0}", NULL},
    {"timer_adjust_10_zh-tw", "timer_adjust", "{\"timer_s\":600}", NULL},
    {"start_confirm_zh-tw", "start_confirm", "{\"label\":\"Bomb\",\"timer_s\":600}", NULL},
    {"start_confirm_setup_zh-tw", "start_confirm", "{\"setup\":true}", NULL},
    {"start_confirm_adopt_zh-tw", "start_confirm", "{\"adopt\":true}", NULL},
    {"wifi_setup_zh-tw", "wifi_setup", "{\"ssid\":\"atalaia-3F2A\"}", NULL},
    {"status_adopted_zh-tw", "status",
     "{\"title\":\"已綁定\",\"field\":\"Campo da Atalaia\",\"fingerprint\":\"604A-0A95\"}", NULL},
    {"status_pair_zh-tw", "status",
     "{\"title\":\"配對這個盒子\",\"code\":\"042 137\",\"id\":\"b0c5\",\"field\":\"無\"}", NULL},
    {"pin_entry_locked_zh-tw", "pin_entry", "{\"digits\":0,\"error\":false,\"locked_min\":8}",
     NULL},
    {"pin_entry_no_pin_zh-tw", "pin_entry", "{\"digits\":0,\"error\":false,\"no_pin\":true}", NULL},
    {"yaml_domination_neutral_zh-tw", "neutral", "{}", DOM},
    {"pin_entry", "pin_entry", "{\"digits\":2,\"error\":false}", NULL},
    {"pin_entry_wrong", "pin_entry", "{\"digits\":0,\"error\":true}", NULL},
    /* The admin PIN after five wrong ones (a wait), and a Field Box with none set (AD-28, AD-29).
     */
    {"pin_entry_locked", "pin_entry", "{\"digits\":0,\"error\":false,\"locked_min\":8}", NULL},
    {"pin_entry_locked_pt", "pin_entry", "{\"digits\":0,\"error\":false,\"locked_min\":8}", NULL},
    {"pin_entry_no_pin", "pin_entry", "{\"digits\":0,\"error\":false,\"no_pin\":true}", NULL},
    {"pin_entry_no_pin_pt", "pin_entry", "{\"digits\":0,\"error\":false,\"no_pin\":true}", NULL},
    /* Adoption (adoption.c, protocol/adoption.md): adopted, and another field's card. */
    {"status_adopted", "status",
     "{\"title\":\"Adopted\",\"field\":\"Campo da Atalaia\",\"fingerprint\":\"604A-0A95\"}", NULL},
    {"status_pair_locked", "status", "{\"title\":\"Pair locked\",\"pairing\":\"restart the box\"}",
     NULL},
    {"status_pair", "status",
     "{\"title\":\"Pair this box\",\"code\":\"042 137\",\"id\":\"b0c5\",\"field\":\"none\"}", NULL},
    {"pin_entry_field", "pin_entry",
     "{\"digits\":3,\"error\":false,\"prompt\":\"PIN to change field\"}", NULL},
    {"preset_select", "preset_select", "{\"presets\":[\"Bomb\",\"Domination\"],\"selected\":1}",
     NULL},
    {"preset_select_long", "preset_select",
     "{\"presets\":[\"Bomb\",\"Domination\",\"Bomb (short fuse)\",\"Domination: 3 teams\","
     "\"Night game with a very long name that does not fit\",\"Training\",\"King of the hill\"],"
     "\"selected\":5}",
     NULL},
    {"preset_select_empty", "preset_select", "{\"presets\":[],\"selected\":1}", NULL},
    /* The ten built-in presets, two pages (decision M2-1). */
    {"preset_select_page1", "preset_select",
     "{\"presets\":[\"Bomb\",\"Domination\",\"Hold-All Domination\",\"Last Stand\",\"Codes\","
     "\"Kill Confirmed\",\"Respawn and Lives\",\"Player Check-in\",\"Medic Kit\"],"
     "\"selected\":1,\"page\":1,\"pages\":2}",
     NULL},
    {"preset_select_page2", "preset_select",
     "{\"presets\":[\"Master and Satellites\"],\"selected\":1,\"page\":2,\"pages\":2}", NULL},
    {"timer_adjust", "timer_adjust", "{\"timer_s\":600}", NULL},
    {"timer_adjust_no_limit", "timer_adjust", "{\"timer_s\":0}", NULL},
    {"start_confirm", "start_confirm", "{\"label\":\"Bomb\",\"timer_s\":600}", NULL},
    {"start_confirm_setup", "start_confirm", "{\"setup\":true}", NULL},
    {"start_confirm_adopt", "start_confirm", "{\"adopt\":true}", NULL},
    {"preset_select_setup", "preset_select",
     "{\"presets\":[\"Bomb\",\"Wi-Fi setup\"],\"selected\":2}", NULL},
    {"wifi_setup", "wifi_setup", "{\"ssid\":\"atalaia-3F2A\"}", NULL},
    /* Declarative templates (ADR-P3-4): Bomb and Domination migrated, the phase 3 modes. */
    {"yaml_bomb_standby", "standby", "{\"arm\":\"red\"}", BOMB},
    {"yaml_bomb_standby_arming", "standby", "{\"arm\":\"red\",\"progress\":0.6}", BOMB},
    {"yaml_bomb_standby_pt", "standby", "{\"arm\":\"red\"}", BOMB},
    {"yaml_bomb_countdown_defusing_pt", "countdown",
     "{\"left\":231,\"defuse\":0.4,\"team\":\"red\"}", BOMB},
    {"yaml_bomb_exploded_pt", "exploded", "{\"team\":\"red\"}", BOMB},
    {"yaml_bomb_countdown", "countdown", "{\"left\":299}", BOMB},
    {"yaml_bomb_countdown_defusing", "countdown", "{\"left\":231,\"defuse\":0.4}", BOMB},
    {"yaml_bomb_countdown_last_seconds", "countdown", "{\"left\":7,\"team\":\"red\"}", BOMB},
    {"yaml_bomb_defused", "defused", "{\"team\":\"blue\"}", BOMB},
    {"yaml_bomb_defused_yellow", "defused", "{\"team\":\"yellow\"}", BOMB},
    {"yaml_bomb_exploded", "exploded", "{\"team\":\"red\"}", BOMB},
    {"yaml_domination_neutral", "neutral", "{}", DOM},
    {"yaml_domination_neutral_pt", "neutral", "{}", DOM},
    {"yaml_domination_captured_pt", "captured", "{\"team\":\"red\",\"points\":12,\"since\":95}",
     DOM},
    {"yaml_domination_final_score_pt", "final_score", "{\"owner\":\"blue\",\"points\":40}", DOM},
    {"yaml_domination_captured", "captured", "{\"team\":\"red\",\"points\":12,\"since\":95}", DOM},
    {"yaml_domination_final_score", "final_score", "{\"owner\":\"blue\",\"points\":40}", DOM},
    {"yaml_domination_final_score_no_owner", "final_score", "{}", DOM},
    {"yaml_kill_confirmed", "tags", "{\"error\":false}", KILL},
    {"yaml_kill_confirmed_open", "tags",
     "{\"team\":\"red\",\"left\":14,\"message\":\"Kill confirmed: b1\",\"error\":false}", KILL},
    {"yaml_kill_confirmed_forged", "tags", "{\"message\":\"Forged tag\",\"error\":true}", KILL},
    {"yaml_respawn", "respawn",
     "{\"team\":\"blue\",\"player\":\"b3\",\"lives\":17,\"message\":\"Back in the game\","
     "\"error\":false}",
     RESPAWN},
    {"yaml_respawn_out", "respawn",
     "{\"team\":\"red\",\"player\":\"r1\",\"lives\":0,\"message\":\"No lives left: team out\","
     "\"error\":true}",
     RESPAWN},
    {"yaml_checkin", "checkin",
     "{\"total\":5,\"counts\":\"RED 3  BLUE 2\",\"team\":\"red\",\"message\":\"Checked in: r2\","
     "\"error\":false}",
     CHECKIN},
    /* The Medic Kit: Portuguese by default (accents folded for the ASCII fonts), and English. */
    {"yaml_medic_idle", "medic_idle", "{\"remaining\":4}", MEDIC},
    {"yaml_medic_idle_team_one_left", "medic_idle", "{\"remaining\":1,\"team\":\"blue\"}", MEDIC},
    {"yaml_medic_hold", "medic_hold",
     "{\"player\":\"b1\",\"team\":\"blue\",\"progress\":0.6,\"left\":4,\"remaining\":4}", MEDIC},
    {"yaml_medic_healed", "medic_healed",
     "{\"player\":\"b1\",\"team\":\"blue\",\"remaining\":3,\"used\":1,\"max\":2}", MEDIC},
    {"yaml_medic_refused", "medic_refused",
     "{\"reason\":\"limit\",\"message\":\"Chegaste ao limite de tratamentos\",\"player\":\"r2\","
     "\"team\":\"red\",\"remaining\":3}",
     MEDIC},
    {"yaml_medic_empty", "medic_empty", "{}", MEDIC},
    {"yaml_medic_hold_en", "medic_hold",
     "{\"player\":\"b1\",\"team\":\"blue\",\"progress\":0.25,\"left\":8,\"remaining\":4}",
     MEDIC_EN},
    /* Master and Satellites: a free box, a satellite, and the master with the controller's status.
     */
    {"yaml_master_satellites_neutral", "neutral", "{}", MASTER},
    {"yaml_master_satellites_status_pt", "master_status",
     "{\"team\":\"red\",\"since\":95,\"held\":2,\"of\":3,\"points\":4}", MASTER},
    {"yaml_master_satellites_captured", "captured", "{\"team\":\"blue\",\"since\":95}", MASTER},
    {"yaml_master_satellites_status", "master_status",
     "{\"team\":\"red\",\"since\":95,\"held\":2,\"of\":3,\"points\":4}", MASTER},
    {"yaml_master_satellites_status_no_points", "master_status",
     "{\"team\":\"yellow\",\"since\":3700,\"held\":1,\"of\":4,\"points\":0}", MASTER},
    /* Target Windows (not a preset until the addon exists): dark, after a hit, and a window open.
     */
    {"yaml_target_windows_standby", "standby", "{\"hits\":0}", TARGET},
    {"yaml_target_windows_standby_hit", "standby", "{\"team\":\"blue\",\"hits\":3}", TARGET},
    {"yaml_target_windows_window", "window", "{\"team\":\"red\",\"left\":4}", TARGET},
    {"yaml_target_windows_standby_hit_pt", "standby", "{\"team\":\"blue\",\"hits\":3}", TARGET},
    /* The Hacking Terminal: each puzzle, a lock, the solved screen with a code, in pt and en. */
    {"yaml_hack_code", "hack_code",
     "{\"team\":\"red\",\"typed\":\"8 5 _ _\",\"digits\":4,\"tries\":3,\"locked\":0,"
     "\"note\":\"enter\",\"g1\":\"8571\",\"r1\":2,\"c1\":2,\"g2\":\"5678\","
     "\"r2\":0,\"c2\":2,\"g3\":\"1234\",\"r3\":0,\"c3\":1}",
     HACK},
    {"yaml_hack_code_locked_en", "hack_code",
     "{\"owner\":\"blue\",\"typed\":\"_ _ _ _ _ _\",\"digits\":6,\"tries\":1,\"locked\":7,"
     "\"note\":\"enter\",\"g1\":\"012345\",\"r1\":1,\"c1\":3}",
     HACK_EN},
    {"yaml_hack_wires", "hack_wires",
     "{\"team\":\"blue\",\"wires\":\"- - 3 4 - 6\",\"cut\":3,\"of\":6,\"locked\":0}", HACK},
    {"yaml_hack_wires_yours", "hack_wires",
     "{\"team\":\"red\",\"owner\":\"red\",\"wires\":\"1 2 3\",\"cut\":0,\"of\":3,\"locked\":0,"
     "\"note\":\"yours\"}",
     HACK},
    {"yaml_hack_wires_locked_en", "hack_wires",
     "{\"wires\":\"1 2 3 4\",\"cut\":0,\"of\":4,\"locked\":20}", HACK_EN},
    {"yaml_hack_sequence_show", "hack_sequence",
     "{\"phase\":\"show\",\"key\":6,\"step\":2,\"of\":4,\"locked\":0}", HACK},
    {"yaml_hack_sequence_input_en", "hack_sequence",
     "{\"team\":\"yellow\",\"owner\":\"red\",\"phase\":\"input\",\"step\":2,\"of\":5,"
     "\"locked\":0}",
     HACK_EN},
    {"yaml_hack_sequence_idle", "hack_sequence",
     "{\"phase\":\"idle\",\"step\":0,\"of\":4,\"locked\":0}", HACK},
    {"yaml_hack_solved", "hack_solved", "{\"team\":\"red\",\"code\":\"4711\",\"capture\":true}",
     HACK},
    {"yaml_hack_solved_en", "hack_solved", "{\"capture\":false}", HACK_EN},
    /* VIP / Payload: a checkpoint (the box's role), and the payload's screen (an Android prop's,
     * drawn here too: the box carries every template). */
    {"yaml_vip_checkpoint_free", "checkpoint_free", "{}", VIP},
    {"yaml_vip_checkpoint_held_en", "checkpoint_held", "{\"team\":\"blue\",\"since\":95}", VIP_EN},
    {"yaml_vip_payload_moving", "payload", "{\"team\":\"red\",\"state\":\"moving\",\"metres\":75}",
     VIP},
    {"yaml_vip_payload_weak_en", "payload", "{\"team\":\"red\",\"state\":\"weak\",\"metres\":40}",
     VIP_EN},
    {"yaml_vip_payload_extracted", "payload",
     "{\"team\":\"red\",\"state\":\"extracted\",\"metres\":0}", VIP},
    /* Objectives: what a scenario's setup makes of a node (no parameters: the language and the
     * objective's name come in the setup, as data). */
    {"yaml_obj_wait", "obj_status", "{\"state\":\"wait\"}", OBJ},
    {"yaml_obj_off_en", "obj_status", "{\"state\":\"off\",\"label\":\"Vault\",\"lang\":\"en\"}",
     OBJ},
    {"yaml_obj_done", "obj_status", "{\"state\":\"done\",\"team\":\"red\",\"label\":\"Ponte\"}",
     OBJ},
    {"yaml_obj_failed_en", "obj_status",
     "{\"state\":\"failed\",\"label\":\"Site A\",\"lang\":\"en\"}", OBJ},
    {"yaml_obj_capture", "obj_capture", "{\"label\":\"Ponte\",\"only\":\"red\",\"hold_ms\":3000}",
     OBJ},
    {"yaml_obj_capture_held_en", "obj_capture",
     "{\"label\":\"Bridge\",\"team\":\"blue\",\"hold_ms\":3000,\"lang\":\"en\"}", OBJ},
    {"yaml_obj_code", "obj_code", "{\"label\":\"Cofre\",\"team\":\"red\",\"digits\":3}", OBJ},
    {"yaml_obj_code_wrong_en", "obj_code", "{\"digits\":0,\"note\":\"wrong\",\"lang\":\"en\"}",
     OBJ},
    {"yaml_obj_code_ok", "obj_code",
     "{\"label\":\"Cofre\",\"team\":\"red\",\"digits\":0,\"note\":\"ok\"}", OBJ},
    {"yaml_obj_tags_en", "obj_tags",
     "{\"label\":\"Intel\",\"team\":\"blue\",\"have\":1,\"count\":2,\"lang\":\"en\"}", OBJ},
    {"yaml_obj_tags_again", "obj_tags",
     "{\"label\":\"Dados\",\"team\":\"red\",\"have\":2,\"count\":2,"
     "\"note\":\"again\"}",
     OBJ},
    {"yaml_obj_tags_cards_en", "obj_tags",
     "{\"label\":\"HQ\",\"have\":0,\"count\":2,\"note\":\"team_first\",\"any\":true,"
     "\"lang\":\"en\"}",
     OBJ},
    {"yaml_obj_bomb_standby", "obj_bomb",
     "{\"label\":\"Local A\",\"phase\":\"standby\",\"attackers\":\"red\",\"fuse_s\":60,"
     "\"left\":0}",
     OBJ},
    {"yaml_obj_bomb_armed_en", "obj_bomb",
     "{\"phase\":\"armed\",\"team\":\"red\",\"left\":42,\"fuse_s\":60,\"lang\":\"en\"}", OBJ},
    {"yaml_obj_bomb_exploded", "obj_bomb",
     "{\"phase\":\"exploded\",\"team\":\"red\",\"left\":0,\"fuse_s\":60}", OBJ},
    /* Money Factory: a factory (free, being taken, held, without capture), a collection, a
     * bank, a deposit and a refusal; the box's language picks Portuguese or English. */
    {"yaml_money_neutral_pt", "neutral", "{\"stock\":0}", MONEY},
    {"yaml_money_neutral_taking", "neutral", "{\"stock\":5,\"taker\":\"blue\",\"progress\":0.4}",
     MONEY},
    {"yaml_money_captured_pt", "captured", "{\"team\":\"red\",\"since\":95,\"stock\":35}", MONEY},
    {"yaml_money_factory", "factory", "{\"stock\":12}", MONEY},
    {"yaml_money_collected_pt", "collected",
     "{\"player\":\"r1\",\"team\":\"red\",\"amount\":15,\"carrying\":20,\"stock\":20}", MONEY},
    {"yaml_money_bank_pt", "bank", "{\"total\":45,\"counts\":\"RED 30  BLUE 15\"}", MONEY},
    {"yaml_money_deposited", "deposited",
     "{\"player\":\"b1\",\"team\":\"blue\",\"amount\":12,\"total\":27}", MONEY},
    {"yaml_money_refused_pt", "refused",
     "{\"reason\":\"full\",\"player\":\"r1\",\"team\":\"red\",\"carrying\":20}", MONEY},
    /* The built-in modes' own texts in German and Traditional Chinese (P5H-12): a German or a
     * Chinese box draws them; the modes with a language parameter take it from params.lang. */
    {"yaml_domination_captured_de", "captured", "{\"team\":\"red\",\"points\":12,\"since\":95}",
     DOM},
    {"yaml_domination_final_score_de", "final_score", "{\"owner\":\"blue\",\"points\":40}", DOM},
    {"yaml_bomb_standby_arming_de", "standby", "{\"arm\":\"red\",\"progress\":0.6}", BOMB},
    {"yaml_bomb_countdown_defusing_de", "countdown", "{\"left\":231,\"defuse\":0.4}", BOMB},
    {"yaml_master_satellites_status_de", "master_status",
     "{\"team\":\"red\",\"since\":95,\"held\":2,\"of\":3,\"points\":4}", MASTER},
    {"yaml_target_windows_standby_hit_de", "standby", "{\"team\":\"blue\",\"hits\":3}", TARGET},
    {"yaml_hack_code_de", "hack_code",
     "{\"team\":\"red\",\"typed\":\"8 5 _ _\",\"digits\":4,\"tries\":3,\"locked\":0,"
     "\"note\":\"enter\",\"g1\":\"8571\",\"r1\":2,\"c1\":2,\"g2\":\"5678\","
     "\"r2\":0,\"c2\":2,\"g3\":\"1234\",\"r3\":0,\"c3\":1}",
     HACK_DE},
    {"yaml_bomb_defused_de", "defused", "{\"team\":\"blue\"}", BOMB},
    {"yaml_bomb_defused_pt", "defused", "{\"team\":\"blue\"}", BOMB},
    {"yaml_hack_sequence_locked_de", "hack_sequence",
     "{\"phase\":\"idle\",\"step\":0,\"of\":4,\"locked\":20}", HACK_DE},
    {"yaml_hack_wires_locked_de", "hack_wires",
     "{\"wires\":\"1 2 3 4\",\"cut\":0,\"of\":4,\"locked\":20}", HACK_DE},
    {"yaml_medic_idle_de", "medic_idle", "{\"remaining\":4}", MEDIC_DE},
    {"yaml_vip_payload_weak_de", "payload", "{\"team\":\"red\",\"state\":\"weak\",\"metres\":40}",
     VIP_DE},
    {"yaml_obj_capture_de", "obj_capture",
     "{\"label\":\"Brücke\",\"only\":\"red\",\"hold_ms\":3000}", OBJ},
    {"yaml_money_neutral_taking_de", "neutral", "{\"stock\":5,\"taker\":\"blue\",\"progress\":0.4}",
     MONEY},
    {"yaml_money_refused_de", "refused",
     "{\"reason\":\"full\",\"player\":\"r1\",\"team\":\"red\",\"carrying\":20}", MONEY},
    {"yaml_domination_captured_zh-tw", "captured", "{\"team\":\"red\",\"points\":12,\"since\":95}",
     DOM},
    {"yaml_domination_final_score_zh-tw", "final_score", "{\"owner\":\"blue\",\"points\":40}", DOM},
    {"yaml_bomb_countdown_defusing_zh-tw", "countdown", "{\"left\":231,\"defuse\":0.4}", BOMB},
    {"yaml_bomb_exploded_zh-tw", "exploded", "{\"team\":\"red\"}", BOMB},
    {"yaml_master_satellites_status_zh-tw", "master_status",
     "{\"team\":\"red\",\"since\":95,\"held\":2,\"of\":3,\"points\":4}", MASTER},
    {"yaml_target_windows_standby_hit_zh-tw", "standby", "{\"team\":\"blue\",\"hits\":3}", TARGET},
    {"yaml_hack_code_zh-tw", "hack_code",
     "{\"team\":\"red\",\"typed\":\"8 5 _ _\",\"digits\":4,\"tries\":3,\"locked\":0,"
     "\"note\":\"enter\",\"g1\":\"8571\",\"r1\":2,\"c1\":2,\"g2\":\"5678\","
     "\"r2\":0,\"c2\":2,\"g3\":\"1234\",\"r3\":0,\"c3\":1}",
     HACK_ZH},
    {"yaml_hack_sequence_input_zh-tw", "hack_sequence",
     "{\"team\":\"yellow\",\"owner\":\"red\",\"phase\":\"input\",\"step\":2,\"of\":5,"
     "\"locked\":0}",
     HACK_ZH},
    {"yaml_medic_healed_zh-tw", "medic_healed",
     "{\"player\":\"b1\",\"team\":\"blue\",\"remaining\":3,\"used\":1,\"max\":2}", MEDIC_ZH},
    {"yaml_vip_checkpoint_free_zh-tw", "checkpoint_free", "{}", VIP_ZH},
    {"yaml_obj_tags_zh-tw", "obj_tags",
     "{\"team\":\"blue\",\"have\":1,\"count\":2,\"note\":\"wrong_team\"}", OBJ},
    {"yaml_obj_bomb_armed_zh-tw", "obj_bomb",
     "{\"phase\":\"armed\",\"team\":\"red\",\"left\":42,\"fuse_s\":60}", OBJ},
    {"yaml_money_captured_zh-tw", "captured", "{\"team\":\"red\",\"since\":95,\"stock\":35}",
     MONEY},
    {"yaml_money_refused_zh-tw", "refused",
     "{\"reason\":\"full\",\"player\":\"r1\",\"team\":\"red\",\"carrying\":20}", MONEY},
    /* Progressive Domination: a box waiting, the active box free, being taken, held, held in
     * the last place while another team takes it, and completed; every language once or more. */
    {"yaml_prog_inactive", "inactive", "{\"done\":1,\"of\":4}", PROG},
    {"yaml_prog_inactive_pt", "inactive", "{\"done\":1,\"of\":4}", PROG},
    {"yaml_prog_inactive_no_word_de", "inactive", "{}", PROG},
    {"yaml_prog_inactive_zh-tw", "inactive", "{\"done\":1,\"of\":4}", PROG},
    {"yaml_prog_neutral", "neutral", "{\"step\":2,\"of\":4,\"final\":false}", PROG},
    {"yaml_prog_neutral_taking_pt", "neutral",
     "{\"step\":2,\"of\":4,\"final\":false,\"taker\":\"blue\",\"progress\":0.4}", PROG},
    {"yaml_prog_neutral_final_de", "neutral", "{\"step\":4,\"of\":4,\"final\":true}", PROG},
    {"yaml_prog_neutral_zh-tw", "neutral", "{\"step\":2,\"of\":4,\"final\":false}", PROG},
    {"yaml_prog_captured", "captured",
     "{\"team\":\"red\",\"since\":95,\"step\":2,\"of\":4,\"final\":false,\"held_min\":4,"
     "\"need_min\":10,\"points\":24,\"share\":0.4}",
     PROG},
    {"yaml_prog_captured_pt", "captured",
     "{\"team\":\"red\",\"since\":95,\"step\":2,\"of\":4,\"final\":false,\"held_min\":4,"
     "\"need_min\":10,\"points\":24,\"share\":0.4}",
     PROG},
    {"yaml_prog_captured_final_taking_de", "captured",
     "{\"team\":\"blue\",\"since\":95,\"step\":4,\"of\":4,\"final\":true,\"held_min\":9,"
     "\"need_min\":10,\"points\":54,\"share\":0.9,\"taker\":\"red\",\"progress\":0.6}",
     PROG},
    {"yaml_prog_captured_zh-tw", "captured",
     "{\"team\":\"red\",\"since\":95,\"step\":2,\"of\":4,\"final\":false,\"held_min\":4,"
     "\"need_min\":10,\"points\":24,\"share\":0.4}",
     PROG},
    {"yaml_prog_completed", "completed", "{\"team\":\"blue\",\"step\":1,\"of\":4,\"done\":1}",
     PROG},
    {"yaml_prog_completed_pt", "completed", "{\"team\":\"blue\",\"step\":1,\"of\":4,\"done\":1}",
     PROG},
    {"yaml_prog_completed_de", "completed", "{\"team\":\"blue\",\"step\":1,\"of\":4,\"done\":1}",
     PROG},
    {"yaml_prog_completed_zh-tw", "completed", "{\"team\":\"blue\",\"step\":1,\"of\":4,\"done\":1}",
     PROG},
    /* Kill Confirmed, Respawn and Player Check-in in the box's language (their templates'
     * own texts; what their scripts write, "message", stays English). */
    {"yaml_kill_confirmed_pt", "tags", "{\"error\":false}", KILL},
    {"yaml_kill_confirmed_de", "tags", "{\"error\":false}", KILL},
    {"yaml_kill_confirmed_zh-tw", "tags", "{\"error\":false}", KILL},
    {"yaml_kill_confirmed_open_pt", "tags", "{\"team\":\"red\",\"left\":14,\"error\":false}", KILL},
    {"yaml_kill_confirmed_open_de", "tags", "{\"team\":\"red\",\"left\":14,\"error\":false}", KILL},
    {"yaml_kill_confirmed_open_zh-tw", "tags", "{\"team\":\"red\",\"left\":14,\"error\":false}",
     KILL},
    {"yaml_respawn_pt", "respawn", "{\"team\":\"blue\",\"lives\":17,\"error\":false}", RESPAWN},
    {"yaml_respawn_de", "respawn", "{\"team\":\"blue\",\"lives\":17,\"error\":false}", RESPAWN},
    {"yaml_respawn_zh-tw", "respawn", "{\"team\":\"blue\",\"lives\":17,\"error\":false}", RESPAWN},
    {"yaml_respawn_start_pt", "respawn", "{\"lives\":20}", RESPAWN},
    {"yaml_respawn_start_de", "respawn", "{\"lives\":20}", RESPAWN},
    {"yaml_respawn_start_zh-tw", "respawn", "{\"lives\":20}", RESPAWN},
    {"yaml_checkin_pt", "checkin", "{\"total\":5,\"counts\":\"RED 3  BLUE 2\",\"team\":\"red\"}",
     CHECKIN},
    {"yaml_checkin_de", "checkin", "{\"total\":5,\"counts\":\"RED 3  BLUE 2\",\"team\":\"red\"}",
     CHECKIN},
    {"yaml_checkin_zh-tw", "checkin", "{\"total\":5,\"counts\":\"RED 3  BLUE 2\",\"team\":\"red\"}",
     CHECKIN},
    /* The game timer's bar along the bottom edge (ADR-P1-3), over a C screen and a mode's own
     * template: a game two thirds left, half left, and in its last minute (red). */
    {"timer_bar_status", "status",
     "{\"title\":\"Game on\",\"mode\":\"Domination\",\"timer_s\":600}", NULL},
    {"timer_bar_neutral", "neutral", "{\"hold_s\":3}", NULL},
    {"timer_bar_yaml_domination", "neutral", "{\"hold_s\":3}", DOM},
    {"timer_bar_last_minute", "countdown", "{\"left\":47}", NULL},
};
#define CASE_COUNT ((int)(sizeof(cases) / sizeof(cases[0])))

static int failures;

static uint8_t rendered[W * H * 3];

static void fail(const char *name, const char *msg)
{
    fprintf(stderr, "FAIL screen %s: %s\n", name, msg);
    failures++;
}

/* Every visible widget must lie inside the screen and inside its parent. */
static void check_bounds(const char *name, lv_obj_t *obj, const lv_area_t *outer)
{
    uint32_t n = lv_obj_get_child_count(obj);
    for (uint32_t i = 0; i < n; i++) {
        lv_obj_t *child = lv_obj_get_child(obj, (int32_t)i);
        if (lv_obj_has_flag(child, LV_OBJ_FLAG_HIDDEN)) continue;
        lv_area_t a;
        lv_obj_get_coords(child, &a);
        if (a.x1 < outer->x1 || a.y1 < outer->y1 || a.x2 > outer->x2 || a.y2 > outer->y2) {
            char msg[160];
            snprintf(msg, sizeof(msg),
                     "a widget at (%d,%d)-(%d,%d) is outside (%d,%d)-(%d,%d), so it is clipped",
                     (int)a.x1, (int)a.y1, (int)a.x2, (int)a.y2, (int)outer->x1, (int)outer->y1,
                     (int)outer->x2, (int)outer->y2);
            fail(name, msg);
        }
        check_bounds(name, child, &a);
    }
}

/* No two visible labels may overlap: text drawn over text is never intended. */
#define LABELS_MAX 64
static int collect_labels(lv_obj_t *obj, lv_area_t *out, int n)
{
    uint32_t count = lv_obj_get_child_count(obj);
    for (uint32_t i = 0; i < count && n < LABELS_MAX; i++) {
        lv_obj_t *child = lv_obj_get_child(obj, (int32_t)i);
        if (lv_obj_has_flag(child, LV_OBJ_FLAG_HIDDEN)) continue;
        if (lv_obj_check_type(child, &lv_label_class) && lv_label_get_text(child)[0]) {
            lv_obj_get_coords(child, &out[n++]);
        }
        n = collect_labels(child, out, n);
    }
    return n;
}

static void check_overlaps(const char *name)
{
    lv_area_t a[LABELS_MAX];
    int n = collect_labels(lv_screen_active(), a, 0);
    for (int i = 0; i < n; i++) {
        for (int j = i + 1; j < n; j++) {
            if (a[i].x1 <= a[j].x2 && a[j].x1 <= a[i].x2 && a[i].y1 <= a[j].y2 &&
                a[j].y1 <= a[i].y2) {
                char msg[160];
                snprintf(msg, sizeof(msg), "labels at (%d,%d)-(%d,%d) and (%d,%d)-(%d,%d) overlap",
                         (int)a[i].x1, (int)a[i].y1, (int)a[i].x2, (int)a[i].y2, (int)a[j].x1,
                         (int)a[j].y1, (int)a[j].x2, (int)a[j].y2);
                fail(name, msg);
            }
        }
    }
}

/* "pt" for a name ending in "_pt", "de" for "_de", "zh-tw" for "_zh-tw", else "" (no language
 * given: English). */
static const char *language(const char *name)
{
    size_t n = strlen(name);
    if (n > 3 && strcmp(name + n - 3, "_pt") == 0) return "pt";
    if (n > 3 && strcmp(name + n - 3, "_de") == 0) return "de";
    if (n > 6 && strcmp(name + n - 6, "_zh-tw") == 0) return "zh-tw";
    return "";
}

/* Every letter on the screen is in its label's own font (font_check.h). */
static void check_glyphs(const char *name)
{
    char msg[200] = "";
    if (font_check_labels(lv_screen_active(), msg, sizeof(msg)) > 0) fail(name, msg);
}

/* A kept logo as a box would have fetched it: a test pattern, a disc on a blue field, in the
 * folder the renderer's box_logo reads. */
static void install_logo(bool on)
{
    static char dir[512];
    if (!dir[0]) {
        snprintf(dir, sizeof(dir), "%s/logo", SCREENS_OUT_DIR);
        mkdir(dir, 0755);
        box_logo_init(dir);
    }
    box_logo_forget();
    if (!on) return;
    static uint8_t file[BL_ID_LEN + BL_BYTES];
    memset(file, '7', BL_ID_LEN);
    uint8_t *f = file + BL_ID_LEN;
    memcpy(f, "ALG1", 4);
    f[4] = BL_SIDE;
    f[6] = BL_SIDE;
    for (int y = 0; y < BL_SIDE; y++) {
        for (int x = 0; x < BL_SIDE; x++) {
            int dx = x - 48, dy = y - 48;
            uint16_t px = dx * dx + dy * dy < 40 * 40 ? (uint16_t)0xFFE0 /* yellow */
                                                      : (uint16_t)(0x001F + (x / 3) * 32);
            if (x < 2 || y < 2 || x > 93 || y > 93)
                px = 0xF800; /* a red frame: the edges are seen */
            f[BL_HEADER + 2 * (y * BL_SIDE + x)] = (uint8_t)(px & 0xFF);
            f[BL_HEADER + 2 * (y * BL_SIDE + x) + 1] = (uint8_t)(px >> 8);
        }
    }
    char path[560];
    snprintf(path, sizeof(path), "%s/logo.bin", dir);
    FILE *out = fopen(path, "wb");
    if (out == NULL || fwrite(file, 1, sizeof(file), out) != sizeof(file)) {
        fail("(logo)", "cannot write the test logo");
    }
    if (out) fclose(out);
}

static void render(const screen_case_t *c)
{
    install_logo(strncmp(c->name, "field_logo_", 11) == 0);
    box_lang_set_code(language(c->name));
    if (c->mode) screen_render(SCREEN_MODE_MESSAGE, c->mode);
    if (!screen_render(c->template_name, c->data)) fail(c->name, "template not recognised");
    if (c->mode && !screen_template_widget_count()) fail(c->name, "not drawn from its template");
    for (size_t i = 0; i < sizeof(timer_bars) / sizeof(timer_bars[0]); i++) {
        if (strcmp(timer_bars[i].name, c->name) != 0) continue;
        screen_timer_bar(timer_bars[i].left, timer_bars[i].total);
        if (screen_timer_bar_left() != timer_bars[i].left)
            fail(c->name, "the timer bar is not shown");
    }
    test_display_render();
    test_display_rgb888(rendered);
}

static bool update_mode(void)
{
    const char *v = getenv("ATALAIA_UPDATE_SCREENS");
    return v && v[0] && strcmp(v, "0") != 0;
}

static void compare_with_reference(const screen_case_t *c)
{
    char path[512];
    snprintf(path, sizeof(path), "%s/%s.png", SCREENS_OUT_DIR, c->name);
    if (!png_write_rgb(path, W, H, rendered)) fail(c->name, "cannot write the rendered PNG");

    snprintf(path, sizeof(path), "%s/%s.png", SCREENS_REF_DIR, c->name);
    if (update_mode()) {
        if (!png_write_rgb(path, W, H, rendered)) fail(c->name, "cannot update the reference");
        printf("updated %s\n", path);
        return;
    }

    int rw = 0, rh = 0;
    uint8_t *ref = png_read_rgb(path, &rw, &rh);
    if (!ref) {
        fail(c->name, "no reference PNG; run with ATALAIA_UPDATE_SCREENS=1 to create it");
        return;
    }
    if (rw != W || rh != H) {
        fail(c->name, "the reference PNG is not 320x240");
        png_free(ref);
        return;
    }

    int diff = 0, x1 = W, y1 = H, x2 = -1, y2 = -1;
    static uint8_t diff_img[W * H * 3];
    for (int i = 0; i < W * H; i++) {
        bool same = memcmp(&rendered[3 * i], &ref[3 * i], 3) == 0;
        for (int k = 0; k < 3; k++) {
            diff_img[3 * i + k] = same ? (uint8_t)(rendered[3 * i + k] / 4) : (k == 1 ? 0 : 255);
        }
        if (same) continue;
        diff++;
        int x = i % W, y = i / W;
        if (x < x1) x1 = x;
        if (y < y1) y1 = y;
        if (x > x2) x2 = x;
        if (y > y2) y2 = y;
    }
    png_free(ref);
    if (diff) {
        snprintf(path, sizeof(path), "%s/%s.diff.png", SCREENS_OUT_DIR, c->name);
        png_write_rgb(path, W, H, diff_img);
        fprintf(stderr,
                "  %d pixels differ in (%d,%d)-(%d,%d)\n  rendered: %s/%s.png\n  diff: %s\n", diff,
                x1, y1, x2, y2, SCREENS_OUT_DIR, c->name, path);
        fail(c->name, "differs from its reference; if intended, run with ATALAIA_UPDATE_SCREENS=1");
    }
}

/* Every reference PNG must belong to a case, so stale images do not linger. */
static void check_no_stale_references(void)
{
    DIR *dir = opendir(SCREENS_REF_DIR);
    if (!dir) {
        fail("(all)", "cannot open the reference folder " SCREENS_REF_DIR);
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
        if (!known) fail(e->d_name, "reference PNG without a test case; delete it or add a case");
    }
    closedir(dir);
}

/* Patching a shown template must give the same pixels as building it afresh. */
static void check_patch_matches_build(void)
{
    static uint8_t patched[W * H * 3];
    screen_renderer_reset();
    screen_render("countdown", "{\"left\":299}");
    test_display_render();
    screen_render("countdown", "{\"left\":7}");
    test_display_render();
    test_display_rgb888(patched);

    screen_renderer_reset();
    screen_render("countdown", "{\"left\":7}");
    test_display_render();
    test_display_rgb888(rendered);
    if (memcmp(patched, rendered, sizeof(rendered)) != 0) {
        fail("countdown", "patching 299 -> 7 differs from building the screen at 7");
    }

    /* The same for a declarative template, through the colour change at 10 s. */
    screen_renderer_reset();
    screen_render(SCREEN_MODE_MESSAGE, BOMB);
    screen_render("countdown", "{\"left\":299}");
    test_display_render();
    screen_render("countdown", "{\"left\":7,\"team\":\"red\"}");
    test_display_render();
    test_display_rgb888(patched);
    screen_renderer_reset();
    screen_render(SCREEN_MODE_MESSAGE, BOMB);
    screen_render("countdown", "{\"left\":7,\"team\":\"red\"}");
    test_display_render();
    test_display_rgb888(rendered);
    if (memcmp(patched, rendered, sizeof(rendered)) != 0) {
        fail("yaml_bomb_countdown", "patching 299 -> 7 differs from building the screen at 7");
    }
}

int main(void)
{
    mkdir(SCREENS_OUT_DIR, 0755);
    test_display_init();

    for (int i = 0; i < CASE_COUNT; i++) {
        /* Start each case from an empty screen, as after a template change. */
        screen_renderer_reset();
        render(&cases[i]);
        lv_area_t screen = {0, 0, W - 1, H - 1};
        check_bounds(cases[i].name, lv_screen_active(), &screen);
        check_overlaps(cases[i].name);
        check_glyphs(cases[i].name);
        compare_with_reference(&cases[i]);
    }
    check_patch_matches_build();
    if (!update_mode()) check_no_stale_references();

    if (failures) {
        fprintf(stderr, "screens: %d failure(s)\n", failures);
        return 1;
    }
    printf("screens: %d renders match their reference images (%s)\n", CASE_COUNT, SCREENS_OUT_DIR);
    return 0;
}
