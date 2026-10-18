/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Capability proxy payloads (atalaia/proxy.h, protocol/capability-proxy.md).
 */
#include "atalaia/proxy.h"

#include <stdio.h>
#include <string.h>

#include "atalaia/codec.h"
#include "cbor_int.h"

#define KEY_UNKNOWN_FIRST 6
#define KEY_UNKNOWN_LAST  23
#define CBOR_FALSE        20
#define CBOR_TRUE         21

uint8_t atalaia_proxy_modem_type(uint8_t proxy_type)
{
    return proxy_type >= ATALAIA_PROXY_RADIO_RX && proxy_type <= ATALAIA_PROXY_RADIO_ERROR
               ? (uint8_t)(proxy_type - 3)
               : 0;
}

/* cap_id, event, method: 1-23 bytes of a-z 0-9 . _ - */
static bool name_ok(const char *s)
{
    size_t n = 0;
    for (; s[n]; n++) {
        char c = s[n];
        if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '.' || c == '_' ||
              c == '-')) {
            return false;
        }
    }
    return n >= 1 && n <= ATALAIA_PROXY_TEXT_MAX;
}

/* fw_version: 1-23 printable ASCII bytes. */
static bool printable_ok(const char *s)
{
    size_t n = 0;
    for (; s[n]; n++) {
        if ((unsigned char)s[n] < 0x20 || (unsigned char)s[n] > 0x7E) return false;
    }
    return n >= 1 && n <= ATALAIA_PROXY_TEXT_MAX;
}

static void put_bool(mc_writer_t *w, bool v)
{
    mc_put_head(w, CBOR_MAJOR_SIMPLE, v ? CBOR_TRUE : CBOR_FALSE);
}

static bool read_bool(mc_reader_t *r, bool *out)
{
    unsigned major;
    uint64_t v;
    if (!mc_read_head(r, &major, &v) || major != CBOR_MAJOR_SIMPLE ||
        (v != CBOR_TRUE && v != CBOR_FALSE)) {
        return false;
    }
    *out = v == CBOR_TRUE;
    return true;
}

/* A capability descriptor: a map whose "id" and "type" are non-empty text. */
static bool descriptor_ok(const uint8_t *p, size_t len)
{
    mc_reader_t r;
    mc_init_reader(&r, p, len);
    uint64_t count;
    if (!mc_read_map(&r, &count)) return false;
    bool id = false, type = false;
    for (uint64_t i = 0; i < count; i++) {
        char key[8];
        size_t klen;
        unsigned major;
        uint64_t v;
        const uint8_t *at = r.p;
        if (!mc_read_head(&r, &major, &v) || major != CBOR_MAJOR_TEXT) return false;
        r.p = at;
        bool short_key = v < sizeof(key);
        if (short_key) {
            if (!mc_read_text(&r, key, sizeof(key), &klen)) return false;
        } else if (!mc_skip_value(&r)) {
            return false;
        }
        bool want = short_key && (strcmp(key, "id") == 0 || strcmp(key, "type") == 0);
        if (want) {
            at = r.p;
            if (!mc_read_head(&r, &major, &v) || major != CBOR_MAJOR_TEXT || v == 0) return false;
            r.p = at;
            if (strcmp(key, "id") == 0) id = true;
            if (strcmp(key, "type") == 0) type = true;
        }
        if (!mc_skip_value(&r)) return false;
    }
    return id && type;
}

/* ---- IDENT ------------------------------------------------------------------ */

/* The end of the JSON value starting at s[i] (an object), or 0. */
static size_t json_object_end(const char *s, size_t i)
{
    if (s[i] != '{') return 0;
    int depth = 0;
    bool str = false;
    for (; s[i]; i++) {
        char c = s[i];
        if (str) {
            if (c == '\\' && s[i + 1]) {
                i++;
            } else if (c == '"') {
                str = false;
            }
        } else if (c == '"') {
            str = true;
        } else if (c == '{' || c == '[') {
            depth++;
        } else if (c == '}' || c == ']') {
            if (--depth == 0) return i + 1;
        }
    }
    return 0;
}

static size_t skip_ws(const char *s, size_t i)
{
    while (s[i] == ' ' || s[i] == '\t' || s[i] == '\n' || s[i] == '\r') i++;
    return i;
}

/*
 * Walks the JSON array of descriptors: with w == NULL only counts them,
 * otherwise writes each as a CBOR map. Returns the count, or -1.
 */
