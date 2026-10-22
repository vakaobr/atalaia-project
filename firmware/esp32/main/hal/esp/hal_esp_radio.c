/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * SX1262 LoRa radio driver for the Heltec WiFi LoRa 32 V4 (V4.3 with the
 * KCT8103L front-end module, or V4.2 with the GC1109: Kconfig "Board
 * revision"). EU868 band, SF7/BW125, single shared game channel (default
 * 869.525 MHz, g2 sub-band, 10% duty cycle, 500 mW ERP). The TX power and
 * the duty-cycle budget follow the sub-band of the channel in use
 * (radio/radio_limits.c, RFC 0001 Amendment 3): 25 mW ERP and 1% (or 0.1%)
 * outside 869.4-869.65 MHz. FEM gain (~14 dB) and antenna gain are
 * accounted for in the TX power setting (decision C2).
 *
 * The FEM is powered (its LDO on GPIO 7, its chip enable on GPIO 2, and
 * the revision's mode pin) only after the SX1262 answers its probe;
 * hal/board_fem.c plans the order. Before phase E the LDO pin was held
 * low, which on real boards would have left the FEM unpowered.
 *
 * The init function probes the SX1262 by reading a register. If the
 * chip is not present (e.g. Wokwi emulator), init returns -1 and the
 * rest of the firmware boots without radio -- same pattern as PN532.
 */

#ifdef ESP_PLATFORM

#include "../board_fem.h"
#include "../hal_radio.h"
#include "../../radio/noise_stats.h"
#include "../../radio/radio_limits.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_rom_sys.h"
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

#define PIN_FEM_EN   CONFIG_ATALAIA_RADIO_FEM_EN_PIN
#define PIN_VFEM_CTL CONFIG_ATALAIA_RADIO_VFEM_CTL_PIN

#if CONFIG_ATALAIA_BOARD_HELTEC_V4_2
#define BOARD_FEM   BOARD_FEM_GC1109
#define PIN_FEM_PA  CONFIG_ATALAIA_RADIO_FEM_PA_PIN
#define PIN_FEM_CTX (-1)
#else
#define BOARD_FEM   BOARD_FEM_KCT8103L
#define PIN_FEM_PA  (-1)
#define PIN_FEM_CTX CONFIG_ATALAIA_RADIO_FEM_CTX_PIN
#endif

static const board_fem_pins_t fem_pins = {
    .fem = BOARD_FEM,
    .power_pin = PIN_VFEM_CTL,
    .enable_pin = PIN_FEM_EN,
    .pa_pin = PIN_FEM_PA,
    .ctx_pin = PIN_FEM_CTX,
};

static void fem_apply(const board_pin_step_t *steps, size_t n)
{
    for (size_t i = 0; i < n; i++) {
        gpio_set_level(steps[i].pin, steps[i].level);
        if (steps[i].delay_us) esp_rom_delay_us(steps[i].delay_us);
    }
}

static void fem_power_off(void)
{
    board_pin_step_t steps[BOARD_FEM_MAX_STEPS];
    fem_apply(steps, board_fem_power_off(&fem_pins, steps, BOARD_FEM_MAX_STEPS));
}
#define FEM_GAIN_DB      CONFIG_ATALAIA_RADIO_FEM_GAIN_DB
#define ANTENNA_GAIN_DBI CONFIG_ATALAIA_RADIO_ANTENNA_GAIN_DBI

/* Default game channel from Kconfig (869.525 MHz, g2 sub-band). */
#ifndef CONFIG_ATALAIA_RADIO_DEFAULT_CHANNEL_HZ
#define CONFIG_ATALAIA_RADIO_DEFAULT_CHANNEL_HZ 869525000
#endif

/* LoRa parameters: SF7, BW125, CR4/5. */
#define LORA_SF       7
#define LORA_BW_HZ    125000
#define LORA_CR       1 /* 4/5 */
#define LORA_PREAMBLE 8
/* The SX126x private-network sync word (0x1424; LoRaWAN's public one is
 * 0x3444), so LoRaWAN gateways and devices sharing a channel do not
 * demodulate game packets, nor the boxes theirs. ADR-P2's radio settings
 * chose "private"; earlier builds wrote 0x3444 by mistake. */
#define LORA_SYNC_WORD 0x1424

/* The conducted TX power comes from the channel's sub-band (radio_limits):
 * with FEM=14 dB and antenna=2 dBi, 13 dBm on 869.4-869.65 MHz (500 mW ERP)
 * and 0 dBm elsewhere (25 mW ERP). */

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
#define SX_CMD_SET_CAD              0xC5
#define SX_CMD_SET_CAD_PARAMS       0x88
#define SX_CMD_GET_DEVICE_ERRORS    0x17
#define SX_CMD_CLR_DEVICE_ERRORS    0x07

/* The Heltec V3/V4 clock the SX1262 from a 1.8 V TCXO powered by its DIO3
 * (as RadioLib and Meshtastic's Heltec variants set it). Without it the
 * crystal oscillator never starts: registers still answer on the RC clock,
 * but the PLL cannot lock and every SetTx times out. */
#define SX_TCXO_1V8       0x02
#define SX_TCXO_DELAY     320 /* 5 ms, in 15.625 us steps */
#define SX_ERR_XOSC_START (1 << 5)

/* IRQ masks. */
#define SX_IRQ_TX_DONE      (1 << 0)
#define SX_IRQ_RX_DONE      (1 << 1)
#define SX_IRQ_HEADER_ERR   (1 << 5)
#define SX_IRQ_CRC_ERR      (1 << 6)
#define SX_IRQ_CAD_DONE     (1 << 7)
#define SX_IRQ_CAD_DETECTED (1 << 8)
#define SX_IRQ_TIMEOUT      (1 << 9)
#define SX_IRQ_ALL          0x03FF

/* ---- State --------------------------------------------------------------- */

static spi_device_handle_t spi_handle;
static SemaphoreHandle_t dio1_sem;

/* The channel in use, its sub-band's TX power and the per-sub-band airtime
 * of the last hour (60-bucket sliding window, core duty_cycle.c). */
static radio_limits_t limits;

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

/* ---- Radio ops ----------------------------------------------------------- */

static int sx_set_frequency(uint32_t freq_hz)
{
    /* Freq register = freq * 2^25 / 32 MHz. */
    uint32_t frf = (uint32_t)((uint64_t)freq_hz * (1ULL << 25) / 32000000ULL);
    uint8_t cmd[] = {SX_CMD_SET_RF_FREQUENCY, (uint8_t)(frf >> 24), (uint8_t)(frf >> 16),
                     (uint8_t)(frf >> 8), (uint8_t)(frf & 0xFF)};
    return sx_cmd(cmd, sizeof(cmd), NULL, 0);
}

/* TX power in dBm (conducted), ramp time 200 us. */
static int sx_set_tx_power(int8_t power)
{
    if (power < -9) power = -9;
    if (power > 22) power = 22;
    uint8_t cmd[] = {SX_CMD_SET_TX_PARAMS, (uint8_t)power, 0x04};
    return sx_cmd(cmd, sizeof(cmd), NULL, 0);
}

/* Why the last init failed, in a few words for the modem's OLED ("" = ok). */
static char init_fault[40];

static void set_fault(const char *why)
{
    snprintf(init_fault, sizeof(init_fault), "%s", why);
}

const char *hal_esp_radio_fault(void)
{
    return init_fault;
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
    set_fault(dbg ? "radio init stopped (debug step)" : "");

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
        set_fault("radio SPI bus failed");
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
        set_fault("radio SPI failed");
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
        set_fault("radio: no memory");
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
        set_fault("SX1262 not found (BUSY stuck)");
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
        set_fault("SX1262 not found (no SPI answer)");
        probe_cleanup(4);
        return -1;
    }
    ESP_LOGD(TAG, "probe step 6 done (sync_hi=0x%02X)", sync_hi);
    if (sync_hi == 0x00 || sync_hi == 0xFF) {
        ESP_LOGW(TAG, "SX1262 not detected (sync_hi=0x%02X)", sync_hi);
        set_fault("SX1262 not found");
        probe_cleanup(4);
        return -1;
    }
    if (dbg == 6) {
        probe_cleanup(4);
        return -1;
    }
    ESP_LOGI(TAG, "SX1262 detected (sync_hi=0x%02X)", sync_hi);

    /* ---- Radio present: power the FEM ---- */
    /* FEM control pins are configured only after the probe succeeds,
     * so GPIO 2, 5, 7 and 46 stay free on boards without the SX1262
     * (Wokwi uses GPIO 7 for the keypad and GPIO 5 for button 2).  DIO1
     * ISR was already set up in step 4 above. */
    {
        static const int others[] = {CONFIG_ATALAIA_BTN1_PIN, CONFIG_ATALAIA_BTN2_PIN,
                                     CONFIG_ATALAIA_BTN3_PIN, CONFIG_ATALAIA_BTN4_PIN};
        int clash = board_fem_conflict(&fem_pins, others, sizeof(others) / sizeof(others[0]));
        if (clash >= 0) {
            ESP_LOGE(TAG,
                     "GPIO %d is both a team button and the %s front-end control: move the "
                     "button (menuconfig > Buttons)",
                     clash, board_fem_name(BOARD_FEM));
        }
        board_pin_step_t steps[BOARD_FEM_MAX_STEPS];
        size_t n = board_fem_power_on(&fem_pins, steps, BOARD_FEM_MAX_STEPS);
        uint64_t mask = 0;
        for (size_t i = 0; i < n; i++) mask |= 1ULL << steps[i].pin;
        gpio_config_t fem_cfg = {.pin_bit_mask = mask, .mode = GPIO_MODE_OUTPUT};
        gpio_config(&fem_cfg);
        fem_apply(steps, n);
        ESP_LOGI(TAG, "front-end module %s powered", board_fem_name(BOARD_FEM));
    }

    /* Configure the chip. Any command that fails (BUSY timeout or SPI
     * error) leaves the radio unusable: report it and release it. */
    int rc = 0;

    /* Set standby mode (STDBY_RC). */
    uint8_t standby_cmd[] = {SX_CMD_SET_STANDBY, 0x00};
    rc |= sx_cmd(standby_cmd, sizeof(standby_cmd), NULL, 0);

    /* Power the TCXO from DIO3 before calibrating, then clear the
     * oscillator start-up error the chip flags at power-on without it. */
    uint8_t tcxo_cmd[] = {SX_CMD_SET_DIO3_AS_TCXO, SX_TCXO_1V8, (uint8_t)(SX_TCXO_DELAY >> 16),
                          (uint8_t)(SX_TCXO_DELAY >> 8), (uint8_t)(SX_TCXO_DELAY & 0xFF)};
    rc |= sx_cmd(tcxo_cmd, sizeof(tcxo_cmd), NULL, 0);
    uint8_t clr_err_cmd[] = {SX_CMD_CLR_DEVICE_ERRORS, 0x00, 0x00};
    rc |= sx_cmd(clr_err_cmd, sizeof(clr_err_cmd), NULL, 0);

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

    /* A clock or calibration fault would time out every transmission:
     * refuse the radio instead. */
    uint8_t err_cmd[] = {SX_CMD_GET_DEVICE_ERRORS, 0x00};
    uint8_t err_resp[2] = {0};
    rc |= sx_cmd(err_cmd, sizeof(err_cmd), err_resp, sizeof(err_resp));
    uint16_t dev_errors = (uint16_t)((err_resp[0] << 8) | err_resp[1]);
    if (rc == 0 && dev_errors != 0) {
        ESP_LOGE(TAG, "SX1262 device errors 0x%04x after calibration%s", dev_errors,
                 (dev_errors & SX_ERR_XOSC_START) ? " (TCXO did not start)" : "");
        snprintf(init_fault, sizeof(init_fault), "SX1262 errors 0x%04x%s", dev_errors,
                 (dev_errors & SX_ERR_XOSC_START) ? " (TCXO)" : "");
        fem_power_off();
        probe_cleanup(4);
        return -1;
    }

    /* Set packet type to LoRa. */
    uint8_t pkt_cmd[] = {SX_CMD_SET_PACKET_TYPE, 0x01};
    rc |= sx_cmd(pkt_cmd, sizeof(pkt_cmd), NULL, 0);

    /* The default game channel; its sub-band sets the TX power and budget. */
    radio_limits_init(&limits, FEM_GAIN_DB, ANTENNA_GAIN_DBI);
    uint32_t channel = CONFIG_ATALAIA_RADIO_DEFAULT_CHANNEL_HZ;
    if (!radio_limits_set_channel(&limits, channel)) {
        ESP_LOGE(TAG, "default channel %lu Hz does not fit in an EU868 sub-band; using 869525000",
                 (unsigned long)channel);
        channel = 869525000u;
        radio_limits_set_channel(&limits, channel);
    }
    rc |= sx_set_frequency(channel);

    /* Set modulation parameters: SF7, BW125, CR4/5, low-data-rate off. */
    uint8_t mod_cmd[] = {SX_CMD_SET_MODULATION, LORA_SF, 0x04, LORA_CR, 0x00};
    rc |= sx_cmd(mod_cmd, sizeof(mod_cmd), NULL, 0);

    /* Set PA config for SX1262 (+22 dBm capable PA). */
    uint8_t pa_cmd[] = {SX_CMD_SET_PA_CONFIG, 0x04, 0x07, 0x00, 0x01};
    rc |= sx_cmd(pa_cmd, sizeof(pa_cmd), NULL, 0);

    /* Set TX params: the sub-band's power, ramp time 200us. */
    rc |= sx_set_tx_power(limits.tx_power_dbm);

    /* Set sync word for private network. */
    rc |= sx_write_reg(0x0740, (uint8_t)(LORA_SYNC_WORD >> 8));
    rc |= sx_write_reg(0x0741, (uint8_t)(LORA_SYNC_WORD & 0xFF));

    /* Set buffer base addresses. */
    uint8_t buf_cmd[] = {SX_CMD_SET_BUFFER_BASE, 0x00, 0x80};
    rc |= sx_cmd(buf_cmd, sizeof(buf_cmd), NULL, 0);

    /* Set DIO1 IRQ: TX_DONE | RX_DONE | TIMEOUT | CAD_DONE on DIO1. */
    uint16_t dio1 = SX_IRQ_TX_DONE | SX_IRQ_RX_DONE | SX_IRQ_TIMEOUT | SX_IRQ_CAD_DONE;
    uint8_t irq_cmd[] = {SX_CMD_SET_DIO_IRQ_PARAMS,
                         (uint8_t)((SX_IRQ_ALL) >> 8),
                         (uint8_t)((SX_IRQ_ALL) & 0xFF),
                         (uint8_t)(dio1 >> 8),
                         (uint8_t)(dio1 & 0xFF),
                         0x00,
                         0x00,
                         0x00,
                         0x00};
    rc |= sx_cmd(irq_cmd, sizeof(irq_cmd), NULL, 0);

    if (rc != 0) {
        ESP_LOGE(TAG, "SX1262 configuration failed (BUSY timeout or SPI error)");
        set_fault("SX1262 setup failed");
        fem_power_off();
        probe_cleanup(4);
        return -1;
    }

    ESP_LOGI(TAG, "SX1262 initialised: EU868, SF%d, BW%dk, TX %d dBm, ch %lu Hz", LORA_SF,
             LORA_BW_HZ / 1000, limits.tx_power_dbm, (unsigned long)limits.channel_hz);
    return 0;
}

