/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Adoption: the field card, the box's adoption rules and its console
 * commands (adoption.h, protocol/adoption.md).
 */
#include "adoption.h"

#include <stdio.h>
#include <string.h>

#include "atalaia/join.h"
#include "box_text.h"

/* ---- the field card ------------------------------------------------------ */

#define CARD_VERSION 1
static const char CHECK_LABEL[] = "atalaia-field-card";
static const char FP_LABEL[] = "atalaia-field-fingerprint";

static bool same_bytes(const uint8_t *a, const uint8_t *b, size_t n)
{
    uint8_t d = 0;
    for (size_t i = 0; i < n; i++) d |= (uint8_t)(a[i] ^ b[i]);
    return d == 0;
}

const char *adoption_card_result_name(adoption_card_result_t r)
{
    switch (r) {
    case ADOPTION_CARD_OK: return "ok";
    case ADOPTION_CARD_LENGTH: return "length";
    case ADOPTION_CARD_VERSION: return "version";
    case ADOPTION_CARD_NAME: return "name";
    case ADOPTION_CARD_CHECK: return "check";
    }
    return "?";
}

bool adoption_name_ok(const char *name, size_t len)
{
    if (len > ADOPTION_NAME_MAX) return false;
    const uint8_t *s = (const uint8_t *)name;
    size_t i = 0;
    while (i < len) {
        uint8_t c = s[i];
        if (c < 0x80) {
            if (c < 0x20 || c == 0x7F || c == '"' || c == '\\') return false;
            i++;
            continue;
        }
        size_t n;
        uint32_t cp;
        if (c >= 0xC2 && c <= 0xDF) {
            n = 1;
            cp = c & 0x1Fu;
        } else if (c >= 0xE0 && c <= 0xEF) {
            n = 2;
            cp = c & 0x0Fu;
        } else if (c >= 0xF0 && c <= 0xF4) {
            n = 3;
            cp = c & 0x07u;
        } else {
            return false; /* a continuation byte, an overlong lead (C0, C1) or beyond U+10FFFF */
        }
        if (len - i <= n) return false;
        for (size_t k = 1; k <= n; k++) {
            if ((s[i + k] & 0xC0) != 0x80) return false;
            cp = (cp << 6) | (s[i + k] & 0x3Fu);
        }
        if ((n == 2 && cp < 0x800) || (n == 3 && cp < 0x10000) || cp > 0x10FFFF ||
            (cp >= 0xD800 && cp <= 0xDFFF)) {
            return false; /* overlong, a surrogate, or beyond Unicode */
        }
        i += n + 1;
    }
    return true;
}

static void card_check(const uint8_t key[ADOPTION_KEY_SIZE], const uint8_t *head, size_t head_len,
                       uint8_t out[ADOPTION_CHECK_SIZE])
{
    uint8_t msg[sizeof(CHECK_LABEL) - 1 + 2 + ADOPTION_NAME_MAX];
    memcpy(msg, CHECK_LABEL, sizeof(CHECK_LABEL) - 1);
    memcpy(msg + sizeof(CHECK_LABEL) - 1, head, head_len);
    uint8_t mac[32];
    atalaia_hmac_sha256(key, ADOPTION_KEY_SIZE, msg, sizeof(CHECK_LABEL) - 1 + head_len, mac);
    memcpy(out, mac, ADOPTION_CHECK_SIZE);
}

