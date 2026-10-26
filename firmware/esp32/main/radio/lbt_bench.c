/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The bench test of listen-before-talk's gate (decision SL-25, step 1;
 * docs/runbooks/lbt-bench-gate.md). Bench images only (Kconfig ATALAIA_LBT_BENCH, set in
 * sdkconfig.bench); the commands are typed on the serial console: "@lbt tx", "@lbt probe",
 * "@lbt stop", "@lbt status". Nothing runs until one is typed. "proxy=as923" runs the AS923-TW
 * modulation (SF9/500 kHz, its CAD settings) on 868.3 MHz under EU868 sub-band g's limits
 * (lbt_profile.h), and puts the build's radio settings back when the run ends.
 *
 * The test runs inside the radio task, in place of its loop (radio_task_bench_start): the task
 * owns the SPI bus and the game sends and receives nothing meanwhile. Its log lines ("LBT,...")
 * go through a queue to a low-priority task, so that a slow console never delays a probe.
 */
#ifdef ESP_PLATFORM

#include "sdkconfig.h"

#if CONFIG_ATALAIA_LBT_BENCH

#include "lbt_bench.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "atalaia/duty_cycle.h"
#include "esp_log.h"
#include "esp_random.h"
#include "esp_rom_sys.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "lbt_profile.h"
#include "lbt_stats.h"
#include "radio_region.h"
#include "radio_task.h"

static const char *TAG = "lbt";

/* The transmitter stops when the sub-band's budget left falls under 70 % of it
 * (lbt_profile_guard_ms): at most 30 % of the sub-band's hour is spent, across runs. */
#define IDLE_END_US (60LL * 1000000)

typedef struct {
    char s[224]; /* the cfg line is the longest */
} line_t;

static QueueHandle_t line_q;
static volatile uint32_t lines_dropped;
static lbt_cmd_t active;
static lbt_profile_t prof; /* the radio settings of the run: the build's or the proxy's */
static lbt_stats_t stats;  /* the prober's; 5 KB of waiting probes */

/* ---- the log: a queue and a task that prints ------------------------------------------- */

static void printer_task(void *arg)
{
    (void)arg;
    line_t l;
    for (;;) {
        if (xQueueReceive(line_q, &l, portMAX_DELAY) == pdTRUE) {
            fputs(l.s, stdout);
            fputc('\n', stdout);
        }
    }
}

static bool log_start(void)
{
    if (line_q != NULL) return true;
    line_q = xQueueCreate(160, sizeof(line_t));
    if (line_q == NULL) return false;
    if (xTaskCreatePinnedToCore(printer_task, "lbt_log", 3072, NULL, 1, NULL, 1) != pdPASS) {
        vQueueDelete(line_q);
        line_q = NULL;
        return false;
    }
    return true;
}

static void emit(const char *fmt, ...)
{
    line_t l;
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(l.s, sizeof(l.s), fmt, ap);
    va_end(ap);
    if (xQueueSend(line_q, &l, 0) != pdTRUE) lines_dropped++;
}

static uint32_t now_us32(void)
{
    return (uint32_t)esp_timer_get_time();
}

static uint32_t symbol_us(const lbt_profile_t *p)
{
    return (uint32_t)(((uint64_t)1 << p->sf) * 1000000u / p->bw_hz);
}

/* The run's radio settings, all of them: profile, channel, modulation, the CAD settings under test
 * and the duty limit (bench_lbt_gate.py reports them). */
static void emit_cfg(const char *role)
{
    char tx[8];
    if (prof.proxy) {
        snprintf(tx, sizeof(tx), "%d", (int)prof.tx_power_dbm);
    } else {
        snprintf(tx, sizeof(tx), "hal");
    }
    emit("LBT,cfg,role=%s,profile=%s,region=%s,mod=%s,freq=%lu,sf=%u,bw=%lu,sym_us=%lu,cad_sym=%u,"
         "det_peak=%u,det_min=%u,peak_proven=%u,duty_ppm=%lu,limit_dbm=%d,tx_dbm=%s",
         role, prof.name, radio_region_code(RADIO_REGION), prof.mod_from,
         (unsigned long)prof.freq_hz, (unsigned)prof.sf, (unsigned long)prof.bw_hz,
         (unsigned long)symbol_us(&prof), (unsigned)prof.cad.symbols, (unsigned)prof.cad.det_peak,
         (unsigned)prof.cad.det_min, (unsigned)prof.cad.det_peak_bench_proven,
         (unsigned long)prof.duty_ppm, (int)prof.limit_dbm, tx);
}

/* A proxy run puts the radio on its profile before anything else and the build's settings back
 * after (the game's radio is the test's meanwhile). The channel is asserted inside the sub-band
 * and clear of every AS923 frequency before the radio is touched. */
