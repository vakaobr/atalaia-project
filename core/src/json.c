/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "json.h"

#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "lauxlib.h"

#define JSON_MAX_DEPTH 16
#define JSON_MAX_NUMBER 64

/* ---- Encoding ------------------------------------------------------------
 * Pieces are collected in a Lua table and joined at the end. A luaL_Buffer
 * cannot stay open across the nested stack work that tables need.
 */

typedef struct {
    lua_State *L;
    int parts;
    lua_Integer count;
    int depth;
} encoder_t;

static void put_top(encoder_t *e)
{
    lua_rawseti(e->L, e->parts, ++e->count);
}

static void put(encoder_t *e, const char *s)
{
    lua_pushstring(e->L, s);
    put_top(e);
}

static void push_quoted(lua_State *L, const char *s, size_t len)
{
    luaL_Buffer b;
    luaL_buffinit(L, &b);
    luaL_addchar(&b, '"');
    for (size_t i = 0; i < len; i++) {
        unsigned char c = (unsigned char)s[i];
        switch (c) {
        case '"':  luaL_addstring(&b, "\\\""); break;
        case '\\': luaL_addstring(&b, "\\\\"); break;
        case '\n': luaL_addstring(&b, "\\n"); break;
        case '\r': luaL_addstring(&b, "\\r"); break;
        case '\t': luaL_addstring(&b, "\\t"); break;
        case '\b': luaL_addstring(&b, "\\b"); break;
        case '\f': luaL_addstring(&b, "\\f"); break;
        default:
            if (c < 0x20) {
                char esc[8];
                snprintf(esc, sizeof(esc), "\\u%04x", c);
                luaL_addstring(&b, esc);
            } else {
                luaL_addchar(&b, (char)c);
            }
        }
    }
    luaL_addchar(&b, '"');
    luaL_pushresult(&b);
}

static void encode_value(encoder_t *e, int idx);

static int key_compare(const char *a, size_t alen, const char *b, size_t blen)
{
    int c = memcmp(a, b, alen < blen ? alen : blen);
    if (c != 0) {
        return c;
    }
    return alen < blen ? -1 : (alen > blen ? 1 : 0);
}

static void encode_object(encoder_t *e, int idx, lua_Integer count)
{
    /* Emit keys in sorted order by repeatedly picking the smallest key
     * greater than the previous one. Tables here are small. */
    lua_State *L = e->L;
    const char *prev = NULL;
    size_t prev_len = 0;

    put(e, "{");
    for (lua_Integer i = 0; i < count; i++) {
        const char *best = NULL;
        size_t best_len = 0;
        lua_pushnil(L);
        while (lua_next(L, idx)) {
            size_t len;
            const char *k = lua_tolstring(L, -2, &len);
            lua_pop(L, 1);
            if (prev != NULL && key_compare(k, len, prev, prev_len) <= 0) {
                continue;
            }
            if (best == NULL || key_compare(k, len, best, best_len) < 0) {
                best = k;
                best_len = len;
            }
        }
        if (i > 0) {
            put(e, ",");
        }
        push_quoted(L, best, best_len);
        put_top(e);
        put(e, ":");
        lua_pushlstring(L, best, best_len);
        lua_rawget(L, idx);
        encode_value(e, -1);
        lua_pop(L, 1);
        prev = best; /* stays valid: the key is anchored in the table */
        prev_len = best_len;
    }
    put(e, "}");
}

static void encode_table(encoder_t *e, int idx)
{
    lua_State *L = e->L;
    if (++e->depth > JSON_MAX_DEPTH) {
        luaL_error(L, "cannot encode JSON nested deeper than %d", JSON_MAX_DEPTH);
    }
    luaL_checkstack(L, 6, "JSON encoding");

    lua_Integer len = (lua_Integer)lua_rawlen(L, idx);
    lua_Integer count = 0;
    bool array_like = true;
    bool string_keys = true;

    lua_pushnil(L);
    while (lua_next(L, idx)) {
        lua_pop(L, 1);
        count++;
        if (lua_type(L, -1) == LUA_TSTRING) {
            array_like = false;
        } else if (lua_isinteger(L, -1)) {
            lua_Integer k = lua_tointeger(L, -1);
            string_keys = false;
            if (k < 1 || k > len) {
                array_like = false;
            }
        } else {
            array_like = false;
            string_keys = false;
        }
    }

    if (count == 0) {
        put(e, "{}");
    } else if (array_like && count == len) {
        put(e, "[");
        for (lua_Integer i = 1; i <= len; i++) {
            if (i > 1) {
                put(e, ",");
            }
            lua_rawgeti(L, idx, i);
            encode_value(e, -1);
            lua_pop(L, 1);
        }
        put(e, "]");
    } else if (string_keys) {
        encode_object(e, idx, count);
    } else {
        luaL_error(L, "cannot encode a table with mixed or sparse keys as JSON");
    }
    e->depth--;
}