adoption_card_result_t adoption_card_decode(const uint8_t *data, size_t len, adoption_card_t *out)
{
    if (data == NULL || len < ADOPTION_CARD_MIN || len > ADOPTION_CARD_MAX) {
        return ADOPTION_CARD_LENGTH;
    }
    if (data[0] != CARD_VERSION) return ADOPTION_CARD_VERSION;
    size_t n = data[1];
    if (n > ADOPTION_NAME_MAX || len != ADOPTION_CARD_MIN + n) return ADOPTION_CARD_LENGTH;
    if (!adoption_name_ok((const char *)data + 2, n)) return ADOPTION_CARD_NAME;
    const uint8_t *key = data + 2 + n;
    uint8_t check[ADOPTION_CHECK_SIZE];
    card_check(key, data, 2 + n, check);
    if (!same_bytes(check, key + ADOPTION_KEY_SIZE, ADOPTION_CHECK_SIZE))
        return ADOPTION_CARD_CHECK;
    memcpy(out->key, key, ADOPTION_KEY_SIZE);
    memcpy(out->name, data + 2, n);
    out->name[n] = '\0';
    return ADOPTION_CARD_OK;
}

size_t adoption_card_encode(const adoption_card_t *card, uint8_t *buf, size_t cap)
{
    size_t n = strlen(card->name);
    if (!adoption_name_ok(card->name, n) || cap < ADOPTION_CARD_MIN + n) return 0;
    buf[0] = CARD_VERSION;
    buf[1] = (uint8_t)n;
    memcpy(buf + 2, card->name, n);
    memcpy(buf + 2 + n, card->key, ADOPTION_KEY_SIZE);
    card_check(card->key, buf, 2 + n, buf + 2 + n + ADOPTION_KEY_SIZE);
    return ADOPTION_CARD_MIN + n;
}

size_t adoption_card_from_ndef_tag(const uint8_t *mem, size_t len, const uint8_t **payload)
{
    return atalaia_ndef_find_mime(mem, len, ADOPTION_NDEF_TYPE, payload);
}

void adoption_fingerprint(const uint8_t key[ADOPTION_KEY_SIZE], char out[ADOPTION_FP_SIZE])
{
    uint8_t mac[32];
    atalaia_hmac_sha256(key, ADOPTION_KEY_SIZE, (const uint8_t *)FP_LABEL, sizeof(FP_LABEL) - 1,
                        mac);
    snprintf(out, ADOPTION_FP_SIZE, "%02X%02X-%02X%02X", mac[0], mac[1], mac[2], mac[3]);
}

/* ---- the adoption rules -------------------------------------------------- */

const char *adopt_result_name(adopt_result_t r)
{
    switch (r) {
    case ADOPT_ADOPTED: return "adopted";
    case ADOPT_SAME: return "same";
    case ADOPT_READOPTED: return "readopted";
    case ADOPT_NEED_PIN: return "need_pin";
    case ADOPT_BAD_PIN: return "bad_pin";
    case ADOPT_LOCKED: return "locked";
    case ADOPT_BUSY: return "busy";
    case ADOPT_BAD_KEY: return "bad_key";
    case ADOPT_BAD_CARD: return "bad_card";
    case ADOPT_STORE_FAILED: return "store_failed";
    case ADOPT_NO_PIN: return "no_pin";
    }
    return "?";
}

void adoption_init(adoption_t *a, const adoption_ops_t *ops, const char *admin_pin)
{
    memset(a, 0, sizeof(*a));
    if (ops != NULL) a->ops = *ops;
    admin_pin_init(&a->own_pin, NULL, admin_pin);
    a->pin = &a->own_pin;
}

void adoption_set_pin(adoption_t *a, admin_pin_t *pin)
{
    a->pin = pin != NULL ? pin : &a->own_pin;
}

static void set_name(char dst[ADOPTION_NAME_MAX + 1], const char *name)
{
    size_t n = name ? strlen(name) : 0;
    if (n > ADOPTION_NAME_MAX || !adoption_name_ok(name, n)) n = 0;
    if (n) memcpy(dst, name, n);
    dst[n] = '\0';
}

void adoption_restore(adoption_t *a, const uint8_t key[ADOPTION_KEY_SIZE], const char *name)
{
    a->adopted = true;
    memcpy(a->key, key, ADOPTION_KEY_SIZE);
    set_name(a->name, name);
    adoption_fingerprint(a->key, a->fingerprint);
}

