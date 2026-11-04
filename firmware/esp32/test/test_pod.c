/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I/O pod's proxy (main/pod/pod.c) and capabilities (main/pod/pod_caps.c)
 * with a recording hardware abstraction and an in-memory phone on each link:
 * IDENT, CMD with its ACK and once-only action, EVT with its resends and the
 * broken link, the radio passthrough with the modem's logic (types 3 up), the
 * radio cleared when its link goes, and every capability's events and
 * commands; the simple outputs lent to the phone (main/pod/pod_outputs.c, the expansion
 * port's increment 9) with a fake RMT: their CMDs, their limits, off when the link goes or the
 * phone falls silent, and IDENT's room for them; the expansion port (main/pod/pod_port.c, the
 * port half of increment 9) on the module core behind a fake bus: hits lent and armed by the
 * phone, a module's outputs lent without the feedback flag and turned off with the link, and the
 * EVT pod.modules after every IDENT and change. The frames come from
 * protocol/vectors/capability_proxy.yaml where a vector exists. Crypto: the core's test stub (the
 * real AES-CCM: the host pod, test/pod_host, in the app's and the controller's tests).
 */
#include <stdio.h>
#include <string.h>

#include "atalaia/codec.h"
#include "atalaia/join.h"
#include "atalaia/msg_codec.h"
#include "atalaia/packet.h"
#include "atalaia/tag.h"
#include "check.h"
#include "pod/pod.h"
#include "pod/pod_caps.h"
#include "pod/pod_json.h"
#include "module_sim.h"
#include "pod/pod_outputs.h"
#include "pod/pod_port.h"
#include "pod/pod_settings.h"
#include "proxy_vectors.h"
#include "simple_out.h"

/* ---- A phone on each link ------------------------------------------------------- */

#define OUT_MAX 32

typedef struct {
    modem_decoder_t dec;
    int frames;
    uint8_t type[OUT_MAX];
    size_t len[OUT_MAX];
    uint8_t payload[OUT_MAX][MODEM_FRAME_PAYLOAD_MAX];
    size_t raw_len[OUT_MAX];
    uint8_t raw[OUT_MAX][MODEM_FRAME_MAX];
} phone_t;

static phone_t phone[POD_LINK_COUNT];
static int writing_link;

static void phone_frame(void *ctx, uint8_t type, const uint8_t *payload, size_t len)
{
    phone_t *ph = (phone_t *)ctx;
    if (ph->frames >= OUT_MAX) return;
    ph->type[ph->frames] = type;
    ph->len[ph->frames] = len;
    memcpy(ph->payload[ph->frames], payload, len);
    ph->frames++;
}

/* ---- Recording hardware ------------------------------------------------------------ */

static uint8_t buttons;
static char key_down;
static bool nfc_present;
static hal_nfc_tag_t nfc_tag;
static uint8_t nfc_mem[POD_NFC_MEM];
static int nfc_mem_len;
static int led_fills, led_shows, led_sets, led_lit;
static uint8_t led_rgb[3];
static int led_brightness = -1;
static uint8_t led_px[24][3];
static int tones;
static uint32_t tone_hz[16], tone_ms[16];
static int audio_stops, audio_volume = -1;

static int ok_init(void)
{
    return 0;
}
static void no_deinit(void)
{
}
static uint8_t poll_buttons(void)
{
    return buttons;
}
static char scan_key(void)
{
    return key_down;
}
static bool poll_nfc(hal_nfc_tag_t *t)
{
    if (!nfc_present) return false;
    *t = nfc_tag;
    return true;
}
static int read_mem(uint8_t *buf, size_t cap)
{
    if (nfc_mem_len <= 0) return -1;
    size_t n = (size_t)nfc_mem_len < cap ? (size_t)nfc_mem_len : cap;
    memcpy(buf, nfc_mem, n);
    return (int)n;
}
static void led_fill(uint8_t r, uint8_t g, uint8_t b)
{
    led_fills++;
    led_rgb[0] = r;
    led_rgb[1] = g;
    led_rgb[2] = b;
    for (int i = 0; i < 24; i++) {
        led_px[i][0] = r;
        led_px[i][1] = g;
        led_px[i][2] = b;
    }
}
static void led_set(int i, uint8_t r, uint8_t g, uint8_t b)
{
    led_sets++;
    if (i >= 0 && i < 24) {
        led_px[i][0] = r;
        led_px[i][1] = g;
        led_px[i][2] = b;
    }
}
static void led_show(void)
{
    led_shows++;
    led_lit = 0;
    for (int i = 0; i < 24; i++) {
        if (led_px[i][0] | led_px[i][1] | led_px[i][2]) led_lit++;
    }
}
static void led_set_brightness(uint8_t pct)
{
    led_brightness = pct;
}
static void tone(void *ctx, uint32_t hz, uint32_t ms)
{
    (void)ctx;
    if (tones < 16) {
        tone_hz[tones] = hz;
        tone_ms[tones] = ms;
    }
    tones++;
}
static void stop(void *ctx)
{
    (void)ctx;
    audio_stops++;
}
static void volume(void *ctx, uint8_t v)
{
    (void)ctx;
    audio_volume = v;
}

static const hal_button_ops_t button_ops = {ok_init, poll_buttons, no_deinit};
static const hal_keypad_ops_t keypad_ops = {ok_init, scan_key, no_deinit};
static const hal_nfc_ops_t nfc_ops = {ok_init, poll_nfc, read_mem, no_deinit};
static const hal_led_ops_t led_ops = {ok_init,  led_fill,           led_set,
                                      led_show, led_set_brightness, no_deinit};
static hal_t hal;

/* ---- The pod under test --------------------------------------------------------------- */

static pod_t pod;
static pod_caps_t caps;
static uint32_t clock_ms;
static int radio_sends;
static uint8_t radio_pkt[RADIO_MAX_PKT_LEN];
static size_t radio_pkt_len;
static uint32_t radio_tag;
static int measures;
static int link_actives;

static int link_write(void *ctx, pod_link_t link, const uint8_t *frame, size_t len)
{
    (void)ctx;
    phone_t *ph = &phone[link];
    writing_link = (int)link;
    int before = ph->frames;
    modem_decoder_feed(&ph->dec, frame, len, phone_frame, ph);
    if (ph->frames > before && ph->frames <= OUT_MAX) {
        ph->raw_len[ph->frames - 1] = len;
        memcpy(ph->raw[ph->frames - 1], frame, len);
    }
    return 0;
}
static uint32_t now(void *ctx)
{
    (void)ctx;
    return clock_ms;
}
/* The phone acknowledges every EVT at each turn, as the app does (off unless a test sets it). */
static bool auto_ack;
static int acked_upto[POD_LINK_COUNT];
/* The simple outputs (none unless a test adds them: add_output). */
static pod_outputs_t outs;
static simple_out_t simple[OUTPUTS_MAX];
static int simple_count; /* the simple outputs added (not outputs_t's count of every channel) */
/* The expansion port (no bus unless a test plugs modules in: setup_port). */
static pod_port_t port;
static module_sim_t sims[EXP_ADDR_COUNT];
static bool plugged[EXP_ADDR_COUNT];

static bool command(void *ctx, const atalaia_proxy_msg_t *m)
{
    (void)ctx;
    if (pod_outputs_owns(&outs, m->cap_id)) return pod_outputs_command(&outs, m);
    if (pod_port_owns(&port, m->cap_id)) return pod_port_command(&port, m);
    return pod_caps_command(&caps, m);
}
static const char *fw = "0.3.0";
static int compact_idents;
static pod_ident_level_t last_level;
static int last_trim; /* the outputs the IDENT sent left out (POD_IDENT_TRIM) */

static int ident(void *ctx, atalaia_proxy_ident_t *out, pod_ident_level_t level, int trim)
{
    (void)ctx;
    snprintf(out->fw_version, sizeof(out->fw_version), "%s", fw);
    int listed =
        pod_port_ident_caps(&port, &caps, level, trim, out->caps_json, sizeof(out->caps_json));
    compact_idents += level != POD_IDENT_FULL;
    out->has_battery = true;
    out->battery_pct = 87;
    return listed;
}
static void ident_sent(void *ctx, pod_ident_level_t level, int trim)
{
    (void)ctx;
    last_level = level;
    last_trim = trim;
    pod_port_ident_sent(&port, level);
}
/* The pod's and the port's log lines (the last few). */
static char logs[8][160];
static int log_count;
static void log_line(void *ctx, const char *line)
{
    (void)ctx;
    snprintf(logs[log_count % 8], sizeof(logs[0]), "%s", line);
    log_count++;
}
static bool logged(const char *text)
{
    for (int i = 0; i < 8 && i < log_count; i++) {
        if (strstr(logs[i], text) != NULL) return true;
    }
    return false;
}
static bool emit(void *ctx, const char *cap_id, const char *event, const char *data)
{
    (void)ctx;
    return pod_event(&pod, cap_id, event, data);
}
static void link_active(void *ctx, pod_link_t link)
{
    (void)ctx;
    (void)link;
    link_actives++;
    pod_caps_report(&caps, emit, NULL);
}
static bool radio_send(void *ctx, const uint8_t *pkt, size_t len, uint32_t tag)
{
    (void)ctx;
    radio_sends++;
    memcpy(radio_pkt, pkt, len);
    radio_pkt_len = len;
    radio_tag = tag;
    return true;
}
static int set_channel(void *ctx, uint32_t hz)
{
    (void)ctx;
    (void)hz;
    return 0;
}
static uint32_t duty(void *ctx)
{
    (void)ctx;
    return 360000;
}
static int measure_start(void *ctx, uint32_t hz, uint16_t dwell, bool cad)
{
    (void)ctx;
    (void)hz;
    (void)dwell;
    (void)cad;
    measures++;
    return 0;
}

static void clear_phones(void)
{
    for (int i = 0; i < POD_LINK_COUNT; i++) {
        memset(&phone[i], 0, sizeof(phone[i]));
        modem_decoder_init(&phone[i].dec);
    }
}

static pod_caps_config_t full_config(void)
{
    pod_caps_config_t cfg;
    memset(&cfg, 0, sizeof(cfg));
    for (int i = 0; i < POD_BUTTONS; i++) cfg.button[i] = true;
    cfg.keypad = true;
    cfg.nfc = true;
    cfg.leds = true;
    cfg.led_count = 24;
    cfg.audio = true;
    cfg.tamper = true;
    return cfg;
}

static void setup_with(const pod_caps_config_t *cfg, bool radio)
{
    clear_phones();
    buttons = 0;
    key_down = HAL_KEY_NONE;
    nfc_present = false;
    nfc_mem_len = 0;
    led_fills = led_shows = led_sets = led_lit = 0;
    led_brightness = -1;
    memset(led_px, 0, sizeof(led_px));
    tones = audio_stops = 0;
    audio_volume = -1;
    radio_sends = measures = link_actives = compact_idents = log_count = 0;
    fw = "0.3.0";
    clock_ms = 1000;
    memset(&hal, 0, sizeof(hal));
    hal.buttons = &button_ops;
    hal.keypad = &keypad_ops;
    hal.nfc = &nfc_ops;
    hal.leds = &led_ops;
    pod_audio_t audio = {tone, stop, volume, NULL};
    pod_caps_init(&caps, cfg, &hal, &audio);
    pod_io_t io = {link_write, now, command, ident, link_active, log_line, NULL, NULL, ident_sent};
    modem_io_t rio = {
        .radio_send = radio_send,
        .set_channel = set_channel,
        .duty_cycle_remaining_ms = duty,
        .now_ms = now,
        .measure_start = measure_start,
    };
    pod_init(&pod, &io, &rio, &atalaia_crypto_test_stub, "test", radio, 16);
    pod_outputs_init(&outs, NULL);
    simple_count = 0;
    pod_port_ops_t pops = {.ctx = NULL, .emit = emit, .log = log_line};
    pod_port_init(&port, NULL, &outs, NULL, &pops);
    memset(plugged, 0, sizeof(plugged));
    auto_ack = false;
    memset(acked_upto, 0, sizeof(acked_upto));
}

static void setup(void)
{
    pod_caps_config_t cfg = full_config();
    setup_with(&cfg, true);
}

/* The phone sends a frame on a link. */
static void phone_send(pod_link_t link, uint8_t type, const uint8_t *payload, size_t len)
{
    uint8_t frame[MODEM_FRAME_MAX];
    size_t n = modem_frame_encode(type, payload, len, frame, sizeof(frame));
    CHECK(n > 0);
    pod_feed(&pod, link, frame, n);
}

static const proxy_frame_vector_t *frame_vector(const char *name)
{
    for (size_t i = 0; i < PROXY_FRAME_VECTOR_COUNT; i++) {
        if (strcmp(proxy_frame_vectors[i].name, name) == 0) return &proxy_frame_vectors[i];
    }
    return NULL;
}

/* The phone's frames as the vectors write them (bytes on the wire). */
static void phone_send_vector(pod_link_t link, const char *name)
{
    const proxy_frame_vector_t *v = frame_vector(name);
    CHECK(v != NULL);
    if (v != NULL) pod_feed(&pod, link, v->frame, v->frame_len);
}

static void phone_send(pod_link_t link, uint8_t type, const uint8_t *payload, size_t len);

static void ack_evts(void)
{
    for (int l = 0; l < POD_LINK_COUNT; l++) {
        if (acked_upto[l] > phone[l].frames) acked_upto[l] = 0; /* the phone was cleared */
        for (; acked_upto[l] < phone[l].frames; acked_upto[l]++) {
            int i = acked_upto[l];
            atalaia_proxy_msg_t m;
            if (phone[l].type[i] != ATALAIA_PROXY_EVT ||
                !atalaia_proxy_msg_decode(phone[l].payload[i], phone[l].len[i], &m)) {
                continue;
            }
            uint8_t b[2];
            atalaia_proxy_ack_encode(m.seq, b, sizeof(b));
            phone_send((pod_link_t)l, ATALAIA_PROXY_ACK, b, 2);
        }
    }
}

static void advance(uint32_t ms)
{
    while (ms > 0) {
        uint32_t step = ms < 10 ? ms : 10;
        clock_ms += step;
        ms -= step;
        if (auto_ack) ack_evts();
        pod_caps_poll(&caps, clock_ms, -1, emit, NULL);
        pod_tick(&pod);
        pod_outputs_tick(&outs, pod_phone_on(&pod), pod_heard_ms(&pod), clock_ms);
        pod_port_tick(&port, pod_phone_on(&pod), clock_ms);
    }
}

static bool last_msg(pod_link_t link, atalaia_proxy_msg_t *m)
{
    phone_t *ph = &phone[link];
    for (int i = ph->frames - 1; i >= 0; i--) {
        if (ph->type[i] == ATALAIA_PROXY_EVT) {
            return atalaia_proxy_msg_decode(ph->payload[i], ph->len[i], m);
        }
    }
    return false;
}

static int count_type(pod_link_t link, uint8_t type)
{
    int n = 0;
    for (int i = 0; i < phone[link].frames; i++) n += phone[link].type[i] == type;
    return n;
}

