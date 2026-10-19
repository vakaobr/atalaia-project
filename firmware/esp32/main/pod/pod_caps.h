/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I/O pod's capabilities (design specification section 7, decision PF6):
 * what the Field Box's hardware abstraction (main/hal/) offers, as capability
 * descriptors for IDENT, events for EVT and commands from CMD.
 *
 *   id        type     events (EVT)                         commands (CMD)
 *   btn.1-4   button   press, hold {"ms"} every 250 ms,     -
 *                      release {"ms"}
 *   keypad    keypad   key {"key": "0"-"9", "*", "#"}       clear
 *   ring      led      -                                    fill {"team"} or {"r","g","b"},
 *                                                           color, off, set_brightness,
 *                                                           progress
 *   audio     audio    -                                    tone {"freq","ms"}, play,
 *                                                           stop, set_volume
 *   nfc       nfc      tag {"uid", "tag"}                   -
 *   case      tamper   opened, closed                       -
 *
 * Only what is fitted is listed: the buttons whose pin is set, the keypad
 * and the NFC reader if they answered at boot, the ring and the amplifier if
 * their pins are set, the enclosure switch if its pin is set. Button N stands
 * for the game's N-th team, as on a Field Box; a button the builder gave a
 * colour carries it as "team" (the phone uses it when the game has a team of
 * that name, decision PF6). IDENT must fit in 256 bytes: when the colours do
 * not fit, they are left out (pod_caps_descriptors' with_teams).
 *
 * The NFC reader forwards a player tag's record (protocol/nfc-tag.md) as hex,
 * or just the UID for a card without one; join cards are not forwarded (the
 * phone joins by QR code or text). The enclosure switch is armed once it has
 * read closed, so a pod built without one never reports a tamper (PF8).
 *
 * Plain C on the HAL ops: host-tested with recording ops (test/test_pod.c).
 */
#ifndef ATALAIA_POD_CAPS_H
#define ATALAIA_POD_CAPS_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "atalaia/proxy.h"
#include "hal/hal.h"
#include "key_filter.h"

#define POD_BUTTONS            4
#define POD_HOLD_INTERVAL_MS   250 /* modes/README.md: team_input.hold every 250 ms */
#define POD_NFC_POLL_MS        300 /* as the Field Box polls during a game */
#define POD_KEY_SCAN_MS        10  /* key_filter.h: scans 10 ms apart */
#define POD_TAMPER_DEBOUNCE_MS 50
#define POD_NFC_MEM            888 /* NTAG216 user memory */

typedef struct {
    bool button[POD_BUTTONS];      /* the button's pin is set */
    const char *team[POD_BUTTONS]; /* its team (colour) if the builder set one, else NULL */
    bool keypad;                   /* the PCF8574 answered */
    bool nfc;                      /* the PN532 answered */
    bool leds;                     /* the ring's data pin is set */
    uint16_t led_count;
    bool audio;  /* the I2S pins are set */
    bool tamper; /* the enclosure switch's pin is set */
} pod_caps_config_t;

/* Sound on the pod: queued, so a CMD never waits for a tone to end. */
typedef struct {
    void (*tone)(void *ctx, uint32_t freq_hz, uint32_t ms); /* freq 0: a pause */
    void (*stop)(void *ctx);
    void (*volume)(void *ctx, uint8_t percent);
    void *ctx;
} pod_audio_t;

/* Sends an EVT (pod_event). */
typedef bool (*pod_emit_fn)(void *ctx, const char *cap_id, const char *event,
                            const char *data_json);

typedef struct {
    pod_caps_config_t cfg;
    const hal_t *hal;
    pod_audio_t audio;

    uint32_t now_ms;
    bool started;

    /* Buttons. */
    bool pressed[POD_BUTTONS];
    uint32_t held_ms[POD_BUTTONS];
    uint32_t since_hold[POD_BUTTONS];

    /* Keypad. */
    key_filter_t keys;
    uint32_t last_scan_ms;

    /* NFC. */
    uint32_t last_nfc_ms;
    uint8_t last_uid[10];
    uint8_t last_uid_len;
    uint8_t mem[POD_NFC_MEM];

    /* Enclosure switch. */
    bool tamper_armed; /* has read closed once */
    bool tamper_open;  /* debounced state */
    int tamper_raw;
    uint32_t tamper_since_ms;

    /* LED ring. */
    uint8_t fill[3];
    uint8_t brightness;
    uint32_t commands_unknown;
} pod_caps_t;

void pod_caps_init(pod_caps_t *c, const pod_caps_config_t *cfg, const hal_t *hal,
                   const pod_audio_t *audio);

/*
 * The capability descriptors, as the JSON array IDENT carries, with the
 * buttons' colours when with_teams. Returns its length, or 0.
 */
size_t pod_caps_descriptors(const pod_caps_t *c, char *out, size_t cap, bool with_teams);

/*
 * Reads the hardware and sends the events: call every few milliseconds.
 * tamper_raw: the enclosure switch, -1 not fitted, 0 closed, 1 open.
 */
void pod_caps_poll(pod_caps_t *c, uint32_t now_ms, int tamper_raw, pod_emit_fn emit, void *ctx);

/* A link became active: an open case is reported again. */
void pod_caps_report(pod_caps_t *c, pod_emit_fn emit, void *ctx);

/* A CMD for one of the capabilities. Returns false for an unknown capability or method. */
bool pod_caps_command(pod_caps_t *c, const atalaia_proxy_msg_t *m);

/* A team's colour on the ring ("red", "blue"...; "none" and "off" are black). */
void pod_caps_team_rgb(const char *team, uint8_t rgb[3]);

#endif /* ATALAIA_POD_CAPS_H */
