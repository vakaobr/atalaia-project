/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Tests for the keyed rand() seeding (LIVE2-2) against protocol/vectors/rand.json: the state the
 * HMAC gives, the raw outputs, and rand(1, 1000000) from a script. The same vectors run in
 * simulator/tests/test_rand.py and the app's Dart tests.
 */
#include <stdio.h>
#include <string.h>

#include "atalaia/node.h"
#include "check.h"
#include "rand.h"
#include "rand_vectors.h"

typedef struct {
    char log[8][64];
    int logs;
} rand_log_t;

static void on_log(void *user, const char *message)
{
    rand_log_t *r = user;
    if (r->logs < 8) snprintf(r->log[r->logs], sizeof(r->log[0]), "%s", message);
    r->logs++;
}

static void lua_values(const uint8_t key[16], uint32_t seed, uint16_t node_id, rand_log_t *out)
{
    memset(out, 0, sizeof(*out));
    atalaia_node_config_t cfg = {0};
    cfg.node_id = node_id;
    cfg.game_seed = seed;
    cfg.instr_limit = 200000;
    if (key != NULL) memcpy(cfg.rand_key, key, 16);
    cfg.callbacks.log = on_log;
    cfg.callbacks.user = out;
    atalaia_node_t *n = atalaia_node_create(&cfg);
    CHECK(n != NULL);
    if (n == NULL) return;
    static const char src[] = "on('go', function()\n"
                              "for i = 1, 4 do log(rand(1, 1000000)) end\nend)\n";
    CHECK(atalaia_node_load(n, src, strlen(src), "=test"));
    CHECK(atalaia_node_input(n, "go", NULL));
    atalaia_node_destroy(n);
}

static void test_vectors(void)
{
    for (size_t i = 0; i < RAND_VECTOR_COUNT; i++) {
        const rand_vector_t *v = &rand_vectors[i];
        atalaia_rand_t r;
        atalaia_rand_seed_keyed(&r, v->key, v->game_seed, v->node_id);
        uint8_t state[16];
        for (int w = 0; w < 4; w++) {
            for (int b = 0; b < 4; b++) state[4 * w + b] = (uint8_t)(r.s[w] >> (8 * b));
        }
        if (memcmp(state, v->state, 16) != 0) printf("rand vector %s: wrong state\n", v->name);
        CHECK(memcmp(state, v->state, 16) == 0);
        for (int k = 0; k < 4; k++) {
            uint32_t x = atalaia_rand_next(&r);
            if (x != v->next[k]) printf("rand vector %s: output %d is %u\n", v->name, k, x);
            CHECK(x == v->next[k]);
        }
        rand_log_t got;
        lua_values(v->key, v->game_seed, v->node_id, &got);
        CHECK(got.logs == 4);
        for (int k = 0; k < 4 && k < got.logs; k++) {
            char want[32];
            snprintf(want, sizeof(want), "%u", v->lua[k]);
            if (strcmp(got.log[k], want) != 0)
                printf("rand vector %s: rand() %d is %s\n", v->name, k, got.log[k]);
            CHECK(strcmp(got.log[k], want) == 0);
        }
    }
}

/* What a player can see (seed, node id) is not enough: another key, or none, gives another game. */
static void test_unkeyed_differs(void)
{
    const rand_vector_t *v = &rand_vectors[0];
    rand_log_t keyed, plain;
    lua_values(v->key, v->game_seed, v->node_id, &keyed);
    lua_values(NULL, v->game_seed, v->node_id, &plain);
    CHECK(keyed.logs == 4 && plain.logs == 4);
    int same = 0;
    for (int k = 0; k < 4; k++) same += strcmp(keyed.log[k], plain.log[k]) == 0;
    CHECK(same < 4);
    /* And the unkeyed seed is the old one: the same inputs give the same game. */
    rand_log_t again;
    lua_values(NULL, v->game_seed, v->node_id, &again);
    for (int k = 0; k < 4; k++) CHECK(strcmp(plain.log[k], again.log[k]) == 0);
}

void run_rand_tests(void)
{
    test_vectors();
    test_unkeyed_differs();
}