static void say(adoption_t *a, const char *line)
{
    if (a->ops.log) a->ops.log(a->ops.ctx, line);
}

adopt_result_t adoption_offer(adoption_t *a, const uint8_t key[ADOPTION_KEY_SIZE], const char *name,
                              const char *pin)
{
    const char *nm = name ? name : "";
    if (!adoption_name_ok(nm, strlen(nm))) return ADOPT_BAD_KEY;
    if (a->ops.busy && a->ops.busy(a->ops.ctx)) return ADOPT_BUSY;
    adopt_result_t ok = ADOPT_ADOPTED;
    if (a->adopted && same_bytes(a->key, key, ADOPTION_KEY_SIZE)) {
        if (nm[0] == '\0' || strcmp(nm, a->name) == 0) return ADOPT_SAME;
        ok = ADOPT_SAME; /* the same field, renamed: store the new name */
    } else if (a->adopted) {
        /* The admin PIN (admin_pin.h): none set on a Field Box moves it nowhere; a wait
         * refuses before anything is compared or counted. */
        if (!admin_pin_is_set(a->pin)) return ADOPT_NO_PIN;
        if (admin_pin_wait_ms(a->pin) > 0) return ADOPT_LOCKED;
        if (pin == NULL || pin[0] == '\0') return ADOPT_NEED_PIN;
        switch (admin_pin_check(a->pin, pin)) {
        case ADMIN_PIN_OK: break;
        case ADMIN_PIN_STORE_FAILED: return ADOPT_STORE_FAILED;
        case ADMIN_PIN_NOT_SET: return ADOPT_NO_PIN;
        default: return admin_pin_wait_ms(a->pin) > 0 ? ADOPT_LOCKED : ADOPT_BAD_PIN;
        }
        ok = ADOPT_READOPTED;
    }
    if (a->ops.store == NULL || !a->ops.store(a->ops.ctx, key, nm)) return ADOPT_STORE_FAILED;
    a->adopted = true;
    memcpy(a->key, key, ADOPTION_KEY_SIZE);
    set_name(a->name, nm);
    adoption_fingerprint(a->key, a->fingerprint);
    return ok;
}

/* ---- what the box shows -------------------------------------------------- */

static void show_result(adoption_t *a, adopt_result_t r, uint32_t now_ms)
{
    /* In the box's language (box_text.h, decision BN-14). */
    static const struct {
        adopt_result_t r;
        box_text_id_t title;
    } titles[] = {
        {ADOPT_ADOPTED, TX_ADOPTED},         {ADOPT_SAME, TX_ALREADY_ADOPTED},
        {ADOPT_READOPTED, TX_ADOPTED},       {ADOPT_BAD_PIN, TX_WRONG_PIN},
        {ADOPT_LOCKED, TX_ADOPTION_LOCKED},  {ADOPT_BUSY, TX_GAME_JOINED},
        {ADOPT_BAD_KEY, TX_NOT_ADOPTED},     {ADOPT_BAD_CARD, TX_BAD_FIELD_CARD},
        {ADOPT_STORE_FAILED, TX_NOT_STORED}, {ADOPT_NEED_PIN, TX_ADMIN_PIN_NEEDED},
    };
    if (r == ADOPT_LOCKED || r == ADOPT_NO_PIN) {
        /* The PIN's own screen: how long it is locked for, or that none is set (AD-28, AD-29). */
        char pin_data[96];
        if (r == ADOPT_LOCKED) {
            snprintf(pin_data, sizeof(pin_data),
                     "{\"digits\":0,\"error\":false,\"locked_min\":%lu}",
                     (unsigned long)admin_pin_wait_min(a->pin));
        } else {
            snprintf(pin_data, sizeof(pin_data), "{\"digits\":0,\"error\":false,\"no_pin\":true}");
        }
        if (a->ops.screen) a->ops.screen(a->ops.ctx, "pin_entry", pin_data);
        a->overlay = true;
        a->overlay_until_ms = now_ms + ADOPTION_SCREEN_MS;
        return;
    }
    const char *title = box_text(TX_ADOPTION);
    for (size_t i = 0; i < sizeof(titles) / sizeof(titles[0]); i++) {
        if (titles[i].r == r) title = box_text(titles[i].title);
    }
    char data[200];
    if (a->adopted) {
        snprintf(data, sizeof(data), "{\"title\":\"%s\",\"field\":\"%s\",\"fingerprint\":\"%s\"}",
                 title, a->name[0] ? a->name : "-", a->fingerprint);
    } else {
        snprintf(data, sizeof(data), "{\"title\":\"%s\",\"field\":\"%s\"}", title,
                 box_text(TX_FIELD_NONE));
    }
    if (a->ops.screen) a->ops.screen(a->ops.ctx, "status", data);
    a->overlay = true;
    a->overlay_until_ms = now_ms + ADOPTION_SCREEN_MS;
}

