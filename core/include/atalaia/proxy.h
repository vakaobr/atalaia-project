/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Capability proxy protocol v1 (ADR-P3-2, protocol/capability-proxy.md):
 * the payloads an I/O pod and a phone exchange. The frames around them
 * (0xA5 sync, type, length, CRC-16) are the USB modem's
 * (firmware/esp32/main/modem/modem_framing.h); the radio frames carry the
 * modem's payloads unchanged. Here: IDENT, EVT, CMD and ACK.
 *
 * EVT and CMD have the same layout (cap_id, event or method, data or args,
 * seq), so one struct serves both. Maps travel as JSON text in the structs,
 * like CMD params elsewhere in the core. The Python codec
 * (simulator/atalaia_sim/capability_proxy.py) checks the same vectors
 * (protocol/vectors/capability_proxy.yaml).
 */
#ifndef ATALAIA_PROXY_H
#define ATALAIA_PROXY_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define ATALAIA_PROXY_VERSION     1
#define ATALAIA_PROXY_PAYLOAD_MAX 256
#define ATALAIA_PROXY_TEXT_MAX    23 /* fw_version, cap_id, event, method (bytes) */
#define ATALAIA_PROXY_CAPS_MAX    16
#define ATALAIA_PROXY_JSON_MAX    512 /* a payload's maps as JSON, NUL included */

typedef enum {
    ATALAIA_PROXY_IDENT = 0x01,
    ATALAIA_PROXY_EVT = 0x02,
    ATALAIA_PROXY_CMD = 0x03,
    ATALAIA_PROXY_ACK = 0x04,
    ATALAIA_PROXY_RADIO_RX = 0x05,     /* the modem's RX */
    ATALAIA_PROXY_RADIO_TX = 0x06,     /* the modem's TX */
    ATALAIA_PROXY_RADIO_TX_ACK = 0x07, /* the modem's TX_ACK */
    ATALAIA_PROXY_RADIO_CMD = 0x08,    /* the modem's CMD; IDENT (7) is answered with IDENT */
    ATALAIA_PROXY_RADIO_STATUS = 0x09, /* the modem's STATUS */
    ATALAIA_PROXY_RADIO_ERROR = 0x0A,  /* the modem's ERROR */
    ATALAIA_PROXY_RADIO_NOISE = 0x0B,  /* the modem's NOISE, the answer to MEASURE (decision PF2) */
} atalaia_proxy_type_t;

/* The modem frame type a radio frame carries (proxy type - 3), or 0. */
uint8_t atalaia_proxy_modem_type(uint8_t proxy_type);

typedef struct {
    char fw_version[ATALAIA_PROXY_TEXT_MAX + 1];
    /* JSON array of capability descriptors: [{"id":"btn.red","type":"button"},...] */
    char caps_json[ATALAIA_PROXY_JSON_MAX];
    bool has_battery;
    uint8_t battery_pct; /* 0-100, when has_battery */
    bool has_radio;
    uint8_t protocol_version; /* 1 */
} atalaia_proxy_ident_t;

/* EVT (name = event, data) or CMD (name = method, args). */
typedef struct {
    char cap_id[ATALAIA_PROXY_TEXT_MAX + 1];
    char name[ATALAIA_PROXY_TEXT_MAX + 1];
    char data_json[ATALAIA_PROXY_JSON_MAX]; /* a JSON object; "" or "{}" for none */
    uint16_t seq;
} atalaia_proxy_msg_t;

/*
 * Encoders return the payload length, or 0 if a field is invalid or it
 * does not fit in cap (or in ATALAIA_PROXY_PAYLOAD_MAX). Decoders return
 * false for anything but a valid payload, and then leave *out zeroed.
 */
size_t atalaia_proxy_ident_encode(const atalaia_proxy_ident_t *in, uint8_t *buf, size_t cap);
bool atalaia_proxy_ident_decode(const uint8_t *buf, size_t len, atalaia_proxy_ident_t *out);

size_t atalaia_proxy_msg_encode(const atalaia_proxy_msg_t *in, uint8_t *buf, size_t cap);
bool atalaia_proxy_msg_decode(const uint8_t *buf, size_t len, atalaia_proxy_msg_t *out);

size_t atalaia_proxy_ack_encode(uint16_t seq, uint8_t *buf, size_t cap);
bool atalaia_proxy_ack_decode(const uint8_t *buf, size_t len, uint16_t *seq);

#endif /* ATALAIA_PROXY_H */
