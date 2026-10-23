/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I/O pod's side of the capability proxy protocol v1 (ADR-P3-2, ADR-P3-3,
 * protocol/capability-proxy.md): the frames between the pod and a phone on
 * two links, USB (the ESP32-S3's USB-Serial-JTAG CDC port) and Bluetooth LE
 * (the pod's GATT service, main/pod/pod_ble.c).
 *
 *   IDENT  answered to every RADIO_CMD IDENT, and sent when a BLE link is
 *          ready (connected, encrypted, Pod TX subscribed);
 *   EVT    a capability's event (main/pod/pod_caps.c), numbered by the pod,
 *          sent on every active link, sent again after 500 ms without an
 *          ACK, up to 3 times; after that the links are broken (inactive)
 *          until the phone speaks on them again;
 *   CMD    acknowledged on the link it came on, acted on once (the last 16
 *          seqs of each link are remembered; a new connection or a RADIO_CMD
 *          IDENT starts the list again, since the phone numbers from 0);
 *   RADIO_ the USB radio modem's own logic (main/modem/modem.c) with the
 *          frame types shifted by 3: AES-CCM, dedupe, the epoch window, the
 *          duty cycle and the channel rules are the modem's.
 *
 * The game key lives in RAM only, as on the modem, and is forgotten (CLEAR)
 * when the link that configured the radio goes away (decision PF5): a phone
 * that links again sends IDENT and CONFIGURE again.
 *
 * Plain C with injected I/O, no ESP-IDF: the same code runs on the pod, in
 * the host tests (test/test_pod.c) and in the host pod (test/pod_host).
 */
#ifndef ATALAIA_POD_H
#define ATALAIA_POD_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "atalaia/proxy.h"
#include "modem/modem.h"

typedef enum {
    POD_LINK_USB = 0,
    POD_LINK_BLE = 1,
    POD_LINK_COUNT = 2,
} pod_link_t;

#define POD_OUTBOX   16  /* EVTs waiting for their ACK */
#define POD_RETRY_MS 500 /* protocol/capability-proxy.md: resend after 500 ms ... */
#define POD_RETRIES  3   /* ... up to 3 times */
#define POD_SEEN     16  /* CMD seqs remembered per link */

typedef struct {
    /* Writes a whole frame on a link. Returns 0 on success. */
    int (*link_write)(void *ctx, pod_link_t link, const uint8_t *frame, size_t len);
    /* Monotonic milliseconds. */
    uint32_t (*now_ms)(void *ctx);
    /* A valid CMD, acted on once. Returns false if the pod has no such
     * capability or method (the CMD was acknowledged all the same). */
    bool (*command)(void *ctx, const atalaia_proxy_msg_t *cmd);
    /* The IDENT's fw_version, caps_json and battery; the pod fills has_radio
     * and protocol_version. compact: the first try did not fit in 256
     * bytes; leave out what is optional (the buttons' colours). */
    void (*ident)(void *ctx, atalaia_proxy_ident_t *out, bool compact);
    /* A link became active (may be NULL): the capabilities may report their
     * state again (an open case). */
    void (*link_active)(void *ctx, pod_link_t link);
    /* A log line (may be NULL). */
    void (*log)(void *ctx, const char *line);
    void *ctx;
} pod_io_t;

typedef struct {
    bool up;     /* the transport is there (USB host present, BLE link ready) */
    bool active; /* the phone is on it: frames go to it */
    modem_decoder_t dec;
    uint16_t seen[POD_SEEN];
    uint8_t seen_count;
    uint8_t seen_next;
} pod_link_state_t;

typedef struct {
    bool used;
    uint16_t seq;
    uint8_t tries; /* resends so far */
    uint32_t sent_ms;
    uint16_t len;
    uint8_t frame[MODEM_FRAME_MAX];
} pod_pending_t;

typedef struct {
    uint32_t evt_sent;     /* EVTs put on the links (first sending) */
    uint32_t evt_retries;  /* resends */
    uint32_t evt_acked;    /* ACKs that matched a waiting EVT */
    uint32_t evt_lost;     /* EVTs given up after 3 resends */
    uint32_t evt_dropped;  /* no active link, a full outbox, or too big */
    uint32_t cmds;         /* valid CMDs acted on */
    uint32_t cmd_repeats;  /* valid CMDs acknowledged again, not acted on */
    uint32_t cmd_unknown;  /* acted on, but no such capability or method */
    uint32_t bad_payloads; /* CMD or ACK payloads refused (not acknowledged) */
    uint32_t ignored;      /* frame types the pod does not take from a phone */
    uint32_t links_broken; /* links made inactive by an EVT nobody acknowledged */
    uint32_t radio_cleared;
} pod_counters_t;

typedef struct {
    pod_io_t io;
    pod_link_state_t links[POD_LINK_COUNT];
    modem_t radio;
    int radio_owner; /* the link that configured the radio, or -1 */
    int radio_link;  /* the link of the phone's last radio frame, or -1 */
    int replying;    /* the link of the frame being handled, or -1 */
    bool muted;      /* drop the modem's frames (an internal CLEAR) */
    uint16_t evt_seq;
    int8_t last_rssi; /* RSSI of the last packet heard; INT8_MIN for none */
    pod_pending_t outbox[POD_OUTBOX];
    pod_counters_t count;
} pod_t;

/*
 * IDENT's fw_version (1-23 printable bytes) from the image's version (up to 31): the version
 * itself when it fits; else without the trailing identifiers of its build metadata, one by
 * one (0.3.0-dev.412+g8560d54.dirty -> 0.3.0-dev.412+g8560d54), then without the metadata;
 * else cut (decision FV-5). "unknown" for an empty one.
 */
void pod_fw_version(const char *image_version, char out[ATALAIA_PROXY_TEXT_MAX + 1]);

/*
 * Prepares the pod. radio_io is the modem's I/O (its serial_write and
 * frame_out are replaced); radio_present says whether the SX1262 answered
 * at boot. Sends nothing.
 */
void pod_init(pod_t *p, const pod_io_t *io, const modem_io_t *radio_io,
              const atalaia_crypto_ops_t *crypto, const char *fw_version, bool radio_present,
              uint16_t epoch_window);

/*
 * The transport of a link came or went (USB host attached or detached, a
 * BLE link ready or lost). Going away makes the link inactive, drops its
 * half-received frame and, if it configured the radio, clears the radio.
 * A new connection forgets the link's CMD seqs.
 */
void pod_set_link_up(pod_t *p, pod_link_t link, bool up);

/* Makes a link active (the phone is listening on it). */
void pod_set_link_active(pod_t *p, pod_link_t link);

bool pod_link_active(const pod_t *p, pod_link_t link);

/* Bytes received on a link: complete frames are handled at once. */
void pod_feed(pod_t *p, pod_link_t link, const uint8_t *data, size_t len);

/* Sends an IDENT frame on a link. */
void pod_send_ident(pod_t *p, pod_link_t link);

/*
 * A capability's event, as an EVT on every active link (data_json: a JSON
 * object, "" or "{}" for none). Returns false if no link is active, the
 * outbox is full or the payload does not fit (counted as dropped).
 */
bool pod_event(pod_t *p, const char *cap_id, const char *event, const char *data_json);

/* Time passes: EVT resends, broken links. */
void pod_tick(pod_t *p);

/* EVTs still waiting for their ACK. */
size_t pod_pending(const pod_t *p);

/* The radio side (from the radio task): a packet heard, a TX outcome, a measurement. */
void pod_on_air_rx(pod_t *p, const uint8_t *pkt, size_t len, int8_t rssi, int8_t snr);
void pod_on_tx_result(pod_t *p, uint32_t tag, modem_tx_status_t status);
void pod_on_measure_result(pod_t *p, int rc, const noise_result_t *r);

/*
 * The Pod Status characteristic's 3 bytes (protocol/capability-proxy.md):
 * battery % (0xFF unknown: battery_pct < 0), RSSI of the last radio packet
 * (0x80 none), flags (bit 0 radio present, bit 1 radio configured, bit 2
 * USB host connected).
 */
void pod_status_bytes(const pod_t *p, int battery_pct, bool usb_host, uint8_t out[3]);

#endif /* ATALAIA_POD_H */
