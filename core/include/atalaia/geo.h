/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Geo utilities (ADR-P4-9): great-circle distance and zone tests on WGS 84
 * latitudes and longitudes in degrees, for geo.distance() and geo.in_zone().
 *
 * Every result is the same, bit for bit, on every platform the core runs on
 * (desktop, ESP32, Android): geo.c uses only IEEE 754 additions,
 * subtractions, multiplications, divisions and square roots, which are
 * correctly rounded everywhere, with its own sine, cosine and arc tangent
 * instead of the C library's, and is compiled without contracting a * b + c
 * into a fused multiply-add (decision M3-1).
 */
#ifndef ATALAIA_GEO_H
#define ATALAIA_GEO_H

#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* The sphere's radius: the mean radius of the Earth, 6,371 km (ADR-P4-9). */
#define ATALAIA_GEO_EARTH_RADIUS_M 6371000.0

/* The most vertices a polygon zone may have. */
#define ATALAIA_GEO_POLYGON_MAX 32

/* True for a finite latitude from -90 to 90 and a finite longitude from
 * -180 to 180 (both inclusive). */
bool atalaia_geo_valid(double lat, double lon);

/* The great-circle distance in metres between two points, by the haversine
 * formula on a sphere of ATALAIA_GEO_EARTH_RADIUS_M. NaN when a point is not
 * valid (atalaia_geo_valid). */
double atalaia_geo_distance_m(double lat1, double lon1, double lat2, double lon2);

/* True when the point is at most radius_m metres from the centre
 * (atalaia_geo_distance_m <= radius_m: the edge is inside). False when a
 * point is not valid or radius_m is negative or not finite. */
bool atalaia_geo_in_circle(double lat, double lon, double centre_lat, double centre_lon,
                           double radius_m);

/* True when the point is inside the polygon of count vertices
 * (points[i][0] latitude, points[i][1] longitude, the last joined to the
 * first), by ray casting with latitude and longitude as plane coordinates.
 * A point on a vertex, or on an edge as the arithmetic finds it, is inside.
 * For simple polygons that do not cross the 180th meridian; a
 * self-intersecting polygon gives the even-odd answer. False when count is
 * below 3 or above ATALAIA_GEO_POLYGON_MAX, or any coordinate is not
 * valid. */
bool atalaia_geo_in_polygon(double lat, double lon, const double (*points)[2], size_t count);

#ifdef __cplusplus
}
#endif

#endif /* ATALAIA_GEO_H */
