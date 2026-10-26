/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Tests for the on-board OLED's status view mapping (oled_view.h): every
 * screen update becomes a header, one big value and a footer.
 */
#include <string.h>

#include "box_text.h"
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
    CHECK(strcmp(t.big, "READY") == 0); /* the Bomb's "standby" (decision BN-11) */
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

/* A zone (BN-11): the captured screen's points and held time (BN-23), and the taker. */
static void test_zone_screens(void)
{
    oled_text_t t = map("DOMINATION", "captured", "{\"team\":\"red\",\"points\":12,\"since\":95}");
    CHECK(strcmp(t.big, "RED") == 0);
    CHECK(strcmp(t.head, "DOMINATION") == 0);
    CHECK(strcmp(t.head_right, "12 pts") == 0);
    CHECK(t.since == 95);
    CHECK(t.bar == -1);
    CHECK(strcmp(t.foot, "ZONE HELD") == 0); /* until the game's clock gives the held time */
    CHECK(oled_text_held(&t, 230));
    CHECK(strcmp(t.foot, "held for 2:15") == 0);
    CHECK(!oled_text_held(&t, 230)); /* unchanged */
    CHECK(oled_text_held(&t, 90));   /* a clock behind the capture: 0:00, never negative */
    CHECK(strcmp(t.foot, "held for 0:00") == 0);
    /* Without points or a capture time (another mode's captured screen): as before. */
    t = map("HILL", "captured", "{\"team\":\"blue\"}");
    CHECK(t.head_right[0] == '\0');
    CHECK(t.since == -1);
    CHECK(!oled_text_held(&t, 230));
    CHECK(strcmp(t.foot, "ZONE HELD") == 0);
    /* Another team holding its button: the bar and the taker; the held time waits. */
    t = map("HILL", "captured",
            "{\"team\":\"red\",\"points\":1,\"since\":5,\"taker\":\"blue\","
            "\"progress\":0.25}");
    CHECK(t.bar == 25);
    CHECK(strcmp(t.foot, "BLUE") == 0);
    CHECK(!oled_text_held(&t, 230));
    CHECK(strcmp(t.foot, "BLUE") == 0);
    t = map("HILL", "captured", "{\"team\":\"red\",\"progress\":0.25}");
    CHECK(strcmp(t.foot, "ZONE HELD") == 0);
    t = map("HILL", "neutral", "{\"taker\":\"red\",\"progress\":0.5}");
    CHECK(strcmp(t.big, "NEUTRAL") == 0);
    CHECK(strcmp(t.foot, "RED") == 0);
    t = map("HILL", "neutral", "{}");
    CHECK(strcmp(t.foot, "Hold to capture") == 0);
    CHECK(t.bar == -1);
    t = map("HILL", "neutral", "{\"taker\":\"red\"}"); /* no bar: no taker either */
    CHECK(strcmp(t.foot, "Hold to capture") == 0);
}

/* The box's own hold bar on a zone's screens, for modes that send no progress (BN-26):
 * Domination's neutral and captured carry no bar of their own. */
