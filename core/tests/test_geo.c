/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Tests for the geo utilities (ADR-P4-9) against protocol/vectors/geo.json:
 * known answers from the sources the vectors cite, within their tolerance,
 * and every result's exact bits (the determinism pins, decision M3-1), both
 * through the C functions and through geo.distance() and geo.in_zone() in a
 * script. simulator/tests/test_geo.py runs the same vectors through the
 * shared library.
 */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "atalaia/geo.h"
#include "atalaia/node.h"
#include "check.h"
#include "geo_vectors.h"

#define CHECK_NAMED(cond, name)                                                                    \
    do {                                                                                           \
        if (!(cond)) {                                                                             \
            fprintf(stderr, "FAIL %s:%d: %s (vector %s)\n", __FILE__, __LINE__, #cond, (name));    \
            check_failures++;                                                                      \
        }                                                                                          \
    } while (0)

#define GEO_TEXT 512

typedef struct {
    int logs;
    char log[GEO_TEXT];
    int errors;
    char error[GEO_TEXT];
    int events;
} geo_recorder_t;

static void on_event(void *user, const atalaia_event_t *ev, const char *data)
{
    geo_recorder_t *r = user;
    r->events++;
    if (strcmp(ev->type, "script.error") == 0) {
        r->errors++;
        snprintf(r->error, sizeof(r->error), "%s", data);
    }
}

static void on_log(void *user, const char *message)
{
    geo_recorder_t *r = user;
    r->logs++;
    snprintf(r->log, sizeof(r->log), "%s", message);
}

static atalaia_node_t *make_node(geo_recorder_t *r)
{
    memset(r, 0, sizeof(*r));
    atalaia_node_config_t cfg = {0};
    cfg.node_id = 3;
    cfg.game_seed = 1;
    cfg.instr_limit = 200000;
    cfg.callbacks.event = on_event;
    cfg.callbacks.log = on_log;
    cfg.callbacks.user = r;
    atalaia_node_t *n = atalaia_node_create(&cfg);
    CHECK(n != NULL);
    return n;
}

/* Runs src as the body of a handler; returns the node (the caller destroys it). */
static atalaia_node_t *run(geo_recorder_t *r, const char *src)
{
    atalaia_node_t *n = make_node(r);
    char script[4096];
    snprintf(script, sizeof(script), "on('go', function()\n%s\nend)\n", src);
    CHECK(atalaia_node_load(n, script, strlen(script), "=test"));
    CHECK(atalaia_node_input(n, "go", NULL));
    return n;
}

static uint64_t bits_of(double d)
{
    uint64_t u;
    memcpy(&u, &d, sizeof(u));
    return u;
}

static void test_distance_vectors(void)
{
    for (size_t i = 0; i < GEO_DISTANCE_VECTOR_COUNT; i++) {
        const geo_distance_vector_t *v = &geo_distance_vectors[i];
        double d = atalaia_geo_distance_m(v->a_lat, v->a_lon, v->b_lat, v->b_lon);
        if (v->known) {
            CHECK_NAMED(fabs(d - v->metres) <= v->tolerance_m, v->name);
        }
        /* Exact, on every platform (M3-1), and the same both ways round. */
        CHECK_NAMED(bits_of(d) == v->bits, v->name);
        CHECK_NAMED(bits_of(atalaia_geo_distance_m(v->b_lat, v->b_lon, v->a_lat, v->a_lon)) ==
                        v->bits,
                    v->name);
    }
}

/* The same distances from a script: the coordinates go in as hexadecimal
 * float literals and the result comes out with %a, so no digit is lost. */
static void test_distance_from_lua(void)
{
    for (size_t i = 0; i < GEO_DISTANCE_VECTOR_COUNT; i++) {
        const geo_distance_vector_t *v = &geo_distance_vectors[i];
        char src[512];
        snprintf(src, sizeof(src), "log(string.format('%%a', geo.distance(%a, %a, %a, %a)))",
                 v->a_lat, v->a_lon, v->b_lat, v->b_lon);
        geo_recorder_t r;
        atalaia_node_t *n = run(&r, src);
        CHECK_NAMED(r.logs == 1 && r.errors == 0, v->name);
        CHECK_NAMED(bits_of(strtod(r.log, NULL)) == v->bits, v->name);
        atalaia_node_destroy(n);
    }
}

static void test_zone_vectors(void)
{
    for (size_t i = 0; i < GEO_ZONE_VECTOR_COUNT; i++) {
        const geo_zone_vector_t *v = &geo_zone_vectors[i];
        bool inside = v->circle
                          ? atalaia_geo_in_circle(v->lat, v->lon, v->c_lat, v->c_lon, v->radius_m)
                          : atalaia_geo_in_polygon(v->lat, v->lon, v->points, v->count);
        CHECK_NAMED(inside == v->inside, v->name);

        char src[2048];
        int len;
        if (v->circle) {
            len = snprintf(src, sizeof(src),
                           "log(geo.in_zone(%a, %a, { type = 'circle', lat = %a, lon = %a, "
                           "radius_m = %a }))",
                           v->lat, v->lon, v->c_lat, v->c_lon, v->radius_m);
        } else {
            len =
                snprintf(src, sizeof(src), "log(geo.in_zone(%a, %a, { type = 'polygon', points = {",
                         v->lat, v->lon);
            for (size_t k = 0; k < v->count; k++) {
                len += snprintf(src + len, sizeof(src) - (size_t)len, "{%a, %a},", v->points[k][0],
                                v->points[k][1]);
            }
            len += snprintf(src + len, sizeof(src) - (size_t)len, "} }))");
        }
        CHECK(len > 0 && (size_t)len < sizeof(src));
        geo_recorder_t r;
        atalaia_node_t *n = run(&r, src);
        CHECK_NAMED(r.logs == 1 && r.errors == 0, v->name);
        CHECK_NAMED(strcmp(r.log, v->inside ? "true" : "false") == 0, v->name);
        atalaia_node_destroy(n);
    }
}

/* Argument errors are script errors (script.error), and the node runs on. */
static void test_error_vectors(void)
{
    for (size_t i = 0; i < GEO_ERROR_VECTOR_COUNT; i++) {
        geo_recorder_t r;
        atalaia_node_t *n = run(&r, geo_error_vectors[i].script);
        CHECK_NAMED(r.errors == 1, geo_error_vectors[i].name);
        CHECK_NAMED(strstr(r.error, geo_error_vectors[i].message) != NULL,
                    geo_error_vectors[i].name);
        CHECK_NAMED(atalaia_node_status(n) == ATALAIA_NODE_RUNNING, geo_error_vectors[i].name);
        atalaia_node_destroy(n);
    }
}

/* The C functions refuse what the script API refuses. */
static void test_c_arguments(void)
{
    CHECK(isnan(atalaia_geo_distance_m(90.5, 0, 0, 0)));
    CHECK(isnan(atalaia_geo_distance_m(0, 0, 0, -180.5)));
    CHECK(isnan(atalaia_geo_distance_m(NAN, 0, 0, 0)));
    CHECK(isnan(atalaia_geo_distance_m(0, INFINITY, 0, 0)));
    CHECK(atalaia_geo_valid(-90, -180) && atalaia_geo_valid(90, 180));
    CHECK(!atalaia_geo_valid(0, NAN));

    CHECK(atalaia_geo_in_circle(1, 1, 1, 1, 0));
    CHECK(!atalaia_geo_in_circle(1, 1, 1, 1, -1));
    CHECK(!atalaia_geo_in_circle(1, 1, 1, 1, NAN));
    CHECK(!atalaia_geo_in_circle(1, 1, 1, 1, INFINITY));
    CHECK(!atalaia_geo_in_circle(91, 1, 1, 1, 10));

    static const double tri[3][2] = {{0, 0}, {0, 10}, {10, 0}};
    CHECK(atalaia_geo_in_polygon(1, 1, tri, 3));
    CHECK(!atalaia_geo_in_polygon(1, 1, tri, 2));
    CHECK(!atalaia_geo_in_polygon(1, 1, NULL, 3));
    CHECK(!atalaia_geo_in_polygon(1, 1, tri, ATALAIA_GEO_POLYGON_MAX + 1));
    CHECK(!atalaia_geo_in_polygon(NAN, 1, tri, 3));
    static const double bad[3][2] = {{0, 0}, {0, 10}, {10, 200}};
    CHECK(!atalaia_geo_in_polygon(1, 1, bad, 3));

    /* 32 vertices are allowed: a 32-gon around (0, 0). */
    double ring[ATALAIA_GEO_POLYGON_MAX][2];
    for (int k = 0; k < ATALAIA_GEO_POLYGON_MAX; k++) {
        double t = 2.0 * 3.14159265358979 * k / ATALAIA_GEO_POLYGON_MAX;
        ring[k][0] = cos(t);
        ring[k][1] = sin(t);
    }
    CHECK(atalaia_geo_in_polygon(0, 0, (const double(*)[2])ring, ATALAIA_GEO_POLYGON_MAX));
    CHECK(!atalaia_geo_in_polygon(1.5, 0, (const double(*)[2])ring, ATALAIA_GEO_POLYGON_MAX));
}

/* geo is a table of two functions in every script, and an integer argument is
 * a number like any other. */
static void test_lua_surface(void)
{
    geo_recorder_t r;
    atalaia_node_t *n =
        run(&r, "local k = {} for name in pairs(geo) do k[#k + 1] = name end\n"
                "table.sort(k)\n"
                "log(table.concat(k, ','), geo.distance(0, 0, 0, 0), "
                "geo.in_zone(0, 0, { type = 'circle', lat = 0, lon = 0, radius_m = 0 }))");
    CHECK(r.logs == 1 && r.errors == 0);
    CHECK(strcmp(r.log, "distance,in_zone 0.0 true") == 0);
    atalaia_node_destroy(n);
}

void run_geo_tests(void)
{
    test_distance_vectors();
    test_distance_from_lua();
    test_zone_vectors();
    test_error_vectors();
    test_c_arguments();
    test_lua_surface();
}