static bool profile_enter(const hal_radio_ops_t *radio, const char *role)
{
    if (!prof.proxy) return true;
    hal_radio_profile_t hp;
    lbt_profile_to_hal(&prof, &hp);
    if (!lbt_profile_channel_ok(&prof) || radio->set_profile == NULL ||
        radio->set_profile(&hp) != 0) {
        emit("LBT,end,role=%s,reason=profile", role);
        return false;
    }
    return true;
}

static void profile_leave(const hal_radio_ops_t *radio)
{
    if (prof.proxy && radio->set_profile != NULL) (void)radio->set_profile(NULL);
}

/* ---- the prober ----------------------------------------------------------------------------- */

static void emit_summary(const lbt_stats_t *s)
{
    uint32_t in_n = lbt_stats_in_total(s), in_hit = lbt_stats_hit_total(s);
    emit("LBT,sum,frames=%lu,lost=%lu,in=%lu,hit=%lu,hit_pm=%lu,out=%lu,out_busy=%lu,amb=%lu,err=%"
         "lu",
         (unsigned long)s->frames, (unsigned long)s->frames_lost, (unsigned long)in_n,
         (unsigned long)in_hit, (unsigned long)lbt_permille(in_hit, in_n), (unsigned long)s->out_n,
         (unsigned long)s->out_busy, (unsigned long)s->amb_n, (unsigned long)s->err_n);
    char d[LBT_DECILES * 12 + 8];
    size_t o = 0;
    for (int i = 0; i < LBT_DECILES; i++) {
        o += (size_t)snprintf(d + o, sizeof(d) - o, "%s%lu/%lu", i ? ":" : "",
                              (unsigned long)s->in_n[i], (unsigned long)s->in_hit[i]);
    }
    emit("LBT,dec,n/hit=%s", d);
    emit("LBT,seg,pre=%lu/%lu,hdr=%lu/%lu,pay=%lu/%lu,by_cad=%lu,by_pre=%lu,by_hdr=%lu",
         (unsigned long)s->seg_n[LBT_SEG_PREAMBLE], (unsigned long)s->seg_hit[LBT_SEG_PREAMBLE],
         (unsigned long)s->seg_n[LBT_SEG_HEADER], (unsigned long)s->seg_hit[LBT_SEG_HEADER],
         (unsigned long)s->seg_n[LBT_SEG_PAYLOAD], (unsigned long)s->seg_hit[LBT_SEG_PAYLOAD],
         (unsigned long)s->hit_cad, (unsigned long)s->hit_preamble, (unsigned long)s->hit_header);
    emit("LBT,tim,cad_n=%lu,cad_avg_us=%lu,cad_min_us=%lu,cad_max_us=%lu,rearm_avg_us=%lu,"
         "rearm_max_us=%lu,probes_dropped=%lu,lines_dropped=%lu",
         (unsigned long)s->cad_n, (unsigned long)(s->cad_n ? s->cad_sum_us / s->cad_n : 0),
         (unsigned long)s->cad_min_us, (unsigned long)s->cad_max_us,
         (unsigned long)(s->rearm_n ? s->rearm_sum_us / s->rearm_n : 0),
         (unsigned long)s->rearm_max_us, (unsigned long)s->dropped, (unsigned long)lines_dropped);
}

/* A frame arrived: its window, and what the probes made of it. */
static void handle_frame(const hal_radio_ops_t *radio, lbt_stats_t *s, const uint8_t *buf,
                         size_t len, int8_t rssi, bool *have_seq, uint32_t *last_seq)
{
    uint32_t airtime = lbt_profile_airtime_us(&prof, len);
    uint32_t end = (uint32_t)(radio->last_rx_done_us != NULL ? radio->last_rx_done_us() : 0);
    uint32_t seq = 0, lost = 0;
    bool ours = lbt_frame_parse(buf, len, &seq);
    if (ours) {
        if (*have_seq && seq > *last_seq + 1) lost = seq - *last_seq - 1;
        if (!*have_seq || seq > *last_seq) *last_seq = seq;
        *have_seq = true;
    }
    lbt_stats_frame(s, end, airtime, symbol_us(&prof), lost);
    emit("LBT,r,%lu,%lu,%u,%ld,%lu,%d,%lu", (unsigned long)s->frames, (unsigned long)end,
         (unsigned)len, ours ? (long)seq : -1L, (unsigned long)airtime, (int)rssi,
         (unsigned long)lost);
    if (s->frames % LBT_SUMMARY_EVERY == 0) emit_summary(s);
}

