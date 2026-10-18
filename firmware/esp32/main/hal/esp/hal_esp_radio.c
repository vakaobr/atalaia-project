/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * SX1262 LoRa radio driver for the Heltec WiFi LoRa 32 V4.3.
 * EU868 band, SF7/BW125, single shared game channel (default
 * 869.525 MHz, g2 sub-band, 10% duty cycle, 500 mW ERP).
 * FEM gain (~14 dB) is accounted for in the TX power setting.
 *
 * The init function probes the SX1262 by reading a register. If the
 * chip is not present (e.g. Wokwi emulator), init returns -1 and the
 * rest of the firmware boots without radio -- same pattern as PN532.
 */

#ifdef ESP_PLATFORM

#include "../hal_radio.h"
#include "../../radio/radio_power.h"

#include <stdint.h>
#include <string.h>

#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "sdkconfig.h"

static const char *TAG = "radio";

/* ---- Pin configuration from Kconfig -------------------------------------- */

#define PIN_NSS  CONFIG_ATALAIA_RADIO_NSS_PIN
#define PIN_SCK  CONFIG_ATALAIA_RADIO_SCK_PIN
#define PIN_MOSI CONFIG_ATALAIA_RADIO_MOSI_PIN
#define PIN_MISO CONFIG_ATALAIA_RADIO_MISO_PIN
#define PIN_RST  CONFIG_ATALAIA_RADIO_RST_PIN
#define PIN_BUSY CONFIG_ATALAIA_RADIO_BUSY_PIN
#define PIN_DIO1 CONFIG_ATALAIA_RADIO_DIO1_PIN

#define PIN_FEM_EN       CONFIG_ATALAIA_RADIO_FEM_EN_PIN
#define PIN_VFEM_CTL     CONFIG_ATALAIA_RADIO_VFEM_CTL_PIN
#define FEM_GAIN_DB      CONFIG_ATALAIA_RADIO_FEM_GAIN_DB
#define ANTENNA_GAIN_DBI CONFIG_ATALAIA_RADIO_ANTENNA_GAIN_DBI

/* Default game channel from Kconfig (869.525 MHz, g2 sub-band). */
#ifndef CONFIG_ATALAIA_RADIO_DEFAULT_CHANNEL_HZ
#define CONFIG_ATALAIA_RADIO_DEFAULT_CHANNEL_HZ 869525000
#endif

/* LoRa parameters: SF7, BW125, CR4/5. */
#define LORA_SF        7
#define LORA_BW_HZ     125000
#define LORA_CR        1 /* 4/5 */
#define LORA_PREAMBLE  8
#define LORA_SYNC_WORD 0x3444 /* private network */

/* EU868 g2-band: 27 dBm ERP = 500 mW.  Conducted power accounts for
 * the FEM gain and the antenna gain (see radio_power.h).
 * With FEM=14 dB and antenna=2 dBi: (27*100+215 - 14*100 - 2*100)/100 = 13 dBm. */
#define TX_POWER_DBM                                                                               \
    atalaia_eu868_tx_power_dbm(ATALAIA_EU868_G2_ERP_LIMIT_DBM, FEM_GAIN_DB, ANTENNA_GAIN_DBI)

/* SX1262 commands. */
#define SX_CMD_SET_SLEEP            0x84
#define SX_CMD_SET_STANDBY          0x80
#define SX_CMD_SET_RX               0x82
#define SX_CMD_SET_TX               0x83
#define SX_CMD_WRITE_REGISTER       0x0D
#define SX_CMD_READ_REGISTER        0x1D
#define SX_CMD_WRITE_BUFFER         0x0E
#define SX_CMD_READ_BUFFER          0x1E
#define SX_CMD_SET_DIO_IRQ_PARAMS   0x08
#define SX_CMD_GET_IRQ_STATUS       0x12
#define SX_CMD_CLR_IRQ_STATUS       0x02
#define SX_CMD_SET_RF_FREQUENCY     0x86
#define SX_CMD_SET_PACKET_TYPE      0x8A
#define SX_CMD_SET_MODULATION       0x8B
#define SX_CMD_SET_PACKET_PARAMS    0x8C
#define SX_CMD_SET_TX_PARAMS        0x8E
#define SX_CMD_SET_BUFFER_BASE      0x8F
#define SX_CMD_GET_RX_BUFFER_STATUS 0x13
#define SX_CMD_GET_PACKET_STATUS    0x14
#define SX_CMD_GET_RSSI_INST        0x15
#define SX_CMD_SET_DIO2_AS_RF_SW    0x9D
#define SX_CMD_SET_DIO3_AS_TCXO     0x97
#define SX_CMD_CALIBRATE            0x89
#define SX_CMD_SET_REGULATOR_MODE   0x96
#define SX_CMD_SET_PA_CONFIG        0x95