static void ack(pod_link_t link, uint16_t seq)
{
    uint8_t b[2];
    atalaia_proxy_ack_encode(seq, b, sizeof(b));
    phone_send(link, ATALAIA_PROXY_ACK, b, 2);
}

/* ---- IDENT ----------------------------------------------------------------------------- */

/* IDENT's fw_version from the image's version (FV-5): 23 bytes at most. */
static void test_fw_version(void)
{
    static const char *const cases[][2] = {
        {"0.3.0-dev.412+g8560d54", "0.3.0-dev.412+g8560d54"},       /* 22: as it is */
        {"0.3.0-dev.412+g8560d54.dirty", "0.3.0-dev.412+g8560d54"}, /* 28: no ".dirty" */
        {"0.3.0-dev.1234+g1234567.dirty", "0.3.0-dev.1234+g1234567"},
        {"0.3.0-dev.12345+g1234567.dirty", "0.3.0-dev.12345"}, /* the hash too */
        {"0.3.0-dev.12345+g1234567", "0.3.0-dev.12345"},
        {"1.2.3-12345678901234567890", "1.2.3-12345678901234567"}, /* no metadata: cut */
        {"1.2.3-1234567890123456789+gabcdef0", "1.2.3-12345678901234567"},
        {"0.3.0", "0.3.0"},
        {"0.3.0+b", "0.3.0+b"},
        {"", "unknown"},
    };
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        char out[ATALAIA_PROXY_TEXT_MAX + 1];
        memset(out, 'x', sizeof(out));
        pod_fw_version(cases[i][0], out);
        if (strcmp(out, cases[i][1]) != 0) {
            fprintf(stderr, "FAIL pod_fw_version(%s) = %s, not %s\n", cases[i][0], out,
                    cases[i][1]);
            check_failures++;
        }
        check_count++;
    }
    char out[ATALAIA_PROXY_TEXT_MAX + 1];
    pod_fw_version(NULL, out);
    CHECK(strcmp(out, "unknown") == 0);
}

static void test_ident(void)
{
    setup();
    CHECK(!pod_link_active(&pod, POD_LINK_USB));
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    CHECK(pod_link_active(&pod, POD_LINK_USB));
    CHECK(link_actives == 1);
    CHECK(phone[POD_LINK_USB].frames == 1 && phone[POD_LINK_USB].type[0] == ATALAIA_PROXY_IDENT);
    CHECK(phone[POD_LINK_BLE].frames == 0);
    atalaia_proxy_ident_t id;
    CHECK(atalaia_proxy_ident_decode(phone[POD_LINK_USB].payload[0], phone[POD_LINK_USB].len[0],
                                     &id));
    CHECK(strcmp(id.fw_version, "0.3.0") == 0 && id.has_radio && id.protocol_version == 1);
    CHECK(id.has_battery && id.battery_pct == 87);
    /* Keys 6-8 (PE24-101): it measures, and relays field and pair frames. */
    CHECK(id.measure == ATALAIA_PROXY_YES && id.field_frames == ATALAIA_PROXY_YES &&
          id.pair_frames == ATALAIA_PROXY_YES);
    CHECK(strcmp(id.caps_json,
                 "[{\"id\":\"btn.1\",\"type\":\"button\"},{\"id\":\"btn.2\",\"type\":\"button\"},"
                 "{\"id\":\"btn.3\",\"type\":\"button\"},{\"id\":\"btn.4\",\"type\":\"button\"},"
                 "{\"id\":\"keypad\",\"type\":\"keypad\"},"
                 "{\"id\":\"ring\",\"type\":\"led\",\"count\":24},"
                 "{\"id\":\"audio\",\"type\":\"audio\"},{\"id\":\"nfc\",\"type\":\"nfc\"},"
                 "{\"id\":\"case\",\"type\":\"tamper\"}]") == 0);
    CHECK(compact_idents == 0);

    /* Everything fitted, the flags and the longest fw_version still fit in 256 bytes
     * (237: PF6, PE24-101). */
    fw = "0.3.0-123-g0123456-dirt"; /* 23 bytes */
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    CHECK(phone[POD_LINK_USB].frames == 2 && phone[POD_LINK_USB].len[1] <= 256 - 18);
    CHECK(atalaia_proxy_ident_decode(phone[POD_LINK_USB].payload[1], phone[POD_LINK_USB].len[1],
                                     &id) &&
          strlen(id.fw_version) == 23 && compact_idents == 0);

    /* Colours on the buttons: in IDENT while they fit, left out when they do not (the
     * flags stay: they are not optional to the phone). */
    pod_caps_config_t coloured = full_config();
    coloured.team[0] = "red";
    coloured.team[1] = "blue";
    coloured.team[2] = "green";
    setup_with(&coloured, true);
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    CHECK(atalaia_proxy_ident_decode(phone[POD_LINK_USB].payload[0], phone[POD_LINK_USB].len[0],
                                     &id));
    CHECK(strstr(id.caps_json, "{\"id\":\"btn.3\",\"type\":\"button\",\"team\":\"green\"}") !=
              NULL &&
          compact_idents == 0);
    coloured.team[3] = "yellow"; /* four colours and the flags: 261 bytes */
    setup_with(&coloured, true);
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    fw = "0.3.0-123-g0123456-dirt";
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    CHECK(phone[POD_LINK_USB].frames == 2 && compact_idents == 2);
    for (int k = 0; k < 2; k++) {
        CHECK(atalaia_proxy_ident_decode(phone[POD_LINK_USB].payload[k], phone[POD_LINK_USB].len[k],
                                         &id));
        CHECK(strstr(id.caps_json, "team") == NULL && strstr(id.caps_json, "\"case\"") != NULL);
        CHECK(id.field_frames == ATALAIA_PROXY_YES && id.pair_frames == ATALAIA_PROXY_YES);
    }

    /* A pod without a radio and with two buttons says so. */
    pod_caps_config_t cfg;
    memset(&cfg, 0, sizeof(cfg));
    cfg.button[0] = true;
    cfg.button[2] = true;
    cfg.team[2] = "blue";
    setup_with(&cfg, false);
    phone_send_vector(POD_LINK_BLE, "cmd_ident");
    CHECK(phone[POD_LINK_BLE].frames == 1);
    CHECK(atalaia_proxy_ident_decode(phone[POD_LINK_BLE].payload[0], phone[POD_LINK_BLE].len[0],
                                     &id));
    CHECK(!id.has_radio);
    /* No radio: nothing to measure with; the relay is the firmware's (FIELD_TX gets no_radio). */
    CHECK(id.measure == ATALAIA_PROXY_NO && id.field_frames == ATALAIA_PROXY_YES &&
          id.pair_frames == ATALAIA_PROXY_YES);
    CHECK(strcmp(id.caps_json, "[{\"id\":\"btn.1\",\"type\":\"button\"},"
                               "{\"id\":\"btn.3\",\"type\":\"button\",\"team\":\"blue\"}]") == 0);

    /* No hardware abstraction: only the enclosure switch (a plain GPIO) is left. */
    pod_caps_config_t none = full_config();
    pod_caps_init(&caps, &none, NULL, NULL);
    char json[64];
    CHECK(pod_caps_descriptors(&caps, json, sizeof(json), true) > 0 &&
          strcmp(json, "[{\"id\":\"case\",\"type\":\"tamper\"}]") == 0);
    /* Too small a buffer: refused, not cut. */
    pod_caps_init(&caps, &none, &hal, NULL);
    CHECK(pod_caps_descriptors(&caps, json, sizeof(json), true) == 0);
}

/* ---- CMD ------------------------------------------------------------------------------- */

static void test_cmd(void)
{
    setup();
    phone_send_vector(POD_LINK_USB, "ring_fill"); /* ring fill {"team":"red"}, seq 1 */
    CHECK(phone[POD_LINK_USB].frames == 1 && phone[POD_LINK_USB].type[0] == ATALAIA_PROXY_ACK);
    uint16_t seq = 0xFFFF;
    CHECK(atalaia_proxy_ack_decode(phone[POD_LINK_USB].payload[0], 2, &seq) && seq == 1);
    CHECK(led_fills == 1 && led_rgb[0] == 255 && led_rgb[1] == 0 && led_rgb[2] == 0);
    CHECK(led_shows == 1 && led_lit == 24);

    /* The same frame again (the ACK was lost): acknowledged again, acted on once. */
    phone_send_vector(POD_LINK_USB, "ring_fill");
    CHECK(count_type(POD_LINK_USB, ATALAIA_PROXY_ACK) == 2 && led_fills == 1);
    CHECK(pod.count.cmd_repeats == 1 && pod.count.cmds == 1);

    phone_send_vector(POD_LINK_USB, "tone"); /* spk... the vector's cap is "spk" */
    CHECK(count_type(POD_LINK_USB, ATALAIA_PROXY_ACK) == 3);
    CHECK(tones == 0 && pod.count.cmd_unknown == 1); /* this pod's speaker is "audio" */

    /* The ACK frame for seq 65534 is byte for byte the vector's. */
    int before = phone[POD_LINK_USB].frames;
    phone_send_vector(POD_LINK_USB, "clear_no_args"); /* keypad clear, seq 65534 */
    CHECK(phone[POD_LINK_USB].frames == before + 1);
    uint8_t ack_frame[8];
    uint8_t ack_payload[2];
    atalaia_proxy_ack_encode(65534, ack_payload, 2);
    size_t n = modem_frame_encode(ATALAIA_PROXY_ACK, ack_payload, 2, ack_frame, sizeof(ack_frame));
    CHECK(phone[POD_LINK_USB].raw_len[before] == n &&
          memcmp(phone[POD_LINK_USB].raw[before], ack_frame, n) == 0);
    CHECK(pod.count.cmd_unknown == 1); /* keypad clear is known */

    /* An invalid CMD payload is not acknowledged. */
    for (size_t i = 0; i < PROXY_BAD_VECTOR_COUNT; i++) {
        const proxy_bad_vector_t *b = &proxy_bad_vectors[i];
        if (b->type != ATALAIA_PROXY_CMD && b->type != ATALAIA_PROXY_ACK) continue;
        before = phone[POD_LINK_USB].frames;
        uint32_t bad = pod.count.bad_payloads;
        phone_send(POD_LINK_USB, b->type, b->payload, b->payload_len);
        CHECK(phone[POD_LINK_USB].frames == before);
        CHECK(pod.count.bad_payloads == bad + 1);
    }

    /* A new link (RADIO_CMD IDENT) numbers from 0 again: seq 1 acts again. */
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    phone_send_vector(POD_LINK_USB, "ring_fill");
    CHECK(led_fills == 2);

    /* The other link has its own seqs. */
    phone_send_vector(POD_LINK_BLE, "ring_fill");
    CHECK(led_fills == 3 && count_type(POD_LINK_BLE, ATALAIA_PROXY_ACK) == 1);

    /* Frames a phone must not send, and unknown types: ignored, unanswered. */
    before = phone[POD_LINK_USB].frames;
    uint32_t ignored = pod.count.ignored;
    phone_send_vector(POD_LINK_USB, "button_hold"); /* an EVT */
    phone_send_vector(POD_LINK_USB, "rx");          /* a RADIO_RX */
    phone_send_vector(POD_LINK_USB, "field_rx");    /* a RADIO_FIELD_RX */
    phone_send_vector(POD_LINK_USB, "field_ack");   /* a RADIO_FIELD_ACK */
    uint8_t x = 1;
    phone_send(POD_LINK_USB, 0x0F, &x, 1);
    phone_send(POD_LINK_USB, 0x7F, NULL, 0);
    CHECK(phone[POD_LINK_USB].frames == before && pod.count.ignored == ignored + 6);
}

/* ---- EVT ------------------------------------------------------------------------------- */

static void test_evt(void)
{
    setup();
    /* No phone yet: a press is dropped. */
    buttons = 0x01;
    advance(10);
    CHECK(pod.count.evt_dropped == 1 && pod_pending(&pod) == 0);
    buttons = 0;
    advance(10);

    phone_send_vector(POD_LINK_USB, "cmd_ident");
    buttons = 0x02; /* button 2: blue */
    advance(10);
    atalaia_proxy_msg_t m;
    CHECK(last_msg(POD_LINK_USB, &m) && strcmp(m.cap_id, "btn.2") == 0 &&
          strcmp(m.name, "press") == 0 && strcmp(m.data_json, "{}") == 0);
    uint16_t first = m.seq;
    ack(POD_LINK_USB, first);
    CHECK(pod_pending(&pod) == 0 && pod.count.evt_acked == 1);

    /* Held: hold every 250 ms with the time held so far, then release. */
    advance(250);
    CHECK(last_msg(POD_LINK_USB, &m) && strcmp(m.name, "hold") == 0 &&
          strcmp(m.data_json, "{\"ms\":250}") == 0 && m.seq == (uint16_t)(first + 1));
    ack(POD_LINK_USB, m.seq);
    advance(250);
    CHECK(last_msg(POD_LINK_USB, &m) && strcmp(m.data_json, "{\"ms\":500}") == 0);
    ack(POD_LINK_USB, m.seq);
    buttons = 0;
    advance(10);
    CHECK(last_msg(POD_LINK_USB, &m) && strcmp(m.name, "release") == 0 &&
          strcmp(m.data_json, "{\"ms\":510}") == 0);
    ack(POD_LINK_USB, m.seq);
    CHECK(pod_pending(&pod) == 0);

    /* Not acknowledged: sent again unchanged every 500 ms, 3 times, then the link is broken. */
    int evts = count_type(POD_LINK_USB, ATALAIA_PROXY_EVT);
    buttons = 0x04;
    advance(10);
    buttons = 0;
    advance(10); /* press and release, both waiting */
    CHECK(count_type(POD_LINK_USB, ATALAIA_PROXY_EVT) == evts + 2 && pod_pending(&pod) == 2);
    int press_at = evts;
    for (int resend = 1; resend <= 3; resend++) {
        advance(500);
        CHECK(count_type(POD_LINK_USB, ATALAIA_PROXY_EVT) == evts + 2 + 2 * resend);
    }
    /* The resent press is the same bytes. */
    phone_t *ph = &phone[POD_LINK_USB];
    int k = 0, first_press = -1, last_press = -1;
    for (int i = 0; i < ph->frames; i++) {
        if (ph->type[i] != ATALAIA_PROXY_EVT) continue;
        if (k == press_at) first_press = i;
        if (k == press_at + 6) last_press = i;
        k++;
    }
    CHECK(first_press >= 0 && last_press >= 0 &&
          ph->raw_len[first_press] == ph->raw_len[last_press] &&
          memcmp(ph->raw[first_press], ph->raw[last_press], ph->raw_len[first_press]) == 0);
    advance(500);
    CHECK(!pod_link_active(&pod, POD_LINK_USB) && pod.count.links_broken == 1);
    CHECK(pod_pending(&pod) == 0 && pod.count.evt_lost == 2);
    /* The phone speaks again: active again. */
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    CHECK(pod_link_active(&pod, POD_LINK_USB));

    /* Two links: every EVT on both; an ACK on either clears it. */
    phone_send_vector(POD_LINK_BLE, "cmd_ident");
    int usb = count_type(POD_LINK_USB, ATALAIA_PROXY_EVT);
    int ble = count_type(POD_LINK_BLE, ATALAIA_PROXY_EVT);
    buttons = 0x08;
    advance(10);
    CHECK(count_type(POD_LINK_USB, ATALAIA_PROXY_EVT) == usb + 1);
    CHECK(count_type(POD_LINK_BLE, ATALAIA_PROXY_EVT) == ble + 1);
    CHECK(last_msg(POD_LINK_BLE, &m) && strcmp(m.cap_id, "btn.4") == 0);
    ack(POD_LINK_BLE, m.seq);
    CHECK(pod_pending(&pod) == 0);
    buttons = 0;
    advance(10);
    CHECK(last_msg(POD_LINK_USB, &m));
    ack(POD_LINK_USB, m.seq);

    /* One link goes: the other keeps the EVTs. */
    pod_set_link_up(&pod, POD_LINK_BLE, false);
    CHECK(!pod_link_active(&pod, POD_LINK_BLE) && pod_link_active(&pod, POD_LINK_USB));
    ble = count_type(POD_LINK_BLE, ATALAIA_PROXY_EVT);
    buttons = 0x01;
    advance(10);
    CHECK(count_type(POD_LINK_BLE, ATALAIA_PROXY_EVT) == ble && pod_pending(&pod) == 1);
    /* The last one goes too: the waiting EVTs are dropped. */
    pod_set_link_up(&pod, POD_LINK_USB, true);
    pod_set_link_up(&pod, POD_LINK_USB, false);
    CHECK(pod_pending(&pod) == 0);

    /* A full outbox: dropped, counted. */
    setup();
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    for (int i = 0; i < POD_OUTBOX; i++) CHECK(pod_event(&pod, "case", "opened", ""));
    CHECK(!pod_event(&pod, "case", "opened", "") && pod.count.evt_dropped == 1);
    /* What does not encode is refused. */
    setup();
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    CHECK(!pod_event(&pod, "Bad Name", "x", ""));
    CHECK(!pod_event(&pod, "case", "opened", "[1]"));
}