static int put_caps(const char *json, mc_writer_t *w)
{
    size_t i = skip_ws(json, 0);
    if (json[i] != '[') return -1;
    i = skip_ws(json, i + 1);
    int count = 0;
    if (json[i] == ']') return skip_ws(json, i + 1) == strlen(json) ? 0 : -1;
    for (;;) {
        size_t end = json_object_end(json, i);
        if (end == 0 || count >= ATALAIA_PROXY_CAPS_MAX) return -1;
        if (w) {
            char one[ATALAIA_PROXY_JSON_MAX];
            if (end - i >= sizeof(one)) return -1;
            memcpy(one, json + i, end - i);
            one[end - i] = '\0';
            size_t n = atalaia_json_map_encode(one, w->buf + w->pos, w->cap - w->pos, NULL);
            if (n == 0 || !descriptor_ok(w->buf + w->pos, n)) return -1;
            w->pos += n;
        }
        count++;
        i = skip_ws(json, end);
        if (json[i] == ']') break;
        if (json[i] != ',') return -1;
        i = skip_ws(json, i + 1);
    }
    return skip_ws(json, i + 1) == strlen(json) ? count : -1;
}

size_t atalaia_proxy_ident_encode(const atalaia_proxy_ident_t *in, uint8_t *buf, size_t cap)
{
    if (!in || !buf || !printable_ok(in->fw_version) || in->protocol_version != 1 ||
        (in->has_battery && in->battery_pct > 100)) {
        return 0;
    }
    int caps = put_caps(in->caps_json, NULL);
    if (caps < 0) return 0;
    if (cap > ATALAIA_PROXY_PAYLOAD_MAX) cap = ATALAIA_PROXY_PAYLOAD_MAX;
    mc_writer_t w;
    mc_init_writer(&w, buf, cap);
    mc_put_map(&w, in->has_battery ? 5 : 4);
    mc_put_uint(&w, 1);
    mc_put_text(&w, in->fw_version);
    mc_put_uint(&w, 2);
    mc_put_array(&w, (uint64_t)caps);
    if (!w.ok || put_caps(in->caps_json, &w) != caps) return 0;
    if (in->has_battery) {
        mc_put_uint(&w, 3);
        mc_put_uint(&w, in->battery_pct);
    }
    mc_put_uint(&w, 4);
    put_bool(&w, in->has_radio);
    mc_put_uint(&w, 5);
    mc_put_uint(&w, ATALAIA_PROXY_VERSION);
    return w.ok ? w.pos : 0;
}

static bool ident_decode(const uint8_t *buf, size_t len, atalaia_proxy_ident_t *t)
{
    if (len > ATALAIA_PROXY_PAYLOAD_MAX) return false;
    mc_reader_t r;
    mc_init_reader(&r, buf, len);
    uint64_t count;
    if (!mc_read_map(&r, &count) || count > KEY_UNKNOWN_LAST) return false;
    uint64_t prev = 0;
    unsigned seen = 0;
    for (uint64_t e = 0; e < count; e++) {
        uint64_t key;
        if (!mc_read_uint(&r, &key) || key <= prev) return false;
        prev = key;
        switch (key) {
        case 1:
            if (!mc_read_text(&r, t->fw_version, sizeof(t->fw_version), NULL) ||
                !printable_ok(t->fw_version)) {
                return false;
            }
            break;
        case 2: {
            uint64_t n;
            if (!mc_read_array(&r, &n) || n > ATALAIA_PROXY_CAPS_MAX) return false;
            size_t o = 0;
            t->caps_json[o++] = '[';
            for (uint64_t i = 0; i < n; i++) {
                size_t used = 0;
                char one[ATALAIA_PROXY_JSON_MAX];
                if (!atalaia_json_map_decode(r.p, mc_remaining(&r), &used, one, sizeof(one),
                                             NULL) ||
                    !descriptor_ok(r.p, used)) {
                    return false;
                }
                r.p += used;
                size_t l = strlen(one);
                if (o + l + 2 >= sizeof(t->caps_json)) return false;
                if (i > 0) t->caps_json[o++] = ',';
                memcpy(t->caps_json + o, one, l);
                o += l;
            }
            t->caps_json[o++] = ']';
            t->caps_json[o] = '\0';
            break;
        }
        case 3: {
            uint64_t v;
            if (!mc_read_uint(&r, &v) || v > 100) return false;
            t->has_battery = true;
            t->battery_pct = (uint8_t)v;
            break;
        }
        case 4:
            if (!read_bool(&r, &t->has_radio)) return false;
            break;
        case 5: {
            uint64_t v;
            if (!mc_read_uint(&r, &v) || v != ATALAIA_PROXY_VERSION) return false;
            t->protocol_version = (uint8_t)v;
            break;
        }
        default:
            if (key < KEY_UNKNOWN_FIRST || key > KEY_UNKNOWN_LAST || !mc_skip_value(&r)) {
                return false;
            }
            continue;
        }
        seen |= 1u << key;
    }
    const unsigned required = 1u << 1 | 1u << 2 | 1u << 4 | 1u << 5;
    return (seen & required) == required && mc_remaining(&r) == 0 && r.ok;
}