/* IRQ masks. */
#define SX_IRQ_TX_DONE (1 << 0)
#define SX_IRQ_RX_DONE (1 << 1)
#define SX_IRQ_TIMEOUT (1 << 9)
#define SX_IRQ_ALL     0x03FF

/* ---- State --------------------------------------------------------------- */

static spi_device_handle_t spi_handle;
static SemaphoreHandle_t dio1_sem;

/* Duty-cycle tracking: 60-bucket sliding window per sub-band.
 * g2 sub-band (869.4-869.65 MHz, 10% = 360 s/h). */
#define DC_BUCKETS   60
#define DC_WINDOW_MS (3600U * 1000U)
#define DC_BUDGET_US (360000U * 1000U)

static uint32_t dc_buckets[DC_BUCKETS];
static uint32_t dc_used_us;
static uint32_t dc_current_bucket;
static uint32_t dc_last_update_ms;

/* ---- SPI helpers --------------------------------------------------------- */

/* BUSY must drop before every command; ~200 ms covers the longest SX1262
 * operation (calibration). A chip that never releases BUSY, or a floating
 * pin on a board without the chip, is reported as an error. */
#define SX_BUSY_TIMEOUT_MS 200

static int sx_wait_busy(void)
{
    for (int i = 0; i < SX_BUSY_TIMEOUT_MS; i++) {
        if (!gpio_get_level(PIN_BUSY)) return 0;
        vTaskDelay(1); /* one tick = 1 ms (CONFIG_FREERTOS_HZ=1000) */
    }
    return gpio_get_level(PIN_BUSY) ? -1 : 0;
}

/* One SX1262 command: waits for BUSY, then a single SPI transaction.
 * Returns 0 on success, -1 on a BUSY timeout or an SPI error. */
static int sx_cmd(const uint8_t *cmd, size_t cmd_len, uint8_t *resp, size_t resp_len)
{
    uint8_t tx_buf[260];
    uint8_t rx_buf[260];
    size_t total = cmd_len + resp_len;
    if (total > sizeof(tx_buf)) return -1;
    if (sx_wait_busy() != 0) return -1;
    spi_transaction_t t = {0};
    memset(tx_buf, 0, total);
    memcpy(tx_buf, cmd, cmd_len);
    t.length = total * 8;
    t.tx_buffer = tx_buf;
    t.rx_buffer = rx_buf;
    if (spi_device_transmit(spi_handle, &t) != ESP_OK) return -1;
    if (resp && resp_len > 0) {
        memcpy(resp, rx_buf + cmd_len, resp_len);
    }
    return 0;
}

static int sx_write_reg(uint16_t addr, uint8_t value)
{
    uint8_t cmd[] = {SX_CMD_WRITE_REGISTER, (uint8_t)(addr >> 8), (uint8_t)(addr & 0xFF), value};
    return sx_cmd(cmd, sizeof(cmd), NULL, 0);
}

static int sx_read_reg(uint16_t addr, uint8_t *value)
{
    uint8_t cmd[] = {SX_CMD_READ_REGISTER, (uint8_t)(addr >> 8), (uint8_t)(addr & 0xFF), 0x00};
    return sx_cmd(cmd, sizeof(cmd), value, 1);
}

/* ---- DIO1 ISR ------------------------------------------------------------ */

static void IRAM_ATTR dio1_isr(void *arg)
{
    (void)arg;
    BaseType_t higher;
    xSemaphoreGiveFromISR(dio1_sem, &higher);
    if (higher) portYIELD_FROM_ISR();
}

/* ---- Duty-cycle tracking ------------------------------------------------- */

static void dc_tick(uint32_t now_ms)
{
    if (dc_last_update_ms == 0) {
        dc_last_update_ms = now_ms;
        return;
    }
    uint32_t elapsed = now_ms - dc_last_update_ms;
    uint32_t bucket_ms = DC_WINDOW_MS / DC_BUCKETS; /* 60 s */
    while (elapsed >= bucket_ms) {
        dc_current_bucket = (dc_current_bucket + 1) % DC_BUCKETS;
        dc_used_us -= dc_buckets[dc_current_bucket];
        dc_buckets[dc_current_bucket] = 0;
        elapsed -= bucket_ms;
        dc_last_update_ms += bucket_ms;
    }
}