/* ---- The radio passthrough ---------------------------------------------------------- */

static int find_type(pod_link_t link, uint8_t type)
{
    for (int i = phone[link].frames - 1; i >= 0; i--) {
        if (phone[link].type[i] == type) return i;
    }
    return -1;
}

static void put16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)(v >> 8);
    p[1] = (uint8_t)v;
}

static void test_radio(void)
{
    setup();
    /* CONFIGURE (game 4242, node 0, epoch 9, 2 hops, 869.525 MHz): RADIO_STATUS back. */
    phone_send_vector(POD_LINK_USB, "cmd_configure");
    int i = find_type(POD_LINK_USB, ATALAIA_PROXY_RADIO_STATUS);
    CHECK(i >= 0);
    if (i >= 0) {
        phone[POD_LINK_USB].payload[i][phone[POD_LINK_USB].len[i]] = 0;
        CHECK(strstr((const char *)phone[POD_LINK_USB].payload[i], "\"configured\":true") != NULL);
        CHECK(strstr((const char *)phone[POD_LINK_USB].payload[i], "\"channel_hz\":869525000") !=
              NULL);
    }
    CHECK(pod.radio.configured && pod.radio_owner == POD_LINK_USB);

    /* RADIO_TX from the phone's node: encrypted, queued; its outcome is RADIO_TX_ACK. */
    uint8_t tx[9 + 3] = {0x20, 0, 0, 0, 0, 0, 5, 2, 2, 0xa1, 0x01, 0x00};
    put16(tx + 1, 4242);
    put16(tx + 3, 0);
    phone_send(POD_LINK_USB, ATALAIA_PROXY_RADIO_TX, tx, sizeof(tx));
    CHECK(radio_sends == 1 && radio_tag == 6);
    atalaia_header_t h;
    CHECK(atalaia_header_decode(radio_pkt, &h) && ATALAIA_VF_ENC(h.version_flags) && h.seq == 5);
    pod_on_tx_result(&pod, radio_tag, MODEM_TX_OK);
    i = find_type(POD_LINK_USB, ATALAIA_PROXY_RADIO_TX_ACK);
    CHECK(i >= 0 && phone[POD_LINK_USB].len[i] == 3 && phone[POD_LINK_USB].payload[i][1] == 5 &&
          phone[POD_LINK_USB].payload[i][2] == MODEM_TX_OK);
    /* The same seq again would reuse a nonce: refused. */
    phone_send(POD_LINK_USB, ATALAIA_PROXY_RADIO_TX, tx, sizeof(tx));
    i = find_type(POD_LINK_USB, ATALAIA_PROXY_RADIO_TX_ACK);
    CHECK(radio_sends == 1 && i >= 0 && phone[POD_LINK_USB].payload[i][2] == MODEM_TX_NONCE_REUSE);

    /* A packet a box sent: RADIO_RX with its plaintext, RSSI, SNR and epoch. */
    /* The cmd_configure vector's game key. */
    static const uint8_t game_key[16] = {0x2b, 0x7e, 0x15, 0x16, 0x28, 0xae, 0xd2, 0xa6,
                                         0xab, 0xf7, 0x15, 0x88, 0x09, 0xcf, 0x4f, 0x3c};
    atalaia_header_t bh = {ATALAIA_VF_MAKE(1, 1, 1, 1), 4242, 7, 3, 2, 2};
    const uint8_t plain[] = {0xa1, 0x01, 0x02};
    uint8_t pkt[64];
    size_t pkt_len = atalaia_packet_encrypt(&bh, 1, game_key, plain, sizeof(plain), pkt,
                                            sizeof(pkt), &atalaia_crypto_test_stub);
    CHECK(pkt_len > 0);
    pod_on_air_rx(&pod, pkt, pkt_len, -87, 6);
    i = find_type(POD_LINK_USB, ATALAIA_PROXY_RADIO_RX);
    CHECK(i >= 0 && phone[POD_LINK_USB].len[i] == 9 + sizeof(plain) + 4);
    if (i >= 0) {
        const uint8_t *p = phone[POD_LINK_USB].payload[i];
        CHECK(memcmp(p + 9, plain, sizeof(plain)) == 0);
        CHECK((int8_t)p[12] == -87 && (int8_t)p[13] == 6 && p[14] == 0 && p[15] == 1);
    }
    CHECK(phone[POD_LINK_BLE].frames == 0); /* only to the link that runs the radio */

    /* MEASURE while a game is configured: RADIO_ERROR busy (the modem's code 7). */
    uint8_t measure[8] = {MODEM_CMD_MEASURE, 0x33, 0xd3, 0xe6, 0x08, 0x13, 0x88, 1};
    phone_send(POD_LINK_USB, ATALAIA_PROXY_RADIO_CMD, measure, sizeof(measure));
    i = find_type(POD_LINK_USB, ATALAIA_PROXY_RADIO_ERROR);
    CHECK(i >= 0 && phone[POD_LINK_USB].payload[i][0] == MODEM_ERR_BUSY && measures == 0);

    /* The radio's link goes: the key is forgotten. */
    pod_set_link_up(&pod, POD_LINK_USB, true);
    pod_set_link_up(&pod, POD_LINK_USB, false);
    CHECK(!pod.radio.configured && pod.radio_owner < 0 && pod.count.radio_cleared == 1);
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    tx[6] = 6;
    phone_send(POD_LINK_USB, ATALAIA_PROXY_RADIO_TX, tx, sizeof(tx));
    i = find_type(POD_LINK_USB, ATALAIA_PROXY_RADIO_TX_ACK);
    CHECK(i >= 0 && phone[POD_LINK_USB].payload[i][2] == MODEM_TX_NOT_CONFIGURED);

    /* Not configured: MEASURE runs, and its NOISE comes back as RADIO_NOISE (0x0B). */
    phone_send(POD_LINK_USB, ATALAIA_PROXY_RADIO_CMD, measure, sizeof(measure));
    CHECK(measures == 1);
    noise_result_t r;
    memset(&r, 0, sizeof(r));
    r.channel_hz = 869525000;
    r.dwell_ms = 5000;
    r.samples = 4980;
    r.min_dbm = -121;
    r.mean_dbm = -115;
    r.p50_dbm = -116;
    r.p90_dbm = -110;
    r.max_dbm = -95;
    r.cad_tries = 50;
    r.cad_detected = 2;
    pod_on_measure_result(&pod, 0, &r);
    i = find_type(POD_LINK_USB, ATALAIA_PROXY_RADIO_NOISE);
    CHECK(i >= 0 && phone[POD_LINK_USB].len[i] == NOISE_RESULT_LEN);
    const proxy_frame_vector_t *nv = frame_vector("noise");
    CHECK(nv != NULL && i >= 0 && nv->payload_len == NOISE_RESULT_LEN &&
          memcmp(phone[POD_LINK_USB].payload[i], nv->payload, NOISE_RESULT_LEN) == 0);

    /* CLEAR by the phone: STATUS, and the owner is gone. */
    phone_send_vector(POD_LINK_USB, "cmd_configure");
    CHECK(pod.radio_owner == POD_LINK_USB);
    uint8_t clear = MODEM_CMD_CLEAR;
    phone_send(POD_LINK_USB, ATALAIA_PROXY_RADIO_CMD, &clear, 1);
    CHECK(!pod.radio.configured && pod.radio_owner < 0);

    /* No radio chip: RADIO_TX gets no_radio, IDENT says has_radio false. */
    pod_caps_config_t cfg = full_config();
    setup_with(&cfg, false);
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    phone_send(POD_LINK_USB, ATALAIA_PROXY_RADIO_TX, tx, sizeof(tx));
    i = find_type(POD_LINK_USB, ATALAIA_PROXY_RADIO_TX_ACK);
    CHECK(i >= 0 && phone[POD_LINK_USB].payload[i][2] == MODEM_TX_NO_RADIO);

    /* Pod Status: battery, last RSSI, flags. */
    setup();
    uint8_t st[3];
    pod_status_bytes(&pod, -1, false, st);
    CHECK(st[0] == 0xFF && st[1] == 0x80 && st[2] == 0x01);
    phone_send_vector(POD_LINK_USB, "cmd_configure");
    pod_on_air_rx(&pod, pkt, 4, -70, 0); /* too short to forward, but heard */
    pod_status_bytes(&pod, 57, true, st);
    CHECK(st[0] == 57 && (int8_t)st[1] == -70 && st[2] == 0x07);
}

/* ---- Field and pair frames (PE24-100) ------------------------------------------------- */

/* The last frame of a type on a link is a vector's payload. */
static bool last_is(pod_link_t link, uint8_t type, const char *vector)
{
    int i = find_type(link, type);
    const proxy_frame_vector_t *v = frame_vector(vector);
    return i >= 0 && v != NULL && v->type == type && phone[link].len[i] == v->payload_len &&
           memcmp(phone[link].payload[i], v->payload, v->payload_len) == 0;
}

static void test_field_relay(void)
{
    const proxy_frame_vector_t *ftx = frame_vector("field_tx");
    const proxy_frame_vector_t *ptx = frame_vector("pair_tx");
    CHECK(ftx != NULL && ptx != NULL);
    if (ftx == NULL || ptx == NULL) return;

    /* No game configured (a sealed re-invite, a pairing by code): the phone's first frame is
     * its IDENT, then a field frame goes on air as it is, hop_limit 0, tagged with its id. */
    setup();
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    phone_send_vector(POD_LINK_USB, "field_tx");
    CHECK(!pod.radio.configured && radio_sends == 1 && radio_tag == (MODEM_FIELD_TAG | 513));
    CHECK(radio_pkt_len == ftx->payload_len - 2 &&
          memcmp(radio_pkt, ftx->payload + 2, radio_pkt_len) == 0);
    CHECK(pod.radio.count.field_tx == 1 && pod.count.ignored == 0);
    /* Its outcome, the duty cycle's refusal here, comes back as RADIO_FIELD_ACK. */
    pod_on_tx_result(&pod, radio_tag, MODEM_TX_DUTY_CYCLE);
    CHECK(last_is(POD_LINK_USB, ATALAIA_PROXY_RADIO_FIELD_ACK, "field_ack"));
    pod_on_tx_result(&pod, radio_tag, MODEM_TX_OK);
    int i = find_type(POD_LINK_USB, ATALAIA_PROXY_RADIO_FIELD_ACK);
    CHECK(i >= 0 && phone[POD_LINK_USB].payload[i][2] == MODEM_TX_OK);

    /* A field frame heard: RADIO_FIELD_RX to the phone, as it is, with RSSI and SNR. */
    pod_on_air_rx(&pod, ftx->payload + 2, ftx->payload_len - 2, -87, 6);
    CHECK(last_is(POD_LINK_USB, ATALAIA_PROXY_RADIO_FIELD_RX, "field_rx"));
    CHECK(pod.radio.count.field_rx == 1 && phone[POD_LINK_BLE].frames == 0);

    /* Pair frames (type 10, in the clear) ride the same frames. */
    phone_send_vector(POD_LINK_USB, "pair_tx");
    CHECK(radio_sends == 2 && radio_tag == (MODEM_FIELD_TAG | 2) &&
          radio_pkt_len == ptx->payload_len - 2 &&
          memcmp(radio_pkt, ptx->payload + 2, radio_pkt_len) == 0);
    pod_on_air_rx(&pod, ptx->payload + 2, ptx->payload_len - 2, -101, -3);
    CHECK(last_is(POD_LINK_USB, ATALAIA_PROXY_RADIO_FIELD_RX, "pair_rx"));

    /* Not the shape of a field or pair frame (a game packet): invalid, not sent. */
    uint8_t bad[2 + 40];
    memset(bad, 0, sizeof(bad));
    put16(bad, 77);
    bad[2] = 0x22; /* version 1, encrypted */
    put16(bad + 3, 4242);
    bad[10] = 2; /* a game message's type */
    phone_send(POD_LINK_USB, ATALAIA_PROXY_RADIO_FIELD_TX, bad, sizeof(bad));
    i = find_type(POD_LINK_USB, ATALAIA_PROXY_RADIO_FIELD_ACK);
    CHECK(radio_sends == 2 && i >= 0 && phone[POD_LINK_USB].payload[i][1] == 77 &&
          phone[POD_LINK_USB].payload[i][2] == MODEM_TX_INVALID);
    /* Shorter than its id: the modem's ERROR. */
    phone_send(POD_LINK_USB, ATALAIA_PROXY_RADIO_FIELD_TX, bad, 1);
    i = find_type(POD_LINK_USB, ATALAIA_PROXY_RADIO_ERROR);
    CHECK(i >= 0 && phone[POD_LINK_USB].payload[i][0] == MODEM_ERR_BAD_FRAME);

    /* While a measurement runs the radio is busy. */
    uint8_t measure[8] = {MODEM_CMD_MEASURE, 0x33, 0xd3, 0xe6, 0x08, 0x13, 0x88, 1};
    phone_send(POD_LINK_USB, ATALAIA_PROXY_RADIO_CMD, measure, sizeof(measure));
    CHECK(measures == 1);
    phone_send_vector(POD_LINK_USB, "field_tx");
    i = find_type(POD_LINK_USB, ATALAIA_PROXY_RADIO_FIELD_ACK);
    CHECK(radio_sends == 2 && i >= 0 && phone[POD_LINK_USB].payload[i][2] == MODEM_TX_BUSY);

    /* With a game configured: field frames still go and come (GAME_OVER, a re-invite during a
     * game), the heard ones to the link that runs the radio. */
    setup();
    phone_send_vector(POD_LINK_BLE, "cmd_ident");
    phone_send_vector(POD_LINK_USB, "cmd_configure");
    CHECK(pod.radio_owner == POD_LINK_USB);
    phone_send_vector(POD_LINK_USB, "field_tx");
    CHECK(radio_sends == 1);
    pod_on_air_rx(&pod, ftx->payload + 2, ftx->payload_len - 2, -87, 6);
    CHECK(last_is(POD_LINK_USB, ATALAIA_PROXY_RADIO_FIELD_RX, "field_rx"));
    CHECK(find_type(POD_LINK_BLE, ATALAIA_PROXY_RADIO_FIELD_RX) < 0);

    /* A phone on Bluetooth only, before any game: what is heard goes to it. */
    setup();
    phone_send_vector(POD_LINK_BLE, "cmd_ident");
    pod_on_air_rx(&pod, ptx->payload + 2, ptx->payload_len - 2, -101, -3);
    CHECK(last_is(POD_LINK_BLE, ATALAIA_PROXY_RADIO_FIELD_RX, "pair_rx"));
    CHECK(phone[POD_LINK_USB].frames == 0);

    /* No phone yet: heard, counted, sent nowhere. */
    setup();
    pod_on_air_rx(&pod, ftx->payload + 2, ftx->payload_len - 2, -87, 6);
    CHECK(phone[POD_LINK_USB].frames == 0 && phone[POD_LINK_BLE].frames == 0);

    /* No radio chip: RADIO_FIELD_ACK no_radio. */
    pod_caps_config_t cfg = full_config();
    setup_with(&cfg, false);
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    phone_send_vector(POD_LINK_USB, "field_tx");
    i = find_type(POD_LINK_USB, ATALAIA_PROXY_RADIO_FIELD_ACK);
    CHECK(radio_sends == 0 && i >= 0 && phone[POD_LINK_USB].payload[i][2] == MODEM_TX_NO_RADIO);

    /* A largest field frame (217 bytes) fits a frame both ways, over Bluetooth too. */
    setup();
    phone_send_vector(POD_LINK_BLE, "cmd_ident");
    uint8_t big[2 + MODEM_FIELD_MAX];
    memcpy(big, ftx->payload, ftx->payload_len);
    memset(big + ftx->payload_len, 0x5a, sizeof(big) - ftx->payload_len);
    phone_send(POD_LINK_BLE, ATALAIA_PROXY_RADIO_FIELD_TX, big, sizeof(big));
    CHECK(radio_sends == 1 && radio_pkt_len == MODEM_FIELD_MAX);
    pod_on_air_rx(&pod, big + 2, MODEM_FIELD_MAX, -60, 9);
    i = find_type(POD_LINK_BLE, ATALAIA_PROXY_RADIO_FIELD_RX);
    CHECK(i >= 0 && phone[POD_LINK_BLE].len[i] == MODEM_FIELD_MAX + 2);
}

