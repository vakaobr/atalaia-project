/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifdef ESP_PLATFORM

#include "../hal_audio.h"

#include "driver/i2s_std.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

static const char *TAG = "hal_audio";

/* ---- Kconfig pins ---- */

#ifndef CONFIG_ATALAIA_AUDIO_BCLK_PIN
#define CONFIG_ATALAIA_AUDIO_BCLK_PIN 6
#endif
#ifndef CONFIG_ATALAIA_AUDIO_LRCLK_PIN
#define CONFIG_ATALAIA_AUDIO_LRCLK_PIN 15
#endif
#ifndef CONFIG_ATALAIA_AUDIO_DOUT_PIN
#define CONFIG_ATALAIA_AUDIO_DOUT_PIN 16
#endif

/* Audio is disabled when any pin is -1. */
#define AUDIO_ENABLED                                                                              \
    (CONFIG_ATALAIA_AUDIO_BCLK_PIN >= 0 && CONFIG_ATALAIA_AUDIO_LRCLK_PIN >= 0 &&                  \
     CONFIG_ATALAIA_AUDIO_DOUT_PIN >= 0)

#define SAMPLE_RATE   16000
#define DMA_BUF_COUNT 4
#define DMA_BUF_LEN   256

static i2s_chan_handle_t tx_handle;
static uint8_t current_volume = 80; /* 0-100 */

/* ---- WAV header ---- */

typedef struct __attribute__((packed)) {
    char riff_tag[4]; /* "RIFF" */
    uint32_t file_size;
    char wave_tag[4]; /* "WAVE" */
    char fmt_tag[4];  /* "fmt " */
    uint32_t fmt_size;
    uint16_t audio_format;
    uint16_t num_channels;
    uint32_t sample_rate;
    uint32_t byte_rate;
    uint16_t block_align;
    uint16_t bits_per_sample;
    char data_tag[4]; /* "data" */
    uint32_t data_size;
} wav_header_t;

/* ---- ops implementation ---- */

static int esp_audio_init(void)
{
#if !AUDIO_ENABLED
    ESP_LOGI(TAG, "Audio disabled (pins not assigned)");
    return 0;
#else
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_AUTO, I2S_ROLE_MASTER);
    chan_cfg.dma_desc_num = DMA_BUF_COUNT;
    chan_cfg.dma_frame_num = DMA_BUF_LEN;

    esp_err_t err = i2s_new_channel(&chan_cfg, &tx_handle, NULL);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "I2S new channel failed: %s", esp_err_to_name(err));
        return -1;
    }

    i2s_std_config_t std_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE),
        .slot_cfg =
            I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO),
        .gpio_cfg =
            {
                .mclk = I2S_GPIO_UNUSED,
                .bclk = (gpio_num_t)CONFIG_ATALAIA_AUDIO_BCLK_PIN,
                .ws = (gpio_num_t)CONFIG_ATALAIA_AUDIO_LRCLK_PIN,
                .dout = (gpio_num_t)CONFIG_ATALAIA_AUDIO_DOUT_PIN,
                .din = I2S_GPIO_UNUSED,
                .invert_flags =
                    {
                        .mclk_inv = false,
                        .bclk_inv = false,
                        .ws_inv = false,
                    },
            },
    };

    err = i2s_channel_init_std_mode(tx_handle, &std_cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "I2S std mode init failed: %s", esp_err_to_name(err));
        return -1;
    }

    err = i2s_channel_enable(tx_handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "I2S channel enable failed: %s", esp_err_to_name(err));
        return -1;
    }

    ESP_LOGI(TAG, "I2S audio output initialised at %d Hz", SAMPLE_RATE);
    return 0;
#endif /* AUDIO_ENABLED */
}

static int esp_audio_play_wav(const char *path)
{
#if !AUDIO_ENABLED
    (void)path;
    return 0;
#else
    FILE *f = fopen(path, "rb");
    if (!f) {
        ESP_LOGE(TAG, "Cannot open WAV file: %s", path);
        return -1;
    }

    wav_header_t hdr;
    if (fread(&hdr, 1, sizeof(hdr), f) != sizeof(hdr)) {
        ESP_LOGE(TAG, "Failed to read WAV header: %s", path);
        fclose(f);
        return -1;
    }

    if (memcmp(hdr.riff_tag, "RIFF", 4) != 0 || memcmp(hdr.wave_tag, "WAVE", 4) != 0) {
        ESP_LOGE(TAG, "Invalid WAV file: %s", path);
        fclose(f);
        return -1;
    }

    /* Stream audio data to I2S */
    uint8_t buf[512];
    uint32_t remaining = hdr.data_size;
    size_t bytes_written;

    while (remaining > 0) {
        size_t to_read = remaining < sizeof(buf) ? remaining : sizeof(buf);
        size_t got = fread(buf, 1, to_read, f);
        if (got == 0) break;

        /* Apply volume scaling for 16-bit samples */
        if (hdr.bits_per_sample == 16 && current_volume < 100) {
            int16_t *samples = (int16_t *)buf;
            size_t n = got / 2;
            for (size_t i = 0; i < n; i++) {
                samples[i] = (int16_t)(samples[i] * current_volume / 100);
            }
        }

        i2s_channel_write(tx_handle, buf, got, &bytes_written, portMAX_DELAY);
        remaining -= (uint32_t)got;
    }

    fclose(f);
    return 0;
#endif /* AUDIO_ENABLED */
}

static int esp_audio_tone(uint32_t freq_hz, uint32_t duration_ms)
{
    if (freq_hz == 0 || duration_ms == 0) return 0;
#if !AUDIO_ENABLED
    return 0;
#else

    uint32_t total_samples = SAMPLE_RATE * duration_ms / 1000;
    int16_t buf[256];
    uint32_t written = 0;

    while (written < total_samples) {
        uint32_t chunk = total_samples - written;
        if (chunk > 256) chunk = 256;

        for (uint32_t i = 0; i < chunk; i++) {
            double t = (double)(written + i) / SAMPLE_RATE;
            double val = sin(2.0 * M_PI * freq_hz * t);
            int16_t sample = (int16_t)(val * 16000 * current_volume / 100);
            buf[i] = sample;
        }

        size_t bytes_written;
        i2s_channel_write(tx_handle, buf, chunk * sizeof(int16_t), &bytes_written, portMAX_DELAY);
        written += chunk;
    }

    return 0;
#endif /* AUDIO_ENABLED */
}

static void esp_audio_stop(void)
{
#if !AUDIO_ENABLED
    return;
#else
    /* Flush the DMA buffers with silence */
    uint8_t silence[512];
    memset(silence, 0, sizeof(silence));
    size_t bytes_written;
    i2s_channel_write(tx_handle, silence, sizeof(silence), &bytes_written, portMAX_DELAY);
#endif /* AUDIO_ENABLED */
}

static void esp_audio_set_volume(uint8_t volume)
{
    current_volume = volume > 100 ? 100 : volume;
}

static void esp_audio_deinit(void)
{
    if (tx_handle) {
        i2s_channel_disable(tx_handle);
        i2s_del_channel(tx_handle);
        tx_handle = NULL;
    }
}

const hal_audio_ops_t hal_esp_audio_ops = {
    .init = esp_audio_init,
    .play_wav = esp_audio_play_wav,
    .tone = esp_audio_tone,
    .stop = esp_audio_stop,
    .set_volume = esp_audio_set_volume,
    .deinit = esp_audio_deinit,
};

#endif /* ESP_PLATFORM */