static void prober_body(const hal_radio_ops_t *radio)
{
    uint32_t rng = esp_random() | 1u;
    lbt_stats_init(&stats);
    lines_dropped = 0;
    if (radio->set_channel(prof.freq_hz) != 0 || radio->set_mode(HAL_RADIO_MODE_RX) != 0 ||
        radio->channel_busy == NULL) {
        emit("LBT,end,role=probe,reason=radio");
        return;
    }
    emit_cfg("probe");
    emit("LBT,start,role=probe,frames=%lu,gap_us=%lu-%lu", (unsigned long)active.frames,
         (unsigned long)active.gap_min_us, (unsigned long)active.gap_max_us);

    bool have_seq = false;
    uint32_t last_seq = 0;
    int64_t last_frame_at = esp_timer_get_time();
    int64_t next = esp_timer_get_time();
    uint32_t loops = 0;
    const char *reason = "frames";
    while (stats.frames < active.frames) {
        if (radio_task_bench_stop_requested()) {
            reason = "stop";
            break;
        }
        if (esp_timer_get_time() - last_frame_at > IDLE_END_US) {
            reason = "idle";
            break;
        }
        hal_radio_busy_t info;
        int rc = radio->channel_busy(&info);
        (void)rc;
        lbt_stats_probe(&stats, (uint32_t)info.sample_us, info.why, info.cad_us, info.rearm_us);
        emit("LBT,p,%lu,%u,%lu,%lu", (unsigned long)(uint32_t)info.sample_us, (unsigned)info.why,
             (unsigned long)info.cad_us, (unsigned long)info.rearm_us);

        if (info.why == HAL_BUSY_RX_DONE) {
            uint8_t buf[255];
            int8_t rssi = 0;
            size_t len = radio->recv(buf, sizeof(buf), &rssi);
            if (len > 0) {
                handle_frame(radio, &stats, buf, len, rssi, &have_seq, &last_seq);
                last_frame_at = esp_timer_get_time();
            } else {
                radio->set_mode(HAL_RADIO_MODE_RX); /* a damaged frame: clear it, listen again */
            }
        }

        /* The next probe a random gap after this one's start (or at once if it ran longer). */
        next += (int64_t)lbt_rand_range(&rng, active.gap_min_us, active.gap_max_us);
        int64_t wait = next - esp_timer_get_time();
        if (wait > 0) {
            esp_rom_delay_us((uint32_t)wait);
        } else {
            next = esp_timer_get_time();
        }
        if ((++loops & 127u) == 0) vTaskDelay(1); /* let the idle task run */
    }
    emit_summary(&stats);
    emit("LBT,end,role=probe,reason=%s,frames=%lu", reason, (unsigned long)stats.frames);
}

static void prober(const hal_radio_ops_t *radio)
{
    if (!profile_enter(radio, "probe")) return;
    prober_body(radio);
    profile_leave(radio);
}

/* ---- the transmitter ---------------------------------------------------------------------- */

/* The transmitter's totals. run_duty_pm: this run's airtime over its elapsed time, per mille;
 * hour_used_pm: the sub-band's rolling hour spent so far (all runs), per mille of the hour, from
 * the HAL's budget (10 % = 360 000 ms of airtime). */
static void emit_tsum(uint32_t sent, uint32_t failed, uint64_t air_us, int64_t elapsed_us,
                      uint32_t left_ms)
{
    uint32_t budget_ms = lbt_profile_budget_ms(&prof);
    uint32_t used_ms = left_ms > budget_ms ? 0 : budget_ms - left_ms;
    emit("LBT,tsum,sent=%lu,failed=%lu,air_ms=%lu,elapsed_ms=%lu,run_duty_pm=%lu,left_ms=%lu,"
         "hour_used_pm=%lu",
         (unsigned long)sent, (unsigned long)failed, (unsigned long)(air_us / 1000),
         (unsigned long)(elapsed_us / 1000),
         (unsigned long)(elapsed_us > 0 ? air_us * 1000 / (uint64_t)elapsed_us : 0),
         (unsigned long)left_ms, (unsigned long)(used_ms * 1000u / budget_ms));
}