static void encode_value(encoder_t *e, int idx)
{
    lua_State *L = e->L;
    idx = lua_absindex(L, idx);
    switch (lua_type(L, idx)) {
    case LUA_TNIL:
        put(e, "null");
        break;
    case LUA_TBOOLEAN:
        put(e, lua_toboolean(L, idx) ? "true" : "false");
        break;
    case LUA_TNUMBER:
        if (lua_isinteger(L, idx)) {
            lua_pushfstring(L, "%I", (LUAI_UACINT)lua_tointeger(L, idx));
        } else {
            lua_Number n = lua_tonumber(L, idx);
            if (!isfinite(n)) {
                luaL_error(L, "cannot encode NaN or infinity as JSON");
            }
            lua_pushfstring(L, "%f", (LUAI_UACNUMBER)n);
        }
        put_top(e);
        break;
    case LUA_TSTRING: {
        size_t len;
        const char *s = lua_tolstring(L, idx, &len);
        push_quoted(L, s, len);
        put_top(e);
        break;
    }
    case LUA_TTABLE:
        encode_table(e, idx);
        break;
    default:
        luaL_error(L, "cannot encode a %s as JSON", luaL_typename(L, idx));
    }
}

void atalaia_json_push_encoded(lua_State *L, int idx)
{
    idx = lua_absindex(L, idx);
    lua_newtable(L);
    encoder_t e = {L, lua_gettop(L), 0, 0};
    encode_value(&e, idx);

    luaL_Buffer b;
    luaL_buffinit(L, &b);
    for (lua_Integer i = 1; i <= e.count; i++) {
        lua_rawgeti(L, e.parts, i);
        luaL_addvalue(&b);
    }
    luaL_pushresult(&b);
    lua_remove(L, e.parts);
}

/* ---- Decoding ------------------------------------------------------------ */

typedef struct {
    lua_State *L;
    const char *start;
    const char *p;
    int depth;
} decoder_t;

static void fail(decoder_t *d, const char *what)
{
    luaL_error(d->L, "invalid JSON at offset %d: %s", (int)(d->p - d->start), what);
}

static void skip_space(decoder_t *d)
{
    while (*d->p == ' ' || *d->p == '\t' || *d->p == '\n' || *d->p == '\r') {
        d->p++;
    }
}

