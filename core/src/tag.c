/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Player tags (atalaia/tag.h, protocol/nfc-tag.md).
 */
#include "atalaia/tag.h"

#include <stdio.h>
#include <string.h>

#include "atalaia/join.h"

const char *atalaia_tag_result_name(atalaia_tag_result_t result)
{
    switch (result) {
    case ATALAIA_TAG_OK: return "ok";
    case ATALAIA_TAG_ERR_FORMAT: return "format";
    case ATALAIA_TAG_ERR_VERSION: return "version";
    case ATALAIA_TAG_ERR_GAME: return "game";
    case ATALAIA_TAG_ERR_MAC: return "mac";
    case ATALAIA_TAG_ERR_TEAM: return "team";
    }
    return "unknown";
}

static bool player_char(uint8_t c)
{
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '-' ||
           c == '_' || c == '.';
}

static bool player_bytes_ok(const uint8_t *p, size_t n)
{
    if (n < 1 || n > ATALAIA_TAG_PLAYER_MAX) return false;
    for (size_t i = 0; i < n; i++) {
        if (!player_char(p[i])) return false;
    }
    return true;
}

bool atalaia_tag_player_ok(const char *player)
{
    if (player == NULL) return false;
    size_t n = 0;
    while (n <= ATALAIA_TAG_PLAYER_MAX && player[n] != '\0') n++;
    return player_bytes_ok((const uint8_t *)player, n);
}

static void mac16(const uint8_t key[ATALAIA_TAG_KEY_SIZE], const uint8_t *msg, size_t len,
                  uint8_t out[ATALAIA_TAG_MAC_SIZE])
{
    uint8_t full[32];
    atalaia_hmac_sha256(key, ATALAIA_TAG_KEY_SIZE, msg, len, full);
    memcpy(out, full, ATALAIA_TAG_MAC_SIZE);
}

size_t atalaia_tag_encode(const atalaia_tag_t *t, const uint8_t game_key[ATALAIA_TAG_KEY_SIZE],
                          uint8_t *buf, size_t cap)
{
    if (!t || !game_key || !buf || !atalaia_tag_player_ok(t->player)) return 0;
    size_t plen = strlen(t->player);
    size_t total = 1 + plen + 1 + 2 + ATALAIA_TAG_MAC_SIZE;
    if (total > cap) return 0;
    size_t o = 0;
    buf[o++] = ATALAIA_TAG_VERSION;
    memcpy(buf + o, t->player, plen);
    o += plen;
    buf[o++] = t->team;
    buf[o++] = (uint8_t)(t->game_id >> 8);
    buf[o++] = (uint8_t)t->game_id;
    mac16(game_key, buf, o, buf + o);
    return total;
}

atalaia_tag_result_t atalaia_tag_decode(const uint8_t *buf, size_t len, uint16_t game_id,
                                        const uint8_t game_key[ATALAIA_TAG_KEY_SIZE],
                                        uint8_t team_count, atalaia_tag_t *out)
{
    if (!buf || len < ATALAIA_TAG_MIN || len > ATALAIA_TAG_MAX) return ATALAIA_TAG_ERR_FORMAT;
    if (buf[0] != ATALAIA_TAG_VERSION) return ATALAIA_TAG_ERR_VERSION;
    size_t signed_len = len - ATALAIA_TAG_MAC_SIZE;
    uint16_t gid = (uint16_t)(buf[signed_len - 2] << 8 | buf[signed_len - 1]);
    if (gid != game_id) return ATALAIA_TAG_ERR_GAME;
    if (!game_key) return ATALAIA_TAG_ERR_MAC;

    uint8_t mac[ATALAIA_TAG_MAC_SIZE];
    mac16(game_key, buf, signed_len, mac);
    uint8_t diff = 0;
    for (size_t i = 0; i < ATALAIA_TAG_MAC_SIZE; i++)
        diff |= (uint8_t)(mac[i] ^ buf[signed_len + i]);
    if (diff != 0) return ATALAIA_TAG_ERR_MAC;

    size_t plen = signed_len - 1 - 1 - 2;
    if (!player_bytes_ok(buf + 1, plen)) return ATALAIA_TAG_ERR_FORMAT;
    uint8_t team = buf[1 + plen];
    if (team > team_count) return ATALAIA_TAG_ERR_TEAM;
    if (out) {
        memcpy(out->player, buf + 1, plen);
        out->player[plen] = '\0';
        out->team = team;
        out->game_id = gid;
    }
    return ATALAIA_TAG_OK;
}