static void show_pin(adoption_t *a, bool error)
{
    char data[96];
    snprintf(data, sizeof(data), "{\"digits\":%u,\"error\":%s,\"prompt\":\"%s\"}",
             (unsigned)a->typed_len, error ? "true" : "false", box_text(TX_PIN_TO_CHANGE_FIELD));
    if (a->ops.screen) a->ops.screen(a->ops.ctx, "pin_entry", data);
}

static void log_result(adoption_t *a, const char *via, adopt_result_t r)
{
    char line[120];
    if (adopt_result_ok(r)) {
        snprintf(line, sizeof(line), "adoption (%s): %s, field %s \"%s\"", via,
                 adopt_result_name(r), a->fingerprint, a->name);
    } else {
        snprintf(line, sizeof(line), "adoption (%s): refused, %s", via, adopt_result_name(r));
    }
    say(a, line);
}

void adoption_report(adoption_t *a, const char *via, adopt_result_t r, uint32_t now_ms)
{
    log_result(a, via, r);
    if (r != ADOPT_BUSY) show_result(a, r, now_ms);
}

bool adoption_tap(adoption_t *a, const uint8_t *mem, size_t len, uint32_t now_ms,
                  adopt_result_t *result)
{
    const uint8_t *payload = NULL;
    size_t n = adoption_card_from_ndef_tag(mem, len, &payload);
    if (n == 0) return false;
    adoption_card_t card;
    adoption_card_result_t cr = adoption_card_decode(payload, n, &card);
    adopt_result_t r;
    if (cr != ADOPTION_CARD_OK) {
        char line[64];
        snprintf(line, sizeof(line), "adoption (card): bad field card (%s)",
                 adoption_card_result_name(cr));
        say(a, line);
        r = ADOPT_BAD_CARD;
        show_result(a, r, now_ms);
    } else {
        r = adoption_offer(a, card.key, card.name, NULL);
        log_result(a, "card", r);
        if (r == ADOPT_NEED_PIN) {
            a->pending = true;
            a->pending_card = card;
            a->pending_since_ms = now_ms;
            a->typed_len = 0;
            a->typed[0] = '\0';
            a->overlay = false;
            show_pin(a, false);
        } else {
            a->pending = false;
            /* With a game joined the box keeps the game's screen: the log says why. */
            if (r != ADOPT_BUSY) show_result(a, r, now_ms);
        }
    }
    memset(&card, 0, sizeof(card));
    if (result) *result = r;
    return true;
}

bool adoption_active(const adoption_t *a)
{
    return a->pending || a->overlay;
}

static void end_pending(adoption_t *a)
{
    a->pending = false;
    memset(&a->pending_card, 0, sizeof(a->pending_card));
    memset(a->typed, 0, sizeof(a->typed));
    a->typed_len = 0;
}