/* Whether the chip is in continuous RX; anything that takes it out clears this. */
static bool rx_armed;

/* Continuous RX on the current channel, for packets of any length. The chip
 * stays in RX after each packet, so recv() only collects them: re-arming per
 * call left a deaf gap that lost a frame sent right after another (found on
 * the bench: an invite's second part, a game's START right before its TIME). */
static int sx_start_rx(void)
{
    uint8_t pkt_cmd[] = {SX_CMD_SET_PACKET_PARAMS, 0x00, LORA_PREAMBLE, 0x00, 0xFF, 0x01, 0x00};
    uint8_t clr_cmd[] = {SX_CMD_CLR_IRQ_STATUS, 0xFF, 0xFF};
    uint8_t rx_cmd[] = {SX_CMD_SET_RX, 0xFF, 0xFF, 0xFF}; /* continuous */
    rx_armed = false;
    if (sx_cmd(pkt_cmd, sizeof(pkt_cmd), NULL, 0) != 0 ||
        sx_cmd(clr_cmd, sizeof(clr_cmd), NULL, 0) != 0) {
        return -1;
    }
    xSemaphoreTake(dio1_sem, 0); /* drop a stale DIO1 edge */
    if (sx_cmd(rx_cmd, sizeof(rx_cmd), NULL, 0) != 0) return -1;
    rx_armed = true;
    return 0;
}

