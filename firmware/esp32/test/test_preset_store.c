/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Tests for preset_store: save, load, list and delete game presets
 * using a temporary POSIX directory.
 */
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "check.h"
#include "preset_store.h"

static char temp_dir[256];

static void setup_preset_dir(void)
{
    snprintf(temp_dir, sizeof(temp_dir), "/tmp/atalaia_test_%d", getpid());
    mkdir(temp_dir, 0755);
    preset_store_init(temp_dir);
}

/* ---- tests ---- */

static void test_save_load_roundtrip(void)
{
    setup_preset_dir();

    preset_t p = {0};
    snprintf(p.mode_id, sizeof(p.mode_id), "org.atalaia.domination");
    snprintf(p.params_json, sizeof(p.params_json), "{\"tick_s\":10}");
    snprintf(p.source, sizeof(p.source), "-- test");
    p.source_len = strlen(p.source);
    p.duration_s = 600;

    CHECK(preset_store_save(1, &p));

    preset_t loaded = {0};
    CHECK(preset_store_load(1, &loaded));
    CHECK(strcmp(loaded.mode_id, "org.atalaia.domination") == 0);
    CHECK(strcmp(loaded.params_json, "{\"tick_s\":10}") == 0);
    CHECK(strcmp(loaded.source, "-- test") == 0);
    CHECK(loaded.source_len == strlen("-- test"));
    CHECK(loaded.duration_s == 600);
}

static void test_list_presets(void)
{
    setup_preset_dir();

    preset_t p = {0};
    for (int i = 1; i <= 3; i++) {
        snprintf(p.mode_id, sizeof(p.mode_id), "mode_%d", i);
        snprintf(p.source, sizeof(p.source), "-- mode %d", i);
        p.source_len = strlen(p.source);
        p.duration_s = (uint32_t)(i * 60);
        CHECK(preset_store_save(i, &p));
    }

    preset_summary_t summaries[PRESET_MAX_SLOTS];
    int count = preset_store_list(summaries, PRESET_MAX_SLOTS);
    CHECK(count == 3);

    /* Verify mode_ids are present (order may vary). */
    int found = 0;
    for (int i = 0; i < count; i++) {
        if (strcmp(summaries[i].mode_id, "mode_1") == 0) found |= 1;
        if (strcmp(summaries[i].mode_id, "mode_2") == 0) found |= 2;
        if (strcmp(summaries[i].mode_id, "mode_3") == 0) found |= 4;
    }
    CHECK(found == 7);
}

static void test_delete_preset(void)
{
    setup_preset_dir();

    preset_t p = {0};
    snprintf(p.mode_id, sizeof(p.mode_id), "org.atalaia.bomb");
    snprintf(p.source, sizeof(p.source), "-- bomb");
    p.source_len = strlen(p.source);
    CHECK(preset_store_save(5, &p));

    preset_t loaded = {0};
    CHECK(preset_store_load(5, &loaded));

    CHECK(preset_store_delete(5));
    CHECK(!preset_store_load(5, &loaded));
}

static void test_invalid_index(void)
{
    setup_preset_dir();

    preset_t p = {0};
    snprintf(p.mode_id, sizeof(p.mode_id), "test");
    snprintf(p.source, sizeof(p.source), "-- x");
    p.source_len = 4;

    /* Index 0 is invalid (1-based). */
    CHECK(!preset_store_save(0, &p));
    CHECK(!preset_store_load(0, &p));
    CHECK(!preset_store_delete(0));

    /* Index beyond max is invalid. */
    CHECK(!preset_store_save(PRESET_MAX_SLOTS + 1, &p));
    CHECK(!preset_store_load(PRESET_MAX_SLOTS + 1, &p));
    CHECK(!preset_store_delete(PRESET_MAX_SLOTS + 1));
}

void run_preset_store_tests(void)
{
    test_save_load_roundtrip();
    test_list_presets();
    test_delete_preset();
    test_invalid_index();
}
