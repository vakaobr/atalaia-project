/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I/O pod's Bluetooth LE GATT service (main/pod/pod_ble.c) with the
 * Bluetooth stack stubbed: the advertised service UUID and name, the link
 * that becomes ready only when connected, encrypted and subscribed, IDENT on
 * that moment, frames cut to the MTU (and joined again by the phone's
 * framing), a CMD written in two pieces reaching the hardware stub and its
 * ACK coming back, a button press on the hardware stub reaching the phone as
 * an EVT, a busy stack, Pod Status, unencrypted writes refused, and the
 * radio forgotten when the phone goes.
 *
 * Its own executable, so that `ctest -R ble_gatt_stub` runs it alone.
 */
#include <stdio.h>
#include <string.h>

#include "atalaia/proxy.h"
#include "modem/modem_framing.h"
#include "pod/pod.h"
#include "pod/pod_ble.h"
#include "pod/pod_caps.h"
#include "proxy_vectors.h"

static int failures, checks;

#define CHECK(cond)                                                                                \
    do {                                                                                           \
        checks++;                                                                                  \
        if (!(cond)) {                                                                             \
            fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);                        \
            failures++;                                                                            \
        }                                                                                          \
    } while (0)

/* ---- The stack stub: what the phone would receive ---------------------------------- */

#define NOTES 64

static int notes, status_notes;
static size_t note_len[NOTES];
static int busy_after = -1; /* the stack reports busy once this many notifications went */
static bool stack_fails;
static uint8_t last_status[3];
static modem_decoder_t phone_dec;
static int phone_frames;
static uint8_t phone_type[NOTES];
static uint8_t phone_payload[NOTES][MODEM_FRAME_PAYLOAD_MAX];
static size_t phone_len[NOTES];

static void phone_frame(void *ctx, uint8_t type, const uint8_t *payload, size_t len)
{
    (void)ctx;
    if (phone_frames >= NOTES) return;
    phone_type[phone_frames] = type;
    memcpy(phone_payload[phone_frames], payload, len);
    phone_len[phone_frames] = len;
    phone_frames++;
}

static int stub_notify(void *ctx, uint16_t conn, pod_ble_chr_t chr, const uint8_t *data, size_t len)
{
    (void)ctx;
    CHECK(conn == 7);
    if (stack_fails) return -1;
    if (chr == POD_BLE_STATUS) {
        CHECK(len == 3);
        memcpy(last_status, data, 3);
        status_notes++;
        return 0;
    }
    if (busy_after >= 0 && notes >= busy_after) return 1;
    if (notes < NOTES) note_len[notes] = len;
    notes++;
    /* The phone joins the notifications: the framing finds the frames. */
    modem_decoder_feed(&phone_dec, data, len, phone_frame, NULL);
    return 0;
}

/* ---- The hardware stub ------------------------------------------------------------------- */

static uint8_t buttons;
static int fills;
static uint8_t fill_rgb[3];

static int ok(void)
{
    return 0;
}
static void none(void)
{
}
static uint8_t poll(void)
{
    return buttons;
}
static void fill(uint8_t r, uint8_t g, uint8_t b)
{
    fills++;
    fill_rgb[0] = r;
    fill_rgb[1] = g;
    fill_rgb[2] = b;
}
static void set(int i, uint8_t r, uint8_t g, uint8_t b)
{
    (void)i;
    (void)r;
    (void)g;
    (void)b;
}
static void bright(uint8_t v)
{
    (void)v;
}

static const hal_button_ops_t button_ops = {ok, poll, none};
static const hal_led_ops_t led_ops = {ok, fill, set, none, bright, none};
static hal_t hal;

/* ---- The pod ------------------------------------------------------------------------------- */

static pod_t pod;
static pod_caps_t caps;
static pod_ble_t ble;
static uint32_t clock_ms;