/* ---- A box's firmware update through the pod (PE24-130) --------------------------------- */

/*
 * The update needs no frame of its own: the offer is CMD update (opcode 9, RFC 0001 Amendment
 * 6), an ordinary game packet the phone sends as RADIO_TX; the box's answers are a HELLO with
 * its version and, for a failure its HTTPS report cannot carry, the event node.update_failed,
 * ordinary game packets that come back as RADIO_RX. The image and the report go over the
 * field's Wi-Fi, past the pod. So the pod needs no capability bit for it (the proxy's IDENT
 * keys 6-8 tell of frame types an older pod ignores; every pod relays these).
 */
static void test_update_relay(void)
{
    static const uint8_t game_key[16] = {0x2b, 0x7e, 0x15, 0x16, 0x28, 0xae, 0xd2, 0xa6,
                                         0xab, 0xf7, 0x15, 0x88, 0x09, 0xcf, 0x4f, 0x3c};
    setup();
    phone_send_vector(POD_LINK_USB, "cmd_configure"); /* game 4242, node 0, key above */
    CHECK(pod.radio.configured && pod.radio_owner == POD_LINK_USB);

    /* The offer to box 7, as the controller makes it: critical, sealed by the pod. */
    atalaia_cmd_msg_t cmd;
    memset(&cmd, 0, sizeof(cmd));
    cmd.cmd = 9;
    cmd.dest = 7;
    snprintf(cmd.params_json, sizeof(cmd.params_json),
             "{\"id\":\"0123456789abcdef\",\"version\":\"0.3.0\"}");
    uint8_t body[128];
    size_t body_len = atalaia_cmd_encode(&cmd, body, sizeof(body));
    CHECK(body_len > 0);
    uint8_t tx[9 + 128];
    atalaia_header_t th = {
        ATALAIA_VF_MAKE(1, ATALAIA_PRIO_CRITICAL, 0, 0), 4242, 0, 21, 2, ATALAIA_MSG_CMD};
    atalaia_header_encode(&th, tx);
    memcpy(tx + 9, body, body_len);
    phone_send(POD_LINK_USB, ATALAIA_PROXY_RADIO_TX, tx, 9 + body_len);
    CHECK(radio_sends == 1 && radio_tag == 22 && pod.count.ignored == 0);

    /* What went on air is a sealed game packet that a box with the game's key opens. */
    atalaia_header_t ah;
    uint8_t plain[ATALAIA_RF_PAYLOAD_MAX];
    size_t plain_len = 0;
    CHECK(atalaia_packet_decrypt(radio_pkt, radio_pkt_len, pod.radio.tx_epoch, game_key, &ah, plain,
                                 &plain_len, &atalaia_crypto_test_stub));
    CHECK(ah.type == ATALAIA_MSG_CMD && ah.seq == 21 && ah.source == 0 && ah.game_id == 4242 &&
          ATALAIA_VF_PRIO(ah.version_flags) == ATALAIA_PRIO_CRITICAL &&
          ATALAIA_VF_ENC(ah.version_flags));
    atalaia_cmd_msg_t got;
    CHECK(atalaia_cmd_decode(plain, plain_len, &got) && got.cmd == 9 && got.dest == 7 &&
          strstr(got.params_json, "0123456789abcdef") != NULL &&
          strstr(got.params_json, "0.3.0") != NULL);

    /* The duty cycle is the radio task's, as for every packet: a refusal comes back as
     * RADIO_TX_ACK duty_cycle (for the phone to say so), the airtime's success as ok. */
    pod_on_tx_result(&pod, radio_tag, MODEM_TX_DUTY_CYCLE);
    int i = find_type(POD_LINK_USB, ATALAIA_PROXY_RADIO_TX_ACK);
    CHECK(i >= 0 && phone[POD_LINK_USB].len[i] == 3 && phone[POD_LINK_USB].payload[i][1] == 21 &&
          phone[POD_LINK_USB].payload[i][2] == MODEM_TX_DUTY_CYCLE);
    pod_on_tx_result(&pod, radio_tag, MODEM_TX_OK);
    i = find_type(POD_LINK_USB, ATALAIA_PROXY_RADIO_TX_ACK);
    CHECK(i >= 0 && phone[POD_LINK_USB].payload[i][1] == 21 &&
          phone[POD_LINK_USB].payload[i][2] == MODEM_TX_OK);

    /* The box's node.update_failed (id 52: release, reason, fw), sealed with the game key,
     * comes back as RADIO_RX with its plaintext: the pod never reads it. */
    atalaia_event_t ev;
    CHECK(atalaia_event_init(&ev, 7, 3, 0, "node.update_failed", ATALAIA_TEAM_NONE,
                             ATALAIA_SQUAD_NONE, ATALAIA_PRIO_CRITICAL));
    uint8_t evb[160];
    size_t evb_len = atalaia_event_encode(
        &ev, "{\"release\":\"0123456789abcdef\",\"reason\":\"no_wifi\",\"fw\":\"0.2.0\"}", evb,
        sizeof(evb), NULL);
    CHECK(evb_len > 0);
    atalaia_header_t bh = {
        ATALAIA_VF_MAKE(1, ATALAIA_PRIO_CRITICAL, 0, 1), 4242, 7, 3, 2, ATALAIA_MSG_EVENT};
    uint8_t pkt[ATALAIA_RF_HEADER_SIZE + ATALAIA_RF_PAYLOAD_MAX + ATALAIA_RF_MIC_SIZE];
    size_t pkt_len = atalaia_packet_encrypt(&bh, 2, game_key, evb, evb_len, pkt, sizeof(pkt),
                                            &atalaia_crypto_test_stub);
    CHECK(pkt_len > 0);
    pod_on_air_rx(&pod, pkt, pkt_len, -92, 4);
    i = find_type(POD_LINK_USB, ATALAIA_PROXY_RADIO_RX);
    CHECK(i >= 0 && phone[POD_LINK_USB].len[i] == 9 + evb_len + 4);
    if (i >= 0 && phone[POD_LINK_USB].len[i] == 9 + evb_len + 4) {
        const uint8_t *p = phone[POD_LINK_USB].payload[i];
        CHECK(memcmp(p + 9, evb, evb_len) == 0 && (int8_t)p[9 + evb_len] == -92);
        atalaia_event_t back;
        char data[160];
        CHECK(atalaia_event_decode(p + 9, evb_len, &back, data, sizeof(data), NULL) &&
              strcmp(back.type, "node.update_failed") == 0 && strstr(data, "no_wifi") != NULL);
    }

    /* A pod without a radio chip refuses the offer, saying so (the phone then says why). */
    pod_caps_config_t cfg = full_config();
    setup_with(&cfg, false);
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    phone_send(POD_LINK_USB, ATALAIA_PROXY_RADIO_TX, tx, 9 + body_len);
    i = find_type(POD_LINK_USB, ATALAIA_PROXY_RADIO_TX_ACK);
    CHECK(radio_sends == 0 && i >= 0 && phone[POD_LINK_USB].payload[i][2] == MODEM_TX_NO_RADIO);

    /* No game configured (the phone's CONFIGURE is lost with a link): not configured, not
     * sent, and never an unsealed packet on air. */
    setup();
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    phone_send(POD_LINK_USB, ATALAIA_PROXY_RADIO_TX, tx, 9 + body_len);
    i = find_type(POD_LINK_USB, ATALAIA_PROXY_RADIO_TX_ACK);
    CHECK(radio_sends == 0 && i >= 0 &&
          phone[POD_LINK_USB].payload[i][2] == MODEM_TX_NOT_CONFIGURED);
}

/* ---- Settings pushed over the radio (CMD pod, decision PODC) -------------------------------- */

static pod_settings_t pushed;
static pod_caps_config_t build_config;
static int config_calls, config_saves;

static pod_config_result_t test_config(void *ctx, const char *params_json, uint32_t *rev)
{
    (void)ctx;
    config_calls++;
    pod_config_result_t r = pod_settings_handle(&pushed, params_json, &caps, &build_config, rev);
    if (r == POD_CONFIG_APPLIED) config_saves++;
    return r;
}

/* A sealed game packet from the controller (node 1): CMD with the opcode, params and dest. */
static size_t controller_cmd(uint8_t opcode, const char *params, uint16_t dest, uint16_t seq,
                             uint8_t *pkt, size_t cap)
{
    static const uint8_t game_key[16] = {0x2b, 0x7e, 0x15, 0x16, 0x28, 0xae, 0xd2, 0xa6,
                                         0xab, 0xf7, 0x15, 0x88, 0x09, 0xcf, 0x4f, 0x3c};
    atalaia_cmd_msg_t cmd;
    memset(&cmd, 0, sizeof(cmd));
    cmd.cmd = opcode;
    cmd.dest = dest;
    snprintf(cmd.params_json, sizeof(cmd.params_json), "%s", params);
    uint8_t body[128];
    size_t body_len = atalaia_cmd_encode(&cmd, body, sizeof(body));
    CHECK(body_len > 0);
    atalaia_header_t h = {
        ATALAIA_VF_MAKE(1, ATALAIA_PRIO_CRITICAL, 0, 1), 4242, 1, seq, 2, ATALAIA_MSG_CMD};
    return atalaia_packet_encrypt(&h, 2, game_key, body, body_len, pkt, cap,
                                  &atalaia_crypto_test_stub);
}

