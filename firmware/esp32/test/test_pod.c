/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I/O pod's proxy (main/pod/pod.c) and capabilities (main/pod/pod_caps.c)
 * with a recording hardware abstraction and an in-memory phone on each link:
 * IDENT, CMD with its ACK and once-only action, EVT with its resends and the
 * broken link, the radio passthrough with the modem's logic (types 3 up), the
 * radio cleared when its link goes, and every capability's events and
 * commands. The frames come from protocol/vectors/capability_proxy.yaml where
 * a vector exists. Crypto: the core's test stub (the real AES-CCM: the host
 * pod, test/pod_host, in the app's and the controller's tests).
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
#include "proxy_vectors.h"

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
static bool command(void *ctx, const atalaia_proxy_msg_t *m)
{
    (void)ctx;
    return pod_caps_command(&caps, m);
}
static const char *fw = "0.3.0";
static int compact_idents;

static void ident(void *ctx, atalaia_proxy_ident_t *out, bool compact)
{
    (void)ctx;
    snprintf(out->fw_version, sizeof(out->fw_version), "%s", fw);
    pod_caps_descriptors(&caps, out->caps_json, sizeof(out->caps_json), !compact);
    compact_idents += compact;
    out->has_battery = true;
    out->battery_pct = 87;
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
    radio_sends = measures = link_actives = compact_idents = 0;
    fw = "0.3.0";
    clock_ms = 1000;
    memset(&hal, 0, sizeof(hal));
    hal.buttons = &button_ops;
    hal.keypad = &keypad_ops;
    hal.nfc = &nfc_ops;
    hal.leds = &led_ops;
    pod_audio_t audio = {tone, stop, volume, NULL};
    pod_caps_init(&caps, cfg, &hal, &audio);
    pod_io_t io = {link_write, now, command, ident, link_active, NULL, NULL};
    modem_io_t rio = {
        .radio_send = radio_send,
        .set_channel = set_channel,
        .duty_cycle_remaining_ms = duty,
        .now_ms = now,
        .measure_start = measure_start,
    };
    pod_init(&pod, &io, &rio, &atalaia_crypto_test_stub, "test", radio, 16);
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

static void advance(uint32_t ms)
{
    while (ms > 0) {
        uint32_t step = ms < 10 ? ms : 10;
        clock_ms += step;
        ms -= step;
        pod_caps_poll(&caps, clock_ms, -1, emit, NULL);
        pod_tick(&pod);
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

void run_pod_tests(void)
{
    test_fw_version();
    test_ident();
    test_cmd();
    test_evt();
    test_radio();
    test_field_relay();
    test_update_relay();
    test_caps_inputs();
    test_caps_commands();
    test_json();
}