bool atalaia_proxy_ident_decode(const uint8_t *buf, size_t len, atalaia_proxy_ident_t *out)
{
    if (!buf || !out) return false;
    memset(out, 0, sizeof(*out));
    if (ident_decode(buf, len, out)) return true;
    memset(out, 0, sizeof(*out));
    return false;
}

/* ---- EVT and CMD ------------------------------------------------------------ */

static bool json_object_empty(const char *j)
{
    size_t i = skip_ws(j, 0);
    if (j[i] == '\0') return true;
    if (j[i] != '{') return false;
    i = skip_ws(j, i + 1);
    return j[i] == '}' && j[skip_ws(j, i + 1)] == '\0';
}

size_t atalaia_proxy_msg_encode(const atalaia_proxy_msg_t *in, uint8_t *buf, size_t cap)
{
    if (!in || !buf || !name_ok(in->cap_id) || !name_ok(in->name)) return 0;
    bool data = !json_object_empty(in->data_json);
    if (cap > ATALAIA_PROXY_PAYLOAD_MAX) cap = ATALAIA_PROXY_PAYLOAD_MAX;
    mc_writer_t w;
    mc_init_writer(&w, buf, cap);
    mc_put_map(&w, data ? 4 : 3);
    mc_put_uint(&w, 1);
    mc_put_text(&w, in->cap_id);
    mc_put_uint(&w, 2);
    mc_put_text(&w, in->name);
    if (data) {
        mc_put_uint(&w, 3);
        if (!w.ok) return 0;
        size_t n = atalaia_json_map_encode(in->data_json, w.buf + w.pos, w.cap - w.pos, NULL);
        if (n == 0) return 0;
        w.pos += n;
    }
    mc_put_uint(&w, 4);
    mc_put_uint(&w, in->seq);
    return w.ok ? w.pos : 0;
}

static bool msg_decode(const uint8_t *buf, size_t len, atalaia_proxy_msg_t *t)
{
    if (len > ATALAIA_PROXY_PAYLOAD_MAX) return false;
    snprintf(t->data_json, sizeof(t->data_json), "{}");
    mc_reader_t r;
    mc_init_reader(&r, buf, len);
    uint64_t count;
    if (!mc_read_map(&r, &count) || count > KEY_UNKNOWN_LAST) return false;
    uint64_t prev = 0;
    unsigned seen = 0;
    for (uint64_t e = 0; e < count; e++) {
        uint64_t key;
        if (!mc_read_uint(&r, &key) || key <= prev) return false;
        prev = key;
        switch (key) {
        case 1:
            if (!mc_read_text(&r, t->cap_id, sizeof(t->cap_id), NULL) || !name_ok(t->cap_id)) {
                return false;
            }
            break;
        case 2:
            if (!mc_read_text(&r, t->name, sizeof(t->name), NULL) || !name_ok(t->name)) {
                return false;
            }
            break;
        case 3: {
            size_t used = 0;
            if (!atalaia_json_map_decode(r.p, mc_remaining(&r), &used, t->data_json,
                                         sizeof(t->data_json), NULL) ||
                strcmp(t->data_json, "{}") == 0) {
                return false; /* an empty map is left out */
            }
            r.p += used;
            break;
        }
        case 4: {
            uint64_t v;
            if (!mc_read_uint(&r, &v) || v > 0xFFFF) return false;
            t->seq = (uint16_t)v;
            break;
        }
        default:
            if (key < KEY_UNKNOWN_FIRST || key > KEY_UNKNOWN_LAST || !mc_skip_value(&r)) {
                return false;
            }
            continue;
        }
        seen |= 1u << key;
    }
    const unsigned required = 1u << 1 | 1u << 2 | 1u << 4;
    return (seen & required) == required && mc_remaining(&r) == 0 && r.ok;
}

bool atalaia_proxy_msg_decode(const uint8_t *buf, size_t len, atalaia_proxy_msg_t *out)
{
    if (!buf || !out) return false;
    memset(out, 0, sizeof(*out));
    if (msg_decode(buf, len, out)) return true;
    memset(out, 0, sizeof(*out));
    return false;
}

/* ---- ACK -------------------------------------------------------------------- */

size_t atalaia_proxy_ack_encode(uint16_t seq, uint8_t *buf, size_t cap)
{
    if (!buf || cap < 2) return 0;
    buf[0] = (uint8_t)(seq >> 8);
    buf[1] = (uint8_t)seq;
    return 2;
}

bool atalaia_proxy_ack_decode(const uint8_t *buf, size_t len, uint16_t *seq)
{
    if (!buf || !seq || len != 2) return false;
    *seq = (uint16_t)(buf[0] << 8 | buf[1]);
    return true;
}