bool adoption_key(adoption_t *a, char key, uint32_t now_ms)
{
    if (a->pending) {
        a->pending_since_ms = now_ms; /* typing keeps the card waiting */
        if (key >= '0' && key <= '9') {
            if (a->typed_len < ADOPTION_PIN_MAX) {
                a->typed[a->typed_len++] = key;
                a->typed[a->typed_len] = '\0';
            }
            show_pin(a, false);
        } else if (key == '*') {
            if (a->typed_len == 0) {
                end_pending(a);
                say(a, "adoption (card): cancelled");
                a->overlay = true; /* closed at the next tick, which tells the shell to redraw */
                a->overlay_until_ms = now_ms;
            } else {
                a->typed[--a->typed_len] = '\0';
                show_pin(a, false);
            }
        } else if (key == '#') {
            adopt_result_t r =
                adoption_offer(a, a->pending_card.key, a->pending_card.name, a->typed);
            log_result(a, "card", r);
            if (r == ADOPT_BAD_PIN) {
                memset(a->typed, 0, sizeof(a->typed));
                a->typed_len = 0;
                show_pin(a, true);
            } else {
                end_pending(a);
                show_result(a, r, now_ms);
            }
        }
        return true;
    }
    if (a->overlay) {
        a->overlay_until_ms = now_ms; /* closed at the next tick, which tells the shell */
        return true;
    }
    return false;
}

bool adoption_tick(adoption_t *a, uint32_t now_ms)
{
    if (a->pending && now_ms - a->pending_since_ms >= ADOPTION_PIN_WAIT_MS) {
        end_pending(a);
        say(a, "adoption (card): no PIN typed, cancelled");
        return true;
    }
    if (a->overlay && (int32_t)(now_ms - a->overlay_until_ms) >= 0) {
        a->overlay = false;
        return !a->pending;
    }
    return false;
}

/* ---- console commands ---------------------------------------------------- */

/* Copies s into a JSON string body, escaping what JSON needs. */
static void json_text(char *out, size_t cap, const char *s)
{
    size_t o = 0;
    for (const char *p = s ? s : ""; *p && o + 7 < cap; p++) {
        unsigned char c = (unsigned char)*p;
        if (c == '"' || c == '\\') {
            out[o++] = '\\';
            out[o++] = (char)c;
        } else if (c < 0x20) {
            o += (size_t)snprintf(out + o, cap - o, "\\u%04x", c);
        } else {
            out[o++] = (char)c;
        }
    }
    out[o] = '\0';
}

static bool parse_key(const char *hex, uint8_t key[ADOPTION_KEY_SIZE], const char **rest)
{
    for (size_t i = 0; i < 2 * ADOPTION_KEY_SIZE; i++) {
        char c = hex[i];
        int v = (c >= '0' && c <= '9')   ? c - '0'
                : (c >= 'a' && c <= 'f') ? c - 'a' + 10
                : (c >= 'A' && c <= 'F') ? c - 'A' + 10
                                         : -1;
        if (v < 0) return false;
        if (i % 2 == 0) {
            key[i / 2] = (uint8_t)(v << 4);
        } else {
            key[i / 2] |= (uint8_t)v;
        }
    }
    const char *r = hex + 2 * ADOPTION_KEY_SIZE;
    if (*r != '\0' && *r != ' ') return false;
    *rest = r;
    return true;
}

static void reply_state(adoption_t *a, char *buf, size_t cap)
{
    char name[2 * ADOPTION_NAME_MAX + 8];
    json_text(name, sizeof(name), a->name);
    snprintf(buf, cap, "\"state\":\"%s\",\"field\":\"%s\",\"field_name\":\"%s\"",
             a->adopted ? "adopted" : "unadopted", a->adopted ? a->fingerprint : "",
             a->adopted ? name : "");
}