static void dc_record(uint32_t airtime_us, uint32_t now_ms)
{
    dc_tick(now_ms);
    dc_buckets[dc_current_bucket] += airtime_us;
    dc_used_us += airtime_us;
}

/* ---- EU868 channel validation -------------------------------------------- */

/* Returns true if freq_hz is within an EU868 sub-band. */
static bool eu868_channel_valid(uint32_t freq_hz)
{
    return (freq_hz >= 868000000 && freq_hz <= 868600000) || /* g */
           (freq_hz >= 868700000 && freq_hz <= 869200000) || /* g1 */
           (freq_hz >= 869400000 && freq_hz <= 869650000) || /* g2 */
           (freq_hz >= 869700000 && freq_hz <= 870000000);   /* g3 */
}

/* ---- Radio ops ----------------------------------------------------------- */

static int sx_set_frequency(uint32_t freq_hz)
{
    /* Freq register = freq * 2^25 / 32 MHz. */
    uint32_t frf = (uint32_t)((uint64_t)freq_hz * (1ULL << 25) / 32000000ULL);
    uint8_t cmd[] = {SX_CMD_SET_RF_FREQUENCY, (uint8_t)(frf >> 24), (uint8_t)(frf >> 16),
                     (uint8_t)(frf >> 8), (uint8_t)(frf & 0xFF)};
    return sx_cmd(cmd, sizeof(cmd), NULL, 0);
}

/* Undoes the probe steps that ran, newest first. */
static void probe_cleanup(int steps_done)
{
    if (steps_done >= 4 && dio1_sem != NULL) {
        gpio_isr_handler_remove(PIN_DIO1);
        vSemaphoreDelete(dio1_sem);
        dio1_sem = NULL;
    }
    if (steps_done >= 2 && spi_handle != NULL) {
        spi_bus_remove_device(spi_handle);
        spi_handle = NULL;
    }
    if (steps_done >= 1) {
        spi_bus_free(SPI3_HOST);
    }
}