static int link_write(void *ctx, pod_link_t link, const uint8_t *frame, size_t len)
{
    (void)ctx;
    CHECK(link == POD_LINK_BLE);
    return pod_ble_send_frame(&ble, frame, len);
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
static void ident(void *ctx, atalaia_proxy_ident_t *out, bool compact)
{
    (void)ctx;
    snprintf(out->fw_version, sizeof(out->fw_version), "0.3.0");
    pod_caps_descriptors(&caps, out->caps_json, sizeof(out->caps_json), !compact);
}
static bool emit(void *ctx, const char *cap, const char *event, const char *data)
{
    (void)ctx;
    return pod_event(&pod, cap, event, data);
}
static bool radio_send(void *ctx, const uint8_t *pkt, size_t len, uint32_t tag)
{
    (void)ctx;
    (void)pkt;
    (void)len;
    (void)tag;
    return true;
}

static void setup(bool encrypted)
{
    notes = status_notes = phone_frames = fills = 0;
    busy_after = -1;
    stack_fails = false;
    buttons = 0;
    clock_ms = 5000;
    modem_decoder_init(&phone_dec);
    memset(&hal, 0, sizeof(hal));
    hal.buttons = &button_ops;
    hal.leds = &led_ops;
    pod_caps_config_t cfg;
    memset(&cfg, 0, sizeof(cfg));
    cfg.button[0] = true;
    cfg.button[1] = true;
    cfg.leds = true;
    cfg.led_count = 24;
    pod_caps_init(&caps, &cfg, &hal, NULL);
    pod_io_t io = {link_write, now, command, ident, NULL, NULL, NULL, NULL};
    modem_io_t rio = {.radio_send = radio_send, .now_ms = now};
    pod_init(&pod, &io, &rio, &atalaia_crypto_test_stub, "test", true, 16);
    pod_ble_stack_t stack = {stub_notify, NULL};
    pod_ble_init(&ble, &pod, &stack, encrypted);
}

static const proxy_frame_vector_t *vector(const char *name)
{
    for (size_t i = 0; i < PROXY_FRAME_VECTOR_COUNT; i++) {
        if (strcmp(proxy_frame_vectors[i].name, name) == 0) return &proxy_frame_vectors[i];
    }
    return NULL;
}

/* ---- Tests --------------------------------------------------------------------------------- */

static void test_uuids_and_advertising(void)
{
    /* The UUIDs of protocol/capability-proxy.md, least significant byte first on air. */
    static const char *const text[4] = {POD_BLE_UUID_SERVICE, POD_BLE_UUID_TX, POD_BLE_UUID_RX,
                                        POD_BLE_UUID_STATUS};
    const uint8_t *bytes[4] = {pod_ble_uuid_service, pod_ble_uuid_tx, pod_ble_uuid_rx,
                               pod_ble_uuid_status};
    CHECK(strcmp(POD_BLE_UUID_SERVICE, "4174616c-6169-6100-0000-000000000000") == 0);
    CHECK(strcmp(POD_BLE_UUID_TX, "4174616c-6169-6100-0000-000000000001") == 0);
    CHECK(strcmp(POD_BLE_UUID_RX, "4174616c-6169-6100-0000-000000000002") == 0);
    CHECK(strcmp(POD_BLE_UUID_STATUS, "4174616c-6169-6100-0000-000000000003") == 0);
    for (int u = 0; u < 4; u++) {
        uint8_t be[16];
        int n = 0;
        for (const char *p = text[u]; *p && n < 16; p++) {
            if (*p == '-') continue;
            unsigned v;
            sscanf(p, "%2x", &v);
            be[n++] = (uint8_t)v;
            p++;
        }
        CHECK(n == 16);
        for (int i = 0; i < 16; i++) CHECK(bytes[u][i] == be[15 - i]);
    }
    /* "Atalaia" in ASCII starts the UUID (the last bytes on air). */
    for (int i = 0; i < 7; i++) CHECK(pod_ble_uuid_service[15 - i] == (uint8_t) "Atalaia"[i]);

    uint8_t adv[31];
    size_t n = pod_ble_adv_data(adv, sizeof(adv));
    static const uint8_t flags[3] = {0x02, 0x01, 0x06};
    CHECK(n == 21 && memcmp(adv, flags, 3) == 0 && adv[3] == 17 && adv[4] == 0x07);
    CHECK(memcmp(adv + 5, pod_ble_uuid_service, 16) == 0);
    CHECK(pod_ble_adv_data(adv, 20) == 0);

    const uint8_t addr[6] = {0xef, 0xbe, 0xad, 0xde, 0x34, 0x12}; /* 12:34:DE:AD:BE:EF */
    char name[POD_BLE_NAME_SIZE];
    pod_ble_device_name(addr, name);
    CHECK(strcmp(name, "atalaia-pod-BEEF") == 0);
    n = pod_ble_scan_response(name, adv, sizeof(adv));
    CHECK(n == 18 && adv[0] == 17 && adv[1] == 0x09 && memcmp(adv + 2, name, 16) == 0);
    CHECK(pod_ble_scan_response(name, adv, 10) == 0);
}

static void test_ready_and_ident(void)
{
    setup(true);
    pod_ble_on_connect(&ble, 7);
    pod_ble_on_mtu(&ble, 247);
    pod_ble_on_subscribe(&ble, POD_BLE_TX, true);
    /* Connected and subscribed, but not encrypted yet: nothing goes out. */
    CHECK(!ble.ready && notes == 0 && !pod_link_active(&pod, POD_LINK_BLE));
    /* A write before the link is encrypted is refused (the stack refuses it too). */
    const proxy_frame_vector_t *v = vector("cmd_ident");
    pod_ble_on_write(&ble, v->frame, v->frame_len);
    CHECK(ble.count.writes_refused == 1 && notes == 0);
    pod_ble_on_encryption(&ble, true);
    /* Ready: the pod sends its IDENT unasked, and the link is active. */
    CHECK(ble.ready && pod_link_active(&pod, POD_LINK_BLE));
    CHECK(phone_frames == 1 && phone_type[0] == ATALAIA_PROXY_IDENT);
    atalaia_proxy_ident_t id;
    CHECK(atalaia_proxy_ident_decode(phone_payload[0], phone_len[0], &id));
    CHECK(strstr(id.caps_json, "\"btn.2\"") != NULL && id.has_radio);
    /* The IDENT is longer than 20 bytes: in one 244-byte notification at MTU 247. */
    CHECK(notes == 1 && note_len[0] == phone_len[0] + MODEM_FRAME_OVERHEAD);
    /* The phone asks again: IDENT again. */
    pod_ble_on_write(&ble, v->frame, v->frame_len);
    CHECK(phone_frames == 2 && phone_type[1] == ATALAIA_PROXY_IDENT);

    /* Without encryption required (a bench build), subscribing is enough. */
    setup(false);
    pod_ble_on_connect(&ble, 7);
    pod_ble_on_subscribe(&ble, POD_BLE_TX, true);
    CHECK(ble.ready && phone_frames == 1);
}

static void test_mtu_pieces(void)
{
    setup(true);
    pod_ble_on_connect(&ble, 7);
    /* No MTU exchange: 23 bytes, so 20 per notification. */
    pod_ble_on_encryption(&ble, true);
    pod_ble_on_subscribe(&ble, POD_BLE_TX, true);
    CHECK(phone_frames == 1 && phone_type[0] == ATALAIA_PROXY_IDENT);
    size_t frame_len = phone_len[0] + MODEM_FRAME_OVERHEAD;
    CHECK(notes == (int)((frame_len + 19) / 20));
    for (int i = 0; i + 1 < notes; i++) CHECK(note_len[i] == 20);

    /* The stack is busy after 2 pieces: the rest waits for the next flush. */
    notes = 0;
    phone_frames = 0;
    busy_after = 2;
    pod_send_ident(&pod, POD_LINK_BLE);
    CHECK(notes == 2 && phone_frames == 0 && ble.queued > 0);
    busy_after = -1;
    pod_ble_flush(&ble);
    CHECK(phone_frames == 1 && ble.queued == 0);

    /* A failing stack drops what waits; the protocol's resends repair it. */
    stack_fails = true;
    pod_send_ident(&pod, POD_LINK_BLE);
    CHECK(ble.queued == 0 && ble.count.frames_dropped == 1);
    stack_fails = false;

    /* More than the queue holds is dropped, not cut. */
    busy_after = 0;
    notes = 0;
    int sent = 0;
    for (int i = 0; i < 40; i++)
        sent += pod_ble_send_frame(&ble, vector("cmd_configure")->frame,
                                   vector("cmd_configure")->frame_len) == 0;
    CHECK(sent == (int)(POD_BLE_QUEUE / vector("cmd_configure")->frame_len));
    CHECK(ble.queued == (size_t)sent * vector("cmd_configure")->frame_len);
}

static void test_cmd_and_evt(void)
{
    setup(true);
    pod_ble_on_connect(&ble, 7);
    pod_ble_on_mtu(&ble, 247);
    pod_ble_on_encryption(&ble, true);
    pod_ble_on_subscribe(&ble, POD_BLE_TX, true);
    phone_frames = 0;

    /* A CMD written in two pieces (the phone cuts its writes to the MTU too). */
    const proxy_frame_vector_t *v = vector("ring_fill");
    pod_ble_on_write(&ble, v->frame, 10);
    CHECK(fills == 0 && phone_frames == 0);
    pod_ble_on_write(&ble, v->frame + 10, v->frame_len - 10);
    CHECK(fills == 1 && fill_rgb[0] == 255 && fill_rgb[1] == 0 && fill_rgb[2] == 0);
    CHECK(phone_frames == 1 && phone_type[0] == ATALAIA_PROXY_ACK);
    uint16_t seq = 0;
    CHECK(atalaia_proxy_ack_decode(phone_payload[0], phone_len[0], &seq) && seq == 1);

    /* A press on the hardware stub reaches the phone as an EVT. */
    buttons = 0x02;
    pod_caps_poll(&caps, clock_ms += 10, -1, emit, NULL);
    CHECK(phone_frames == 2 && phone_type[1] == ATALAIA_PROXY_EVT);
    atalaia_proxy_msg_t m;
    CHECK(atalaia_proxy_msg_decode(phone_payload[1], phone_len[1], &m));
    CHECK(strcmp(m.cap_id, "btn.2") == 0 && strcmp(m.name, "press") == 0);
    /* Its ACK, written by the phone, clears it. */
    uint8_t ack[2], frame[8];
    atalaia_proxy_ack_encode(m.seq, ack, 2);
    size_t n = modem_frame_encode(ATALAIA_PROXY_ACK, ack, 2, frame, sizeof(frame));
    pod_ble_on_write(&ble, frame, n);
    CHECK(pod_pending(&pod) == 0);

    /* The radio, configured over Bluetooth, is forgotten when the phone goes. */
    v = vector("cmd_configure");
    pod_ble_on_write(&ble, v->frame, v->frame_len);
    CHECK(pod.radio.configured && phone_type[phone_frames - 1] == ATALAIA_PROXY_RADIO_STATUS);
    pod_ble_on_disconnect(&ble);
    CHECK(!ble.ready && !pod_link_active(&pod, POD_LINK_BLE) && !pod.radio.configured);
    /* Writes after the phone left go nowhere. */
    int before = phone_frames;
    pod_ble_on_write(&ble, vector("cmd_ident")->frame, vector("cmd_ident")->frame_len);
    CHECK(phone_frames == before && ble.count.connections == 1);
    /* A new connection starts afresh: the phone's CMD seqs begin again. */
    pod_ble_on_connect(&ble, 7);
    pod_ble_on_encryption(&ble, true);
    pod_ble_on_subscribe(&ble, POD_BLE_TX, true);
    v = vector("ring_fill");
    pod_ble_on_write(&ble, v->frame, v->frame_len);
    CHECK(fills == 2);
}

static void test_status(void)
{
    setup(true);
    uint8_t s[3] = {0xFF, 0x80, 0x01};
    pod_ble_set_status(&ble, s);
    CHECK(status_notes == 0); /* nobody connected */
    pod_ble_on_connect(&ble, 7);
    pod_ble_on_encryption(&ble, true);
    pod_ble_on_subscribe(&ble, POD_BLE_TX, true);
    pod_ble_on_subscribe(&ble, POD_BLE_STATUS, true);
    CHECK(status_notes == 1 && memcmp(last_status, s, 3) == 0);
    pod_ble_set_status(&ble, s); /* unchanged: not notified again */
    CHECK(status_notes == 1);
    pod_status_bytes(&pod, 64, true, s);
    pod_ble_set_status(&ble, s);
    CHECK(status_notes == 2 && last_status[0] == 64 && last_status[2] == 0x05);
}

int main(void)
{
    test_uuids_and_advertising();
    test_ready_and_ident();
    test_mtu_pieces();
    test_cmd_and_evt();
    test_status();
    if (failures) {
        fprintf(stderr, "ble_gatt_stub: %d of %d check(s) failed\n", failures, checks);
        return 1;
    }
    printf("ble_gatt_stub: all %d checks passed\n", checks);
    return 0;
}
