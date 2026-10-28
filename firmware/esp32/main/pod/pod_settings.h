/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I/O pod's settings that the field controller can push over the radio
 * (decision PODC, protocol/pod-config.md): CMD opcode 10, a sealed game
 * packet like every other CMD, whose params are one small JSON object:
 *
 *   {"v":1,"rev":7,"btn":["red","","","blue"],"bright":60,"vol":80,"tamper":true}
 *
 * v is the format's version (1; the pod ignores a higher one), rev counts the
 * controller's pushes (the pod applies a rev only when it is above the last
 * one it took, and acknowledges the same rev again without applying it twice).
 * Every other key is optional and changes one setting: btn the four buttons'
 * colours ("" = the game's N-th team), bright the LED ring's default
 * brightness in percent, vol the sound's volume in percent, tamper whether the
 * enclosure switch reports (never turns on a switch that is not fitted).
 * "reset":true first drops every setting pushed so far (the build's Kconfig
 * values are back). A key the pod does not know, a value out of range, or a
 * colour it has no name for refuse the whole command: nothing is applied.
 *
 * What is NOT here, on purpose: the radio's key, region and channel, the pins,
 * the Bluetooth security and the log. Wiring facts stay in the build's Kconfig
 * and a pod has no admin menu, so no admin PIN (decision PODC-2).
 *
 * Plain C: parsing, merging and writing the stored form are host-tested
 * (test/test_pod_settings.c, the shared vectors protocol/vectors/pod_config.json).
 */
#ifndef ATALAIA_POD_SETTINGS_H
#define ATALAIA_POD_SETTINGS_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "pod.h"
#include "pod_caps.h"

#define POD_SETTINGS_VERSION    1
#define POD_SETTINGS_JSON_MAX   128 /* a CMD's params: its JSON form fits 127 bytes */
#define POD_SETTINGS_COLOUR_MAX 8   /* "purple" and a NUL */
#define POD_CMD_POD             10  /* the CMD opcode (RFC 0001 Amendment 17) */

enum {
    POD_SET_BTN = 1u << 0,
    POD_SET_BRIGHT = 1u << 1,
    POD_SET_VOL = 1u << 2,
    POD_SET_TAMPER = 1u << 3,
};

typedef struct {
    uint32_t rev; /* the last rev taken; 0 = nothing pushed yet */
    uint8_t set;  /* POD_SET_*: the settings that were pushed (the rest follow the build) */
    char btn[POD_BUTTONS][POD_SETTINGS_COLOUR_MAX];
    uint8_t bright;
    uint8_t vol;
    bool tamper;
} pod_settings_t;

/* A parsed command (not yet applied). */
typedef struct {
    uint32_t rev;
    bool reset;
    uint8_t set;
    char btn[POD_BUTTONS][POD_SETTINGS_COLOUR_MAX];
    uint8_t bright;
    uint8_t vol;
    bool tamper;
} pod_settings_cmd_t;

/* (pod_config_result_t is in pod.h.) */

/* Parses a command's params. Returns false (nothing in *out is meant) when it is not valid
 * or its "v" is not 1. */
bool pod_settings_parse(const char *json, pod_settings_cmd_t *out);

/* The stored form of the settings (the same JSON, with the last rev); returns its length, or 0. */
size_t pod_settings_to_json(const pod_settings_t *s, char *out, size_t cap);

/* Reads the stored form back (boot). A damaged one gives the empty settings. */
void pod_settings_load(pod_settings_t *s, const char *json);

/*
 * Handles a CMD pod: parses it, decides by rev, merges it into *s (which the caller saves when
 * the result is APPLIED) and, when it applied, puts the settings on the capabilities (apply
 * below). *rev is the command's rev on APPLIED and SAME.
 */
pod_config_result_t pod_settings_handle(pod_settings_t *s, const char *json, pod_caps_t *caps,
                                        const pod_caps_config_t *build, uint32_t *rev);

/*
 * Puts the settings on the capabilities: the buttons' colours (the pointers refer into *s: keep
 * it alive), the ring's brightness, the sound's volume, the enclosure switch. build: what the
 * Kconfig and the boot gave, which every setting not pushed follows.
 */
void pod_settings_apply(const pod_settings_t *s, pod_caps_t *caps, const pod_caps_config_t *build);

#endif /* ATALAIA_POD_SETTINGS_H */
