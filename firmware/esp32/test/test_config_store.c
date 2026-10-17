/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Tests for config_store: NVS-like key-value storage (in-memory on Linux).
 */
#include <stdio.h>
#include <string.h>

#include "check.h"
#include "config_store.h"

/* ---- tests ---- */

static void test_configured_flag(void)
{
    config_store_init();

    CHECK(!config_store_is_configured());

    config_store_set_configured(true);
    CHECK(config_store_is_configured());

    config_store_set_configured(false);
    CHECK(!config_store_is_configured());
}

static void test_string_values(void)
{
    config_store_init();

    config_store_set_str("node_name", "test-box");

    char buf[64] = {0};
    CHECK(config_store_get_str("node_name", buf, sizeof(buf)));
    CHECK(strcmp(buf, "test-box") == 0);

    /* Unknown key returns false. */
    CHECK(!config_store_get_str("nonexistent", buf, sizeof(buf)));
}

static void test_uint_values(void)
{
    config_store_init();

    config_store_set_u32("brightness", 80);
    CHECK(config_store_get_u32("brightness", 50) == 80);

    /* Unknown key returns the default. */
    CHECK(config_store_get_u32("volume", 42) == 42);
}

static void test_reset_clears_all(void)
{
    config_store_init();

    config_store_set_str("node_name", "alpha");
    config_store_set_u32("brightness", 100);
    config_store_set_configured(true);

    config_store_reset();

    char buf[64];
    CHECK(!config_store_get_str("node_name", buf, sizeof(buf)));
    CHECK(config_store_get_u32("brightness", 50) == 50);
    CHECK(!config_store_is_configured());
}

void run_config_store_tests(void)
{
    test_configured_flag();
    test_string_values();
    test_uint_values();
    test_reset_clears_all();
}
