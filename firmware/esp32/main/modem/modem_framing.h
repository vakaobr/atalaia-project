/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * USB radio modem framing (ADR-P2-4, ADR-P2-5; specified in
 * protocol/usb-modem.md).
 *
 * Every frame on the serial link is:
 *
 *   0xA5 | type (1) | length (2, big-endian) | payload (0-256) | CRC-16 (2, big-endian)
 *
 * The type, length and payload are the ADR-P2-4 frame. The sync byte and
 * the CRC-16/CCITT-FALSE trailer (over type, length and payload) let the
 * receiver find frame boundaries again after junk on the line: the ROM
 * boot messages, a port opened mid-frame, or a dropped byte. The decoder
 * drops bytes until a frame with a valid CRC starts at the sync byte.
 *
 * Plain C, no ESP-IDF dependency: the same code runs on the modem, in the
 * host tests and in the host modem used by the controller's tests.
 */
#ifndef ATALAIA_MODEM_FRAMING_H
#define ATALAIA_MODEM_FRAMING_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define MODEM_SYNC              0xA5
#define MODEM_FRAME_PAYLOAD_MAX 256
#define MODEM_FRAME_HEAD        4 /* sync + type + length */
#define MODEM_FRAME_CRC         2
#define MODEM_FRAME_OVERHEAD    (MODEM_FRAME_HEAD + MODEM_FRAME_CRC)
#define MODEM_FRAME_MAX         (MODEM_FRAME_OVERHEAD + MODEM_FRAME_PAYLOAD_MAX)
#define MODEM_PROTOCOL_VERSION  1

typedef enum {
    MODEM_FRAME_IDENT = 0x01,  /* modem -> host: JSON identity */
    MODEM_FRAME_RX = 0x02,     /* modem -> host: received, decrypted packet */
    MODEM_FRAME_TX = 0x03,     /* host -> modem: packet to encrypt and send */
    MODEM_FRAME_TX_ACK = 0x04, /* modem -> host: result of a TX frame */
    MODEM_FRAME_CMD = 0x05,    /* host -> modem: command */
    MODEM_FRAME_STATUS = 0x06, /* modem -> host: JSON status (reply to every CMD) */
    MODEM_FRAME_ERROR = 0x07,  /* modem -> host: error code + message */
    MODEM_FRAME_NOISE = 0x08,  /* modem -> host: result of a MEASURE command */
    /* Field frames (protocol/field-frames.md): sealed by the controller with the field join
     * key's derived key, which the modem never holds; it only puts them on air and back. */
    MODEM_FRAME_FIELD_TX = 0x09,  /* host -> modem: id (u16) + a whole field frame to send */
    MODEM_FRAME_FIELD_RX = 0x0A,  /* modem -> host: a field frame heard + rssi + snr */
    MODEM_FRAME_FIELD_ACK = 0x0B, /* modem -> host: id (u16) + status, the outcome of a FIELD_TX */
} modem_frame_type_t;

/* CMD opcodes (first payload byte of a CMD frame). */
typedef enum {
    MODEM_CMD_PING = 0x01,           /* [token u32]: reply STATUS with the token */
    MODEM_CMD_CONFIGURE = 0x02,      /* game_id u16, node_id u16, epoch u16, max_hops u8,
                                        channel_hz u32, key[16] */
    MODEM_CMD_SET_CHANNEL = 0x03,    /* channel_hz u32 */
    MODEM_CMD_STATUS = 0x04,         /* reply STATUS */
    MODEM_CMD_SET_PEER_EPOCH = 0x05, /* n x (source u16, epoch u16) */
    MODEM_CMD_CLEAR = 0x06,          /* forget the key and the game */
    MODEM_CMD_IDENT = 0x07,          /* reply IDENT */
    MODEM_CMD_MEASURE = 0x08,        /* channel_hz u32, dwell_ms u16, flags u8 (bit 0: CAD);
                                        reply NOISE when done */
} modem_cmd_t;

/* Payload length of MODEM_CMD_MEASURE, opcode included. */
#define MODEM_MEASURE_LEN 8
#define MODEM_MEASURE_CAD 0x01

/* Payload length of MODEM_CMD_CONFIGURE, opcode included. */
#define MODEM_CONFIGURE_LEN 28

/* TX_ACK status codes. 0-2 are ADR-P2-4's; the others are additions. */
typedef enum {
    MODEM_TX_OK = 0,
    MODEM_TX_DUTY_CYCLE = 1,     /* duty-cycle budget exhausted; not sent */
    MODEM_TX_TIMEOUT = 2,        /* radio error or TX timeout */
    MODEM_TX_NOT_CONFIGURED = 3, /* no game key yet */
    MODEM_TX_INVALID = 4,        /* bad header, wrong game or source, payload too long */
    MODEM_TX_NONCE_REUSE = 5,    /* (epoch, seq) not above the last one sent: refused */
    MODEM_TX_QUEUE_FULL = 6,     /* radio TX queue full */
    MODEM_TX_NO_RADIO = 7,       /* no radio chip found at boot */
    MODEM_TX_BUSY = 8,           /* FIELD_TX while a MEASURE runs */
} modem_tx_status_t;

/* ERROR frame codes. */
typedef enum {
    MODEM_ERR_BAD_FRAME = 1,      /* valid CRC but malformed content */
    MODEM_ERR_UNKNOWN_TYPE = 2,   /* frame type the modem does not accept */
    MODEM_ERR_UNKNOWN_CMD = 3,    /* unknown CMD opcode */
    MODEM_ERR_NOT_CONFIGURED = 4, /* needs CONFIGURE first */
    MODEM_ERR_RADIO = 5,          /* radio missing or refused the setting */
    MODEM_ERR_BAD_PARAMS = 6,     /* parameters out of range */
    MODEM_ERR_BUSY = 7,           /* MEASURE: a game is configured or a measurement runs */
    MODEM_ERR_NO_RADIO = 8,       /* no radio chip, so nothing to measure with */
} modem_error_t;

/* CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflection, no xorout.
 * Check value: crc("123456789") == 0x29B1. */
uint16_t modem_crc16(const uint8_t *data, size_t len);

/*
 * Encodes one frame into out. Returns the frame length, or 0 if the
 * payload is longer than MODEM_FRAME_PAYLOAD_MAX or out is too small.
 */
size_t modem_frame_encode(uint8_t type, const uint8_t *payload, size_t len, uint8_t *out,
                          size_t cap);

/* Called once per complete, CRC-valid frame. payload is valid during the call only. */
typedef void (*modem_frame_cb)(void *ctx, uint8_t type, const uint8_t *payload, size_t len);

typedef struct {
    uint8_t raw[MODEM_FRAME_MAX];
    size_t raw_len;
    uint32_t frames;        /* valid frames delivered */
    uint32_t crc_errors;    /* frames dropped for a bad CRC */
    uint32_t length_errors; /* sync bytes followed by an impossible length */
    uint32_t dropped_bytes; /* bytes skipped while looking for a frame */
} modem_decoder_t;

void modem_decoder_init(modem_decoder_t *d);

/* Feeds bytes from the serial link; calls cb for every complete frame. */
void modem_decoder_feed(modem_decoder_t *d, const uint8_t *data, size_t len, modem_frame_cb cb,
                        void *ctx);

#endif /* ATALAIA_MODEM_FRAMING_H */