static int esp_radio_init(void)
{
    /*
     * Probe the SX1262 over SPI before configuring FEM GPIOs.
     * On boards without the radio (Wokwi emulator), this returns -1
     * without touching GPIO2/GPIO7 (which Wokwi uses for the keypad).
     * The display already owns SPI2_HOST, so the radio uses SPI3_HOST.
     *
     * CONFIG_ATALAIA_RADIO_DEBUG_STEP (1-6) stops init after the given
     * step, for bisecting the init on an emulator; 0 = normal full init.
     * The per-step messages are debug-level logs.
     */
#ifndef CONFIG_ATALAIA_RADIO_DEBUG_STEP
#define CONFIG_ATALAIA_RADIO_DEBUG_STEP 0
#endif
    const int dbg = CONFIG_ATALAIA_RADIO_DEBUG_STEP;

    /* Step 1: SPI bus init. */
    spi_bus_config_t bus_cfg = {
        .miso_io_num = PIN_MISO,
        .mosi_io_num = PIN_MOSI,
        .sclk_io_num = PIN_SCK,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = 260,
    };
    esp_err_t err = spi_bus_initialize(SPI3_HOST, &bus_cfg, SPI_DMA_CH_AUTO);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "radio SPI bus init failed: %s", esp_err_to_name(err));
        return -1;
    }
    ESP_LOGD(TAG, "probe step 1 done (spi_bus_initialize)");
    if (dbg == 1) {
        probe_cleanup(1);
        return -1;
    }

    /* Step 2: SPI device add. */
    spi_device_interface_config_t dev_cfg = {
        .clock_speed_hz = 8 * 1000 * 1000,
        .mode = 0,
        .spics_io_num = PIN_NSS,
        .queue_size = 1,
    };
    err = spi_bus_add_device(SPI3_HOST, &dev_cfg, &spi_handle);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "radio SPI device add failed: %s", esp_err_to_name(err));
        probe_cleanup(1);
        return -1;
    }
    ESP_LOGD(TAG, "probe step 2 done (spi_bus_add_device)");
    if (dbg == 2) {
        probe_cleanup(2);
        return -1;
    }

    /* Step 3: GPIO config for RST, BUSY, DIO1 (no ISR yet). */
    gpio_config_t rst_cfg = {
        .pin_bit_mask = (1ULL << PIN_RST),
        .mode = GPIO_MODE_OUTPUT,
    };
    gpio_config(&rst_cfg);
    gpio_config_t busy_cfg = {
        .pin_bit_mask = (1ULL << PIN_BUSY),
        .mode = GPIO_MODE_INPUT,
    };
    gpio_config(&busy_cfg);
    gpio_config_t dio1_cfg = {
        .pin_bit_mask = (1ULL << PIN_DIO1),
        .mode = GPIO_MODE_INPUT,
    };
    gpio_config(&dio1_cfg);
    ESP_LOGD(TAG, "probe step 3 done (GPIO config RST/BUSY/DIO1)");
    if (dbg == 3) {
        probe_cleanup(3);
        return -1;
    }

    /* Step 4: DIO1 ISR install. */
    dio1_sem = xSemaphoreCreateBinary();
    if (dio1_sem == NULL) {
        ESP_LOGW(TAG, "radio: no memory for the DIO1 semaphore");
        probe_cleanup(3);
        return -1;
    }
    gpio_set_intr_type(PIN_DIO1, GPIO_INTR_POSEDGE);
    gpio_install_isr_service(0);
    gpio_isr_handler_add(PIN_DIO1, dio1_isr, NULL);
    ESP_LOGD(TAG, "probe step 4 done (DIO1 ISR)");
    if (dbg == 4) {
        probe_cleanup(4);
        return -1;
    }

    /* Step 5: Reset pulse, then BUSY must drop. A chip that never releases
     * it, or a floating pin with no chip, means "no radio". */
    gpio_set_level(PIN_RST, 0);
    vTaskDelay(pdMS_TO_TICKS(10));
    gpio_set_level(PIN_RST, 1);
    vTaskDelay(pdMS_TO_TICKS(20));
    if (sx_wait_busy() != 0) {
        ESP_LOGW(TAG, "SX1262 not detected (BUSY stuck high after reset)");
        probe_cleanup(4);
        return -1;
    }
    ESP_LOGD(TAG, "probe step 5 done (reset + BUSY wait)");
    if (dbg == 5) {
        probe_cleanup(4);
        return -1;
    }

    /* Step 6: Probe the SyncWord register. */
    uint8_t sync_hi = 0;
    if (sx_read_reg(0x0740, &sync_hi) != 0) {
        ESP_LOGW(TAG, "SX1262 not detected (no answer on SPI)");
        probe_cleanup(4);
        return -1;
    }
    ESP_LOGD(TAG, "probe step 6 done (sync_hi=0x%02X)", sync_hi);
    if (sync_hi == 0x00 || sync_hi == 0xFF) {
        ESP_LOGW(TAG, "SX1262 not detected (sync_hi=0x%02X)", sync_hi);
        probe_cleanup(4);
        return -1;
    }
    if (dbg == 6) {
        probe_cleanup(4);
        return -1;
    }
    ESP_LOGI(TAG, "SX1262 detected (sync_hi=0x%02X)", sync_hi);

    /* ---- Radio present: configure FEM ---- */
    /* FEM control pins are configured only after the probe succeeds,
     * so GPIO2 and GPIO7 stay free on boards without the SX1262
     * (Wokwi uses GPIO7 for the keypad).  DIO1 ISR was already set
     * up in step 4 above. */
    gpio_config_t fem_cfg = {
        .pin_bit_mask = (1ULL << PIN_FEM_EN) | (1ULL << PIN_VFEM_CTL),
        .mode = GPIO_MODE_OUTPUT,
    };
    gpio_config(&fem_cfg);
    gpio_set_level(PIN_FEM_EN, 1);
    gpio_set_level(PIN_VFEM_CTL, 0); /* RX path by default */

    /* Configure the chip. Any command that fails (BUSY timeout or SPI
     * error) leaves the radio unusable: report it and release it. */
    int rc = 0;

    /* Set standby mode (STDBY_RC). */
    uint8_t standby_cmd[] = {SX_CMD_SET_STANDBY, 0x00};
    rc |= sx_cmd(standby_cmd, sizeof(standby_cmd), NULL, 0);

    /* Set DIO2 as RF switch control. */
    uint8_t dio2_cmd[] = {SX_CMD_SET_DIO2_AS_RF_SW, 0x01};
    rc |= sx_cmd(dio2_cmd, sizeof(dio2_cmd), NULL, 0);

    /* Set regulator to DC-DC. */
    uint8_t reg_cmd[] = {SX_CMD_SET_REGULATOR_MODE, 0x01};
    rc |= sx_cmd(reg_cmd, sizeof(reg_cmd), NULL, 0);

    /* Calibrate. */
    uint8_t cal_cmd[] = {SX_CMD_CALIBRATE, 0x7F};
    rc |= sx_cmd(cal_cmd, sizeof(cal_cmd), NULL, 0);
    vTaskDelay(pdMS_TO_TICKS(10));

    /* Set packet type to LoRa. */
    uint8_t pkt_cmd[] = {SX_CMD_SET_PACKET_TYPE, 0x01};
    rc |= sx_cmd(pkt_cmd, sizeof(pkt_cmd), NULL, 0);

    /* Set frequency to the default game channel. */
    rc |= sx_set_frequency(CONFIG_ATALAIA_RADIO_DEFAULT_CHANNEL_HZ);

    /* Set modulation parameters: SF7, BW125, CR4/5, low-data-rate off. */
    uint8_t mod_cmd[] = {SX_CMD_SET_MODULATION, LORA_SF, 0x04, LORA_CR, 0x00};
    rc |= sx_cmd(mod_cmd, sizeof(mod_cmd), NULL, 0);

    /* Set PA config for SX1262 (+22 dBm capable PA). */
    uint8_t pa_cmd[] = {SX_CMD_SET_PA_CONFIG, 0x04, 0x07, 0x00, 0x01};
    rc |= sx_cmd(pa_cmd, sizeof(pa_cmd), NULL, 0);

    /* Set TX params: power, ramp time 200us. */
    int8_t power = TX_POWER_DBM;
    if (power < -9) power = -9;
    if (power > 22) power = 22;
    uint8_t tx_cmd[] = {SX_CMD_SET_TX_PARAMS, (uint8_t)power, 0x04};
    rc |= sx_cmd(tx_cmd, sizeof(tx_cmd), NULL, 0);

    /* Set sync word for private network. */
    rc |= sx_write_reg(0x0740, (uint8_t)(LORA_SYNC_WORD >> 8));
    rc |= sx_write_reg(0x0741, (uint8_t)(LORA_SYNC_WORD & 0xFF));

    /* Set buffer base addresses. */
    uint8_t buf_cmd[] = {SX_CMD_SET_BUFFER_BASE, 0x00, 0x80};
    rc |= sx_cmd(buf_cmd, sizeof(buf_cmd), NULL, 0);

    /* Set DIO1 IRQ: TX_DONE | RX_DONE | TIMEOUT on DIO1. */
    uint8_t irq_cmd[] = {SX_CMD_SET_DIO_IRQ_PARAMS,
                         (uint8_t)((SX_IRQ_ALL) >> 8),
                         (uint8_t)((SX_IRQ_ALL) & 0xFF),
                         (uint8_t)((SX_IRQ_TX_DONE | SX_IRQ_RX_DONE | SX_IRQ_TIMEOUT) >> 8),
                         (uint8_t)((SX_IRQ_TX_DONE | SX_IRQ_RX_DONE | SX_IRQ_TIMEOUT) & 0xFF),
                         0x00,
                         0x00,
                         0x00,
                         0x00};
    rc |= sx_cmd(irq_cmd, sizeof(irq_cmd), NULL, 0);

    if (rc != 0) {
        ESP_LOGE(TAG, "SX1262 configuration failed (BUSY timeout or SPI error)");
        gpio_set_level(PIN_FEM_EN, 0);
        probe_cleanup(4);
        return -1;
    }

    /* Init duty-cycle tracking. */
    memset(dc_buckets, 0, sizeof(dc_buckets));
    dc_used_us = 0;
    dc_current_bucket = 0;
    dc_last_update_ms = 0;

    ESP_LOGI(TAG, "SX1262 initialised: EU868, SF%d, BW%dk, TX %d dBm, ch %lu Hz", LORA_SF,
             LORA_BW_HZ / 1000, TX_POWER_DBM,
             (unsigned long)CONFIG_ATALAIA_RADIO_DEFAULT_CHANNEL_HZ);
    return 0;
}

