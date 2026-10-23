/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The scenario compiler's C entry points (atalaia/scenario.h, decision
 * PE24-109): a manifest checked and compiled, the size of the scenario
 * events worked out in Lua against the core's own codec, the limits, and
 * malformed, truncated and mutated data trees, every one answered with JSON
 * (never a crash: the sanitizer job runs this too). The rules themselves are
 * checked by both controllers' tests against protocol/vectors/scenario.json
 * and scenario_compile.json.
 */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "atalaia/codec.h"
#include "atalaia/scenario.h"
#include "scenario_internal.h"

static int failures;

#define CHECK(cond)                                                                                \
    do {                                                                                           \
        if (!(cond)) {                                                                             \
            fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);                        \
            failures++;                                                                            \
        }                                                                                          \
    } while (0)

/* A manifest with one objective, as a data tree; %s is the scenario's id. */
static const char MANIFEST[] =
    "{\"map\":[[{\"str\":\"id\"},{\"str\":\"%s\"}],"
    "[{\"str\":\"version\"},{\"str\":\"1\"}],"
    "[{\"str\":\"name\"},{\"str\":\"Ponte \\u00e9 \xf0\x9f\x98\x80\"}],"
    "[{\"str\":\"nodes\"},{\"map\":[[{\"str\":\"a\"},{\"map\":[[{\"str\":\"role\"},"
    "{\"str\":\"objective\"}]]}]]}],"
    "[{\"str\":\"objectives\"},{\"list\":[{\"map\":[[{\"str\":\"id\"},{\"str\":\"hill\"}],"
    "[{\"str\":\"name\"},{\"str\":\"Hill\"}],[{\"str\":\"type\"},{\"str\":\"capture_and_hold\"}],"
    "[{\"str\":\"target\"},{\"str\":\"a\"}]]}]}]]}";

static char *manifest(const char *id)
{
    size_t n = sizeof(MANIFEST) + strlen(id);
    char *out = malloc(n);
    snprintf(out, n, MANIFEST, id);
    return out;
}

static bool contains(const char *text, const char *part)
{
    return text != NULL && strstr(text, part) != NULL;
}

static void test_check_and_compile(void)
{
    char *tree = manifest("org.club.ponte");
    size_t len = 0;
    char *out = atalaia_scenario_check(tree, strlen(tree), &len);
    CHECK(out != NULL && len == strlen(out));
    CHECK(contains(out, "{\"ok\":true,\"problems\":[]}"));
    atalaia_scenario_free(out);

    out = atalaia_scenario_compile(tree, strlen(tree), &len);
    CHECK(contains(out, "\"ok\":true"));
    CHECK(contains(out, "\"id\":\"org.club.ponte\",\"version\":\"1\""));
    CHECK(contains(out, "\"mode.yaml\":\"# SPDX-"));
    CHECK(contains(out, "local SCENARIO = {"));
    CHECK(contains(out, "name: Ponte \xc3\xa9 \xf0\x9f\x98\x80"));
    atalaia_scenario_free(out);
    free(tree);

    /* An error: no package. */
    tree = manifest("Not An Id");
    out = atalaia_scenario_compile(tree, strlen(tree), NULL);
    CHECK(contains(out, "\"ok\":false"));
    CHECK(contains(out, "\"path\":\"id\",\"code\":\"bad_id\""));
    CHECK(!contains(out, "\"files\""));
    atalaia_scenario_free(out);
    free(tree);

    /* A literal, and what Lua cannot hold. */
    const char *literal = "{\"str\":\"a\\\"b\\n\"}";
    out = atalaia_scenario_literal(literal, strlen(literal), NULL);
    CHECK(contains(out, "{\"ok\":true,\"lua\":\"\\\"a\\\\\\\"b\\\\n\\\"\"}"));
    atalaia_scenario_free(out);
    literal = "{\"float\":\"nan\"}";
    out = atalaia_scenario_literal(literal, strlen(literal), NULL);
    CHECK(contains(out, "\"ok\":false"));
    atalaia_scenario_free(out);
    atalaia_scenario_free(NULL);
}

/*
 * The sizes of the scenario events (scenario/protocol.lua) are the core's
 * codec's: scenario.started for ids of every length from 100 to 200 bytes is
 * too large exactly when atalaia_event_encode makes it longer than a LoRa
 * payload, and the message gives the codec's size.
 */
