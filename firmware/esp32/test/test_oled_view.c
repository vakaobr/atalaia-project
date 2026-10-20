/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Tests for the on-board OLED's status view mapping (oled_view.h): every
 * screen update becomes a header, one big value and a footer.
 */
#include <string.h>

#include "check.h"
#include "oled_view.h"

static oled_text_t map(const char *mode, const char *t, const char *data)
{
    oled_text_t out;
    CHECK(oled_text_for(mode, t, data, &out));
    return out;
}

static void test_mode_title(void)
{
    char s[32];
    oled_mode_title("org.atalaia.bomb {\"attackers\":\"red\"}", s, sizeof(s));
    CHECK(strcmp(s, "BOMB") == 0);
    oled_mode_title("org.atalaia.master_satellites {}", s, sizeof(s));
    CHECK(strcmp(s, "MASTER SATELLITES") == 0);
    oled_mode_title("plainmode", s, sizeof(s));
    CHECK(strcmp(s, "PLAINMODE") == 0);
    oled_mode_title("org.atalaia.bomb {}", s, 3); /* truncated, terminated */
    CHECK(strcmp(s, "BO") == 0);
    oled_mode_title(NULL, s, sizeof(s));
    CHECK(s[0] == '\0');
}

static void test_mode_message_changes_nothing(void)
{
    oled_text_t out;
    CHECK(!oled_text_for("", "@mode", "org.atalaia.bomb {}", &out));
    CHECK(!oled_text_for("", NULL, "{}", &out));
}

static void test_pin_entry(void)
{
    oled_text_t t = map("", "pin_entry", "{\"digits\":0,\"error\":false}");
    CHECK(strcmp(t.head, "ADMIN PIN") == 0);
    CHECK(strcmp(t.big, "- - - -") == 0);
    t = map("", "pin_entry", "{\"digits\":3,\"error\":false}");
    CHECK(strcmp(t.big, "* * *") == 0);
    t = map("", "pin_entry", "{\"digits\":0,\"error\":true}");
    CHECK(strcmp(t.foot, "Wrong PIN") == 0);
    t = map("", "pin_entry", "{\"digits\":99}"); /* capped */
    CHECK(strcmp(t.big, "* * * * * * * *") == 0);
}

static void test_preset_select(void)
{
    oled_text_t t = map("", "preset_select",
                        "{\"presets\":[\"Bomb\",\"Domination\"],\"selected\":2,\"page\":1,"
                        "\"pages\":2}");
    CHECK(strcmp(t.head, "GAMES") == 0);
    CHECK(strcmp(t.head_right, "1/2") == 0);
    CHECK(strcmp(t.big, "2 Domination") == 0);
    t = map("", "preset_select", "{\"presets\":[\"Bomb\"],\"selected\":1}");
    CHECK(t.head_right[0] == '\0');
    CHECK(strcmp(t.big, "1 Bomb") == 0);
    t = map("", "preset_select", "{\"presets\":[],\"selected\":1}");
    CHECK(strcmp(t.big, "No games") == 0);
}

static void test_timer_and_start(void)
{
    oled_text_t t = map("", "timer_adjust", "{\"timer_s\":600}");
    CHECK(strcmp(t.big, "10:00") == 0);
    t = map("", "timer_adjust", "{\"timer_s\":3725}");
    CHECK(strcmp(t.big, "1:02:05") == 0);
    t = map("", "start_confirm", "{\"label\":\"Bomb\",\"timer_s\":600}");
    CHECK(strcmp(t.head, "START?") == 0);
    CHECK(strcmp(t.big, "Bomb") == 0);
    CHECK(strcmp(t.head_right, "10:00") == 0);
}