/* Back to continuous RX on the game channel (after TX or a TX failure). */
static int sx_start_rx(void)
{
    uint8_t rx_cmd[] = {SX_CMD_SET_RX, 0xFF, 0xFF, 0xFF}; /* continuous */
    return sx_cmd(rx_cmd, sizeof(rx_cmd), NULL, 0);
}

static int esp_radio_send(const uint8_t *data, size_t len)
{
    if (len == 0 || len > 255) return -1;

    /* No channel hop -- all traffic uses the single game channel. */

    /* Set packet parameters: preamble, header explicit, payload len, CRC on,
     * IQ standard. */
    uint8_t pkt_cmd[] = {
        SX_CMD_SET_PACKET_PARAMS, 0x00, LORA_PREAMBLE, 0x00, (uint8_t)len, 0x01, 0x00};
    if (sx_cmd(pkt_cmd, sizeof(pkt_cmd), NULL, 0) != 0) return -1;

    /* Write payload to buffer at offset 0. */
    uint8_t wr_cmd[2 + 255];
    wr_cmd[0] = SX_CMD_WRITE_BUFFER;
    wr_cmd[1] = 0x00; /* offset */
    memcpy(wr_cmd + 2, data, len);
    if (sx_cmd(wr_cmd, 2 + len, NULL, 0) != 0) return -1;

    /* Clear IRQ and transmit (no timeout). */
    uint8_t clr_cmd[] = {SX_CMD_CLR_IRQ_STATUS, 0xFF, 0xFF};
    if (sx_cmd(clr_cmd, sizeof(clr_cmd), NULL, 0) != 0) return -1;

    uint8_t tx_cmd[] = {SX_CMD_SET_TX, 0x00, 0x00, 0x00};
    if (sx_cmd(tx_cmd, sizeof(tx_cmd), NULL, 0) != 0) return -1;

    /* Wait for TX_DONE on DIO1 (max 2 seconds). */
    if (xSemaphoreTake(dio1_sem, pdMS_TO_TICKS(2000)) != pdTRUE) {
        ESP_LOGW(TAG, "TX timeout");
        sx_start_rx();
        return -2;
    }

    /* Record airtime for duty-cycle tracking.
     * Approximate LoRa SF7/BW125 airtime: ~40ms for a 200-byte packet. */
    uint32_t airtime_us = 1000 * ((uint32_t)len + 20);
    uint32_t now_ms = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);
    dc_record(airtime_us, now_ms);

    /* Return to RX on the game channel after TX. */
    if (sx_start_rx() != 0) return -1;

    return 0;
}

