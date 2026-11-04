/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The simple outputs on the ESP32-S3 (simple_out_esp.h; decisions EXP-32 to EXP-34): each a
 * channel of the RMT peripheral at 1 MHz sending one 20 ms frame (a 1.0 or 2.0 ms pulse, then
 * low) repeated by the hardware's loop count, so a burst stops by itself; the burst scheduler
 * (simple_out.c) queues them from the game task. A flush (a change of width, the signal's end)
 * deletes and re-creates the channel, the one way to drop transmissions already queued; the pin
 * is low in between (the gate input's 10 kohm pull-down). The LED ring has its own RMT channel;
 * the S3 has four for transmitting.
 *
 * On an I/O pod (CONFIG_ATALAIA_POD_MODE; increment 9, EXP-26) the same channels, with their
 * settings from the build (ATALAIA_POD_OUT<n>_FUNCTION, _MAX_ON_S: a pod has no admin PIN and no
 * settings store for them) and the pod's own pins checked instead of the display's.
 */

#ifdef ESP_PLATFORM

#include "simple_out_esp.h"

#include <stdio.h>
#include <string.h>

#include "esp_log.h"
#include "sdkconfig.h"
#if !CONFIG_ATALAIA_POD_MODE
#include "config_store.h"
#endif

#if CONFIG_ATALAIA_SIMPLE_OUT

#include "driver/rmt_tx.h"
#include "simple_out.h"

/* ---- The pins: refused at compile time (Kconfig takes any number), as at run time ---- */

#define SO_PIN1 CONFIG_ATALAIA_SIMPLE_OUT_PIN
#if CONFIG_ATALAIA_SIMPLE_OUT2
#define SO_PIN2 CONFIG_ATALAIA_SIMPLE_OUT2_PIN
#else
#define SO_PIN2 (-1)
#endif

#if SO_PIN1 < 0
#error "CONFIG_ATALAIA_SIMPLE_OUT is on but CONFIG_ATALAIA_SIMPLE_OUT_PIN is -1: give it a GPIO"
#endif
#if SO_PIN2 >= 0 && SO_PIN2 == SO_PIN1
#error "The two simple outputs are on one GPIO"
#endif
#if CONFIG_ATALAIA_BUZZER &&                                                                       \
    (SO_PIN1 == CONFIG_ATALAIA_BUZZER_PIN || SO_PIN2 == CONFIG_ATALAIA_BUZZER_PIN)
#error "A simple output is on the piezo buzzer's GPIO: GPIO 45 is the buzzer or a second output"
#endif
#if CONFIG_ATALAIA_BOARD_HELTEC_V4_3 && (SO_PIN1 == 5 || SO_PIN2 == 5)
#error "GPIO 5 is the V4.3's front-end-module line (CTX): use GPIO 46 on a V4.3"
#endif
#if CONFIG_ATALAIA_BOARD_HELTEC_V4_2 && (SO_PIN1 == 46 || SO_PIN2 == 46)
#error "GPIO 46 is the V4.2's front-end-module line (CPS): use GPIO 5 on a V4.2"
#endif
/* Another part's pin: x is that part's Kconfig pin (only listed when the part is built). */
#define SO_CLASH(x) ((x) >= 0 && ((x) == SO_PIN1 || (x) == SO_PIN2))
#if SO_CLASH(CONFIG_ATALAIA_BTN1_PIN) || SO_CLASH(CONFIG_ATALAIA_BTN2_PIN) ||                      \
    SO_CLASH(CONFIG_ATALAIA_BTN3_PIN) || SO_CLASH(CONFIG_ATALAIA_BTN4_PIN)
#error "A simple output is on a team button's GPIO"
#endif
#if SO_CLASH(CONFIG_ATALAIA_LED_PIN)
#error "A simple output is on the LED ring's GPIO"
#endif
#if CONFIG_ATALAIA_POD_MODE
/* A pod has no display (its pins 1, 3 and 33 are free), but its enclosure switch has a pin. */
#if SO_CLASH(CONFIG_ATALAIA_POD_TAMPER_PIN)
#error "A simple output is on the pod's enclosure switch GPIO"
#endif
#elif SO_CLASH(CONFIG_ATALAIA_DISP_MOSI_PIN) || SO_CLASH(CONFIG_ATALAIA_DISP_CLK_PIN) ||           \
    SO_CLASH(CONFIG_ATALAIA_DISP_CS_PIN) || SO_CLASH(CONFIG_ATALAIA_DISP_DC_PIN) ||                \
    SO_CLASH(CONFIG_ATALAIA_DISP_RST_PIN) || SO_CLASH(CONFIG_ATALAIA_DISP_BL_PIN)
#error "A simple output is on one of the display's GPIOs"
#endif
#if SO_CLASH(CONFIG_ATALAIA_NFC_SDA_PIN) || SO_CLASH(CONFIG_ATALAIA_NFC_SCL_PIN) ||                \
    SO_CLASH(CONFIG_ATALAIA_BATT_SDA_PIN) || SO_CLASH(CONFIG_ATALAIA_BATT_SCL_PIN)
#error "A simple output is on the I2C bus"
#endif
#if SO_CLASH(CONFIG_ATALAIA_AUDIO_BCLK_PIN) || SO_CLASH(CONFIG_ATALAIA_AUDIO_LRCLK_PIN) ||         \
    SO_CLASH(CONFIG_ATALAIA_AUDIO_DOUT_PIN)
#error "A simple output is on one of the I2S amplifier's GPIOs (set them to -1 without one)"
#endif
#if CONFIG_ATALAIA_KP_PCF8574 && SO_CLASH(CONFIG_ATALAIA_KP_INT_PIN)
#error "A simple output is on the keypad expander's INT GPIO"
#endif
#if CONFIG_ATALAIA_KP_GPIO_MATRIX &&                                                               \
    (SO_CLASH(CONFIG_ATALAIA_KP_ROW0_PIN) || SO_CLASH(CONFIG_ATALAIA_KP_ROW1_PIN) ||               \
     SO_CLASH(CONFIG_ATALAIA_KP_ROW2_PIN) || SO_CLASH(CONFIG_ATALAIA_KP_ROW3_PIN) ||               \
     SO_CLASH(CONFIG_ATALAIA_KP_COL0_PIN) || SO_CLASH(CONFIG_ATALAIA_KP_COL1_PIN) ||               \
     SO_CLASH(CONFIG_ATALAIA_KP_COL2_PIN))
#error "A simple output is on a keypad matrix GPIO"
#endif
#if SO_CLASH(CONFIG_ATALAIA_RADIO_NSS_PIN) || SO_CLASH(CONFIG_ATALAIA_RADIO_SCK_PIN) ||            \
    SO_CLASH(CONFIG_ATALAIA_RADIO_MOSI_PIN) || SO_CLASH(CONFIG_ATALAIA_RADIO_MISO_PIN) ||          \
    SO_CLASH(CONFIG_ATALAIA_RADIO_RST_PIN) || SO_CLASH(CONFIG_ATALAIA_RADIO_BUSY_PIN) ||           \
    SO_CLASH(CONFIG_ATALAIA_RADIO_DIO1_PIN) || SO_CLASH(CONFIG_ATALAIA_RADIO_FEM_EN_PIN) ||        \
    SO_CLASH(CONFIG_ATALAIA_RADIO_VFEM_CTL_PIN)
#error "A simple output is on one of the radio's GPIOs"
#endif

static const char *TAG = "simple_out";

/* The parts of this build on their pins, for simple_out_pin_problem (as the checks above). */
static const so_pin_use_t pins_used[] = {
    {"button 1", CONFIG_ATALAIA_BTN1_PIN},
    {"button 2", CONFIG_ATALAIA_BTN2_PIN},
    {"button 3", CONFIG_ATALAIA_BTN3_PIN},
    {"button 4", CONFIG_ATALAIA_BTN4_PIN},
    {"the LED ring", CONFIG_ATALAIA_LED_PIN},
#if CONFIG_ATALAIA_POD_MODE
    {"the enclosure switch", CONFIG_ATALAIA_POD_TAMPER_PIN},
#else
    {"the display", CONFIG_ATALAIA_DISP_MOSI_PIN},
    {"the display", CONFIG_ATALAIA_DISP_CLK_PIN},
    {"the display", CONFIG_ATALAIA_DISP_CS_PIN},
    {"the display", CONFIG_ATALAIA_DISP_DC_PIN},
    {"the display", CONFIG_ATALAIA_DISP_RST_PIN},
    {"the display", CONFIG_ATALAIA_DISP_BL_PIN},
#endif
    {"the amplifier", CONFIG_ATALAIA_AUDIO_BCLK_PIN},
    {"the amplifier", CONFIG_ATALAIA_AUDIO_LRCLK_PIN},
    {"the amplifier", CONFIG_ATALAIA_AUDIO_DOUT_PIN},
};

/* ---- RMT ------------------------------------------------------------------------------ */

#define SO_RMT_HZ 1000000 /* 1 tick = 1 us */

typedef struct {
    int gpio;
    rmt_channel_handle_t chan;
    rmt_encoder_handle_t enc;
} so_rmt_t;

/* One frame each; the hardware repeats it loop_count times. Read by the RMT while it sends:
 * static. */
static const rmt_symbol_word_t frame_on = {
    .duration0 = SO_ON_US, .level0 = 1, .duration1 = SO_FRAME_MS * 1000 - SO_ON_US, .level1 = 0};
static const rmt_symbol_word_t frame_off = {
    .duration0 = SO_OFF_US, .level0 = 1, .duration1 = SO_FRAME_MS * 1000 - SO_OFF_US, .level1 = 0};

static bool chan_open(so_rmt_t *r)
{
    rmt_tx_channel_config_t cfg = {
        .gpio_num = r->gpio,
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = SO_RMT_HZ,
        .mem_block_symbols = 48,
        .trans_queue_depth = 6, /* a burst and its top-ups: at most 0.5 s queued */
    };
    if (rmt_new_tx_channel(&cfg, &r->chan) != ESP_OK) {
        r->chan = NULL;
        return false;
    }
    if (rmt_enable(r->chan) != ESP_OK) {
        rmt_del_channel(r->chan);
        r->chan = NULL;
        return false;
    }
    return true;
}

static void chan_close(so_rmt_t *r)
{
    if (r->chan == NULL) return;
    rmt_disable(r->chan); /* aborts the frame being sent; the pin goes low */
    rmt_del_channel(r->chan);
    r->chan = NULL;
}

static bool rmt_send(void *ctx, uint16_t width_us, uint16_t frames, bool flush)
{
    so_rmt_t *r = (so_rmt_t *)ctx;
    if (flush) chan_close(r);
    if (r->chan == NULL && !chan_open(r)) return false;
    rmt_transmit_config_t tx = {.loop_count = frames, .flags.eot_level = 0};
    const rmt_symbol_word_t *frame = width_us == SO_ON_US ? &frame_on : &frame_off;
    return rmt_transmit(r->chan, r->enc, frame, sizeof(*frame), &tx) == ESP_OK;
}

static so_rmt_t rmts[OUTPUTS_MAX];
static simple_out_t outs[OUTPUTS_MAX];

/* ---- Settings: in NVS on a box, from the build on a pod --------------------------------- */

#if CONFIG_ATALAIA_POD_MODE

/* Building an output into a pod enables it (EXP-28; a pod has no admin PIN, PODC-2), with the
 * build's use and longest on; a use outputs.c does not take leaves it disabled. */
static void load_settings(int index, out_settings_t *s)
{
    outputs_default_settings(index, s);
    const char *fn = CONFIG_ATALAIA_POD_OUT1_FUNCTION;
    uint32_t max_s = CONFIG_ATALAIA_POD_OUT1_MAX_ON_S;
#if CONFIG_ATALAIA_SIMPLE_OUT2
    if (index == 1) {
        fn = CONFIG_ATALAIA_POD_OUT2_FUNCTION;
        max_s = CONFIG_ATALAIA_POD_OUT2_MAX_ON_S;
    }
#endif
    if (!outputs_function_ok(fn)) {
        ESP_LOGE(TAG,
                 "simple output %d: \"%s\" is not a use (siren, strobe, smoke, light, horn, "
                 "out.1-out.9): left disabled",
                 index + 1, fn);
        return;
    }
    snprintf(s->function, sizeof(s->function), "%s", fn);
    s->max_on_s = max_s;
    s->enabled = true;
}

bool simple_out_esp_save(void *ctx, int index, const out_settings_t *s)
{
    (void)ctx;
    (void)index;
    (void)s;
    return false; /* the build's: nothing to store */
}

#else

/* NVS keys: "out1_en" ... (15 characters at most; index is 0 or 1). */
static void load_settings(int index, out_settings_t *s)
{
    char key[24];
    outputs_default_settings(index, s);
    snprintf(key, sizeof(key), "out%d_en", index + 1);
    s->enabled = config_store_get_u32(key, 0) != 0;
    snprintf(key, sizeof(key), "out%d_fn", index + 1);
    char fn[OUT_ID_MAX + 1];
    if (config_store_get_str(key, fn, sizeof(fn)) && outputs_function_ok(fn)) {
        snprintf(s->function, sizeof(s->function), "%s", fn);
    }
    snprintf(key, sizeof(key), "out%d_max", index + 1);
    uint32_t max_s = config_store_get_u32(key, OUT_MAX_ON_DEFAULT_S);
    if (max_s >= 1 && max_s <= OUT_MAX_ON_MAX_S) s->max_on_s = max_s;
}

bool simple_out_esp_save(void *ctx, int index, const out_settings_t *s)
{
    (void)ctx;
    char key[24];
    snprintf(key, sizeof(key), "out%d_en", index + 1);
    config_store_set_u32(key, s->enabled ? 1 : 0);
    snprintf(key, sizeof(key), "out%d_fn", index + 1);
    config_store_set_str(key, s->function);
    snprintf(key, sizeof(key), "out%d_max", index + 1);
    config_store_set_u32(key, s->max_on_s);
    return true;
}

#endif /* CONFIG_ATALAIA_POD_MODE */

static int add(outputs_t *o, int index, int gpio)
{
#if CONFIG_ATALAIA_BOARD_HELTEC_V4_2
    so_board_t board = SO_BOARD_V4_2;
#else
    so_board_t board = SO_BOARD_V4_3;
#endif
#if CONFIG_ATALAIA_BUZZER
    int buzzer = CONFIG_ATALAIA_BUZZER_PIN;
#else
    int buzzer = -1;
#endif
    const char *why = simple_out_pin_problem(gpio, board, buzzer, pins_used,
                                             sizeof(pins_used) / sizeof(pins_used[0]));
    if (why != NULL) {
        ESP_LOGE(TAG, "simple output %d on GPIO %d refused: %s", index + 1, gpio, why);
        return -1;
    }
    so_rmt_t *r = &rmts[index];
    r->gpio = gpio;
    rmt_copy_encoder_config_t enc_cfg = {};
    if (rmt_new_copy_encoder(&enc_cfg, &r->enc) != ESP_OK) {
        ESP_LOGE(TAG, "simple output %d: no RMT encoder", index + 1);
        return -1;
    }
    simple_out_rmt_t rmt = {.ctx = r, .send = rmt_send};
    simple_out_init(&outs[index], gpio, &rmt);
    out_settings_t s;
    load_settings(index, &s);
    out_backend_t be = {.ctx = &outs[index], .drive = simple_out_backend_drive};
    return outputs_add_simple(o, gpio, &be, &s);
}

int simple_out_esp_init(outputs_t *o)
{
    int n = 0;
    if (add(o, 0, SO_PIN1) >= 0) n++;
#if CONFIG_ATALAIA_SIMPLE_OUT2
    if (add(o, 1, SO_PIN2) >= 0) n++;
#endif
    ESP_LOGI(TAG, "%d simple output(s): RMT bursts of %d frames, renewed every %d ms", n,
             SO_BURST_FRAMES, SO_RENEW_MS);
    return n;
}

#else /* !CONFIG_ATALAIA_SIMPLE_OUT */

int simple_out_esp_init(outputs_t *o)
{
    (void)o;
    return 0;
}

bool simple_out_esp_save(void *ctx, int index, const out_settings_t *s)
{
    (void)ctx;
    (void)index;
    (void)s;
    return false;
}

#endif /* CONFIG_ATALAIA_SIMPLE_OUT */

#endif /* ESP_PLATFORM */