static void test_bomb_phases(void)
{
    oled_text_t t = map("BOMB", "standby", "{\"arm\":\"red\"}");
    CHECK(strcmp(t.head, "BOMB") == 0);
    CHECK(strcmp(t.big, "STANDBY") == 0);
    CHECK(strcmp(t.foot, "Hold RED to arm") == 0);
    t = map("BOMB", "countdown", "{\"left\":299}");
    CHECK(strcmp(t.big, "4:59") == 0);
    CHECK(strcmp(t.foot, "until detonation") == 0);
    t = map("BOMB", "countdown", "{\"left\":-3}");
    CHECK(strcmp(t.big, "0:00") == 0);
    CHECK(t.bar == -1);
    /* A hold fills the bar beside the footer; 0 or absent shows none. */
    t = map("BOMB", "standby", "{\"arm\":\"red\",\"progress\":0.6}");
    CHECK(strcmp(t.foot, "ARMING") == 0);
    CHECK(t.bar == 60);
    t = map("BOMB", "standby", "{\"arm\":\"red\",\"progress\":0}");
    CHECK(t.bar == -1);
    t = map("BOMB", "countdown", "{\"left\":231,\"defuse\":0.4}");
    CHECK(strcmp(t.big, "3:51") == 0);
    CHECK(strcmp(t.foot, "DEFUSE") == 0);
    CHECK(t.bar == 40);
    t = map("MEDIC", "medic_hold", "{\"player\":\"b1\",\"team\":\"blue\",\"progress\":1.5}");
    CHECK(t.bar == 100);
    CHECK(strcmp(t.foot, "BLUE") == 0);
    t = map("BOMB", "defused", "{\"team\":\"blue\"}");
    CHECK(strcmp(t.big, "DEFUSED") == 0);
    CHECK(strcmp(t.foot, "BLUE") == 0);
    t = map("BOMB", "exploded", "{\"team\":\"red\"}");
    CHECK(strcmp(t.big, "EXPLODED") == 0);
}

static void test_other_screens(void)
{
    /* No mode yet: the header names the product. */
    oled_text_t t = map("", "paused", "{}");
    CHECK(strcmp(t.head, "ATALAIA") == 0);
    CHECK(strcmp(t.big, "PAUSED") == 0);
    t = map("BOMB", "code_entry",
            "{\"title\":\"defuse\",\"digits\":2,\"left\":61,"
            "\"message\":\"Enter your team code\"}");
    CHECK(strcmp(t.head, "DEFUSE") == 0);
    CHECK(strcmp(t.head_right, "1:01") == 0);
    CHECK(strcmp(t.big, "* *") == 0);
    CHECK(strcmp(t.foot, "Enter your team code") == 0);
    t = map("HOLDALL", "final_score", "{\"owner\":\"yellow\"}");
    CHECK(strcmp(t.big, "GAME OVER") == 0);
    CHECK(strcmp(t.foot, "YELLOW") == 0);
    /* A mode's own template: its name, and a message below. */
    t = map("MEDIC", "medic_refused", "{\"message\":\"Limit reached\"}");
    CHECK(strcmp(t.big, "MEDIC REFUSED") == 0);
    CHECK(strcmp(t.foot, "Limit reached") == 0);
    t = map("KILL CONFIRMED", "tags", "{\"team\":\"red\",\"left\":14}");
    CHECK(strcmp(t.big, "0:14") == 0);
    CHECK(strcmp(t.foot, "RED") == 0);
    t = map("", "status", "{\"title\":\"Game on\",\"mode\":\"Bomb\",\"timer_s\":600}");
    CHECK(strcmp(t.head, "GAME ON") == 0);
    CHECK(strcmp(t.big, "Bomb") == 0);
    CHECK(strcmp(t.foot, "10:00") == 0);
    t = map("", "wifi_setup", "{}");
    CHECK(strcmp(t.big, "atalaia-....") == 0);
    t = map("", "standby", NULL);
    CHECK(strcmp(t.foot, "Waiting") == 0);
}

static void test_pack(void)
{
    static uint16_t frame[HAL_OLED_WIDTH * HAL_OLED_HEIGHT];
    uint8_t fb[HAL_OLED_FB_SIZE];
    memset(frame, 0, sizeof(frame));
    frame[0] = 0xFFFF;                         /* (0,0) white: lit */
    frame[9 * HAL_OLED_WIDTH + 5] = 0xFFFF;    /* (5,9): page 1, bit 1 */
    frame[63 * HAL_OLED_WIDTH + 127] = 0x8410; /* (127,63) mid grey: lit */
    frame[1] = 0x4208;                         /* (1,0) dark grey: off */
    oled_pack(frame, fb);
    CHECK(fb[0] == 0x01);
    CHECK(fb[1] == 0x00);
    CHECK(fb[HAL_OLED_WIDTH + 5] == 0x02);
    CHECK(fb[7 * HAL_OLED_WIDTH + 127] == 0x80);
}

void run_oled_view_tests(void)
{
    test_mode_title();
    test_mode_message_changes_nothing();
    test_pin_entry();
    test_preset_select();
    test_timer_and_start();
    test_bomb_phases();
    test_other_screens();
    test_pack();
}
