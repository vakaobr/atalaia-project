/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#include "hal_stub.h"

#include <string.h>

/* ------------------------------------------------------------------ */
/* Test-assertion counters                                             */
/* ------------------------------------------------------------------ */

int hal_stub_led_fill_count;
char hal_stub_led_last_fill[4];

int hal_stub_audio_play_count;
char hal_stub_audio_last_clip[64];

void hal_stub_reset_counters(void)
{
    hal_stub_led_fill_count = 0;
    memset(hal_stub_led_last_fill, 0, sizeof(hal_stub_led_last_fill));

    hal_stub_audio_play_count = 0;
    memset(hal_stub_audio_last_clip, 0, sizeof(hal_stub_audio_last_clip));
}

/* ------------------------------------------------------------------ */
/* Buttons                                                             */
/* ------------------------------------------------------------------ */

static int stub_buttons_init(void)
{
    return 0;
}
static uint8_t stub_buttons_poll(void)
{
    return 0;
}
static void stub_buttons_deinit(void)
{
}

static const hal_button_ops_t stub_button_ops = {
    .init = stub_buttons_init,
    .poll = stub_buttons_poll,
    .deinit = stub_buttons_deinit,
};

/* ------------------------------------------------------------------ */
/* Keypad                                                              */
/* ------------------------------------------------------------------ */

static int stub_keypad_init(void)
{
    return 0;
}
static char stub_keypad_scan(void)
{
    return HAL_KEY_NONE;
}
static void stub_keypad_deinit(void)
{
}

static const hal_keypad_ops_t stub_keypad_ops = {
    .init = stub_keypad_init,
    .scan = stub_keypad_scan,
    .deinit = stub_keypad_deinit,
};

/* ------------------------------------------------------------------ */
/* LEDs                                                                */
/* ------------------------------------------------------------------ */

static int stub_leds_init(void)
{
    return 0;
}

static void stub_leds_fill(uint8_t r, uint8_t g, uint8_t b)
{
    hal_stub_led_fill_count++;
    hal_stub_led_last_fill[0] = (char)r;
    hal_stub_led_last_fill[1] = (char)g;
    hal_stub_led_last_fill[2] = (char)b;
}

static void stub_leds_set(int index, uint8_t r, uint8_t g, uint8_t b)
{
    (void)index;
    (void)r;
    (void)g;
    (void)b;
}

static void stub_leds_show(void)
{
}
static void stub_leds_set_brightness(uint8_t brightness)
{
    (void)brightness;
}
static void stub_leds_deinit(void)
{
}

static const hal_led_ops_t stub_led_ops = {
    .init = stub_leds_init,
    .fill = stub_leds_fill,
    .set = stub_leds_set,
    .show = stub_leds_show,
    .set_brightness = stub_leds_set_brightness,
    .deinit = stub_leds_deinit,
};

/* ------------------------------------------------------------------ */
/* Display                                                             */
/* ------------------------------------------------------------------ */

static int stub_display_init(void)
{
    return 0;
}

static void stub_display_flush(int x1, int y1, int x2, int y2, const void *color_p,
                               hal_display_flush_ready_cb_t ready_cb)
{
    (void)x1;
    (void)y1;
    (void)x2;
    (void)y2;
    (void)color_p;
    if (ready_cb) {
        ready_cb();
    }
}

static void stub_display_set_brightness(uint8_t brightness)
{
    (void)brightness;
}

static void stub_display_deinit(void)
{
}

static const hal_display_ops_t stub_display_ops = {
    .init = stub_display_init,
    .flush = stub_display_flush,
    .set_brightness = stub_display_set_brightness,
    .deinit = stub_display_deinit,
};

/* ------------------------------------------------------------------ */
/* NFC                                                                 */
/* ------------------------------------------------------------------ */

static int stub_nfc_init(void)
{
    return 0;
}

static bool stub_nfc_poll(hal_nfc_tag_t *tag)
{
    (void)tag;
    return false;
}

static void stub_nfc_deinit(void)
{
}

static const hal_nfc_ops_t stub_nfc_ops = {
    .init = stub_nfc_init,
    .poll = stub_nfc_poll,
    .deinit = stub_nfc_deinit,
};

/* ------------------------------------------------------------------ */
/* Audio                                                               */
/* ------------------------------------------------------------------ */

static int stub_audio_init(void)
{
    return 0;
}

static int stub_audio_play_wav(const char *path)
{
    hal_stub_audio_play_count++;
    if (path) {
        strncpy(hal_stub_audio_last_clip, path, sizeof(hal_stub_audio_last_clip) - 1);
        hal_stub_audio_last_clip[sizeof(hal_stub_audio_last_clip) - 1] = '\0';
    }
    return 0;
}

static int stub_audio_tone(uint32_t freq_hz, uint32_t duration_ms)
{
    (void)freq_hz;
    (void)duration_ms;
    return 0;
}

static void stub_audio_stop(void)
{
}
static void stub_audio_set_volume(uint8_t volume)
{
    (void)volume;
}
static void stub_audio_deinit(void)
{
}

static const hal_audio_ops_t stub_audio_ops = {
    .init = stub_audio_init,
    .play_wav = stub_audio_play_wav,
    .tone = stub_audio_tone,
    .stop = stub_audio_stop,
    .set_volume = stub_audio_set_volume,
    .deinit = stub_audio_deinit,
};

/* ------------------------------------------------------------------ */
/* Battery                                                             */
/* ------------------------------------------------------------------ */

static int stub_battery_init(void)
{
    return 0;
}

static hal_battery_info_t stub_battery_read(void)
{
    return (hal_battery_info_t){
        .voltage_mv = 4200,
        .percent = 100,
        .charging = false,
    };
}

static void stub_battery_deinit(void)
{
}

static const hal_battery_ops_t stub_battery_ops = {
    .init = stub_battery_init,
    .read = stub_battery_read,
    .deinit = stub_battery_deinit,
};

/* ------------------------------------------------------------------ */
/* Public initialiser                                                  */
/* ------------------------------------------------------------------ */

/* ---- Radio stub (defined in hal_radio_stub.c) ---------------------------- */

extern const hal_radio_ops_t hal_stub_radio_ops;

/* ------------------------------------------------------------------ */
/* Public initialiser                                                  */
/* ------------------------------------------------------------------ */

void hal_stub_init(hal_t *hal)
{
    hal->buttons = &stub_button_ops;
    hal->keypad = &stub_keypad_ops;
    hal->leds = &stub_led_ops;
    hal->display = &stub_display_ops;
    hal->nfc = &stub_nfc_ops;
    hal->audio = &stub_audio_ops;
    hal->battery = &stub_battery_ops;
    hal->radio = &hal_stub_radio_ops;

    hal_stub_reset_counters();
}
