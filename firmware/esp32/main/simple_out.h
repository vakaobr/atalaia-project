/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The simple output's signal (draft RFC "The expansion port", decisions EXP-32 to EXP-35): one
 * GPIO, through a spare gate of the 74AHCT125, to an off-the-shelf RC relay switch. The switch
 * closes its relay on long servo pulses and opens it on short ones, and opens it when the pulses
 * stop: the box's lease, done in hardware.
 *
 *   - 50 Hz frames: SO_ON_US (2.0 ms) is on, SO_OFF_US (1.0 ms) is off. While a game runs a
 *     channel that is off still gets 1.0 ms pulses, so the switch sees a live "off".
 *   - The pulses come in bursts the game task renews, never free-running: the RMT peripheral
 *     sends a given number of frames and stops by itself (not LEDC, which would keep pulsing
 *     after a hang). The scheduler keeps SO_BURST_FRAMES frames (0.5 s) queued and tops them up
 *     every SO_RENEW_MS: the first burst is SO_BURST_FRAMES frames, each renewal the frames that
 *     bring the queue back to 0.5 s. So whatever stops the game task, the pulses stop within
 *     0.5 s, and the switch's own signal-loss fail-safe opens the relay (EXP-37).
 *   - A change of width (on to off, off to on) flushes what is queued and starts a new burst
 *     at once: an off never waits behind 0.5 s of on pulses.
 *   - The end of a signal (the game paused, ended or halted; boot): SO_BURST_FRAMES frames of
 *     1.0 ms, then nothing: the pin is held low (the RMT's idle level, and the 10 kohm
 *     pull-down at the gate's input), the switch's signal-lost state, which is off.
 *
 * Platform-free: the RMT is a callback (simple_out_esp.c on the ESP32, a fake in the host tests,
 * log lines in the host box), and the pin checks (simple_out_pin_problem) are the ones the
 * Kconfig build refuses at compile time.
 */
#ifndef ATALAIA_SIMPLE_OUT_H
#define ATALAIA_SIMPLE_OUT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SO_FRAME_MS     20   /* 50 Hz */
#define SO_ON_US        2000 /* on: 2.0 ms */
#define SO_OFF_US       1000 /* off: 1.0 ms */
#define SO_BURST_FRAMES 25   /* 0.5 s of frames queued at most */
#define SO_RENEW_MS     200  /* the game task tops the burst up this often */
#define SO_BURST_MS     (SO_BURST_FRAMES * SO_FRAME_MS)

typedef struct {
    void *ctx;
    /* Queues `frames` frames of width_us pulses (each frame SO_FRAME_MS long), after what is
     * queued, or instead of it (flush: what was queued is dropped, the new burst starts now).
     * False when the peripheral refused (the scheduler tries again at the next turn). */
    bool (*send)(void *ctx, uint16_t width_us, uint16_t frames, bool flush);
} simple_out_rmt_t;

typedef struct {
    int gpio;
    simple_out_rmt_t rmt;
    uint16_t width;      /* the width queued last; 0: never sent */
    uint32_t horizon_ms; /* when what is queued ends */
    uint32_t renew_ms;   /* the last top-up */
    bool live;           /* topping up; false once the signal's end is queued */
    bool pulsing;        /* horizon_ms is ahead (or was, at the last call) */
    uint32_t bursts;     /* sends so far (tests, the host box's status) */
} simple_out_t;

void simple_out_init(simple_out_t *so, int gpio, const simple_out_rmt_t *rmt);

/*
 * Every turn of the game task: on (2.0 ms pulses) or off (1.0 ms), live (keep the pulses coming:
 * a game runs, or the channel is on) or not (end the signal: one last burst of 1.0 ms, then the
 * pin low). The out_backend_t drive of outputs.h.
 */
void simple_out_drive(simple_out_t *so, bool on, bool live, uint32_t now_ms);

/* outputs.h's back-end callback: ctx is a simple_out_t. */
void simple_out_backend_drive(void *ctx, bool on, bool live, uint32_t now_ms);

/* True while queued pulses are still going out (now_ms before the horizon). */
bool simple_out_pulsing(const simple_out_t *so, uint32_t now_ms);

/* ---- Which GPIO (EXP-34; the Kconfig build refuses the same at compile time) ---- */

typedef enum { SO_BOARD_V4_3 = 0, SO_BOARD_V4_2 } so_board_t;

/* A pin another part of the build uses (its Kconfig name for the message). */
typedef struct {
    const char *name;
    int gpio;
} so_pin_use_t;

/*
 * NULL when gpio may carry a simple output on this board revision, with the buzzer on
 * buzzer_gpio (-1: no buzzer) and the parts in `used` on their pins (entries with gpio -1 are
 * ignored); otherwise why not. Refused: not a GPIO of the ESP32-S3; a board-internal pin (the
 * radio, the flash and PSRAM, USB, the OLED's reset, the GNSS connector, UART0, the boot button);
 * the other revision's front-end-module line (GPIO 5 on a V4.3, 46 on a V4.2); GPIO 45 when the
 * buzzer has it (the buzzer or a second output); any pin a part in `used` has. GPIO 46 (V4.3),
 * 5 (V4.2), 45, 1, 3, 33 and 15 are fine (the 10 kohm pull-down holds a strap low at reset).
 */
const char *simple_out_pin_problem(int gpio, so_board_t board, int buzzer_gpio,
                                   const so_pin_use_t *used, size_t used_count);

#endif /* ATALAIA_SIMPLE_OUT_H */