static uint32_t now_ms(void)
{
    return (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);
}

static int esp_radio_send(const uint8_t *data, size_t len)
{
    if (len == 0 || len > 255) return -1;
    /* The whole packet's time on air must fit in the sub-band's budget. */
    if (!radio_limits_can_send(&limits, len, now_ms())) return -3;

    /* No channel hop -- all traffic uses the single game channel. */

    /* Out of continuous RX first, so a packet finishing now cannot raise DIO1
     * after the stale edge is dropped below and pass for TX_DONE. */
    uint8_t stby[] = {SX_CMD_SET_STANDBY, 0x00};
    rx_armed = false;
    if (sx_cmd(stby, sizeof(stby), NULL, 0) != 0) return -1;

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
    xSemaphoreTake(dio1_sem, 0); /* a packet received before standby is not TX_DONE */

    uint8_t tx_cmd[] = {SX_CMD_SET_TX, 0x00, 0x00, 0x00};
    if (sx_cmd(tx_cmd, sizeof(tx_cmd), NULL, 0) != 0) return -1;

    /* Wait for TX_DONE on DIO1 (max 2 seconds). */
    if (xSemaphoreTake(dio1_sem, pdMS_TO_TICKS(2000)) != pdTRUE) {
        ESP_LOGW(TAG, "TX timeout");
        /* The chip may have sent it with only the interrupt lost: count the
         * time on air anyway, so retries stay inside the duty cycle. */
        radio_limits_record(&limits, len, now_ms());
        sx_start_rx();
        return -2;
    }

    /* Record the time on air (LoRa formula, SF7/BW125) in the sub-band's budget. */
    radio_limits_record(&limits, len, now_ms());

    /* Return to RX on the game channel after TX. */
    if (sx_start_rx() != 0) return -1;

    return 0;
}