static int hex_value(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static uint32_t read_hex4(decoder_t *d)
{
    uint32_t v = 0;
    for (int i = 0; i < 4; i++) {
        int h = hex_value(d->p[i]);
        if (h < 0) {
            fail(d, "bad \\u escape");
        }
        v = (v << 4) | (uint32_t)h;
    }
    d->p += 4;
    return v;
}

static void add_utf8(luaL_Buffer *b, uint32_t cp)
{
    if (cp < 0x80) {
        luaL_addchar(b, (char)cp);
    } else if (cp < 0x800) {
        luaL_addchar(b, (char)(0xC0 | (cp >> 6)));
        luaL_addchar(b, (char)(0x80 | (cp & 0x3F)));
    } else if (cp < 0x10000) {
        luaL_addchar(b, (char)(0xE0 | (cp >> 12)));
        luaL_addchar(b, (char)(0x80 | ((cp >> 6) & 0x3F)));
        luaL_addchar(b, (char)(0x80 | (cp & 0x3F)));
    } else {
        luaL_addchar(b, (char)(0xF0 | (cp >> 18)));
        luaL_addchar(b, (char)(0x80 | ((cp >> 12) & 0x3F)));
        luaL_addchar(b, (char)(0x80 | ((cp >> 6) & 0x3F)));
        luaL_addchar(b, (char)(0x80 | (cp & 0x3F)));
    }
}

static void decode_string(decoder_t *d)
{
    luaL_Buffer b;
    luaL_buffinit(d->L, &b);
    d->p++; /* opening quote */
    for (;;) {
        unsigned char c = (unsigned char)*d->p;
        if (c == '"') {
            d->p++;
            break;
        }
        if (c == '\0') {
            fail(d, "unterminated string");
        }
        if (c < 0x20) {
            fail(d, "control character in string");
        }
        if (c != '\\') {
            luaL_addchar(&b, (char)c);
            d->p++;
            continue;
        }
        d->p++;
        char esc = *d->p++;
        switch (esc) {
        case '"':  luaL_addchar(&b, '"'); break;
        case '\\': luaL_addchar(&b, '\\'); break;
        case '/':  luaL_addchar(&b, '/'); break;
        case 'b':  luaL_addchar(&b, '\b'); break;
        case 'f':  luaL_addchar(&b, '\f'); break;
        case 'n':  luaL_addchar(&b, '\n'); break;
        case 'r':  luaL_addchar(&b, '\r'); break;
        case 't':  luaL_addchar(&b, '\t'); break;
        case 'u': {
            uint32_t cp = read_hex4(d);
            if (cp >= 0xD800 && cp <= 0xDBFF) {
                if (d->p[0] != '\\' || d->p[1] != 'u') {
                    fail(d, "unpaired surrogate");
                }
                d->p += 2;
                uint32_t lo = read_hex4(d);
                if (lo < 0xDC00 || lo > 0xDFFF) {
                    fail(d, "unpaired surrogate");
                }
                cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
            } else if (cp >= 0xDC00 && cp <= 0xDFFF) {
                fail(d, "unpaired surrogate");
            }
            add_utf8(&b, cp);
            break;
        }
        default:
            d->p--;
            fail(d, "bad escape");
        }
    }
    luaL_pushresult(&b);
}

static bool is_digit(char c)
{
    return c >= '0' && c <= '9';
}

static void decode_number(decoder_t *d)
{
    const char *s = d->p;
    if (*d->p == '-') d->p++;
    if (*d->p == '0') {
        d->p++;
    } else if (is_digit(*d->p)) {
        while (is_digit(*d->p)) d->p++;
    } else {
        fail(d, "bad number");
    }
    if (*d->p == '.') {
        d->p++;
        if (!is_digit(*d->p)) fail(d, "bad number");
        while (is_digit(*d->p)) d->p++;
    }
    if (*d->p == 'e' || *d->p == 'E') {
        d->p++;
        if (*d->p == '+' || *d->p == '-') d->p++;
        if (!is_digit(*d->p)) fail(d, "bad number");
        while (is_digit(*d->p)) d->p++;
    }

    size_t len = (size_t)(d->p - s);
    char buf[JSON_MAX_NUMBER];
    if (len >= sizeof(buf)) {
        fail(d, "number too long");
    }
    memcpy(buf, s, len);
    buf[len] = '\0';
    if (lua_stringtonumber(d->L, buf) == 0) {
        fail(d, "bad number");
    }
}

static void decode_literal(decoder_t *d, const char *word)
{
    size_t len = strlen(word);
    if (strncmp(d->p, word, len) != 0) {
        fail(d, "unexpected character");
    }
    d->p += len;
}

static void decode_value(decoder_t *d);

static void decode_container(decoder_t *d, char close)
{
    lua_State *L = d->L;
    if (++d->depth > JSON_MAX_DEPTH) {
        fail(d, "nested too deep");
    }
    luaL_checkstack(L, 4, "JSON decoding");
    lua_newtable(L);
    d->p++;
    skip_space(d);
    if (*d->p == close) {
        d->p++;
        d->depth--;
        return;
    }
    lua_Integer index = 1;
    for (;;) {
        skip_space(d);
        if (close == '}') {
            if (*d->p != '"') {
                fail(d, "expected a key");
            }
            decode_string(d);
            skip_space(d);
            if (*d->p != ':') {
                fail(d, "expected ':'");
            }
            d->p++;
            decode_value(d);
            lua_rawset(L, -3); /* a null value leaves the key unset */
        } else {
            decode_value(d);
            lua_rawseti(L, -2, index++);
        }
        skip_space(d);
        if (*d->p == ',') {
            d->p++;
        } else if (*d->p == close) {
            d->p++;
            break;
        } else {
            fail(d, close == '}' ? "expected ',' or '}'" : "expected ',' or ']'");
        }
    }
    d->depth--;
}

static void decode_value(decoder_t *d)
{
    skip_space(d);
    switch (*d->p) {
    case '{': decode_container(d, '}'); break;
    case '[': decode_container(d, ']'); break;
    case '"': decode_string(d); break;
    case 't': decode_literal(d, "true"); lua_pushboolean(d->L, 1); break;
    case 'f': decode_literal(d, "false"); lua_pushboolean(d->L, 0); break;
    case 'n': decode_literal(d, "null"); lua_pushnil(d->L); break;
    default:
        if (*d->p == '-' || is_digit(*d->p)) {
            decode_number(d);
        } else {
            fail(d, *d->p == '\0' ? "unexpected end" : "unexpected character");
        }
    }
}

void atalaia_json_push_decoded(lua_State *L, const char *text)
{
    decoder_t d = {L, text, text, 0};
    decode_value(&d);
    skip_space(&d);
    if (*d.p != '\0') {
        fail(&d, "trailing characters");
    }
}

/* ---- Plain C quoting for system events ----------------------------------- */

char *atalaia_json_quote(char *dst, size_t cap, const char *src)
{
    size_t n = 0;
    if (cap < 3) {
        if (cap > 0) {
            dst[0] = '\0';
        }
        return dst;
    }
    dst[n++] = '"';
    for (; src != NULL && *src != '\0'; src++) {
        unsigned char c = (unsigned char)*src;
        char esc[8];
        const char *out;
        if (c == '"') {
            out = "\\\"";
        } else if (c == '\\') {
            out = "\\\\";
        } else if (c < 0x20) {
            snprintf(esc, sizeof(esc), "\\u%04x", c);
            out = esc;
        } else {
            esc[0] = (char)c;
            esc[1] = '\0';
            out = esc;
        }
        size_t len = strlen(out);
        if (n + len + 2 > cap) {
            break; /* leave room for the closing quote and NUL */
        }
        memcpy(dst + n, out, len);
        n += len;
    }
    dst[n++] = '"';
    dst[n] = '\0';
    return dst;
}