static void test_config_over_radio(void)
{
    pod_caps_config_t cfg = full_config();
    cfg.team[1] = "green"; /* the build's colour of button 2 */
    build_config = cfg;
    setup_with(&cfg, true);
    memset(&pushed, 0, sizeof(pushed));
    config_calls = config_saves = 0;
    pod.io.config = test_config;
    phone_send_vector(POD_LINK_USB, "cmd_configure"); /* game 4242, the key above */
    pod.radio.node_id = 7;                            /* the phone's node id in this game */
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    pod_set_link_active(&pod, POD_LINK_USB);
    int idents = count_type(POD_LINK_USB, ATALAIA_PROXY_IDENT);
    uint8_t pkt[ATALAIA_RF_HEADER_SIZE + ATALAIA_RF_PAYLOAD_MAX + ATALAIA_RF_MIC_SIZE];

    /* Before anything is pushed: the build's colours. */
    char json[ATALAIA_PROXY_JSON_MAX];
    pod_caps_descriptors(&caps, json, sizeof(json), true);
    CHECK(strstr(json, "\"team\":\"green\"") != NULL && strstr(json, "\"team\":\"red\"") == NULL);

    /* A sealed CMD pod to this node: taken by the pod, not passed to the phone, applied, the
     * IDENT sent again, the EVT pod.config {"rev"} sent for the phone to acknowledge on air. */
    size_t n = controller_cmd(
        POD_CMD_POD,
        "{\"v\":1,\"rev\":5,\"btn\":[\"red\",\"\",\"\",\"blue\"],\"bright\":40,\"vol\":70,"
        "\"tamper\":false}",
        7, 30, pkt, sizeof(pkt));
    CHECK(n > 0);
    pod_on_air_rx(&pod, pkt, n, -80, 5);
    CHECK(config_calls == 1 && config_saves == 1 && pod.count.config_applied == 1);
    CHECK(count_type(POD_LINK_USB, ATALAIA_PROXY_RADIO_RX) == 0 && pod.radio.count.rx_taken == 1);
    CHECK(count_type(POD_LINK_USB, ATALAIA_PROXY_IDENT) == idents + 1);
    atalaia_proxy_msg_t m;
    CHECK(last_msg(POD_LINK_USB, &m) && strcmp(m.cap_id, "pod") == 0 &&
          strcmp(m.name, "config") == 0 && strcmp(m.data_json, "{\"rev\":5}") == 0);
    pod_caps_descriptors(&caps, json, sizeof(json), true);
    CHECK(strstr(json, "\"team\":\"red\"") != NULL && strstr(json, "\"team\":\"blue\"") != NULL &&
          strstr(json, "\"team\":\"green\"") == NULL && strstr(json, "\"id\":\"case\"") == NULL);
    CHECK(led_brightness == 40 && caps.brightness == 40 && audio_volume == 70);

    /* The controller's repeat (the phone's ACK was lost; a new packet, the same rev): taken
     * before, acknowledged again, nothing saved twice. */
    n = controller_cmd(POD_CMD_POD,
                       "{\"v\":1,\"rev\":5,\"btn\":[\"red\",\"\",\"\",\"blue\"],\"bright\":40,"
                       "\"vol\":70,\"tamper\":false}",
                       7, 31, pkt, sizeof(pkt));
    pod_on_air_rx(&pod, pkt, n, -80, 5);
    CHECK(config_saves == 1 && pod.count.config_repeats == 1 &&
          count_type(POD_LINK_USB, ATALAIA_PROXY_IDENT) == idents + 1);
    CHECK(last_msg(POD_LINK_USB, &m) && strcmp(m.data_json, "{\"rev\":5}") == 0);

    /* A stale rev, an invalid one: ignored without an answer. */
    int evts = count_type(POD_LINK_USB, ATALAIA_PROXY_EVT);
    n = controller_cmd(POD_CMD_POD, "{\"v\":1,\"rev\":4,\"bright\":10}", 7, 32, pkt, sizeof(pkt));
    pod_on_air_rx(&pod, pkt, n, -80, 5);
    n = controller_cmd(POD_CMD_POD, "{\"v\":1,\"rev\":6,\"bright\":101}", 7, 33, pkt, sizeof(pkt));
    pod_on_air_rx(&pod, pkt, n, -80, 5);
    CHECK(pod.count.config_ignored == 2 && count_type(POD_LINK_USB, ATALAIA_PROXY_EVT) == evts &&
          pushed.rev == 5 && led_brightness == 40);

    /* Not for this pod: to another node, to every node, another opcode: passed to the phone
     * like any packet (it ignores what is not its own). */
    n = controller_cmd(POD_CMD_POD, "{\"v\":1,\"rev\":9,\"bright\":10}", 8, 34, pkt, sizeof(pkt));
    pod_on_air_rx(&pod, pkt, n, -80, 5);
    n = controller_cmd(POD_CMD_POD, "{\"v\":1,\"rev\":9,\"bright\":10}", 0xFFFF, 35, pkt,
                       sizeof(pkt));
    pod_on_air_rx(&pod, pkt, n, -80, 5);
    n = controller_cmd(9, "{\"id\":\"0123456789abcdef\",\"version\":\"0.3.0\"}", 7, 36, pkt,
                       sizeof(pkt));
    pod_on_air_rx(&pod, pkt, n, -80, 5);
    CHECK(config_calls == 4 && count_type(POD_LINK_USB, ATALAIA_PROXY_RADIO_RX) == 3);

    /* A packet sealed with another key is nothing: the CMD is authenticated like every other. */
    static const uint8_t other_key[16] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16};
    atalaia_cmd_msg_t cmd;
    memset(&cmd, 0, sizeof(cmd));
    cmd.cmd = POD_CMD_POD;
    cmd.dest = 7;
    snprintf(cmd.params_json, sizeof(cmd.params_json), "{\"v\":1,\"rev\":99,\"vol\":1}");
    uint8_t body[128];
    size_t body_len = atalaia_cmd_encode(&cmd, body, sizeof(body));
    atalaia_header_t h = {
        ATALAIA_VF_MAKE(1, ATALAIA_PRIO_CRITICAL, 0, 1), 4242, 1, 40, 2, ATALAIA_MSG_CMD};
    n = atalaia_packet_encrypt(&h, 2, other_key, body, body_len, pkt, sizeof(pkt),
                               &atalaia_crypto_test_stub);
    pod_on_air_rx(&pod, pkt, n, -80, 5);
    CHECK(config_calls == 4 && pushed.rev == 5 && pod.radio.count.rx_auth_fail >= 1);

    /* reset: the build's settings are back (button 2 green, the switch on, the ring at 100). */
    n = controller_cmd(POD_CMD_POD, "{\"v\":1,\"rev\":6,\"reset\":true}", 7, 41, pkt, sizeof(pkt));
    pod_on_air_rx(&pod, pkt, n, -80, 5);
    pod_caps_descriptors(&caps, json, sizeof(json), true);
    CHECK(pod.count.config_applied == 2 && strstr(json, "\"team\":\"green\"") != NULL &&
          strstr(json, "\"id\":\"case\"") != NULL && led_brightness == 100);

    /* A pod without the hook (an older build) passes the CMD on like any packet. */
    setup_with(&cfg, true);
    phone_send_vector(POD_LINK_USB, "cmd_configure");
    pod.radio.node_id = 7;
    n = controller_cmd(POD_CMD_POD, "{\"v\":1,\"rev\":1,\"bright\":10}", 7, 50, pkt, sizeof(pkt));
    pod_on_air_rx(&pod, pkt, n, -80, 5);
    CHECK(count_type(POD_LINK_USB, ATALAIA_PROXY_RADIO_RX) == 1);
}

/* ---- Capabilities ---------------------------------------------------------------------- */

static void test_caps_inputs(void)
{
    setup();
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    atalaia_proxy_msg_t m;

    /* The keypad: one key per stroke, after 3 stable scans 10 ms apart. */
    key_down = '5';
    advance(40);
    CHECK(last_msg(POD_LINK_USB, &m) && strcmp(m.cap_id, "keypad") == 0 &&
          strcmp(m.name, "key") == 0 && strcmp(m.data_json, "{\"key\":\"5\"}") == 0);
    ack(POD_LINK_USB, m.seq);
    int evts = count_type(POD_LINK_USB, ATALAIA_PROXY_EVT);
    advance(200); /* held: nothing more */
    key_down = HAL_KEY_NONE;
    advance(50);
    CHECK(count_type(POD_LINK_USB, ATALAIA_PROXY_EVT) == evts);

    /* A player tag: its UID and its record, as hex. */
    const uint8_t record[] = {0x01, 0x70, 0x2d, 0x31, 0x37, 0x01, 0x10, 0x92, 0xd8,
                              0xe6, 0xa0, 0xe3, 0xd3, 0x8a, 0x3e, 0x0a, 0x3e, 0x9b,
                              0x2d, 0x9c, 0x5d, 0x4b, 0xbf, 0x63, 0xe1};
    nfc_mem_len = (int)atalaia_tag_to_ndef_tag(record, sizeof(record), nfc_mem, sizeof(nfc_mem));
    CHECK(nfc_mem_len > 0);
    nfc_present = true;
    nfc_tag.uid_len = 7;
    memcpy(nfc_tag.uid, "\x04\xa1\xb2\xc3\xd4\xe5\xf6", 7);
    advance(300);
    CHECK(last_msg(POD_LINK_USB, &m) && strcmp(m.cap_id, "nfc") == 0 && strcmp(m.name, "tag") == 0);
    CHECK(strcmp(m.data_json,
                 "{\"uid\":\"04a1b2c3d4e5f6\","
                 "\"tag\":\"01702d3137011092d8e6a0e3d38a3e0a3e9b2d9c5d4bbf63e1\"}") == 0);
    ack(POD_LINK_USB, m.seq);
    evts = count_type(POD_LINK_USB, ATALAIA_PROXY_EVT);
    advance(900); /* still on the reader: once per tap */
    CHECK(count_type(POD_LINK_USB, ATALAIA_PROXY_EVT) == evts);
    nfc_present = false;
    advance(300);
    /* A card with nothing of ours: the UID only. */
    nfc_present = true;
    nfc_mem_len = 16;
    memset(nfc_mem, 0, 16);
    nfc_tag.uid[0] = 0x05;
    advance(300);
    CHECK(last_msg(POD_LINK_USB, &m) && strcmp(m.data_json, "{\"uid\":\"05a1b2c3d4e5f6\"}") == 0);
    ack(POD_LINK_USB, m.seq);
    /* A join card is not forwarded. */
    const uint8_t join_payload[] = {1, 2, 3, 4, 5, 6, 7, 8};
    nfc_mem_len =
        (int)atalaia_join_to_ndef_tag(join_payload, sizeof(join_payload), nfc_mem, sizeof(nfc_mem));
    CHECK(nfc_mem_len > 0);
    nfc_tag.uid[0] = 0x06;
    evts = count_type(POD_LINK_USB, ATALAIA_PROXY_EVT);
    advance(300);
    CHECK(count_type(POD_LINK_USB, ATALAIA_PROXY_EVT) == evts);
    nfc_present = false;
    advance(300);

    /* The enclosure switch: armed once closed; opened and closed; told again to a new link. */
    pod_caps_poll(&caps, clock_ms += 10, 1, emit, NULL);
    pod_caps_poll(&caps, clock_ms += 100, 1, emit, NULL);
    CHECK(count_type(POD_LINK_USB, ATALAIA_PROXY_EVT) == evts); /* open, never closed: no alarm */
    pod_caps_poll(&caps, clock_ms += 10, 0, emit, NULL);
    pod_caps_poll(&caps, clock_ms += 20, 0, emit, NULL); /* a bounce: not yet */
    CHECK(!caps.tamper_armed);
    pod_caps_poll(&caps, clock_ms += 40, 0, emit, NULL);
    CHECK(caps.tamper_armed && count_type(POD_LINK_USB, ATALAIA_PROXY_EVT) == evts);
    pod_caps_poll(&caps, clock_ms += 10, 1, emit, NULL);
    pod_caps_poll(&caps, clock_ms += 60, 1, emit, NULL);
    CHECK(last_msg(POD_LINK_USB, &m) && strcmp(m.cap_id, "case") == 0 &&
          strcmp(m.name, "opened") == 0);
    ack(POD_LINK_USB, m.seq);
    pod_caps_poll(&caps, clock_ms += 60, 1, emit, NULL);
    CHECK(count_type(POD_LINK_USB, ATALAIA_PROXY_EVT) == evts + 1); /* once */
    phone_send_vector(POD_LINK_BLE, "cmd_ident"); /* a new link hears it is open */
    CHECK(last_msg(POD_LINK_BLE, &m) && strcmp(m.name, "opened") == 0);
    ack(POD_LINK_BLE, m.seq);
    pod_caps_poll(&caps, clock_ms += 10, 0, emit, NULL);
    pod_caps_poll(&caps, clock_ms += 60, 0, emit, NULL);
    CHECK(last_msg(POD_LINK_USB, &m) && strcmp(m.name, "closed") == 0);
}

static bool run_cmd(const char *cap, const char *method, const char *args)
{
    atalaia_proxy_msg_t m;
    memset(&m, 0, sizeof(m));
    snprintf(m.cap_id, sizeof(m.cap_id), "%s", cap);
    snprintf(m.name, sizeof(m.name), "%s", method);
    snprintf(m.data_json, sizeof(m.data_json), "%s", args);
    return pod_caps_command(&caps, &m);
}

static void test_caps_commands(void)
{
    setup();
    /* PD16's shapes: fill {"team"}, tone {"freq","ms"}, others {"args": [...]}. */
    CHECK(run_cmd("ring", "fill", "{\"team\":\"blue\"}") && led_rgb[2] == 255 && led_lit == 24);
    CHECK(run_cmd("ring", "fill", "{\"args\":[\"green\"]}") && led_rgb[1] == 255);
    CHECK(run_cmd("ring", "fill", "{\"team\":\"none\"}") && led_lit == 0);
    CHECK(run_cmd("ring", "color", "{\"r\":10,\"g\":20,\"b\":30}") && led_rgb[0] == 10 &&
          led_rgb[1] == 20 && led_rgb[2] == 30);
    CHECK(run_cmd("ring", "color", "{\"args\":[1,2,300]}") && led_rgb[2] == 255);
    CHECK(!run_cmd("ring", "color", "{\"args\":[1,2]}"));
    CHECK(run_cmd("ring", "fill", "{\"team\":\"red\"}"));
    CHECK(run_cmd("ring", "progress", "{\"args\":[0.5]}") && led_lit == 12);
    CHECK(led_px[11][0] == 255 && led_px[12][0] == 0);
    CHECK(run_cmd("ring", "progress", "{\"value\":2}") && led_lit == 24);
    CHECK(run_cmd("ring", "off", "") && led_lit == 0);
    CHECK(run_cmd("ring", "progress", "{\"args\":[0.25]}") && led_lit == 6 && led_px[0][1] == 255);
    CHECK(run_cmd("ring", "set_brightness", "{\"args\":[40]}") && led_brightness == 40);
    CHECK(run_cmd("ring", "set_brightness", "{\"pct\":140}") && led_brightness == 100);
    CHECK(!run_cmd("ring", "set_brightness", "{}"));
    CHECK(!run_cmd("ring", "pattern", "{}"));

    CHECK(run_cmd("audio", "tone", "{\"freq\":2000,\"ms\":150}") && tones == 1 &&
          tone_hz[0] == 2000 && tone_ms[0] == 150);
    CHECK(run_cmd("audio", "tone", "{\"args\":[30000,0]}") && tone_hz[1] == 20000 &&
          tone_ms[1] == 1);
    CHECK(!run_cmd("audio", "tone", "{\"freq\":2000}"));
    tones = 0;
    CHECK(run_cmd("audio", "play", "{\"args\":[\"armed\"]}") && tones == 3 && tone_hz[1] == 0);
    CHECK(run_cmd("audio", "play", "{\"args\":[\"some_clip\"]}") && tones == 4 &&
          tone_hz[3] == 2000);
    CHECK(run_cmd("audio", "stop", "") && audio_stops == 1);
    CHECK(run_cmd("audio", "set_volume", "{\"args\":[30]}") && audio_volume == 30);
    CHECK(!run_cmd("audio", "say", "{\"args\":[\"hello\"]}"));

    CHECK(run_cmd("keypad", "clear", ""));
    CHECK(!run_cmd("nfc", "write", "{\"args\":[\"00\"]}")); /* not supported yet */
    CHECK(!run_cmd("btn.1", "led", "{\"args\":[\"on\"]}")); /* no button lights */
    CHECK(!run_cmd("screen", "text", "{}"));

    /* Parts not fitted take no commands. */
    pod_caps_config_t cfg;
    memset(&cfg, 0, sizeof(cfg));
    setup_with(&cfg, true);
    CHECK(!run_cmd("ring", "fill", "{\"team\":\"red\"}") && led_fills == 0);
    CHECK(!run_cmd("audio", "tone", "{\"freq\":1,\"ms\":1}") && tones == 0);
    CHECK(caps.commands_unknown == 2);

    uint8_t rgb[3];
    pod_caps_team_rgb("orange", rgb);
    CHECK(rgb[0] == 255 && rgb[1] == 128 && rgb[2] == 0);
    pod_caps_team_rgb("teal", rgb);
    CHECK(rgb[0] == 255 && rgb[1] == 255 && rgb[2] == 255);
}

