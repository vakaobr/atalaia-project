/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The simple output's burst scheduler and pin checks (simple_out.h; decisions EXP-32, EXP-34).
 */
#include "simple_out.h"

#include <stdio.h>
#include <string.h>

void simple_out_init(simple_out_t *so, int gpio, const simple_out_rmt_t *rmt)
{
    memset(so, 0, sizeof(*so));
    so->gpio = gpio;
    if (rmt != NULL) so->rmt = *rmt;
    /* Until the first drive: as at boot, the signal is to end (1.0 ms for 0.5 s, then low). */
    so->live = true;
    so->width = SO_OFF_US;
}

bool simple_out_pulsing(const simple_out_t *so, uint32_t now_ms)
{
    return so->pulsing && (int32_t)(so->horizon_ms - now_ms) > 0;
}

static bool send(simple_out_t *so, uint16_t width, uint16_t frames, bool flush)
{
    if (so->rmt.send == NULL || !so->rmt.send(so->rmt.ctx, width, frames, flush)) return false;
    so->bursts++;
    return true;
}

/* A new burst of SO_BURST_FRAMES frames now, instead of what is queued. */
static void restart(simple_out_t *so, uint16_t width, uint32_t now)
{
    bool queued = simple_out_pulsing(so, now);
    if (!send(so, width, SO_BURST_FRAMES, queued)) return;
    so->width = width;
    so->horizon_ms = now + SO_BURST_MS;
    so->renew_ms = now;
    so->pulsing = true;
}

void simple_out_drive(simple_out_t *so, bool on, bool live, uint32_t now_ms)
{
    if (so->pulsing && !simple_out_pulsing(so, now_ms)) so->pulsing = false;
    if (!live && !on) {
        /* The signal ends: one last burst of off pulses (unless that is what went out last),
         * then nothing, the pin low. */
        if (so->live) {
            so->live = false;
            if (so->width != SO_OFF_US || !so->pulsing) {
                restart(so, SO_OFF_US, now_ms);
            } else {
                /* Off pulses already: top them up to a full 0.5 s once more, then stop. */
                uint32_t left = so->horizon_ms - now_ms;
                uint16_t frames = (uint16_t)((SO_BURST_MS - left) / SO_FRAME_MS);
                if (frames > 0 && send(so, SO_OFF_US, frames, false)) {
                    so->horizon_ms += (uint32_t)frames * SO_FRAME_MS;
                }
            }
        }
        return;
    }
    uint16_t width = on ? SO_ON_US : SO_OFF_US;
    so->live = true;
    if (!so->pulsing || width != so->width) {
        restart(so, width, now_ms); /* a new state goes out at once */
        return;
    }
    if (now_ms - so->renew_ms < SO_RENEW_MS) return;
    /* The renewal: what brings the queue back to SO_BURST_FRAMES frames from now. */
    uint32_t left = so->horizon_ms - now_ms;
    if (left >= SO_BURST_MS) return;
    uint16_t frames = (uint16_t)((SO_BURST_MS - left) / SO_FRAME_MS);
    if (frames == 0) return;
    if (send(so, width, frames, false)) {
        so->horizon_ms += (uint32_t)frames * SO_FRAME_MS;
        so->renew_ms = now_ms;
    }
}

void simple_out_backend_drive(void *ctx, bool on, bool live, uint32_t now_ms)
{
    simple_out_drive((simple_out_t *)ctx, on, live, now_ms);
}

/* ---- Pins ------------------------------------------------------------------------------ */

const char *simple_out_pin_problem(int gpio, so_board_t board, int buzzer_gpio,
                                   const so_pin_use_t *used, size_t used_count)
{
    static char why[96];
    if (gpio < 0 || gpio > 48 || (gpio >= 22 && gpio <= 25)) return "not a GPIO of the ESP32-S3";
    if (gpio == 0) return "the boot button's strapping pin";
    if (gpio == 2 || gpio == 7) return "the radio front-end module's enable or power line";
    if (gpio >= 8 && gpio <= 14) return "the SX1262 radio's pins";
    if (gpio == 17 || gpio == 18) return "the I2C bus (OLED, keypad, NFC, gauge)";
    if (gpio == 19 || gpio == 20) return "the USB port";
    if (gpio == 21) return "the OLED's reset";
    if (gpio >= 26 && gpio <= 32) return "the flash and PSRAM";
    if (gpio == 34) return "the GNSS connector's power control";
    if (gpio == 36 || gpio == 37) return "the board's Vext and ADC control lines";
    if (gpio >= 38 && gpio <= 42) return "the GNSS connector's pins";
    if (gpio == 43 || gpio == 44) return "UART0 (the console)";
    if (gpio == 5 && board == SO_BOARD_V4_3) {
        return "the V4.3's front-end-module line (CTX); GPIO 46 is free on a V4.3";
    }
    if (gpio == 46 && board == SO_BOARD_V4_2) {
        return "the V4.2's front-end-module line (CPS); GPIO 5 is free on a V4.2";
    }
    if (gpio == 45 && buzzer_gpio == 45) {
        return "the piezo buzzer's pin: GPIO 45 is the buzzer or a second simple output";
    }
    if (buzzer_gpio >= 0 && gpio == buzzer_gpio) return "the piezo buzzer's pin";
    for (size_t i = 0; used != NULL && i < used_count; i++) {
        if (used[i].gpio >= 0 && used[i].gpio == gpio) {
            snprintf(why, sizeof(why), "taken by %s", used[i].name ? used[i].name : "another part");
            return why;
        }
    }
    return NULL;
}
