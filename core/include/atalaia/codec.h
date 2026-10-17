/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Events on the wire: the CBOR payload of a Skirmesh-RF EVENT message.
 *
 * An event travels as a CBOR map with the integer keys of
 * protocol/schema/events.yaml. Standard event types travel as their id and
 * custom ones by name. The event's data, which the core handles as a JSON
 * object, becomes a CBOR map in which standard field names are replaced by
 * their integer keys. protocol/README.md describes the format and limits.
 *
 * Neither function allocates or keeps state, so both are safe to call from
 * any task. Number formatting assumes the C locale.
 */
#ifndef ATALAIA_CODEC_H
#define ATALAIA_CODEC_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "atalaia/event.h"

/* Largest payload, and largest data JSON, either function handles. */
#define ATALAIA_CODEC_MAX_BYTES 65535u
/* Arrays and objects nested in event data, as in the core's JSON. */
#define ATALAIA_CODEC_MAX_DEPTH 16
/* Keys in the data objects open at once (an object and its parents). */
#define ATALAIA_CODEC_MAX_KEYS 128

/*
 * Encodes ev and its data (a JSON object, or NULL for none) into buf.
 * Returns the number of bytes written, or 0 if the event or its data is
 * invalid or does not fit in cap bytes; *error (if error is not NULL) then
 * says why.
 */
size_t atalaia_event_encode(const atalaia_event_t *ev, const char *data_json,
                            uint8_t *buf, size_t cap, const char **error);

/*
 * Decodes a payload into ev, and its data into data_json as a compact JSON
 * object (data_cap bytes including the terminating NUL; "{}" if the event
 * has no data). Returns false if the payload is not a valid event or the
 * data does not fit; *error (if error is not NULL) then says why.
 */
bool atalaia_event_decode(const uint8_t *buf, size_t len, atalaia_event_t *ev,
                          char *data_json, size_t data_cap, const char **error);

#endif /* ATALAIA_CODEC_H */