static void test_json(void)
{
    char s[16];
    double v;
    const char *j = "{\"a\":{\"team\":\"x\"},\"team\":\"r\\\"ed\",\"n\":-2.5,\"t\":true,"
                    "\"args\":[ \"s\" , 7, [1,2], 9 ]}";
    CHECK(pod_json_str(j, "team", s, sizeof(s)) && strcmp(s, "r\"ed") == 0);
    CHECK(pod_json_num(j, "n", &v) && v == -2.5);
    CHECK(pod_json_num(j, "t", &v) && v == 1);
    CHECK(!pod_json_num(j, "team", &v));
    CHECK(!pod_json_str(j, "missing", s, sizeof(s)));
    CHECK(pod_json_arg_str(j, 0, s, sizeof(s)) && strcmp(s, "s") == 0);
    CHECK(pod_json_arg_num(j, 1, &v) && v == 7);
    CHECK(pod_json_arg_num(j, 3, &v) && v == 9);
    CHECK(!pod_json_arg_num(j, 2, &v) && !pod_json_arg_num(j, 4, &v));
    CHECK(!pod_json_str("{\"team\":\"averyveryverylongname\"}", "team", s, sizeof(s)));
    CHECK(!pod_json_str("[\"team\"]", "team", s, sizeof(s)));
    CHECK(!pod_json_str("{\"team\":\"open", "team", s, sizeof(s)));
    CHECK(!pod_json_num("", "x", &v) && !pod_json_num(NULL, "x", &v));
    CHECK(!pod_json_arg_num("{\"args\":3}", 0, &v));
}

/* ---- Simple outputs (main/pod/pod_outputs.c; the expansion port's increment 9) --------- */

typedef struct {
    int out; /* which output */
    uint16_t width;
    uint16_t frames;
    bool flush;
    uint32_t t;
} so_burst_t;

static so_burst_t so_bursts[512];
static int so_burst_count;

static bool fake_rmt(void *ctx, uint16_t width_us, uint16_t frames, bool flush)
{
    simple_out_t *so = (simple_out_t *)ctx;
    if (so_burst_count < 512) {
        so_bursts[so_burst_count++] =
            (so_burst_t){(int)(so - simple), width_us, frames, flush, clock_ms};
    }
    return true;
}

/* An enabled simple output with that use and longest on, as a pod build adds it. */
static void add_output(const char *function, int gpio, uint32_t max_on_s)
{
    auto_ack = true; /* the phone acknowledges the EVT pod.modules */
    int i = simple_count++;
    simple_out_rmt_t rmt = {.ctx = &simple[i], .send = fake_rmt};
    simple_out_init(&simple[i], gpio, &rmt);
    out_settings_t s;
    outputs_default_settings(i, &s);
    s.enabled = true;
    snprintf(s.function, sizeof(s.function), "%s", function);
    s.max_on_s = max_on_s;
    out_backend_t be = {.ctx = &simple[i], .drive = simple_out_backend_drive};
    CHECK(outputs_add_simple(&outs.out, gpio, &be, &s) == i);
}

/* A pod with a siren on GPIO 33 (30 s) and a strobe on GPIO 1 (10 s), its signal ended at boot,
 * and a phone on USB. */
static void setup_outputs(void)
{
    /* Two buttons, the ring and the case: room in IDENT for both outputs (EXPI9-27). */
    pod_caps_config_t cfg;
    memset(&cfg, 0, sizeof(cfg));
    cfg.button[0] = cfg.button[1] = true;
    cfg.leds = true;
    cfg.led_count = 24;
    cfg.tamper = true;
    setup_with(&cfg, true);
    auto_ack = true; /* the phone acknowledges the EVT pod.modules */
    so_burst_count = 0;
    add_output("siren", 33, 30);
    add_output("strobe", 1, 10);
    advance(10);
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    advance(10);
}

/* The phone's CMD for an output, as the app sends it. */
static void out_cmd(const char *cap, const char *method, const char *args, uint16_t seq)
{
    atalaia_proxy_msg_t m;
    memset(&m, 0, sizeof(m));
    snprintf(m.cap_id, sizeof(m.cap_id), "%s", cap);
    snprintf(m.name, sizeof(m.name), "%s", method);
    snprintf(m.data_json, sizeof(m.data_json), "%s", args);
    m.seq = seq;
    uint8_t buf[ATALAIA_PROXY_PAYLOAD_MAX];
    size_t n = atalaia_proxy_msg_encode(&m, buf, sizeof(buf));
    CHECK(n > 0);
    phone_send(POD_LINK_USB, ATALAIA_PROXY_CMD, buf, n);
}

static bool level(int i)
{
    return outputs_level(&outs.out, i);
}

/* The last burst queued for output i (NULL: none). */
static const so_burst_t *last_burst(int i)
{
    for (int k = so_burst_count - 1; k >= 0; k--) {
        if (so_bursts[k].out == i) return &so_bursts[k];
    }
    return NULL;
}

static void test_outputs_ident(void)
{
    /* The vector's pod: two buttons, the ring, the case and a siren, from a release build. */
    pod_caps_config_t cfg;
    memset(&cfg, 0, sizeof(cfg));
    cfg.button[0] = cfg.button[1] = true;
    cfg.leds = true;
    cfg.led_count = 24;
    cfg.tamper = true;
    setup_with(&cfg, true);
    add_output("siren", 33, 30);
    fw = "0.8.0";
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    const proxy_frame_vector_t *v = frame_vector("pod_simple_output");
    CHECK(v != NULL && phone[POD_LINK_USB].frames == 1);
    if (v != NULL) {
        CHECK(phone[POD_LINK_USB].raw_len[0] == v->frame_len &&
              memcmp(phone[POD_LINK_USB].raw[0], v->frame, v->frame_len) == 0);
    }
    CHECK(compact_idents == 0);

    /* Only an enabled output is lent (EXP-28), and its CMDs are its own. */
    CHECK(pod_outputs_owns(&outs, "siren") && !pod_outputs_owns(&outs, "ring") &&
          !pod_outputs_owns(&outs, "strobe"));
    out_settings_t off;
    outputs_default_settings(0, &off);
    CHECK(outputs_configure(&outs.out, 0, &off) == OUT_OK); /* disabled: "out.1" */
    CHECK(!pod_outputs_owns(&outs, "siren") && !pod_outputs_owns(&outs, "out.1"));
    char json[ATALAIA_PROXY_JSON_MAX] = "[]";
    CHECK(pod_outputs_append(&outs, json, 2, sizeof(json), true, 0) == 2 &&
          strcmp(json, "[]") == 0);

    /* Appending: after the parts, with the flag or without; nothing when it does not fit. */
    setup();
    add_output("siren", 33, 30);
    add_output("siren", 1, 30); /* the same use twice: siren.2 */
    snprintf(json, sizeof(json), "[]");
    size_t n = pod_outputs_append(&outs, json, 2, sizeof(json), true, 0);
    CHECK(n == strlen(json) &&
          strcmp(json, "[{\"id\":\"siren\",\"type\":\"output\",\"feedback\":false},"
                       "{\"id\":\"siren.2\",\"type\":\"output\",\"feedback\":false}]") == 0);
    snprintf(json, sizeof(json), "[{\"id\":\"nfc\",\"type\":\"nfc\"}]");
    n = pod_outputs_append(&outs, json, strlen(json), sizeof(json), false, 0);
    CHECK(n == strlen(json) &&
          strcmp(json, "[{\"id\":\"nfc\",\"type\":\"nfc\"},{\"id\":\"siren\",\"type\":\"output\"},"
                       "{\"id\":\"siren.2\",\"type\":\"output\"}]") == 0);
    char small[48] = "[{\"id\":\"nfc\",\"type\":\"nfc\"}]";
    CHECK(pod_outputs_append(&outs, small, strlen(small), sizeof(small), false, 0) == 0);
    CHECK(strcmp(small, "[{\"id\":\"nfc\",\"type\":\"nfc\"}]") == 0);

    /* Room in 256 bytes (PF6): every part, the longest version and a siren fit once the flag
     * is left out and the version cut to its release; with a second output, the last one goes
     * (EXPI9-27): not lent, refused, the siren still lent. */
    setup();
    add_output("siren", 33, 30);
    fw = "0.3.0-123-g0123456-dirt"; /* 23 bytes */
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    atalaia_proxy_ident_t id;
    CHECK(phone[POD_LINK_USB].frames == 1 &&
          atalaia_proxy_ident_decode(phone[POD_LINK_USB].payload[0], phone[POD_LINK_USB].len[0],
                                     &id));
    CHECK(last_level == POD_IDENT_SHORT_FW && strcmp(id.fw_version, "0.3.0") == 0);
    CHECK(strstr(id.caps_json, "{\"id\":\"siren\",\"type\":\"output\"}") != NULL &&
          strstr(id.caps_json, "feedback") == NULL && strstr(id.caps_json, "\"case\"") != NULL);
    fw = "0.8.0"; /* a release: everything, the flag too */
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    CHECK(atalaia_proxy_ident_decode(phone[POD_LINK_USB].payload[1], phone[POD_LINK_USB].len[1],
                                     &id));
    CHECK(last_level == POD_IDENT_FULL && strstr(id.caps_json, "\"feedback\":false") != NULL);
    add_output("strobe", 1, 30);
    fw = "0.3.0-123-g0123456-dirt";
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    CHECK(atalaia_proxy_ident_decode(phone[POD_LINK_USB].payload[2], phone[POD_LINK_USB].len[2],
                                     &id));
    CHECK(last_level == POD_IDENT_TRIM && last_trim == 1 &&
          strstr(id.caps_json, "{\"id\":\"siren\",\"type\":\"output\"}") != NULL &&
          strstr(id.caps_json, "strobe") == NULL && strstr(id.caps_json, "\"case\"") != NULL &&
          strcmp(id.fw_version, "0.3.0") == 0);
    CHECK(pod_outputs_owns(&outs, "siren") && !pod_outputs_owns(&outs, "strobe"));
    CHECK(logged("sent with 1 output(s) left out") && logged("not lent (off, refused): strobe"));
    /* Not lent: its CMD names no capability of the pod, and the output layer refuses it too. */
    uint32_t unknown = pod.count.cmd_unknown;
    out_cmd("strobe", "pulse", "{\"ms\":1000}", 7);
    CHECK(pod.count.cmd_unknown == unknown + 1 && !outs.out.ch[1].on);
    CHECK(outputs_switch(&outs.out, "strobe", OUT_ACT_ON, 1000, 0, 0, OUT_SRC_FIELD) ==
          OUT_DISABLED);
}

static void test_outputs_boot_and_live(void)
{
    setup();
    so_burst_count = 0;
    add_output("siren", 33, 30);
    /* Boot, no phone: the signal ends (1.0 ms pulses for 0.5 s, then the pin low). */
    advance(2000);
    CHECK(so_burst_count == 1 && so_bursts[0].width == SO_OFF_US &&
          so_bursts[0].frames == SO_BURST_FRAMES);
    CHECK(!simple_out_pulsing(&simple[0], clock_ms));
    /* A phone on a link: a live off, renewed every 200 ms. */
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    advance(1000);
    CHECK(simple_out_pulsing(&simple[0], clock_ms) && last_burst(0)->width == SO_OFF_US);
    CHECK(so_burst_count >= 5 && simple[0].horizon_ms - clock_ms <= SO_BURST_MS);
    /* The phone goes quiet with nothing on: fine, the pulses carry on. */
    advance(5000);
    CHECK(simple_out_pulsing(&simple[0], clock_ms) && outs.quiet_offs == 0);
}

static void test_outputs_commands(void)
{
    setup_outputs();
    int acks = count_type(POD_LINK_USB, ATALAIA_PROXY_ACK);
    /* The vectors' pulse: on for 10 s, 2.0 ms pulses at once (a flush), acknowledged. */
    phone_send_vector(POD_LINK_USB, "siren_pulse");
    CHECK(count_type(POD_LINK_USB, ATALAIA_PROXY_ACK) == acks + 1);
    CHECK(level(0) && outs.commands == 1);
    advance(10);
    CHECK(last_burst(0)->width == SO_ON_US && last_burst(0)->flush);
    for (int k = 0; k < 19; k++) { /* the phone keeps the lease */
        advance(500);
        phone_send_vector(POD_LINK_USB, "cmd_ping");
    }
    CHECK(level(0));
    advance(600);
    CHECK(!level(0) && last_burst(0)->width == SO_OFF_US); /* its 10 s are over: a live off */
    advance(500);

    /* off; on for at most its longest (30 s); the vector's pattern. */
    phone_send_vector(POD_LINK_USB, "siren_on_for_at_most_30_s");
    CHECK(level(0));
    phone_send_vector(POD_LINK_USB, "siren_off");
    CHECK(!level(0) && outs.commands == 3);
    advance(600);
    out_cmd("siren", "on", "{\"ms\":600000}", 40);
    CHECK(level(0) && outs.out.ch[0].until_ms - outs.out.ch[0].start_ms == 30000);
    out_cmd("siren", "off", "", 41);
    advance(600);
    out_cmd("strobe", "pattern", "{\"on_ms\":500,\"off_ms\":500,\"ms\":4000}", 42);
    CHECK(level(1) && outs.out.ch[1].pattern);
    advance(500);
    phone_send_vector(POD_LINK_USB, "cmd_ping");
    advance(10);
    CHECK(!level(1)); /* its off half */
    advance(500);
    CHECK(level(1));

    /* The floors and the rules: a pulse lasts 500 ms at least; a faster pattern, an on within
     * 500 ms of an off, bad arguments: refused, still acknowledged. */
    out_cmd("strobe", "off", "", 43);
    advance(600);
    uint32_t refused = outs.refused;
    out_cmd("siren", "pulse", "{\"ms\":100}", 44);
    CHECK(level(0) && outs.out.ch[0].until_ms - outs.out.ch[0].start_ms == 500);
    advance(510);
    CHECK(!level(0));
    out_cmd("siren", "pulse", "{\"ms\":1000}", 45); /* 10 ms after it went off */
    CHECK(!level(0) && outs.refused == refused + 1);
    advance(500);
    out_cmd("strobe", "pattern", "{\"on_ms\":100,\"off_ms\":500,\"ms\":4000}", 46);
    out_cmd("siren", "pulse", "", 47);
    out_cmd("siren", "pulse", "{\"ms\":0}", 48);
    out_cmd("siren", "on", "{\"ms\":600001}", 49);
    out_cmd("siren", "pulse", "{\"ms\":\"1000\"}", 50);
    out_cmd("siren", "pulse", "{\"ms\":true}", 51);
    out_cmd("siren", "pulse", "{\"ms\":1000.5}", 52);
    out_cmd("strobe", "pattern", "{\"on_ms\":500,\"ms\":4000}", 53);
    CHECK(!level(0) && !level(1) && outs.refused == refused + 9);
    /* A method an output does not have: acknowledged, counted unknown. */
    uint32_t unknown = pod.count.cmd_unknown;
    out_cmd("siren", "toggle", "", 54);
    CHECK(pod.count.cmd_unknown == unknown + 1);
    /* A repeated seq is acted on once. */
    out_cmd("siren", "pulse", "{\"ms\":2000}", 55);
    uint32_t start = outs.out.ch[0].start_ms;
    advance(100);
    out_cmd("siren", "pulse", "{\"ms\":2000}", 55);
    CHECK(outs.out.ch[0].start_ms == start && pod.count.cmd_repeats >= 1);
}