bool adoption_command(adoption_t *a, const char *cmd, const adoption_identity_t *id,
                      uint32_t now_ms, char *reply, size_t cap)
{
    char state[200];
    if (strcmp(cmd, "adopt-info") == 0) {
        char name[64], mac[32], fw[48];
        json_text(name, sizeof(name), id ? id->name : "");
        json_text(mac, sizeof(mac), id ? id->mac : "");
        json_text(fw, sizeof(fw), id ? id->fw : "");
        reply_state(a, state, sizeof(state));
        bool busy = a->ops.busy && a->ops.busy(a->ops.ctx);
        snprintf(reply, cap,
                 ADOPTION_REPLY_PREFIX "{\"v\":1,\"kind\":\"info\",\"name\":\"%s\",\"mac\":\"%s\","
                                       "\"fw\":\"%s\",%s,\"busy\":%s,\"locked\":%s,"
                                       "\"locked_min\":%lu,\"pin_set\":%s}",
                 name, mac, fw, state, busy ? "true" : "false",
                 admin_pin_wait_ms(a->pin) > 0 ? "true" : "false",
                 (unsigned long)admin_pin_wait_min(a->pin),
                 admin_pin_is_set(a->pin) ? "true" : "false");
        return true;
    }
    bool adopt = strncmp(cmd, "adopt ", 6) == 0;
    bool joinkey = strncmp(cmd, "joinkey ", 8) == 0;
    if (!adopt && !joinkey) return false;

    uint8_t key[ADOPTION_KEY_SIZE];
    const char *rest = NULL;
    adopt_result_t r;
    char pin[ADOPTION_PIN_MAX + 1] = "";
    char name[ADOPTION_NAME_MAX + 1] = "";
    if (!parse_key(cmd + (adopt ? 6 : 8), key, &rest)) {
        r = ADOPT_BAD_KEY;
    } else if (joinkey) {
        r = *rest == '\0' ? adoption_offer(a, key, "", NULL) : ADOPT_BAD_KEY;
    } else {
        /* "@adopt <key> [<pin>|-] [<name>]": the name is the rest of the line. */
        bool ok = true;
        if (*rest == ' ') {
            const char *p = rest + 1;
            const char *sp = strchr(p, ' ');
            size_t n = sp ? (size_t)(sp - p) : strlen(p);
            if (n == 0 || n > ADOPTION_PIN_MAX) {
                ok = false;
            } else if (!(n == 1 && p[0] == '-')) {
                memcpy(pin, p, n);
                pin[n] = '\0';
            }
            if (ok && sp != NULL) {
                size_t m = strlen(sp + 1);
                if (m > ADOPTION_NAME_MAX || !adoption_name_ok(sp + 1, m)) {
                    ok = false;
                } else {
                    memcpy(name, sp + 1, m);
                    name[m] = '\0';
                }
            }
        }
        r = ok ? adoption_offer(a, key, name, pin[0] ? pin : NULL) : ADOPT_BAD_KEY;
    }
    memset(key, 0, sizeof(key));
    memset(pin, 0, sizeof(pin));
    log_result(a, adopt ? "usb" : "joinkey", r);
    if (adopt_result_ok(r) || r == ADOPT_LOCKED || r == ADOPT_BAD_PIN || r == ADOPT_NO_PIN) {
        show_result(a, r, now_ms);
    }
    if (joinkey) {
        snprintf(reply, cap, "join key: %s",
                 adopt_result_ok(r) ? "stored"
                 : r == ADOPT_NEED_PIN
                     ? "refused (adopted to another field: \"@adopt <key> <admin PIN>\")"
                 : r == ADOPT_NO_PIN
                     ? "refused (adopted to another field, and no admin PIN is set: \"@admin-pin\")"
                 : r == ADOPT_BAD_KEY ? "refused (64 hex digits)"
                 : r == ADOPT_BUSY    ? "refused while a game is joined"
                                      : adopt_result_name(r));
        return true;
    }
    reply_state(a, state, sizeof(state));
    snprintf(reply, cap, ADOPTION_REPLY_PREFIX "{\"v\":1,\"kind\":\"result\",\"result\":\"%s\",%s}",
             adopt_result_name(r), state);
    return true;
}
