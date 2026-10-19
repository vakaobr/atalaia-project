/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Geo utilities (ADR-P4-9): the haversine distance and zone tests.
 *
 * Replays must give the same answers on every platform (decision M3-1), so
 * this file uses only +, -, *, / and sqrt, which IEEE 754 rounds correctly
 * on every machine the core targets (x86-64 and arm64 hardware, armv7 VFP,
 * the ESP32's software doubles), and no C library sine, cosine or arc
 * tangent, whose last bit differs between glibc, musl, bionic and newlib.
 * The sine, cosine and arc tangent below are Taylor polynomials on small
 * ranges, with coefficients written as exact hexadecimal doubles (the
 * nearest double to each 1/n! or 1/n). The build compiles this file with
 * -ffp-contract=off so that no compiler fuses a * b + c into one rounding
 * on a machine that has FMA (arm64, and clang contracts by default), and
 * the check below refuses a build that evaluates doubles in extended
 * precision (x87).
 */
#include "atalaia/geo.h"

#include <float.h>
#include <math.h>

#if !defined(FLT_EVAL_METHOD) || FLT_EVAL_METHOD != 0
#error "geo.c needs doubles evaluated as doubles (FLT_EVAL_METHOD 0), for identical results"
#endif
#if defined(__clang__)
#pragma STDC FP_CONTRACT OFF
#endif

#define RAD_PER_DEG 0x1.1df46a2529d39p-6 /* pi / 180 */
#define PI_2        0x1.921fb54442d18p+0 /* pi / 2 */
#define PI_6        0x1.0c152382d7365p-1 /* pi / 6 */
#define SQRT_3      0x1.bb67ae8584caap+0
#define TAN_15      0x1.126145e9ecd58p-2 /* 2 - sqrt(3), tan(pi / 12) */
#define TINY        0x1p-27              /* below it, sin x = x and cos x = 1 in doubles */

static double absd(double x)
{
    return x < 0.0 ? -x : x;
}

/* sin x for |x| <= pi/4: x - x^3/3! + ... - x^15/15! + x^17/17! (the next
 * term is below 1e-19). */
static double ksin(double x)
{
    if (absd(x) < TINY) {
        return x;
    }
    double z = x * x;
    double p = 0x1.952c77030ad4ap-49;   /* 1/17! */
    p = -0x1.ae7f3e733b81fp-41 + z * p; /* -1/15! */
    p = 0x1.6124613a86d09p-33 + z * p;  /* 1/13! */
    p = -0x1.ae64567f544e4p-26 + z * p; /* -1/11! */
    p = 0x1.71de3a556c734p-19 + z * p;  /* 1/9! */
    p = -0x1.a01a01a01a01ap-13 + z * p; /* -1/7! */
    p = 0x1.1111111111111p-7 + z * p;   /* 1/5! */
    p = -0x1.5555555555555p-3 + z * p;  /* -1/3! */
    return x + (x * z) * p;
}

/* cos x for |x| <= pi/4: 1 - x^2/2! + ... - x^18/18! (the next term is below
 * 1e-20). */
static double kcos(double x)
{
    if (absd(x) < TINY) {
        return 1.0;
    }
    double z = x * x;
    double p = -0x1.6827863b97d97p-53;  /* -1/18! */
    p = 0x1.ae7f3e733b81fp-45 + z * p;  /* 1/16! */
    p = -0x1.93974a8c07c9dp-37 + z * p; /* -1/14! */
    p = 0x1.1eed8eff8d898p-29 + z * p;  /* 1/12! */
    p = -0x1.27e4fb7789f5cp-22 + z * p; /* -1/10! */
    p = 0x1.a01a01a01a01ap-16 + z * p;  /* 1/8! */
    p = -0x1.6c16c16c16c17p-10 + z * p; /* -1/6! */
    p = 0x1.5555555555555p-5 + z * p;   /* 1/4! */
    p = -0.5 + z * p;                   /* -1/2! */
    return 1.0 + z * p;
}

/* sin and cos of an angle in degrees, |d| <= 90. Above 45 degrees the
 * complement 90 - |d| is exact (Sterbenz), so the polynomials only ever see
 * |x| <= pi/4. */
static double sin_deg(double d)
{
    double a = absd(d);
    double s = a <= 45.0 ? ksin(a * RAD_PER_DEG) : kcos((90.0 - a) * RAD_PER_DEG);
    return d < 0.0 ? -s : s;
}

static double cos_deg(double d)
{
    double a = absd(d);
    return a <= 45.0 ? kcos(a * RAD_PER_DEG) : ksin((90.0 - a) * RAD_PER_DEG);
}

/* atan u for |u| <= tan 15 degrees (0.268): u - u^3/3 + ... - u^27/27 (the
 * next term is below 1e-18). */
static double katan(double u)
{
    if (absd(u) < TINY) {
        return u;
    }
    double z = u * u;
    double p = -0x1.2f684bda12f68p-5;  /* -1/27 */
    p = 0x1.47ae147ae147bp-5 + z * p;  /* 1/25 */
    p = -0x1.642c8590b2164p-5 + z * p; /* -1/23 */
    p = 0x1.8618618618618p-5 + z * p;  /* 1/21 */
    p = -0x1.af286bca1af28p-5 + z * p; /* -1/19 */
    p = 0x1.e1e1e1e1e1e1ep-5 + z * p;  /* 1/17 */
    p = -0x1.1111111111111p-4 + z * p; /* -1/15 */
    p = 0x1.3b13b13b13b14p-4 + z * p;  /* 1/13 */
    p = -0x1.745d1745d1746p-4 + z * p; /* -1/11 */
    p = 0x1.c71c71c71c71cp-4 + z * p;  /* 1/9 */
    p = -0x1.2492492492492p-3 + z * p; /* -1/7 */
    p = 0x1.999999999999ap-3 + z * p;  /* 1/5 */
    p = -0x1.5555555555555p-2 + z * p; /* -1/3 */
    return u + (u * z) * p;
}

/* atan t for 0 <= t <= 1: above tan 15 degrees,
 * atan t = 30 degrees + atan((t sqrt 3 - 1) / (t + sqrt 3)). */
static double atan_unit(double t)
{
    if (t > TAN_15) {
        return PI_6 + katan((t * SQRT_3 - 1.0) / (t + SQRT_3));
    }
    return katan(t);
}

/* atan2(y, x) for y, x >= 0, not both 0. */
static double atan2_pos(double y, double x)
{
    if (y > x) {
        return PI_2 - atan_unit(x / y);
    }
    return atan_unit(y / x);
}

bool atalaia_geo_valid(double lat, double lon)
{
    /* NaN fails every comparison; infinities fail the ranges. */
    return lat >= -90.0 && lat <= 90.0 && lon >= -180.0 && lon <= 180.0;
}

double atalaia_geo_distance_m(double lat1, double lon1, double lat2, double lon2)
{
    if (!atalaia_geo_valid(lat1, lon1) || !atalaia_geo_valid(lat2, lon2)) {
        return NAN;
    }
    double dlat = lat2 - lat1;
    double dlon = lon2 - lon1;
    /* The shorter way round; exact, since 180 <= |dlon| <= 360 here. */
    if (dlon > 180.0) {
        dlon -= 360.0;
    } else if (dlon < -180.0) {
        dlon += 360.0;
    }
    double s_lat = sin_deg(dlat * 0.5);
    double s_lon = sin_deg(dlon * 0.5);
    double a = s_lat * s_lat + cos_deg(lat1) * cos_deg(lat2) * s_lon * s_lon;
    if (a > 1.0) {
        a = 1.0;
    }
    double c = 2.0 * atan2_pos(sqrt(a), sqrt(1.0 - a));
    return ATALAIA_GEO_EARTH_RADIUS_M * c;
}

bool atalaia_geo_in_circle(double lat, double lon, double centre_lat, double centre_lon,
                           double radius_m)
{
    if (!(radius_m >= 0.0) || radius_m > DBL_MAX) {
        return false;
    }
    /* NaN for an invalid point, and NaN <= r is false. */
    return atalaia_geo_distance_m(lat, lon, centre_lat, centre_lon) <= radius_m;
}

bool atalaia_geo_in_polygon(double lat, double lon, const double (*points)[2], size_t count)
{
    if (points == NULL || count < 3 || count > ATALAIA_GEO_POLYGON_MAX ||
        !atalaia_geo_valid(lat, lon)) {
        return false;
    }
    for (size_t i = 0; i < count; i++) {
        if (!atalaia_geo_valid(points[i][0], points[i][1])) {
            return false;
        }
    }
    /* y is latitude, x longitude. */
    bool inside = false;
    for (size_t i = 0, j = count - 1; i < count; j = i++) {
        double yi = points[i][0], xi = points[i][1];
        double yj = points[j][0], xj = points[j][1];
        /* On the edge from j to i (or on a vertex): inside. */
        if (lat >= (yi < yj ? yi : yj) && lat <= (yi < yj ? yj : yi) &&
            lon >= (xi < xj ? xi : xj) && lon <= (xi < xj ? xj : xi)) {
            double cross = (xj - xi) * (lat - yi) - (yj - yi) * (lon - xi);
            if (cross == 0.0) {
                return true;
            }
        }
        /* A ray towards increasing longitude crosses this edge. */
        if ((yi > lat) != (yj > lat)) {
            double x = xi + (lat - yi) * (xj - xi) / (yj - yi);
            if (lon < x) {
                inside = !inside;
            }
        }
    }
    return inside;
}