static void transmitter_body(const hal_radio_ops_t *radio)
{
    uint32_t rng = esp_random() | 1u;
    if (radio->set_channel(prof.freq_hz) != 0 || radio->set_mode(HAL_RADIO_MODE_RX) != 0) {
        emit("LBT,end,role=tx,reason=radio");
        return;
    }
    emit_cfg("tx");
    uint32_t rem0 = radio->duty_cycle_remaining_ms();
    emit("LBT,start,role=tx,frames=%lu,budget_left_ms=%lu,min_left_ms=%lu",
         (unsigned long)active.frames, (unsigned long)rem0,
         (unsigned long)lbt_profile_guard_ms(&prof));

    int64_t t0 = esp_timer_get_time();
    uint64_t air_us = 0;
    uint32_t sent = 0, failed = 0;
    const char *reason = "frames";
    while (sent < active.frames) {
        if (radio_task_bench_stop_requested()) {
            reason = "stop";
            break;
        }
        uint32_t rem = radio->duty_cycle_remaining_ms();
        if (rem < lbt_profile_guard_ms(&prof)) {
            reason = "duty_guard";
            break;
        }
        size_t len = lbt_rand_range(&rng, LBT_STATE_LEN_MIN, LBT_STATE_LEN_MAX);
        uint8_t buf[LBT_STATE_LEN_MAX];
        lbt_frame_build(buf, len, sent, &rng);
        int rc = radio->send(buf, len);
        uint32_t air = lbt_profile_airtime_us(&prof, len);
        if (rc != 0) {
            failed++;
            emit("LBT,txfail,seq=%lu,rc=%d", (unsigned long)sent, rc);
            if (rc == -3) {
                reason = "duty_guard";
                break;
            }
        } else {
            air_us += air;
        }
        emit("LBT,t,%lu,%lu,%u,%lu", (unsigned long)sent, (unsigned long)now_us32(), (unsigned)len,
             (unsigned long)air);
        sent++;
        if (sent % LBT_SUMMARY_EVERY == 0) {
            emit_tsum(sent, failed, air_us, esp_timer_get_time() - t0,
                      radio->duty_cycle_remaining_ms());
        }
        /* The next frame a random 300-700 ms later, in slices so that a stop is heard. */
        uint32_t gap = lbt_rand_range(&rng, LBT_TX_GAP_MIN_MS, LBT_TX_GAP_MAX_MS);
        while (gap > 0 && !radio_task_bench_stop_requested()) {
            uint32_t slice = gap > 50 ? 50 : gap;
            vTaskDelay(pdMS_TO_TICKS(slice));
            gap -= slice;
        }
    }
    emit_tsum(sent, failed, air_us, esp_timer_get_time() - t0, radio->duty_cycle_remaining_ms());
    emit("LBT,end,role=tx,reason=%s,sent=%lu", reason, (unsigned long)sent);
}

static void transmitter(const hal_radio_ops_t *radio)
{
    if (!profile_enter(radio, "tx")) return;
    transmitter_body(radio);
    profile_leave(radio);
}

/* ---- the console command ---------------------------------------------------------------- */

static uint32_t proxy_frames_max(void)
{
    lbt_profile_t p;
    return lbt_profile_as923_eu868(&p, -1, -1, INT8_MIN) ? lbt_profile_frames_max(&p) : 0;
}

void lbt_bench_command(const char *args)
{
    lbt_cmd_t cmd;
    if (!lbt_parse_cmd(args, &cmd) || cmd.kind == LBT_CMD_BAD) {
        ESP_LOGW(TAG,
                 "usage: @lbt tx [frames<=%d] | @lbt probe [frames [gap_min_us gap_max_us]] | "
                 "@lbt stop | @lbt status; add proxy=as923 [peak=N] [min=N] [power=dBm] for the "
                 "AS923-TW modulation on 868.3 MHz (tx frames <= %lu)",
                 LBT_TX_FRAMES_MAX, (unsigned long)proxy_frames_max());
        return;
    }
    if (cmd.kind == LBT_CMD_STATUS) {
        ESP_LOGI(TAG, "%s (region %s, channel %lu Hz; proxy=as923 runs SF9/500 kHz on %lu Hz)",
                 radio_task_bench_running() ? "a test is running" : "idle",
                 radio_region_code(RADIO_REGION),
                 (unsigned long)radio_region_default_channel_hz(RADIO_REGION),
                 (unsigned long)LBT_PROXY_FREQ_HZ);
        return;
    }
    if (cmd.kind == LBT_CMD_STOP) {
        radio_task_bench_request_stop();
        ESP_LOGI(TAG, "stop requested");
        return;
    }
    if (!log_start()) {
        ESP_LOGW(TAG, "no memory for the log");
        return;
    }
    if (cmd.proxy) {
        if (!lbt_profile_as923_eu868(&prof, cmd.det_peak, cmd.det_min, cmd.power_dbm)) {
            ESP_LOGW(TAG, "proxy refused: a value is out of range or the channel is not legal");
            return;
        }
    } else {
        lbt_profile_build(&prof, RADIO_REGION);
    }
    active = cmd;
    bool ok = radio_task_bench_start(cmd.kind == LBT_CMD_TX ? transmitter : prober);
    ESP_LOGI(TAG, "%s %s", cmd.kind == LBT_CMD_TX ? "transmitter" : "prober",
             ok ? "started: the radio is the test's until it ends (@lbt stop)"
                : "not started (no radio, or a test is running)");
}

#endif /* CONFIG_ATALAIA_LBT_BENCH */
#endif /* ESP_PLATFORM */