static size_t esp_radio_recv(uint8_t *buf, size_t max_len, int8_t *rssi)
{
    if (!rx_armed && sx_start_rx() != 0) return 0;

    /* Up to 50 ms for a finished packet; the chip keeps listening meanwhile, so
     * returning empty-handed loses nothing (a long packet completes later). */
    if (xSemaphoreTake(dio1_sem, pdMS_TO_TICKS(50)) != pdTRUE) return 0;

    uint8_t irq_cmd[] = {SX_CMD_GET_IRQ_STATUS, 0x00};
    uint8_t irq_resp[2];
    if (sx_cmd(irq_cmd, sizeof(irq_cmd), irq_resp, 2) != 0) return 0;
    uint16_t irq = ((uint16_t)irq_resp[0] << 8) | irq_resp[1];
    /* Clear at once: DIO1 falls, so the next packet raises a new edge. */
    uint8_t clr_cmd[] = {SX_CMD_CLR_IRQ_STATUS, 0xFF, 0xFF};
    if (sx_cmd(clr_cmd, sizeof(clr_cmd), NULL, 0) != 0) {
        rx_armed = false;
        return 0;
    }

    if (!(irq & SX_IRQ_RX_DONE) || (irq & (SX_IRQ_CRC_ERR | SX_IRQ_HEADER_ERR))) {
        return 0; /* a damaged packet; the chip is still listening */
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
    int8_t power;
    if (!radio_limits_power_for(&limits, freq_hz, &power)) {
        ESP_LOGW(TAG, "channel %lu Hz: the 125 kHz channel does not fit in an EU868 sub-band",
                 (unsigned long)freq_hz);
        return -1;
    }
    /* Retune from standby, not mid-receive. Power first when it drops, so the
     * radio never sends at the old (higher) power on the new channel; frequency
     * first when it rises. */
    uint8_t stby[] = {SX_CMD_SET_STANDBY, 0x00};
    rx_armed = false;
    if (sx_cmd(stby, sizeof(stby), NULL, 0) != 0) return -1;
    if (power <= limits.tx_power_dbm) {
        if (sx_set_tx_power(power) != 0 || sx_set_frequency(freq_hz) != 0) return -1;
    } else {
        if (sx_set_frequency(freq_hz) != 0 || sx_set_tx_power(power) != 0) return -1;
    }
    radio_limits_set_channel(&limits, freq_hz);
    rx_armed = false; /* the next recv() listens on the new channel */
    ESP_LOGI(TAG, "channel %lu Hz, TX %d dBm conducted, budget %lu ms left this hour",
             (unsigned long)freq_hz, power,
             (unsigned long)radio_limits_remaining_ms(&limits, now_ms()));
    return 0;
}

static int esp_radio_set_mode(hal_radio_mode_t mode)
{
    switch (mode) {
    case HAL_RADIO_MODE_SLEEP: {
        uint8_t cmd[] = {SX_CMD_SET_SLEEP, 0x00};
        rx_armed = false;
        return sx_cmd(cmd, sizeof(cmd), NULL, 0);
    }
    case HAL_RADIO_MODE_STANDBY: {
        uint8_t cmd[] = {SX_CMD_SET_STANDBY, 0x00};
        rx_armed = false;
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
    return radio_limits_remaining_ms(&limits, now_ms());
}

/* ---- Noise measurement (USB modem MEASURE) -------------------------------- */

/* One channel-activity detection on the current frequency: true if a LoRa
 * preamble was seen. Two symbols, with the detection thresholds the SX126x
 * documentation gives for SF7 / 125 kHz. *ok is false on a radio error. */
static bool sx_cad_once(bool *ok)
{
    uint8_t stby[] = {SX_CMD_SET_STANDBY, 0x00};
    uint8_t params[] = {
        SX_CMD_SET_CAD_PARAMS, 0x01 /* 2 symbols */, 22, 10, 0x00 /* CAD only */, 0x00, 0x00, 0x00};
    uint8_t clr[] = {SX_CMD_CLR_IRQ_STATUS, 0xFF, 0xFF};
    uint8_t cad[] = {SX_CMD_SET_CAD};
    *ok = false;
    rx_armed = false; /* the caller listens again with sx_start_rx() */
    if (sx_cmd(stby, sizeof(stby), NULL, 0) != 0 || sx_cmd(params, sizeof(params), NULL, 0) != 0 ||
        sx_cmd(clr, sizeof(clr), NULL, 0) != 0) {
        return false;
    }
    xSemaphoreTake(dio1_sem, 0); /* drop a stale DIO1 edge */
    if (sx_cmd(cad, sizeof(cad), NULL, 0) != 0) return false;
    if (xSemaphoreTake(dio1_sem, pdMS_TO_TICKS(50)) != pdTRUE) return false;
    uint8_t irq_cmd[] = {SX_CMD_GET_IRQ_STATUS, 0x00};
    uint8_t irq_resp[2];
    if (sx_cmd(irq_cmd, sizeof(irq_cmd), irq_resp, 2) != 0) return false;
    uint16_t irq = ((uint16_t)irq_resp[0] << 8) | irq_resp[1];
    *ok = (irq & SX_IRQ_CAD_DONE) != 0;
    return *ok && (irq & SX_IRQ_CAD_DETECTED) != 0;
}

static int esp_radio_measure(uint32_t freq_hz, uint32_t dwell_ms, bool cad, noise_result_t *out)
{
    static noise_acc_t acc; /* 520 bytes: kept off the radio task's stack */
    if (!atalaia_channel_ok(freq_hz)) return -2;
    if (dwell_ms < NOISE_DWELL_MIN_MS) dwell_ms = NOISE_DWELL_MIN_MS;
    if (dwell_ms > NOISE_DWELL_MAX_MS) dwell_ms = NOISE_DWELL_MAX_MS;
    noise_acc_init(&acc);
    uint8_t stby[] = {SX_CMD_SET_STANDBY, 0x00}; /* retune from standby, not mid-receive */
    int rc = sx_cmd(stby, sizeof(stby), NULL, 0) == 0 && sx_set_frequency(freq_hz) == 0 &&
                     sx_start_rx() == 0
                 ? 0
                 : -1;
    uint32_t start = now_ms();
    uint32_t next_cad = start + 50;
    while (rc == 0 && now_ms() - start < dwell_ms) {
        int8_t rssi = esp_radio_rssi();
        if (rssi == INT8_MIN) {
            rc = -1;
            break;
        }
        noise_acc_add(&acc, rssi);
        if (cad && (int32_t)(now_ms() - next_cad) >= 0) {
            bool ok;
            bool seen = sx_cad_once(&ok);
            if (ok) noise_acc_cad(&acc, seen);
            if (sx_start_rx() != 0) rc = -1;
            next_cad = now_ms() + 100;
        }
        vTaskDelay(1); /* about one reading per millisecond */
    }
    /* Back to the game channel, listening. */
    if (sx_cmd(stby, sizeof(stby), NULL, 0) != 0 || sx_set_frequency(limits.channel_hz) != 0 ||
        sx_start_rx() != 0) {
        rc = -1;
    }
    if (rc != 0) return rc;
    return noise_acc_finish(&acc, freq_hz, (uint16_t)dwell_ms, out) ? 0 : -1;
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
    fem_power_off();
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
    .measure = esp_radio_measure,
    .deinit = esp_radio_deinit,
};

#endif /* ESP_PLATFORM */
