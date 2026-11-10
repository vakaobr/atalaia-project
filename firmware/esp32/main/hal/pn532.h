/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * The PN532 NFC reader's host side over I2C, from the public PN532 User Manual (NXP UM0701-02):
 * the frames (section 6.2.1), the I2C status byte (6.2.4) and the commands the box uses
 * (SAMConfiguration 7.2.10, RFConfiguration 7.3.1, InListPassiveTarget 7.3.5, InDataExchange
 * 7.3.8, InCommunicateThru 7.3.9), with the NFC Forum Type 2 tag commands of the NTAG213/215/216
 * (NXP datasheet: READ 0x30, WRITE 0xA2, GET_VERSION 0x60) carried inside them.
 *
 * Platform-free so the host tests check every byte against a fake PN532
 * (test/test_pn532.c): the bus is three callbacks (pn532_io_t), which hal/esp/hal_esp_nfc.c
 * gives the ESP32's shared I2C bus.
 */
#ifndef ATALAIA_PN532_H
#define ATALAIA_PN532_H

#include "hal_nfc.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define PN532_I2C_ADDR                0x24
#define PN532_READY_BIT               0x01 /* bit 0 of the status byte every I2C read starts with */
#define PN532_TFI_HOST                0xD4 /* host to PN532 */
#define PN532_TFI_PN532               0xD5 /* PN532 to host */
#define PN532_TFI_ERROR               0x7F /* the application level error frame */
#define PN532_CMD_SAMCONFIGURATION    0x14
#define PN532_CMD_RFCONFIGURATION     0x32
#define PN532_CMD_INDATAEXCHANGE      0x40
#define PN532_CMD_INCOMMUNICATETHRU   0x42
#define PN532_CMD_INLISTPASSIVETARGET 0x4A
#define T2_CMD_READ                   0x30 /* 16 bytes: 4 pages from the one named */
#define T2_CMD_WRITE                  0xA2 /* one 4-byte page */
#define T2_CMD_GET_VERSION            0x60 /* 8 bytes: vendor, type, ..., storage size */
#define PN532_TIMEOUT_MS              100  /* the wait for the ACK, and for the response */
#define PN532_FRAME_MAX               64   /* the longest frame the box sends or reads */

/* Errors (negative); a successful exchange returns the response's length. */
#define PN532_ERR_IO          (-1)  /* the bus failed */
#define PN532_ERR_TIMEOUT     (-2)  /* the status byte never said ready */
#define PN532_ERR_NO_ACK      (-3)  /* the answer to a command was not the ACK frame */
#define PN532_ERR_FRAME       (-4)  /* not a normal information frame from the PN532 */
#define PN532_ERR_CHECKSUM    (-5)  /* LCS or DCS wrong */
#define PN532_ERR_ERROR_FRAME (-6)  /* the PN532's error frame (a syntax error) */
#define PN532_ERR_LENGTH      (-7)  /* longer than the read, or than the caller's buffer */
#define PN532_ERR_CODE        (-8)  /* the response is not to the command sent */
#define PN532_ERR_ARG         (-9)  /* a command too long for a frame */
#define PN532_ERR_STATUS      (-10) /* InDataExchange / InCommunicateThru: the tag failed */

typedef struct {
    void *ctx;
    /* One I2C write of the whole buffer. 0 on success. */
    int (*write)(void *ctx, const uint8_t *data, size_t len);
    /* One I2C read of len bytes; the first is the status byte. quiet: the ready poll, whose
     * NACKs while the chip is busy say nothing about the bus. 0 on success. */
    int (*read)(void *ctx, uint8_t *data, size_t len, bool quiet);
    void (*delay_ms)(void *ctx, unsigned ms);
} pn532_io_t;

typedef struct {
    pn532_io_t io;
    bool have_target; /* the last poll found a tag (target 1) */
} pn532_t;

/*
 * A normal information frame (UM0701-02 6.2.1.1) for the command bytes cmd (the command code
 * and its parameters): 00 00 FF LEN LCS D4 cmd... DCS 00, with LEN = 1 + len, LEN + LCS = 0 and
 * D4 + cmd... + DCS = 0 (mod 256). Returns its length, or 0 if it does not fit in cap.
 */
size_t pn532_build_frame(const uint8_t *cmd, size_t len, uint8_t *out, size_t cap);

/* True if rd (an I2C read: the status byte, then the frame) holds the ACK frame 00 00 FF 00 FF 00.
 */
bool pn532_is_ack(const uint8_t *rd, size_t len);

/*
 * The response frame in rd (an I2C read of len bytes: the status byte, then 00 00 FF LEN LCS D5
 * data... DCS 00): copies data (the response code, the command code + 1, and what follows) into
 * resp and returns its length, or a PN532_ERR_*.
 */
int pn532_parse_response(const uint8_t *rd, size_t len, uint8_t *resp, size_t cap);

/*
 * One command: the frame, the ACK, the response (each after the status byte says ready, at most
 * PN532_TIMEOUT_MS). Copies the response from its code on into resp and returns its length, or
 * a PN532_ERR_*. The response code must be the command's + 1.
 */
int pn532_transceive(pn532_t *p, const uint8_t *cmd, size_t len, uint8_t *resp, size_t cap);

/* SAMConfiguration (normal mode) and RFConfiguration MaxRetries (see pn532.c). 0, or an error. */
int pn532_configure(pn532_t *p);

/* InListPassiveTarget: one ISO 14443A tag at 106 kbps. True with tag's UID if one answered. */
bool pn532_poll(pn532_t *p, hal_nfc_tag_t *tag);

/* hal_nfc_ops_t.read_user_memory on the polled tag: pages from 4, until the NDEF message is whole.
 */
int pn532_read_user_memory(pn532_t *p, uint8_t *buf, size_t cap);

/* The Type 2 tag commands on the polled tag. 0, or an error. */
int pn532_t2_read(pn532_t *p, uint8_t page, uint8_t out[16]);
int pn532_t2_write(pn532_t *p, uint8_t page, const uint8_t data[4]);
int pn532_t2_get_version(pn532_t *p, uint8_t out[8]);

/* True once the TLVs in m (a Type 2 tag's memory from page 4) hold a whole NDEF message, or the
 * terminator TLV. */
bool t2_ndef_complete(const uint8_t *m, size_t len);

#endif /* ATALAIA_PN532_H */