static void test_event_sizes_match_the_codec(void)
{
    char id[260];
    char data[300];
    uint8_t buf[512];
    int crossed = 0;
    for (size_t n = 100; n <= 200; n++) {
        memcpy(id, "org.", 4);
        memset(id + 4, 'a', n - 4);
        id[n] = '\0';
        atalaia_event_t ev;
        CHECK(atalaia_event_init(&ev, 0, 0xFFFF, 0xFFFFFFFFu, "scenario.started", 8, 0,
                                 ATALAIA_PRIO_CRITICAL));
        snprintf(data, sizeof(data), "{\"scenario\":\"%s\"}", id);
        size_t size = atalaia_event_encode(&ev, data, buf, sizeof(buf), NULL);
        CHECK(size > 0);

        char *tree = manifest(id);
        char *out = atalaia_scenario_check(tree, strlen(tree), NULL);
        char expected[120];
        snprintf(expected, sizeof(expected), "scenario.started takes %zu bytes", size);
        if (size > 200) {
            crossed++;
            CHECK(contains(out, "\"code\":\"event_too_large\""));
            CHECK(contains(out, expected));
        } else {
            CHECK(!contains(out, "event_too_large"));
        }
        atalaia_scenario_free(out);
        free(tree);
    }
    CHECK(crossed > 0 && crossed < 101);
}

static void check_answer(const char *what, const char *tree, size_t len)
{
    size_t out_len = 0;
    char *out = atalaia_scenario_compile(tree, len, &out_len);
    if (out == NULL || out[0] != '{' || out_len != strlen(out) ||
        (!contains(out, "\"error\"") && !contains(out, "\"problems\""))) {
        fprintf(stderr, "FAIL: %s: %s\n", what, out != NULL ? out : "(null)");
        failures++;
    }
    atalaia_scenario_free(out);
}

static void test_malformed_trees(void)
{
    static const char *const bad[] = {
        "",
        "{",
        "[]",
        "null",
        "{\"str\":1}",
        "{\"int\":\"12x\"}",
        "{\"int\":\"99999999999999999999999999999999999999\"}",
        "{\"int\":\"-9223372036854775808\"}",
        "{\"float\":\"1e999\"}",
        "{\"float\":\"-0.0\"}",
        "{\"alias\":0}",
        "{\"list\":[{\"alias\":0}]}",
        "{\"map\":[[{\"null\":null},{\"map\":[]}],[{\"list\":[]},{\"null\":null}]]}",
        "{\"map\":[[{\"str\":\"id\"}]]}",
        "{\"str\":\"\\ud83d\"}",
        "{\"str\":\"\xed\xa0\xbd\"}",
        "{\"str\":\"\xff\"}",
        "{\"str\":\"\xc0\x80\"}",
        "{\"str\":\"\xf4\x90\x80\x80\"}",
        "{\"str\":\"a\tb\"}",
        "{\"timestamp\":\"x\"}",
        "{\"other\":{\"repr\":\"{1, 2}\",\"truthy\":true}}",
        "{\"other\":{\"repr\":1}}",
        "{\"unknown\":1}",
        "{\"null\":null} trailing",
        "{\"map\":[[{\"str\":\"objectives\"},{\"list\":[{\"map\":[[{\"str\":\"depends_on\"},"
        "{\"alias\":1}]]}]}]]}",
    };
    for (size_t i = 0; i < sizeof(bad) / sizeof(bad[0]); i++) {
        check_answer(bad[i], bad[i], strlen(bad[i]));
    }
    check_answer("NULL", NULL, 0);
    /* A NUL inside the text. */
    check_answer("a NUL", "{\"str\":\"a\0b\"}", 13);

    /* Nested past the limit, as lists and as the JSON's own brackets. */
    size_t depth = 5000;
    char *deep = malloc(depth * 20 + 32);
    size_t k = 0;
    for (size_t i = 0; i < depth; i++) {
        memcpy(deep + k, "{\"list\":[", 9);
        k += 9;
    }
    memcpy(deep + k, "{\"null\":null}", 13);
    k += 13;
    for (size_t i = 0; i < depth; i++) {
        memcpy(deep + k, "]}", 2);
        k += 2;
    }
    char *out = atalaia_scenario_check(deep, k, NULL);
    CHECK(contains(out, "\"code\":\"bad_manifest\""));
    CHECK(contains(out, "nested more than 100 levels deep"));
    atalaia_scenario_free(out);
    memset(deep, '[', depth);
    check_answer("5000 brackets", deep, depth);
    free(deep);
}