static void test_outputs_link_loss(void)
{
    /* USB unplugged with the siren on: off at the next turn, then the signal ends. */
    setup_outputs();
    phone_send_vector(POD_LINK_USB, "siren_pulse");
    advance(100);
    CHECK(level(0));
    pod_set_link_up(&pod, POD_LINK_USB, false);
    advance(10);
    CHECK(!level(0) && outs.link_offs == 1);
    CHECK(last_burst(0)->width == SO_OFF_US && last_burst(0)->flush);
    advance(600);
    CHECK(!simple_out_pulsing(&simple[0], clock_ms)); /* no signal: the switch opens */
    int bursts = so_burst_count;
    advance(2000);
    CHECK(so_burst_count == bursts);

    /* The phone's app hangs with the USB link up: off after 1.5 s without a frame. */
    setup_outputs();
    phone_send_vector(POD_LINK_USB, "siren_pulse");
    advance(POD_OUT_QUIET_MS - 20);
    CHECK(level(0));
    advance(30);
    CHECK(!level(0) && outs.quiet_offs == 1 && last_burst(0)->width == SO_OFF_US);
    /* The link is still up, so the switch keeps seeing a live off (1.0 ms) until it goes. */
    advance(600);
    CHECK(!level(0) && last_burst(0)->width == SO_OFF_US && outs.quiet_offs == 1);
    /* A frame handled after the caller read its clock (heard a few ms after "now", as the host
     * pod's loop does it): the phone was just heard, not silent for 49 days (ROB-5). */
    setup_outputs();
    phone_send_vector(POD_LINK_USB, "siren_pulse");
    advance(100);
    CHECK(level(0));
    pod_outputs_tick(&outs, pod_phone_on(&pod), clock_ms + 3, clock_ms);
    CHECK(level(0) && outs.quiet_offs == 0);
    pod_outputs_tick(&outs, pod_phone_on(&pod), clock_ms + 1, clock_ms + 1);
    CHECK(level(0) && outs.quiet_offs == 0);
    /* ... and the lease still runs from the latest frame. */
    advance(POD_OUT_QUIET_MS + 20);
    CHECK(!level(0) && outs.quiet_offs == 1);
    advance(600);
    /* It speaks again: outputs switch again. */
    phone_send_vector(POD_LINK_USB, "cmd_ping");
    advance(10);
    CHECK(simple_out_pulsing(&simple[0], clock_ms) && !level(0));
    out_cmd("siren", "pulse", "{\"ms\":1000}", 60);
    CHECK(level(0));

    /* Bluetooth lost while both links were up: the USB phone still holds the output. */
    setup_outputs();
    pod_set_link_up(&pod, POD_LINK_BLE, true);
    pod_set_link_active(&pod, POD_LINK_BLE);
    phone_send_vector(POD_LINK_USB, "siren_pulse");
    pod_set_link_up(&pod, POD_LINK_BLE, false);
    advance(10);
    CHECK(level(0) && outs.link_offs == 0);
    /* A command right after the link came back, before the loop's turn: taken. */
    pod_set_link_up(&pod, POD_LINK_USB, false);
    advance(10);
    CHECK(!level(0));
    advance(600);
    pod_set_link_up(&pod, POD_LINK_USB, true);
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    out_cmd("siren", "pulse", "{\"ms\":1000}", 0);
    CHECK(level(0));
}

/* ---- The expansion port (pod_port.c) ------------------------------------------------------ */

static module_sim_t *sim_at(uint8_t addr)
{
    if (addr < EXP_ADDR_FIRST || addr > EXP_ADDR_LAST) return NULL;
    return plugged[addr - EXP_ADDR_FIRST] ? &sims[addr - EXP_ADDR_FIRST] : NULL;
}
static bool f_probe(void *ctx, uint8_t addr)
{
    (void)ctx;
    return sim_at(addr) != NULL;
}
static int f_write(void *ctx, uint8_t addr, const uint8_t *d, size_t n)
{
    (void)ctx;
    module_sim_t *m = sim_at(addr);
    if (m == NULL) return EXP_BUS_FAIL;
    module_sim_write(m, clock_ms, d, n);
    return EXP_BUS_OK;
}
static int f_write_read(void *ctx, uint8_t addr, const uint8_t *o, size_t on, uint8_t *in,
                        size_t inn)
{
    (void)ctx;
    module_sim_t *m = sim_at(addr);
    if (m == NULL) return EXP_BUS_FAIL;
    module_sim_write(m, clock_ms, o, on);
    module_sim_read(m, clock_ms, in, inn);
    return EXP_BUS_OK;
}
static module_sim_t *plug(const char *name, uint8_t addr)
{
    int i = addr - EXP_ADDR_FIRST;
    CHECK(module_sim_named(&sims[i], name, addr, clock_ms));
    plugged[i] = true;
    return &sims[i];
}

static int ident_resends;
static void count_ident_resend(void *ctx)
{
    (void)ctx;
    ident_resends++;
    pod_send_ident_all(&pod);
}

/* A pod (cfg) whose phone acknowledges its EVTs; plug() its modules, then start_port(). */
static void setup_port(const pod_caps_config_t *cfg)
{
    setup_with(cfg, true);
    auto_ack = true;
    ident_resends = 0;
}
static void start_port(bool module_outputs, uint32_t max_on_s)
{
    static const exp_bus_t bus = {NULL, f_probe, f_write, f_write_read};
    pod_port_config_t pc = {.module_outputs = module_outputs, .module_max_on_s = max_on_s};
    pod_port_ops_t pops = {
        .ctx = NULL, .emit = emit, .ident_changed = count_ident_resend, .log = log_line};
    pod_port_init(&port, &bus, &outs, &pc, &pops);
    pod_port_start(&port, clock_ms);
}

/* The EVTs of a capability on a link, the n-th from the last (0: the last). */
static bool nth_evt(pod_link_t link, const char *cap, const char *event, int n,
                    atalaia_proxy_msg_t *m)
{
    phone_t *ph = &phone[link];
    for (int i = ph->frames - 1; i >= 0; i--) {
        if (ph->type[i] != ATALAIA_PROXY_EVT ||
            !atalaia_proxy_msg_decode(ph->payload[i], ph->len[i], m)) {
            continue;
        }
        if (strcmp(m->cap_id, cap) == 0 && strcmp(m->name, event) == 0 && n-- == 0) return true;
    }
    return false;
}
static int count_evt(pod_link_t link, const char *cap, const char *event)
{
    int n = 0;
    atalaia_proxy_msg_t m;
    while (nth_evt(link, cap, event, n, &m)) n++;
    return n;
}
static const uint8_t *raw_evt(pod_link_t link, const char *cap, const char *event, size_t *len)
{
    phone_t *ph = &phone[link];
    atalaia_proxy_msg_t m;
    for (int i = ph->frames - 1; i >= 0; i--) {
        if (ph->type[i] == ATALAIA_PROXY_EVT &&
            atalaia_proxy_msg_decode(ph->payload[i], ph->len[i], &m) &&
            strcmp(m.cap_id, cap) == 0 && strcmp(m.name, event) == 0) {
            *len = ph->raw_len[i];
            return ph->raw[i];
        }
    }
    return NULL;
}

static void test_port_hits(void)
{
    pod_caps_config_t cfg;
    memset(&cfg, 0, sizeof(cfg));
    cfg.button[0] = true;
    setup_port(&cfg);
    module_sim_t *t = plug("target", 0x58);
    start_port(false, 30);
    CHECK(module_sim_armed(t) == 0);
    /* The phone links: IDENT lends the hit sensor, the EVT pod.modules follows it. */
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    atalaia_proxy_ident_t id;
    CHECK(phone[POD_LINK_USB].frames == 1 &&
          atalaia_proxy_ident_decode(phone[POD_LINK_USB].payload[0], phone[POD_LINK_USB].len[0],
                                     &id));
    CHECK(strcmp(id.caps_json, "[{\"id\":\"btn.1\",\"type\":\"button\"},"
                               "{\"id\":\"hit\",\"type\":\"hit\"}]") == 0);
    advance(10);
    atalaia_proxy_msg_t m;
    CHECK(nth_evt(POD_LINK_USB, "pod", "modules", 0, &m));
    CHECK(strcmp(m.data_json, "{\"modules\":\"58:target/1.0.0:hit\",\"max_on_s\":{}}") == 0);
    CHECK(pod_port_owns(&port, "hit") && pod_port_owns(&port, "hit.2") &&
          !pod_port_owns(&port, "ring"));

    /* A hit before the phone armed the plate: the module keeps nothing, the phone hears nothing. */
    CHECK(!module_sim_hit(t, clock_ms, 0, MC_EVENT_HIT, 120));
    out_cmd("hit", "arm", "{\"args\":[]}", 1);
    advance(50);
    CHECK(module_sim_armed(t) == 1);
    CHECK(module_sim_hit(t, clock_ms, 0, MC_EVENT_HIT, 180));
    advance(50);
    CHECK(nth_evt(POD_LINK_USB, "hit", "hit", 0, &m) &&
          strcmp(m.data_json, "{\"strength\":180}") == 0);
    /* The vector's bytes: target_hit is {"strength": 200} at its seq. */
    CHECK(port.hits == 1);
    /* Disarm: kept on the module. */
    out_cmd("hit", "disarm", "", 2);
    advance(50);
    CHECK(module_sim_armed(t) == 0);
    out_cmd("hit", "arm", "", 3);
    advance(50);
    CHECK(module_sim_armed(t) == 1);
    /* A method a hit sensor lacks: acknowledged, unknown. */
    uint32_t unknown = pod.count.cmd_unknown;
    out_cmd("hit", "fire", "", 4);
    CHECK(pod.count.cmd_unknown == unknown + 1);

    /* The link goes: disarmed, the arming forgotten; a hit is not kept. */
    pod_set_link_up(&pod, POD_LINK_USB, false);
    advance(50);
    CHECK(module_sim_armed(t) == 0 && port.xb.armed == 0);
    CHECK(!module_sim_hit(t, clock_ms, 0, MC_EVENT_HIT, 90));
    /* It links again: IDENT and the EVT again; nothing armed until the phone says so. */
    pod_set_link_up(&pod, POD_LINK_USB, true);
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    advance(50);
    CHECK(count_evt(POD_LINK_USB, "pod", "modules") == 2 && module_sim_armed(t) == 0);

    /* A second target plugged in during the session: IDENT again (hit, hit.2 with their channel),
     * the EVT with both, and a hit on it says its channel. */
    int idents = count_type(POD_LINK_USB, ATALAIA_PROXY_IDENT);
    module_sim_t *t2 = plug("target", 0x59);
    advance(EXP_PROBE_MS + 100);
    CHECK(ident_resends == 1 && count_type(POD_LINK_USB, ATALAIA_PROXY_IDENT) == idents + 1);
    CHECK(nth_evt(POD_LINK_USB, "pod", "modules", 0, &m));
    CHECK(strcmp(m.data_json, "{\"modules\":\"58:target/1.0.0:hit;59:target/1.0.0:hit.2\","
                              "\"max_on_s\":{}}") == 0);
    int last = phone[POD_LINK_USB].frames - 1;
    for (; last >= 0 && phone[POD_LINK_USB].type[last] != ATALAIA_PROXY_IDENT; last--) {
    }
    CHECK(last >= 0 && atalaia_proxy_ident_decode(phone[POD_LINK_USB].payload[last],
                                                  phone[POD_LINK_USB].len[last], &id));
    CHECK(strstr(id.caps_json, "{\"id\":\"hit\",\"type\":\"hit\",\"channel\":1},"
                               "{\"id\":\"hit.2\",\"type\":\"hit\",\"channel\":2}") != NULL);
    out_cmd("hit.2", "arm", "", 10);
    advance(50);
    CHECK(module_sim_armed(t2) == 1 && module_sim_armed(t) == 0);
    CHECK(module_sim_hit(t2, clock_ms, 0, MC_EVENT_HIT, 90));
    advance(50);
    CHECK(nth_evt(POD_LINK_USB, "hit.2", "hit", 0, &m) &&
          strcmp(m.data_json, "{\"strength\":90,\"channel\":2}") == 0);
    /* Its bytes are the vector's second_target_hit but for the seq: the data the same. */
    size_t rl = 0;
    CHECK(raw_evt(POD_LINK_USB, "hit.2", "hit", &rl) != NULL);

    /* It is unplugged during the session: pod.module_lost, then IDENT and the EVT without it. */
    plugged[1] = false;
    advance(1000);
    CHECK(nth_evt(POD_LINK_USB, "pod", "module_lost", 0, &m));
    CHECK(strcmp(m.data_json, "{\"modules\":\"59:target/1.0.0:hit.2\",\"reason\":\"no_answer\"}") ==
          0);
    CHECK(nth_evt(POD_LINK_USB, "pod", "modules", 0, &m) &&
          strcmp(m.data_json, "{\"modules\":\"58:target/1.0.0:hit\",\"max_on_s\":{}}") == 0);
    CHECK(ident_resends == 2);
    /* Lost with no phone on a link: nothing told. */
    pod_set_link_up(&pod, POD_LINK_USB, false);
    plugged[0] = false;
    int lost = count_evt(POD_LINK_USB, "pod", "module_lost");
    advance(1000);
    CHECK(count_evt(POD_LINK_USB, "pod", "module_lost") == lost);
}