static size_t esp_radio_recv(uint8_t *buf, size_t max_len, int8_t *rssi)
{
    /* Set packet params for max receive. */
    uint8_t pkt_cmd[] = {SX_CMD_SET_PACKET_PARAMS, 0x00, LORA_PREAMBLE, 0x00, 0xFF, 0x01, 0x00};
    if (sx_cmd(pkt_cmd, sizeof(pkt_cmd), NULL, 0) != 0) return 0;

    /* Clear IRQ and set RX with 50ms timeout. */
    uint8_t clr_cmd[] = {SX_CMD_CLR_IRQ_STATUS, 0xFF, 0xFF};
    if (sx_cmd(clr_cmd, sizeof(clr_cmd), NULL, 0) != 0) return 0;

    /* Timeout in units of 15.625 us: 50ms = 3200. */
    uint32_t timeout = 3200;
    uint8_t rx_cmd[] = {SX_CMD_SET_RX, (uint8_t)(timeout >> 16), (uint8_t)(timeout >> 8),
                        (uint8_t)(timeout & 0xFF)};
    if (sx_cmd(rx_cmd, sizeof(rx_cmd), NULL, 0) != 0) return 0;

    /* Wait for RX_DONE or timeout on DIO1. */
    if (xSemaphoreTake(dio1_sem, pdMS_TO_TICKS(100)) != pdTRUE) {
        return 0;
    }

    /* Check IRQ status. */
    uint8_t irq_cmd[] = {SX_CMD_GET_IRQ_STATUS, 0x00};
    uint8_t irq_resp[2];
    if (sx_cmd(irq_cmd, sizeof(irq_cmd), irq_resp, 2) != 0) return 0;
    uint16_t irq = ((uint16_t)irq_resp[0] << 8) | irq_resp[1];

    if (!(irq & SX_IRQ_RX_DONE)) {
        return 0;
    }

    /* Get RX buffer status: payload length and start offset. */
    uint8_t rxbuf_cmd[] = {SX_CMD_GET_RX_BUFFER_STATUS, 0x00};
    uint8_t rxbuf_resp[2];
    if (sx_cmd(rxbuf_cmd, sizeof(rxbuf_cmd), rxbuf_resp, 2) != 0) return 0;
    uint8_t payload_len = rxbuf_resp[0];
    uint8_t start_offset = rxbuf_resp[1];

    if (payload_len == 0 || payload_len > max_len) {
        return 0;
    }

    /* Read payload from buffer. */
    uint8_t rd_cmd[3];
    rd_cmd[0] = SX_CMD_READ_BUFFER;
    rd_cmd[1] = start_offset;
    rd_cmd[2] = 0x00; /* NOP */
    if (sx_cmd(rd_cmd, sizeof(rd_cmd), buf, payload_len) != 0) return 0;

    /* Get packet status for RSSI. */
    uint8_t pkt_status_cmd[] = {SX_CMD_GET_PACKET_STATUS, 0x00};
    uint8_t pkt_status[3];
    if (sx_cmd(pkt_status_cmd, sizeof(pkt_status_cmd), pkt_status, 3) != 0) {
        pkt_status[0] = 0;
    }
    if (rssi) {
        *rssi = (int8_t)(-(int)(pkt_status[0]) / 2);
    }

    return payload_len;
}