static void test_limits(void)
{
    char *tree = manifest("org.club.limits");
    atalaia_scenario_usage_t usage;
    char *out = atalaia_scenario_run_limited("compile", tree, strlen(tree), NULL,
                                             ATALAIA_SCENARIO_MEM_LIMIT,
                                             ATALAIA_SCENARIO_INSTR_LIMIT, &usage);
    CHECK(contains(out, "\"ok\":true"));
    CHECK(usage.mem_peak > 0 && usage.mem_peak < ATALAIA_SCENARIO_MEM_LIMIT / 8);
    CHECK(usage.instructions > 0 && usage.instructions < ATALAIA_SCENARIO_INSTR_LIMIT / 100);
    atalaia_scenario_free(out);

    out = atalaia_scenario_run_limited("compile", tree, strlen(tree), NULL, 64 * 1024,
                                       ATALAIA_SCENARIO_INSTR_LIMIT, NULL);
    CHECK(contains(out, "\"code\":\"too_complex\""));
    atalaia_scenario_free(out);
    out = atalaia_scenario_run_limited("compile", tree, strlen(tree), NULL,
                                       ATALAIA_SCENARIO_MEM_LIMIT, 5000, NULL);
    CHECK(contains(out, "\"code\":\"too_complex\""));
    atalaia_scenario_free(out);
    free(tree);

    /* A text larger than the memory limit. */
    size_t big = ATALAIA_SCENARIO_MEM_LIMIT + 1024;
    char *huge = malloc(big + 16);
    memcpy(huge, "{\"str\":\"", 8);
    memset(huge + 8, 'x', big);
    memcpy(huge + 8 + big, "\"}", 2);
    out = atalaia_scenario_check(huge, big + 10, NULL);
    CHECK(contains(out, "\"code\":\"too_complex\""));
    atalaia_scenario_free(out);
    free(huge);
}

/* A deterministic generator, so a failure here can be replayed. */
static uint32_t rng_state = 0x5ce7a710u;

static uint32_t next(void)
{
    rng_state ^= rng_state << 13;
    rng_state ^= rng_state >> 17;
    rng_state ^= rng_state << 5;
    return rng_state;
}

/* Mutated trees: bytes changed, cut, repeated and inserted, from a valid one. */
static void test_mutated_trees(int rounds)
{
    char *tree = manifest("org.club.fuzz");
    size_t len = strlen(tree);
    static const char pieces[][24] = {
        "{\"alias\":0}",
        "{\"alias\":3}",
        "{\"list\":[]}",
        "{\"map\":[]}",
        "{\"int\":\"-1\"}",
        "{\"float\":\"nan\"}",
        "{\"str\":\"\\ud800\"}",
        "{\"null\":null}",
        "{\"bool\":true}",
        "]",
        "}",
        "[",
        "{",
        ",",
        "\"",
        "\\",
        "\xff",
        "\xed\xa0\x80",
        "\\u0000",
        "{\"timestamp\":\"2026-1",
    };
    char *buf = malloc(len * 3 + 64);
    for (int round = 0; round < rounds; round++) {
        size_t n = len;
        memcpy(buf, tree, len);
        int edits = 1 + (int)(next() % 4);
        for (int e = 0; e < edits; e++) {
            size_t at = n > 0 ? next() % n : 0;
            switch (next() % 4) {
            case 0: /* change a byte */
                if (n > 0) buf[at] = (char)(next() & 0xFF);
                break;
            case 1: /* cut the rest */ n = at; break;
            case 2: { /* insert a piece */
                const char *p = pieces[next() % (sizeof(pieces) / sizeof(pieces[0]))];
                size_t pl = strlen(p);
                if (n + pl < len * 3 + 32) {
                    memmove(buf + at + pl, buf + at, n - at);
                    memcpy(buf + at, p, pl);
                    n += pl;
                }
                break;
            }
            default: { /* repeat a stretch */
                size_t span = 1 + next() % 40;
                if (at + span <= n && n + span < len * 3 + 32) {
                    memmove(buf + at + span, buf + at, n - at);
                    n += span;
                }
                break;
            }
            }
        }
        char what[40];
        snprintf(what, sizeof(what), "mutation %d", round);
        check_answer(what, buf, n);
    }
    free(buf);
    free(tree);
}

int main(int argc, char **argv)
{
    int rounds = argc > 1 ? atoi(argv[1]) : 3000;
    test_check_and_compile();
    test_event_sizes_match_the_codec();
    test_malformed_trees();
    test_limits();
    test_mutated_trees(rounds);
    if (failures) {
        fprintf(stderr, "%d failure(s)\n", failures);
        return 1;
    }
    printf("scenario tests passed (%d mutated trees)\n", rounds);
    return 0;
}