static void test_box_hold_bar(void)
{
    CHECK(oled_mode_hold_ms("org.atalaia.domination {\"capture_hold_ms\":3000,\"tick_s\":10}") ==
          3000);
    CHECK(oled_mode_hold_ms("org.example.hill {\"hold_ms\":5000}") == 5000);
    CHECK(oled_mode_hold_ms("org.atalaia.bomb {\"arm_hold_ms\":5000}") == 0);
    CHECK(oled_mode_hold_ms("org.atalaia.codes") == 0);
    CHECK(oled_mode_hold_ms(NULL) == 0);

    oled_hold_t blue = {"blue", 1600}; /* 1.6 s of 3 s: the 1.5 s step, half the bar */
    oled_text_t t = map("DOMINATION", "neutral", "{}");
    CHECK(t.bar == -1);
    CHECK(oled_text_hold(&t, &blue, 1, 3000));
    CHECK(t.bar == 50);
    CHECK(strcmp(t.foot, "BLUE") == 0);
    CHECK(strcmp(t.big, "NEUTRAL") == 0);

    t = map("DOMINATION", "captured", "{\"team\":\"red\",\"points\":12,\"since\":95}");
    CHECK(oled_text_hold(&t, &blue, 1, 3000));
    CHECK(t.bar == 50);
    CHECK(strcmp(t.foot, "BLUE") == 0);
    CHECK(strcmp(t.head_right, "12 pts") == 0); /* the points stay in the header */
    CHECK(!oled_text_held(&t, 230));            /* the held time waits for the bar to go */
    CHECK(strcmp(t.foot, "BLUE") == 0);

    /* The team that holds the zone: no bar (Domination ignores its holds). */
    oled_hold_t red = {"red", 2000};
    t = map("DOMINATION", "captured", "{\"team\":\"red\",\"since\":95}");
    CHECK(!oled_text_hold(&t, &red, 1, 3000));
    CHECK(t.bar == -1);
    CHECK(oled_text_held(&t, 230));
    CHECK(strcmp(t.foot, "held for 2:15") == 0);
    /* Several buttons down: the one held longest that is not the owner's. */
    oled_hold_t several[3] = {{"red", 2900}, {"green", 250}, {"blue", 750}};
    t = map("DOMINATION", "captured", "{\"team\":\"red\"}");
    CHECK(oled_text_hold(&t, several, 3, 3000));
    CHECK(t.bar == 25);
    CHECK(strcmp(t.foot, "BLUE") == 0);
    /* Just pressed: an empty bar; past the hold time: full. */
    oled_hold_t now = {"blue", 120};
    t = map("DOMINATION", "neutral", "{}");
    CHECK(oled_text_hold(&t, &now, 1, 3000));
    CHECK(t.bar == 0);
    now.ms = 4000;
    t = map("DOMINATION", "neutral", "{}");
    CHECK(oled_text_hold(&t, &now, 1, 3000));
    CHECK(t.bar == 100);

    /* The mode's own bar wins (King of the Hill); no hold time, no buttons, another screen:
     * nothing. */
    t = map("HILL", "neutral", "{\"taker\":\"red\",\"progress\":0.3}");
    CHECK(!oled_text_hold(&t, &blue, 1, 3000));
    CHECK(t.bar == 30);
    CHECK(strcmp(t.foot, "RED") == 0);
    t = map("DOMINATION", "neutral", "{}");
    CHECK(!oled_text_hold(&t, &blue, 1, 0));
    CHECK(!oled_text_hold(&t, &blue, 0, 3000));
    CHECK(t.bar == -1);
    CHECK(strcmp(t.foot, "Hold to capture") == 0);
    t = map("DOMINATION", "playing", "{\"role\":\"zone\"}");
    CHECK(!oled_text_hold(&t, &blue, 1, 3000));
    t = map("BOMB", "standby", "{\"arm\":\"red\"}");
    CHECK(!oled_text_hold(&t, &blue, 1, 3000));
    CHECK(t.bar == -1);
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

/* The splashes' version (FV-8): the version without its commit, then the commit. */
static void version_is(const char *version, const char *want1, const char *want2)
{
    char l1[40], l2[24];
    memset(l1, 'x', sizeof(l1));
    memset(l2, 'x', sizeof(l2));
    oled_version_lines(version, l1, sizeof(l1), l2, sizeof(l2));
    CHECK(strcmp(l1, want1) == 0);
    CHECK(strcmp(l2, want2) == 0);
}

static void test_version_lines(void)
{
    version_is("0.3.0", "v0.3.0", "");                               /* a release */
    version_is("0.4.0-dev", "v0.4.0-dev", "");                       /* a plain idf.py build */
    version_is("0.4.0-rc.1", "v0.4.0-rc.1", "");                     /* --fw-version= */
    version_is("0.4.0-dev.12+gabc1234", "v0.4.0-dev.12", "abc1234"); /* FV-3 */
    version_is("0.4.0-dev.12+gabc1234.dirty", "v0.4.0-dev.12", "abc1234*"); /* changes */
    version_is("0.3.0+5.g8560d54", "v0.3.0+5", "8560d54");                  /* past a release */
    version_is("0.3.0+5.g8560d54.dirty", "v0.3.0+5", "8560d54*");
    /* Other build metadata as it is. */
    version_is("0.3.0+bench", "v0.3.0", "bench");
    version_is("0.3.0+gxyz1234", "v0.3.0", "gxyz1234"); /* not hex */
    version_is("0.3.0+gab1", "v0.3.0", "gab1");         /* too short for a commit */
    version_is("0.3.0+gabc1234.clean", "v0.3.0", "gabc1234.clean");
    version_is("0.3.0+1.2.gabc1234", "v0.3.0", "1.2.gabc1234");
    version_is("0.3.0+5", "v0.3.0", "5");
    version_is("0.3.0+a.b.c.d.e", "v0.3.0", "a.b.c.d.e");
    version_is("", "", "");
    version_is(NULL, "", "");
    /* Cut to the buffers, always terminated. */
    char l1[6], l2[4];
    oled_version_lines("0.4.0-dev.12+gabc1234.dirty", l1, sizeof(l1), l2, sizeof(l2));
    CHECK(strcmp(l1, "v0.4.") == 0);
    CHECK(strcmp(l2, "abc") == 0);
    oled_version_lines("0.4.0-dev.12+gabc1234", NULL, 0, NULL, 0); /* no buffers: nothing */
}

/* A built-in mode's end screen, header and keypad title in the box's language; the name of a
 * mode package or an unknown template as its id says; English as before. */
static void test_names_in_the_boxs_language(void)
{
    char title[32];
    oled_mode_title("org.atalaia.bomb {}", title, sizeof(title));

    box_lang_set(BOX_LANG_EN);
    oled_text_t t = map(title, "defused", "{\"team\":\"blue\"}");
    CHECK(strcmp(t.head, "BOMB") == 0 && strcmp(t.big, "DEFUSED") == 0);

    box_lang_set(BOX_LANG_PT);
    t = map(title, "defused", "{\"team\":\"blue\"}");
    CHECK(strcmp(t.head, "BOMBA") == 0 && strcmp(t.big, "DESARMADA") == 0);
    CHECK(strcmp(t.foot, "BLUE") == 0); /* the team is the GM's word */
    t = map(title, "exploded", "{\"team\":\"red\"}");
    CHECK(strcmp(t.big, "EXPLODIU") == 0);

    box_lang_set(BOX_LANG_DE);
    t = map(title, "exploded", "{\"team\":\"red\"}");
    CHECK(strcmp(t.head, "BOMBE") == 0 && strcmp(t.big, "EXPLODIERT") == 0);
    t = map(title, "code_entry", "{\"title\":\"ARM\",\"digits\":1}");
    CHECK(strcmp(t.head, "SCH\xc3\x84RFEN") == 0);
    t = map(title, "code_entry", "{\"title\":\"DEFUSE\",\"digits\":1}");
    CHECK(strcmp(t.head, "ENTSCH\xc3\x84RFEN") == 0);

    box_lang_set(BOX_LANG_ZH_TW);
    t = map(title, "defused", "{\"team\":\"blue\"}");
    CHECK(strcmp(t.head, "炸彈") == 0 && strcmp(t.big, "已拆除") == 0);
    t = map(title, "code_entry", "{\"title\":\"CODE\",\"digits\":1}");
    CHECK(strcmp(t.head, "密碼") == 0);
    oled_mode_title("org.atalaia.kill_confirmed {}", title, sizeof(title));
    t = map(title, "tags", "{}");
    CHECK(strcmp(t.head, "擊殺確認") == 0 && strcmp(t.big, "標籤") == 0);
    /* A script's own header, a package's mode and a template with no name here stay as they are. */
    t = map(title, "code_entry", "{\"title\":\"Hello\",\"digits\":1}");
    CHECK(strcmp(t.head, "HELLO") == 0);
    t = map("ACME HILL", "my_screen", "{}");
    CHECK(strcmp(t.head, "ACME HILL") == 0 && strcmp(t.big, "MY SCREEN") == 0);

    box_lang_set(BOX_LANG_EN);
    oled_mode_title("org.atalaia.medic {}", title, sizeof(title));
    t = map(title, "medic_refused", "{\"team\":\"red\"}");
    CHECK(strcmp(t.head, "MEDIC") == 0 && strcmp(t.big, "MEDIC REFUSED") == 0);
    box_lang_set(BOX_LANG_PT);
    t = map(title, "medic_refused", "{\"team\":\"red\"}");
    CHECK(strcmp(t.head, "LIGADURAS") == 0 && strcmp(t.big, "RECUSADO") == 0);
    box_lang_set(BOX_LANG_EN);
}

void run_oled_view_tests(void)
{
    test_version_lines();
    test_mode_title();
    test_mode_message_changes_nothing();
    test_pin_entry();
    test_preset_select();
    test_timer_and_start();
    test_bomb_phases();
    test_other_screens();
    test_zone_screens();
    test_box_hold_bar();
    test_pack();
    test_names_in_the_boxs_language();
}