static int esp_radio_set_channel(uint32_t freq_hz)
{
    if (!eu868_channel_valid(freq_hz)) {
        ESP_LOGW(TAG, "channel %lu Hz outside EU868 sub-bands", (unsigned long)freq_hz);
        return -1;
    }
    return sx_set_frequency(freq_hz);
}

static int esp_radio_set_mode(hal_radio_mode_t mode)
{
    switch (mode) {
    case HAL_RADIO_MODE_SLEEP: {
        uint8_t cmd[] = {SX_CMD_SET_SLEEP, 0x00};
        return sx_cmd(cmd, sizeof(cmd), NULL, 0);
    }
    case HAL_RADIO_MODE_STANDBY: {
        uint8_t cmd[] = {SX_CMD_SET_STANDBY, 0x00};
        return sx_cmd(cmd, sizeof(cmd), NULL, 0);
    }
    case HAL_RADIO_MODE_RX: return sx_start_rx();
    case HAL_RADIO_MODE_TX:
        /* TX is started by send(). */
        break;
    }
    return 0;
}

static int8_t esp_radio_rssi(void)
{
    uint8_t cmd[] = {SX_CMD_GET_RSSI_INST, 0x00};
    uint8_t resp[1];
    if (sx_cmd(cmd, sizeof(cmd), resp, 1) != 0) {
        return INT8_MIN; /* no reading */
    }
    return (int8_t)(-(int)resp[0] / 2);
}

static uint32_t esp_radio_duty_cycle_remaining_ms(void)
{
    uint32_t now_ms = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);
    dc_tick(now_ms);
    if (dc_used_us >= DC_BUDGET_US) return 0;
    return (DC_BUDGET_US - dc_used_us) / 1000;
}

static void esp_radio_deinit(void)
{
    if (spi_handle) {
        /* Set sleep. */
        uint8_t cmd[] = {SX_CMD_SET_SLEEP, 0x00};
        (void)sx_cmd(cmd, sizeof(cmd), NULL, 0); /* best effort: we are shutting down */
        spi_bus_remove_device(spi_handle);
        spi_handle = NULL;
        spi_bus_free(SPI3_HOST);
    }
    gpio_set_level(PIN_FEM_EN, 0);
    if (dio1_sem) {
        gpio_isr_handler_remove(PIN_DIO1);
        vSemaphoreDelete(dio1_sem);
        dio1_sem = NULL;
    }
}

const hal_radio_ops_t hal_esp_radio_ops = {
    .init = esp_radio_init,
    .send = esp_radio_send,
    .recv = esp_radio_recv,
    .set_channel = esp_radio_set_channel,
    .set_mode = esp_radio_set_mode,
    .rssi = esp_radio_rssi,
    .duty_cycle_remaining_ms = esp_radio_duty_cycle_remaining_ms,
    .deinit = esp_radio_deinit,
};

#endif /* ESP_PLATFORM */