size_t atalaia_tag_from_ndef_tag(const uint8_t *mem, size_t len, const uint8_t **payload)
{
    return atalaia_ndef_find_mime(mem, len, ATALAIA_TAG_NDEF_TYPE, payload);
}

size_t atalaia_tag_to_ndef_tag(const uint8_t *payload, size_t len, uint8_t *mem, size_t cap)
{
    return atalaia_ndef_write_mime(ATALAIA_TAG_NDEF_TYPE, payload, len, mem, cap);
}

/* ---- the nfc.tag event ----------------------------------------------------- */

typedef struct {
    char *out;
    size_t cap;
    size_t len;
    bool ok;
} jbuf_t;

static void put(jbuf_t *b, const char *s, size_t n)
{
    if (!b->ok || n >= b->cap - b->len) {
        b->ok = false;
        return;
    }
    memcpy(b->out + b->len, s, n);
    b->len += n;
    b->out[b->len] = '\0';
}

static void puts_(jbuf_t *b, const char *s)
{
    put(b, s, strlen(s));
}

/* A JSON string: quotes, backslashes and control characters escaped. */
static void put_string(jbuf_t *b, const char *s)
{
    put(b, "\"", 1);
    for (const unsigned char *p = (const unsigned char *)s; *p; p++) {
        if (*p == '"' || *p == '\\') {
            char e[2] = {'\\', (char)*p};
            put(b, e, 2);
        } else if (*p < 0x20) {
            char e[8];
            int n = snprintf(e, sizeof(e), "\\u%04x", *p);
            put(b, e, (size_t)n);
        } else {
            put(b, (const char *)p, 1);
        }
    }
    put(b, "\"", 1);
}

size_t atalaia_tag_event_json(const uint8_t *uid, size_t uid_len, const uint8_t *payload,
                              size_t len, uint16_t game_id, const uint8_t *game_key,
                              const char *const *teams, size_t team_count, char *json, size_t cap)
{
    if (!json || cap == 0) return 0;
    jbuf_t b = {json, cap, 0, true};
    json[0] = '\0';

    static const char hex[] = "0123456789abcdef";
    char uid_hex[2 * ATALAIA_TAG_UID_MAX + 1];
    if (uid_len > ATALAIA_TAG_UID_MAX) uid_len = ATALAIA_TAG_UID_MAX;
    for (size_t i = 0; i < uid_len; i++) {
        uid_hex[2 * i] = hex[uid[i] >> 4];
        uid_hex[2 * i + 1] = hex[uid[i] & 0x0F];
    }
    uid_hex[2 * uid_len] = '\0';
    puts_(&b, "{\"uid\":\"");
    puts_(&b, uid_hex);
    puts_(&b, "\",\"valid\":");

    const char *reason = NULL;
    atalaia_tag_t tag;
    memset(&tag, 0, sizeof(tag));
    if (payload == NULL) {
        reason = "unsigned";
    } else if (game_key == NULL) {
        reason = "no_game";
    } else {
        uint8_t count = team_count > 255 ? 255 : (uint8_t)team_count;
        atalaia_tag_result_t r = atalaia_tag_decode(payload, len, game_id, game_key, count, &tag);
        if (r != ATALAIA_TAG_OK) reason = atalaia_tag_result_name(r);
    }
    if (reason) {
        puts_(&b, "false,\"reason\":\"");
        puts_(&b, reason);
        puts_(&b, "\"}");
    } else {
        puts_(&b, "true,\"player\":\"");
        puts_(&b, tag.player); /* checked: no characters to escape */
        put(&b, "\"", 1);
        if (tag.team > 0 && teams && teams[tag.team - 1]) {
            puts_(&b, ",\"team\":");
            put_string(&b, teams[tag.team - 1]);
        }
        put(&b, "}", 1);
    }
    if (!b.ok) {
        json[0] = '\0';
        return 0;
    }
    return b.len;
}