static void test_port_outputs(void)
{
    /* A siren on GPIO 33 and an out4 lent (siren.2, strobe, smoke, out.4), at most 20 s each. */
    pod_caps_config_t cfg;
    memset(&cfg, 0, sizeof(cfg));
    cfg.button[0] = true;
    setup_port(&cfg);
    so_burst_count = 0;
    add_output("siren", 33, 30);
    module_sim_t *o4 = plug("out4", 0x5C);
    module_sim_t *t = plug("target", 0x58);
    start_port(true, 20);
    advance(10);
    CHECK(outs.out.count == 5 && outs.out.simple == 1);
    CHECK(pod_outputs_owns(&outs, "siren.2") && pod_outputs_owns(&outs, "out.4"));
    fw = "0.8.0";
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    const proxy_frame_vector_t *v = frame_vector("pod_port_modules");
    CHECK(v != NULL && phone[POD_LINK_USB].frames == 1);
    if (v != NULL) {
        CHECK(phone[POD_LINK_USB].raw_len[0] == v->frame_len &&
              memcmp(phone[POD_LINK_USB].raw[0], v->frame, v->frame_len) == 0);
    }
    CHECK(last_level == POD_IDENT_FULL);
    advance(10);
    /* The EVT pod.modules: the box's node.modules text and each lent output's longest on; its
     * bytes are the vector's pod_modules. */
    size_t rl = 0;
    const uint8_t *raw = raw_evt(POD_LINK_USB, "pod", "modules", &rl);
    const proxy_frame_vector_t *ev = frame_vector("pod_modules");
    CHECK(raw != NULL && ev != NULL);
    if (raw != NULL && ev != NULL) {
        atalaia_proxy_msg_t a, b;
        CHECK(atalaia_proxy_msg_decode(ev->payload, ev->payload_len, &b));
        atalaia_proxy_msg_t m;
        CHECK(nth_evt(POD_LINK_USB, "pod", "modules", 0, &m));
        a = m;
        CHECK(strcmp(a.data_json, b.data_json) == 0);
    }

    /* The phone switches the module's siren.2: OUTPUT to the module, its relay on, the lease. */
    out_cmd("siren.2", "pulse", "{\"ms\":5000}", 1);
    advance(60);
    uint8_t bits = 0;
    module_sim_state(o4, clock_ms, &bits, NULL);
    CHECK(bits == 0x01 && o4->outputs_taken >= 1);
    for (int k = 0; k < 6; k++) {
        advance(400);
        phone_send_vector(POD_LINK_USB, "cmd_ping");
    }
    module_sim_state(o4, clock_ms, &bits, NULL);
    CHECK(bits == 0x01 && o4->leases >= 1);
    /* At most the pod's 20 s (the module's strobe: 120 s of its own). */
    out_cmd("strobe", "on", "{\"ms\":600000}", 2);
    int ch = outputs_find(&outs.out, "strobe");
    CHECK(ch >= 0 && outs.out.ch[ch].until_ms - outs.out.ch[ch].start_ms == 20000);

    /* The link goes: the output layer turns them off, the driver tells the module at once. */
    pod_set_link_up(&pod, POD_LINK_USB, false);
    advance(300);
    module_sim_state(o4, clock_ms, &bits, NULL);
    CHECK(bits == 0 && outs.link_offs == 1);

    /* The phone's app hangs with its link up: off after 1.5 s, the module with it. */
    pod_set_link_up(&pod, POD_LINK_USB, true);
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    advance(600);
    out_cmd("smoke", "pulse", "{\"ms\":10000}", 3);
    advance(100);
    module_sim_state(o4, clock_ms, &bits, NULL);
    CHECK(bits == 0x04);
    auto_ack = false;
    advance(POD_OUT_QUIET_MS + 300);
    module_sim_state(o4, clock_ms, &bits, NULL);
    CHECK(bits == 0 && outs.quiet_offs == 1);
    (void)t;

    /* Without --module-outputs (the build's default) the module's channels are not lent; the text
     * still lists them, as a box's node.modules does, and "withheld" names them, as a box's
     * node.outputs_disabled names a module's channels its admin has not enabled (PROPC-7). */
    setup_port(&cfg);
    plug("out4", 0x5C);
    start_port(false, 30);
    advance(10);
    CHECK(!pod_outputs_owns(&outs, "siren") && outs.out.count == 4);
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    atalaia_proxy_ident_t id;
    CHECK(atalaia_proxy_ident_decode(phone[POD_LINK_USB].payload[0], phone[POD_LINK_USB].len[0],
                                     &id) &&
          strstr(id.caps_json, "output") == NULL);
    advance(10);
    atalaia_proxy_msg_t m;
    CHECK(nth_evt(POD_LINK_USB, "pod", "modules", 0, &m) &&
          strcmp(m.data_json, "{\"modules\":\"5c:out4/1.0.0:siren,strobe,smoke,out.4\","
                              "\"max_on_s\":{},"
                              "\"withheld\":\"5c:out4/1.0.0:siren,strobe,smoke,out.4\"}") == 0);
    out_cmd("siren", "pulse", "{\"ms\":1000}", 1);
    CHECK(pod.count.cmd_unknown == 1);

    /* A long version, every part, two targets, a siren and an out4: IDENT drops the flags, the
     * hit sensors' channel and the version, then the outputs one at a time, the last first
     * (EXPI9-27): here none of the five fits, and the hit sensors do. */
    pod_caps_config_t full = full_config();
    setup_port(&full);
    add_output("siren", 33, 30);
    plug("target", 0x58);
    plug("target", 0x59);
    plug("out4", 0x5C);
    start_port(true, 30);
    advance(10);
    fw = "0.3.0-123-g0123456-dirt";
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    CHECK(atalaia_proxy_ident_decode(phone[POD_LINK_USB].payload[0], phone[POD_LINK_USB].len[0],
                                     &id));
    CHECK(last_level == POD_IDENT_TRIM && last_trim == 5 &&
          strstr(id.caps_json, "output") == NULL && strstr(id.caps_json, "\"hit.2\"") != NULL &&
          strstr(id.caps_json, "channel") == NULL);
    CHECK(!pod_outputs_owns(&outs, "siren") && !pod_outputs_owns(&outs, "out.4"));
    advance(10);
    CHECK(nth_evt(POD_LINK_USB, "pod", "modules", 0, &m) &&
          strcmp(m.data_json,
                 "{\"modules\":\"58:target/1.0.0:hit;59:target/1.0.0:hit.2\",\"max_on_s\":{},"
                 "\"withheld\":\"g33:servo:siren;5c:out4/1.0.0:siren.2,strobe,smoke,out.4\"}") ==
              0);
    CHECK(logged("told the phone its outputs not lent: g33:servo:siren;"
                 "5c:out4/1.0.0:siren.2,strobe,smoke,out.4"));
}

/* The EVT pod.modules' data, the last one on USB ("" for none). */
static const char *last_modules(void)
{
    static atalaia_proxy_msg_t m;
    if (!nth_evt(POD_LINK_USB, "pod", "modules", 0, &m)) return "";
    return m.data_json;
}

static void test_port_ident_trim(void)
{
    /* EXPI9-23, EXPI9-27: a pod with every part and an out4 module has room in IDENT for one of
     * the module's four channels: the first is lent, the last three left out (logged), off, never
     * switchable and not in pod.modules. The IDENT's bytes are the vector's. */
    pod_caps_config_t full = full_config();
    setup_port(&full);
    module_sim_t *o4 = plug("out4", 0x5C);
    start_port(true, 30);
    advance(10);
    fw = "0.8.0";
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    const proxy_frame_vector_t *v = frame_vector("pod_full_out4_trimmed");
    CHECK(v != NULL && phone[POD_LINK_USB].frames == 1);
    if (v != NULL) {
        CHECK(phone[POD_LINK_USB].raw_len[0] == v->frame_len &&
              memcmp(phone[POD_LINK_USB].raw[0], v->frame, v->frame_len) == 0);
    }
    CHECK(last_level == POD_IDENT_TRIM && last_trim == 3);
    CHECK(pod_outputs_owns(&outs, "siren") && !pod_outputs_owns(&outs, "strobe") &&
          !pod_outputs_owns(&outs, "smoke") && !pod_outputs_owns(&outs, "out.4"));
    CHECK(
        logged("sent with 3 output(s) left out") &&
        logged("IDENT has no room for 3 output(s), not lent (off, refused): strobe, smoke, out.4"));
    advance(10);
    /* pod.modules: the lent channel in the text, the three others as "withheld" (PROPC-6); the
     * data are the vector's pod_modules_withheld. */
    const proxy_frame_vector_t *wv = frame_vector("pod_modules_withheld");
    atalaia_proxy_msg_t want;
    CHECK(wv != NULL && atalaia_proxy_msg_decode(wv->payload, wv->payload_len, &want));
    CHECK(strcmp(last_modules(), want.data_json) == 0);
    CHECK(strcmp(last_modules(), "{\"modules\":\"5c:out4/1.0.0:siren\",\"max_on_s\":{\"siren\":30},"
                                 "\"withheld\":\"5c:out4/1.0.0:strobe,smoke,out.4\"}") == 0);

    /* Never switchable: the CMD names no capability, the output layer refuses it, the module's
     * relays stay open. */
    uint32_t unknown = pod.count.cmd_unknown;
    out_cmd("out.4", "on", "{\"ms\":5000}", 1);
    out_cmd("strobe", "pulse", "{\"ms\":5000}", 2);
    CHECK(pod.count.cmd_unknown == unknown + 2);
    CHECK(outputs_switch(&outs.out, "smoke", OUT_ACT_ON, 5000, 0, 0, OUT_SRC_FIELD) ==
          OUT_DISABLED);
    advance(60);
    uint8_t bits = 0;
    module_sim_state(o4, clock_ms, &bits, NULL);
    CHECK(bits == 0);
    /* The lent one switches. */
    out_cmd("siren", "on", "{\"ms\":20000}", 3);
    advance(60);
    module_sim_state(o4, clock_ms, &bits, NULL);
    CHECK(bits == 0x01);

    /* A target plugged in: its hit sensor takes the room, so the siren is left out too, and off
     * at once though its 20 s are not over. */
    plug("target", 0x58);
    for (int k = 0; k < 6; k++) {
        advance(400);
        phone_send_vector(POD_LINK_USB, "cmd_ping");
    }
    CHECK(ident_resends >= 1 && last_level == POD_IDENT_TRIM && last_trim == 4);
    CHECK(!pod_outputs_owns(&outs, "siren") &&
          logged("output siren was on: off, left out of IDENT"));
    module_sim_state(o4, clock_ms, &bits, NULL);
    CHECK(bits == 0);
    CHECK(strcmp(last_modules(), "{\"modules\":\"58:target/1.0.0:hit\",\"max_on_s\":{},"
                                 "\"withheld\":\"5c:out4/1.0.0:siren,strobe,smoke,out.4\"}") == 0);
    unknown = pod.count.cmd_unknown;
    out_cmd("siren", "on", "{\"ms\":5000}", 4);
    advance(60);
    module_sim_state(o4, clock_ms, &bits, NULL);
    CHECK(pod.count.cmd_unknown == unknown + 1 && bits == 0);

    /* The target unplugged: the room is back and the siren lent again (off). */
    plugged[0x58 - EXP_ADDR_FIRST] = false;
    for (int k = 0; k < 8; k++) {
        advance(400);
        phone_send_vector(POD_LINK_USB, "cmd_ping");
    }
    CHECK(last_level == POD_IDENT_TRIM && last_trim == 3 && pod_outputs_owns(&outs, "siren"));
    CHECK(strcmp(last_modules(), want.data_json) == 0);
    module_sim_state(o4, clock_ms, &bits, NULL);
    CHECK(bits == 0);

    /* The out4 unplugged: no output is fitted any more; the last EVT says so once, "withheld"
     * empty (a box that lost its last output tells node.outputs_disabled empty once, EXPL-21). */
    phone[POD_LINK_USB].frames = 0; /* room for the frames that follow */
    plugged[0x5C - EXP_ADDR_FIRST] = false;
    advance(EXP_LOST_AFTER * EXP_POLL_OUTPUT_MS + 500); /* a module with no input: polled less */
    CHECK(nth_evt(POD_LINK_USB, "pod", "module_lost", 0, &want) && outs.out.count == 0);
    /* The EVT that follows the loss says "withheld" empty; the one after the IDENT it brings
     * (a pod with no output fitted) no longer carries it. */
    atalaia_proxy_msg_t m;
    CHECK(nth_evt(POD_LINK_USB, "pod", "modules", 1, &m) &&
          strcmp(m.data_json, "{\"modules\":\"\",\"max_on_s\":{},\"withheld\":\"\"}") == 0);
    CHECK(strcmp(last_modules(), "{\"modules\":\"\",\"max_on_s\":{}}") == 0);
    int evts = count_evt(POD_LINK_USB, "pod", "modules");
    advance(2000);
    CHECK(count_evt(POD_LINK_USB, "pod", "modules") == evts);
}

static void test_port_withheld(void)
{
    /* PROPC-6: four buttons, the ring and the case leave IDENT room for an out4's four channels:
     * every one lent, "withheld" empty. A target plugged in takes the room of the last channel,
     * which pod.modules then names as withheld; unplugged, it is lent again and "withheld" is
     * empty again. */
    pod_caps_config_t cfg = full_config();
    cfg.keypad = cfg.nfc = cfg.audio = false;
    setup_port(&cfg);
    plug("out4", 0x5C);
    start_port(true, 30);
    advance(10);
    fw = "0.8.0";
    phone_send_vector(POD_LINK_USB, "cmd_ident");
    advance(10);
    CHECK(last_level == POD_IDENT_FULL && pod_outputs_owns(&outs, "out.4"));
    CHECK(strcmp(last_modules(), "{\"modules\":\"5c:out4/1.0.0:siren,strobe,smoke,out.4\","
                                 "\"max_on_s\":{\"siren\":30,\"strobe\":30,\"smoke\":30,"
                                 "\"out.4\":30},\"withheld\":\"\"}") == 0);
    char text[POD_PORT_TEXT_MAX + 1];
    CHECK(pod_port_withheld_text(&port, text, sizeof(text)) == 0 && text[0] == '\0');

    plug("target", 0x58);
    for (int k = 0; k < 6; k++) {
        advance(400);
        phone_send_vector(POD_LINK_USB, "cmd_ping");
    }
    CHECK(last_level == POD_IDENT_TRIM && last_trim == 1 && !pod_outputs_owns(&outs, "out.4"));
    CHECK(strcmp(last_modules(),
                 "{\"modules\":\"58:target/1.0.0:hit;5c:out4/1.0.0:siren,strobe,smoke\","
                 "\"max_on_s\":{\"siren\":30,\"strobe\":30,\"smoke\":30},"
                 "\"withheld\":\"5c:out4/1.0.0:out.4\"}") == 0);
    CHECK(pod_port_withheld_text(&port, text, sizeof(text)) == strlen("5c:out4/1.0.0:out.4") &&
          strcmp(text, "5c:out4/1.0.0:out.4") == 0);
    CHECK(logged("told the phone its outputs not lent: 5c:out4/1.0.0:out.4"));

    /* Lent again: "withheld" clears. */
    plugged[0x58 - EXP_ADDR_FIRST] = false;
    for (int k = 0; k < 8; k++) {
        advance(400);
        phone_send_vector(POD_LINK_USB, "cmd_ping");
    }
    CHECK(pod_outputs_owns(&outs, "out.4"));
    CHECK(strcmp(last_modules(), "{\"modules\":\"5c:out4/1.0.0:siren,strobe,smoke,out.4\","
                                 "\"max_on_s\":{\"siren\":30,\"strobe\":30,\"smoke\":30,"
                                 "\"out.4\":30},\"withheld\":\"\"}") == 0);

    /* A pod without outputs (a target alone) never adds "withheld" (a box without outputs sends
     * no node.outputs_disabled, EXPL-15): test_port_hits' EVTs. A simple output withheld is in
     * the box's form, "g33:servo:siren" (test_port_outputs). The text keeps whole entries within
     * 100 bytes: */
    setup_port(&cfg);
    for (int i = 0; i < EXP_MODULES_MAX; i++) plug("out4", (uint8_t)(EXP_ADDR_FIRST + i));
    start_port(false, 30);
    advance(10);
    /* Four out4 modules: the first two entries (85 bytes); the third would pass 100, so it is
     * left out whole. */
    CHECK(pod_port_withheld_text(&port, text, sizeof(text)) == 85);
    CHECK(strcmp(text, "58:out4/1.0.0:siren,strobe,smoke,out.4;"
                       "59:out4/1.0.0:siren.2,strobe.2,smoke.2,out.4.2") == 0);
}

void run_pod_tests(void)
{
    test_fw_version();
    test_ident();
    test_cmd();
    test_evt();
    test_radio();
    test_field_relay();
    test_update_relay();
    test_config_over_radio();
    test_caps_inputs();
    test_caps_commands();
    test_json();
    test_outputs_ident();
    test_outputs_boot_and_live();
    test_outputs_commands();
    test_outputs_link_loss();
    test_port_hits();
    test_port_outputs();
    test_port_ident_trim();
    test_port_withheld();
}
