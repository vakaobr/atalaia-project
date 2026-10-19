/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Declarative screen templates (atalaia/screen_template.h): a YAML subset
 * parser, the template checks and the expression evaluator.
 */
#include "atalaia/screen_template.h"

#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ==== YAML subset ========================================================== */

enum { Y_SCALAR = 1, Y_MAP, Y_SEQ };
enum { S_PLAIN = 0, S_SINGLE, S_DOUBLE, S_NULL };

#define Y_NEST_MAX 20

typedef struct {
    atalaia_tpl_t *t;
    const char *src;
    size_t len;
    size_t pos;  /* start of the next unread line */
    int line_no; /* of the line at pos (1-based) */
    /* The current line, once peeked. */
    bool have;
    int indent;
    size_t start, end; /* content (comment and trailing spaces removed) */
    int at_line;
    size_t next_pos;
    int depth;
    char *err;
    size_t err_cap;
    bool failed;
} yp_t;

static bool fail(yp_t *p, int line, const char *fmt, ...)
{
    if (!p->failed && p->err && p->err_cap > 0) {
        int n = snprintf(p->err, p->err_cap, "line %d: ", line);
        if (n >= 0 && (size_t)n < p->err_cap) {
            va_list ap;
            va_start(ap, fmt);
            vsnprintf(p->err + n, p->err_cap - (size_t)n, fmt, ap);
            va_end(ap);
        }
    }
    p->failed = true;
    return false;
}

static bool is_space(char c)
{
    return c == ' ' || c == '\t';
}

/* Finds where a line's content ends: before a comment, without trailing spaces. */
static size_t content_end(const char *s, size_t a, size_t b)
{
    bool single = false, dbl = false;
    size_t end = b;
    for (size_t i = a; i < b; i++) {
        char c = s[i];
        if (dbl) {
            if (c == '\\' && i + 1 < b) {
                i++;
            } else if (c == '"') {
                dbl = false;
            }
        } else if (single) {
            if (c == '\'') single = false;
        } else if (c == '"') {
            dbl = true;
        } else if (c == '\'') {
            single = true;
        } else if (c == '#' && (i == a || is_space(s[i - 1]))) {
            end = i;
            break;
        }
    }
    while (end > a && is_space(s[end - 1])) end--;
    return end;
}

/* Loads the next line with content into the "current line" fields. */
static bool peek(yp_t *p)
{
    if (p->have) return true;
    while (p->pos < p->len) {
        size_t a = p->pos;
        size_t b = a;
        while (b < p->len && p->src[b] != '\n') b++;
        size_t next = b < p->len ? b + 1 : b;
        size_t line_end = b;
        if (line_end > a && p->src[line_end - 1] == '\r') line_end--;
        int line = p->line_no;
        p->pos = next;
        p->line_no++;

        size_t i = a;
        while (i < line_end && p->src[i] == ' ') i++;
        if (i < line_end && p->src[i] == '\t') {
            return fail(p, line, "tabs are not allowed for indentation");
        }
        size_t end = content_end(p->src, i, line_end);
        if (end == i) continue; /* blank or comment only */
        if (end - i >= 3 &&
            (memcmp(p->src + i, "---", 3) == 0 || memcmp(p->src + i, "...", 3) == 0) &&
            (end - i == 3 || is_space(p->src[i + 3]))) {
            return fail(p, line, "only one YAML document is allowed");
        }
        p->have = true;
        p->indent = (int)(i - a);
        p->start = i;
        p->end = end;
        p->at_line = line;
        return true;
    }
    return false;
}

static void consume(yp_t *p)
{
    p->have = false;
}

static int new_node(yp_t *p, uint8_t kind, int line)
{
    atalaia_tpl_t *t = p->t;
    if (t->yaml_count >= ATALAIA_TPL_YAML_MAX) {
        fail(p, line, "the template is too large (more than %d YAML nodes)", ATALAIA_TPL_YAML_MAX);
        return -1;
    }
    atalaia_tpl_yaml_t *y = &t->yaml[t->yaml_count];
    memset(y, 0, sizeof(*y));
    y->kind = kind;
    y->line = (uint16_t)line;
    y->child = -1;
    y->next = -1;
    return t->yaml_count++;
}

static void append_child(yp_t *p, int parent, int child, int *last)
{
    if (*last < 0) {
        p->t->yaml[parent].child = (int16_t)child;
    } else {
        p->t->yaml[*last].next = (int16_t)child;
    }
    *last = child;
}

/* A quoted scalar starting at s[a]; returns the index after its closing quote, or 0. */
static size_t quoted_end(const char *s, size_t a, size_t b)
{
    char q = s[a];
    for (size_t i = a + 1; i < b; i++) {
        if (q == '"' && s[i] == '\\') {
            i++;
        } else if (s[i] == q) {
            if (q == '\'' && i + 1 < b && s[i + 1] == '\'') {
                i++;
                continue;
            }
            return i + 1;
        }
    }
    return 0;
}

/* A scalar from s[a..b): quoted (the whole range) or plain. */
static int scalar(yp_t *p, size_t a, size_t b, int line, bool flow)
{
    int n = new_node(p, Y_SCALAR, line);
    if (n < 0) return -1;
    atalaia_tpl_yaml_t *y = &p->t->yaml[n];
    const char *s = p->src;
    if (a == b) {
        y->style = S_NULL;
        return n;
    }
    char c = s[a];
    if (c == '"' || c == '\'') {
        size_t e = quoted_end(s, a, b);
        if (e == 0) return fail(p, line, "unterminated quoted text"), -1;
        if (e != b) return fail(p, line, "unexpected text after a quoted value"), -1;
        y->style = c == '"' ? S_DOUBLE : S_SINGLE;
    } else {
        if (c == '&' || c == '*' || c == '!') {
            return fail(p, line, "anchors, aliases and tags are not supported"), -1;
        }
        if (c == '|' || c == '>') return fail(p, line, "block scalars are not supported"), -1;
        if (c == '[') return fail(p, line, "flow sequences are not supported"), -1;
        if (c == '{') return fail(p, line, "flow mappings cannot be nested"), -1;
        for (size_t i = a; i < b; i++) {
            if (s[i] == ':' && (i + 1 == b || is_space(s[i + 1]))) {
                return fail(p, line, "a plain value cannot contain ': ' (quote it)"), -1;
            }
            if (flow && (s[i] == '{' || s[i] == '}' || s[i] == '[' || s[i] == ']')) {
                return fail(p, line, "brackets in a flow mapping value must be quoted"), -1;
            }
        }
        y->style = S_PLAIN;
    }
    if (b - a > 0xFFFF) return fail(p, line, "value too long"), -1;
    y->val = (uint16_t)a;
    y->val_len = (uint16_t)(b - a);
    return n;
}

static bool key_char(char c, bool first)
{
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_' ||
           (!first && c >= '0' && c <= '9');
}

/* A key at s[a]: returns its length (followed by ':' and a space or the end), or 0. */
static size_t key_at(const char *s, size_t a, size_t b)
{
    size_t i = a;
    while (i < b && key_char(s[i], i == a)) i++;
    if (i == a || i >= b || s[i] != ':') return 0;
    if (i + 1 < b && !is_space(s[i + 1])) return 0;
    return i - a;
}

static bool same_key(yp_t *p, int parent, size_t key, size_t key_len)
{
    for (int c = p->t->yaml[parent].child; c >= 0; c = p->t->yaml[c].next) {
        const atalaia_tpl_yaml_t *y = &p->t->yaml[c];
        if (y->key_len == key_len && memcmp(p->src + y->key, p->src + key, key_len) == 0)
            return true;
    }
    return false;
}

static int set_key(yp_t *p, int node, int parent, size_t key, size_t key_len, int line)
{
    if (node < 0) return -1;
    if (key_len > 255) return fail(p, line, "key too long"), -1;
    if (same_key(p, parent, key, key_len)) {
        return fail(p, line, "duplicate key '%.*s'", (int)key_len, p->src + key), -1;
    }
    p->t->yaml[node].key = (uint16_t)key;
    p->t->yaml[node].key_len = (uint8_t)key_len;
    return node;
}

/* { key: value, ... } on one line, from s[a] ('{') to s[b-1] ('}'). */
static int flow_map(yp_t *p, size_t a, size_t b, int line)
{
    const char *s = p->src;
    if (b - a < 2 || s[b - 1] != '}')
        return fail(p, line, "a flow mapping must end the line with '}'"), -1;
    int map = new_node(p, Y_MAP, line);
    if (map < 0) return -1;
    int last = -1;
    size_t i = a + 1;
    size_t close = b - 1;
    for (;;) {
        while (i < close && is_space(s[i])) i++;
        if (i == close) break;
        size_t kl = key_at(s, i, close);
        if (kl == 0) return fail(p, line, "expected 'key: value' in the flow mapping"), -1;
        size_t key = i;
        i += kl + 1;
        while (i < close && is_space(s[i])) i++;
        size_t v = i;
        size_t ve;
        if (i < close && (s[i] == '"' || s[i] == '\'')) {
            ve = quoted_end(s, i, close);
            if (ve == 0) return fail(p, line, "unterminated quoted text"), -1;
            i = ve;
            while (i < close && is_space(s[i])) i++;
            if (i < close && s[i] != ',') return fail(p, line, "expected ',' or '}'"), -1;
        } else {
            while (i < close && s[i] != ',') i++;
            ve = i;
            while (ve > v && is_space(s[ve - 1])) ve--;
        }
        int n = set_key(p, scalar(p, v, ve, line, true), map, key, kl, line);
        if (n < 0) return -1;
        append_child(p, map, n, &last);
        if (i < close && s[i] == ',') {
            i++;
            size_t j = i;
            while (j < close && is_space(s[j])) j++;
            if (j == close) return fail(p, line, "a trailing ',' in a flow mapping"), -1;
        }
    }
    return map;
}

/* A value on the same line as its key or dash: s[a..b). */
static int inline_value(yp_t *p, size_t a, size_t b, int line)
{
    if (a < b && p->src[a] == '{') return flow_map(p, a, b, line);
    return scalar(p, a, b, line, false);
}

static int parse_block(yp_t *p, int indent);

/* The value after "key:" with nothing more on the line: a nested block, a
 * sequence at the key's own indentation, or null. */
static int nested_value(yp_t *p, int indent, int line)
{
    if (peek(p)) {
        bool dash =
            p->src[p->start] == '-' && (p->end == p->start + 1 || is_space(p->src[p->start + 1]));
        if (p->indent > indent || (p->indent == indent && dash)) {
            return parse_block(p, p->indent);
        }
    }
    if (p->failed) return -1;
    return scalar(p, 0, 0, line, false); /* null */
}

static int parse_map(yp_t *p, int indent)
{
    int map = new_node(p, Y_MAP, p->have ? p->at_line : p->line_no);
    if (map < 0) return -1;
    int last = -1;
    while (peek(p)) {
        if (p->indent < indent) break;
        int line = p->at_line;
        if (p->indent > indent) return fail(p, line, "unexpected indentation"), -1;
        const char *s = p->src;
        size_t a = p->start, b = p->end;
        if (s[a] == '-' && (b == a + 1 || is_space(s[a + 1]))) {
            return fail(p, line, "a list item where a 'key: value' was expected"), -1;
        }
        size_t kl = key_at(s, a, b);
        if (kl == 0) return fail(p, line, "expected 'key: value'"), -1;
        size_t v = a + kl + 1;
        while (v < b && is_space(s[v])) v++;
        consume(p);
        int n = v < b ? inline_value(p, v, b, line) : nested_value(p, indent, line);
        n = set_key(p, n, map, a, kl, line);
        if (n < 0) return -1;
        append_child(p, map, n, &last);
    }
    return p->failed ? -1 : map;
}

static int parse_seq(yp_t *p, int indent)
{
    int seq = new_node(p, Y_SEQ, p->at_line);
    if (seq < 0) return -1;
    int last = -1;
    while (peek(p)) {
        if (p->indent < indent) break;
        int line = p->at_line;
        if (p->indent > indent) return fail(p, line, "unexpected indentation"), -1;
        const char *s = p->src;
        size_t a = p->start, b = p->end;
        if (!(s[a] == '-' && (b == a + 1 || is_space(s[a + 1])))) break;
        size_t v = a + 1;
        while (v < b && is_space(s[v])) v++;
        int n;
        if (v == b) {
            consume(p);
            n = nested_value(p, indent, line);
        } else if (key_at(s, v, b) > 0) {
            /* "- key: value": a mapping whose entries line up with this key. */
            p->indent = (int)(v - (a - (size_t)p->indent));
            p->start = v;
            n = parse_block(p, p->indent);
        } else {
            consume(p);
            n = inline_value(p, v, b, line);
        }
        if (n < 0) return -1;
        append_child(p, seq, n, &last);
    }
    return p->failed ? -1 : seq;
}

static int parse_block(yp_t *p, int indent)
{
    if (!peek(p)) return -1;
    if (++p->depth > Y_NEST_MAX) return fail(p, p->at_line, "nested too deeply"), -1;
    const char *s = p->src;
    int n;
    if (s[p->start] == '-' && (p->end == p->start + 1 || is_space(s[p->start + 1]))) {
        n = parse_seq(p, indent);
    } else {
        n = parse_map(p, indent);
    }
    p->depth--;
    return n;
}

/* ==== From YAML to a template ============================================== */

typedef struct {
    yp_t *p;
    atalaia_tpl_t *t;
} conv_t;

static const atalaia_tpl_yaml_t *Y(conv_t *c, int i)
{
    return &c->t->yaml[i];
}

static bool key_is(conv_t *c, int i, const char *k)
{
    const atalaia_tpl_yaml_t *y = Y(c, i);
    return y->key_len == strlen(k) && memcmp(c->p->src + y->key, k, y->key_len) == 0;
}

static int child(conv_t *c, int map, const char *k)
{
    for (int i = Y(c, map)->child; i >= 0; i = Y(c, i)->next) {
        if (key_is(c, i, k)) return i;
    }
    return -1;
}

/* Appends the UTF-8 encoding of a code point. */
static size_t put_utf8(char *out, uint32_t cp)
{
    if (cp < 0x80) {
        out[0] = (char)cp;
        return 1;
    }
    if (cp < 0x800) {
        out[0] = (char)(0xC0 | (cp >> 6));
        out[1] = (char)(0x80 | (cp & 0x3F));
        return 2;
    }
    out[0] = (char)(0xE0 | (cp >> 12));
    out[1] = (char)(0x80 | ((cp >> 6) & 0x3F));
    out[2] = (char)(0x80 | (cp & 0x3F));
    return 3;
}

static int hexval(char h)
{
    if (h >= '0' && h <= '9') return h - '0';
    if (h >= 'a' && h <= 'f') return h - 'a' + 10;
    if (h >= 'A' && h <= 'F') return h - 'A' + 10;
    return -1;
}

/* Copies a scalar's text into the pool. Returns its offset, or 0 on failure. */
static uint16_t store(conv_t *c, int i)
{
    const atalaia_tpl_yaml_t *y = Y(c, i);
    atalaia_tpl_t *t = c->t;
    const char *s = c->p->src + y->val;
    size_t n = y->val_len;
    /* The decoded text is never longer than the source. */
    if ((size_t)t->pool_used + n + 1 > ATALAIA_TPL_POOL_MAX) {
        fail(c->p, y->line, "the template's text is too long (%d bytes in all)",
             ATALAIA_TPL_POOL_MAX);
        return 0;
    }
    char *out = t->pool + t->pool_used;
    size_t o = 0;
    if (y->style == S_DOUBLE) {
        for (size_t k = 1; k + 1 < n; k++) {
            char ch = s[k];
            if (ch != '\\') {
                out[o++] = ch;
                continue;
            }
            char e = s[++k];
            switch (e) {
            case 'n': out[o++] = '\n'; break;
            case 't': out[o++] = '\t'; break;
            case '"': out[o++] = '"'; break;
            case '\\': out[o++] = '\\'; break;
            case '/': out[o++] = '/'; break;
            case 'u': {
                uint32_t cp = 0;
                for (int d = 0; d < 4; d++) {
                    int h = k + 1 < n - 1 ? hexval(s[k + 1]) : -1;
                    if (h < 0) {
                        fail(c->p, y->line, "bad \\u escape");
                        return 0;
                    }
                    cp = cp * 16 + (uint32_t)h;
                    k++;
                }
                if (cp == 0 || (cp >= 0xD800 && cp <= 0xDFFF)) {
                    fail(c->p, y->line, "bad \\u escape");
                    return 0;
                }
                o += put_utf8(out + o, cp);
                break;
            }
            default: fail(c->p, y->line, "unknown escape '\\%c'", e); return 0;
            }
        }
    } else if (y->style == S_SINGLE) {
        for (size_t k = 1; k + 1 < n; k++) {
            out[o++] = s[k];
            if (s[k] == '\'') k++; /* '' is one quote */
        }
    } else if (y->style == S_PLAIN) {
        memcpy(out, s, n);
        o = n;
    }
    out[o] = '\0';
    uint16_t off = t->pool_used;
    t->pool_used = (uint16_t)(t->pool_used + o + 1);
    return off;
}

/* A scalar as text in a scratch buffer (for checks; never stored). */
static bool text_of(conv_t *c, int i, char *buf, size_t cap)
{
    const atalaia_tpl_yaml_t *y = Y(c, i);
    if (y->kind != Y_SCALAR || y->style == S_NULL) return false;
    uint16_t before = c->t->pool_used;
    uint16_t off = store(c, i);
    if (off == 0 && c->p->failed) return false;
    snprintf(buf, cap, "%s", c->t->pool + off);
    c->t->pool_used = before;
    return true;
}

static bool want_scalar(conv_t *c, int i, const char *what)
{
    if (Y(c, i)->kind != Y_SCALAR || Y(c, i)->style == S_NULL) {
        return fail(c->p, Y(c, i)->line, "%s must be a value", what);
    }
    return true;
}

static bool parse_int(const char *s, long lo, long hi, long *out)
{
    if (*s == '\0') return false;
    char *end;
    long v = strtol(s, &end, 10);
    if (*end != '\0' || v < lo || v > hi) return false;
    *out = v;
    return true;
}

/* ---- expressions ---------------------------------------------------------- */

/* Value kinds while evaluating. */
enum { V_NIL = 0, V_NUM, V_STR, V_BOOL };

typedef struct {
    int kind;
    double num;
    const char *str; /* decoded, NUL-terminated (inside the evaluator's scratch) */
    size_t len;
} val_t;

typedef struct {
    const char *s; /* the expression */
    size_t len;
    size_t i;
    const atalaia_tpl_scope_t *scope; /* NULL: syntax check only */
    char scratch[256];                /* decoded strings */
    size_t used;
    bool error;
    const char *why;
} ev_t;

static void skip_ws(ev_t *e)
{
    while (e->i < e->len && is_space(e->s[e->i])) e->i++;
}

static bool at(ev_t *e, const char *op)
{
    size_t n = strlen(op);
    skip_ws(e);
    if (e->len - e->i >= n && memcmp(e->s + e->i, op, n) == 0) {
        /* "<" must not match "<=", "!" must not match "!=", "|" never stands alone here. */
        if (n == 1 && e->i + 1 < e->len && e->s[e->i + 1] == '=' &&
            (op[0] == '<' || op[0] == '>' || op[0] == '!' || op[0] == '=')) {
            return false;
        }
        e->i += n;
        return true;
    }
    return false;
}

static void ev_fail(ev_t *e, const char *why)
{
    if (!e->error) e->why = why;
    e->error = true;
}

static val_t nil(void)
{
    val_t v = {V_NIL, 0, NULL, 0};
    return v;
}

static val_t num(double d)
{
    val_t v = {V_NUM, d, NULL, 0};
    return v;
}

static double as_num(val_t v)
{
    if (v.kind == V_NUM || v.kind == V_BOOL) return v.num;
    return 0.0;
}

static bool truth(val_t v)
{
    switch (v.kind) {
    case V_NUM:
    case V_BOOL: return v.num != 0.0;
    case V_STR: return v.len > 0;
    default: return false;
    }
}

/* ---- JSON lookups --------------------------------------------------------- */

static const char *jws(const char *p)
{
    while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r') p++;
    return p;
}

static const char *jskip_string(const char *p)
{
    p++;
    while (*p && *p != '"') {
        if (*p == '\\' && p[1]) p++;
        p++;
    }
    return *p == '"' ? p + 1 : NULL;
}

static const char *jskip_value(const char *p)
{
    p = jws(p);
    if (*p == '"') return jskip_string(p);
    if (*p == '{' || *p == '[') {
        int depth = 0;
        while (*p) {
            if (*p == '"') {
                p = jskip_string(p);
                if (!p) return NULL;
                continue;
            }
            if (*p == '{' || *p == '[') depth++;
            if (*p == '}' || *p == ']') {
                if (--depth == 0) return p + 1;
            }
            p++;
        }
        return NULL;
    }
    while (*p && *p != ',' && *p != '}' && *p != ']' && !is_space(*p) && *p != '\n' && *p != '\r') {
        p++;
    }
    return p;
}

/* The value of key k (k_len bytes) in the object at obj, or NULL. */
static const char *jfind(const char *obj, const char *k, size_t k_len)
{
    const char *p = jws(obj);
    if (*p != '{') return NULL;
    p = jws(p + 1);
    while (*p == '"') {
        const char *name = p + 1;
        const char *after = jskip_string(p);
        if (!after) return NULL;
        bool match = (size_t)(after - 1 - name) == k_len && memcmp(name, k, k_len) == 0;
        p = jws(after);
        if (*p != ':') return NULL;
        p = jws(p + 1);
        if (match) return p;
        p = jskip_value(p);
        if (!p) return NULL;
        p = jws(p);
        if (*p != ',') return NULL;
        p = jws(p + 1);
    }
    return NULL;
}

/* Decodes the JSON string at p into the evaluator's scratch. */
static val_t jstring(ev_t *e, const char *p)
{
    size_t room = sizeof(e->scratch) - e->used;
    if (room < 2) return nil();
    char *out = e->scratch + e->used;
    size_t o = 0;
    p++;
    while (*p && *p != '"') {
        char ch = *p++;
        char tmp[4];
        size_t n = 1;
        tmp[0] = ch;
        if (ch == '\\' && *p) {
            char x = *p++;
            switch (x) {
            case 'n':
            case 'r':
            case 't': tmp[0] = ' '; break;
            case 'u': {
                uint32_t cp = 0;
                for (int d = 0; d < 4 && *p; d++, p++) {
                    int h = hexval(*p);
                    cp = cp * 16 + (uint32_t)(h < 0 ? 0 : h);
                }
                if (cp == 0 || (cp >= 0xD800 && cp <= 0xDFFF)) cp = '?';
                n = put_utf8(tmp, cp);
                break;
            }
            default: tmp[0] = x; break; /* \" \\ \/ */
            }
        }
        if (o + n + 1 > room) break;
        memcpy(out + o, tmp, n);
        o += n;
    }
    out[o] = '\0';
    e->used += o + 1;
    val_t v = {V_STR, 0, out, o};
    return v;
}

static val_t lookup(ev_t *e, const char *name, size_t len)
{
    if (!e->scope) return nil();
    const char *obj = e->scope->data;
    size_t a = 0;
    if (len >= 7 && memcmp(name, "params.", 7) == 0) {
        obj = e->scope->params;
        a = 7;
    }
    if (!obj) return nil();
    const char *p = obj;
    while (a < len) {
        size_t b = a;
        while (b < len && name[b] != '.') b++;
        p = jfind(p, name + a, b - a);
        if (!p) return nil();
        a = b + 1;
    }
    p = jws(p);
    if (*p == '"') return jstring(e, p);
    if (strncmp(p, "true", 4) == 0) {
        val_t v = {V_BOOL, 1, NULL, 0};
        return v;
    }
    if (strncmp(p, "false", 5) == 0) {
        val_t v = {V_BOOL, 0, NULL, 0};
        return v;
    }
    if (*p == '-' || (*p >= '0' && *p <= '9')) {
        char *end;
        double d = strtod(p, &end);
        return end == p ? nil() : num(d);
    }
    return nil(); /* null, objects and arrays */
}

/* ---- the grammar ------------------------------------------------------------
 *   or   := and ('||' and)*
 *   and  := cmp ('&&' cmp)*
 *   cmp  := sum (('<' | '<=' | '>' | '>=' | '==' | '!=') sum)?
 *   sum  := prod (('+' | '-') prod)*
 *   prod := unary (('*' | '/') unary)*
 *   unary:= ('-' | '!') unary | atom
 *   atom := number | 'text' | name ('.' name)* | '(' or ')'
 */

static val_t ev_or(ev_t *e, int depth);

static val_t atom(ev_t *e, int depth)
{
    skip_ws(e);
    if (e->i >= e->len) {
        ev_fail(e, "an expression is missing");
        return nil();
    }
    char c = e->s[e->i];
    if (c == '(') {
        e->i++;
        val_t v = ev_or(e, depth + 1);
        if (!at(e, ")")) ev_fail(e, "a ')' is missing");
        return v;
    }
    if ((c >= '0' && c <= '9') || c == '.') {
        size_t a = e->i;
        while (e->i < e->len && ((e->s[e->i] >= '0' && e->s[e->i] <= '9') || e->s[e->i] == '.')) {
            e->i++;
        }
        char buf[32];
        size_t n = e->i - a;
        if (n >= sizeof(buf)) {
            ev_fail(e, "number too long");
            return nil();
        }
        memcpy(buf, e->s + a, n);
        buf[n] = '\0';
        char *end;
        double d = strtod(buf, &end);
        if (*end != '\0') ev_fail(e, "bad number");
        return num(d);
    }
    if (c == '\'') {
        size_t a = ++e->i;
        while (e->i < e->len && e->s[e->i] != '\'') e->i++;
        if (e->i >= e->len) {
            ev_fail(e, "unterminated 'text'");
            return nil();
        }
        size_t n = e->i - a;
        e->i++;
        size_t room = sizeof(e->scratch) - e->used;
        if (n + 1 > room) {
            ev_fail(e, "text too long");
            return nil();
        }
        char *out = e->scratch + e->used;
        memcpy(out, e->s + a, n);
        out[n] = '\0';
        e->used += n + 1;
        val_t v = {V_STR, 0, out, n};
        return v;
    }
    if (key_char(c, true)) {
        size_t a = e->i;
        for (;;) {
            while (e->i < e->len && key_char(e->s[e->i], e->i == a)) e->i++;
            if (e->i < e->len && e->s[e->i] == '.' && e->i + 1 < e->len &&
                key_char(e->s[e->i + 1], true)) {
                e->i++;
                continue;
            }
            break;
        }
        size_t n = e->i - a;
        if ((n == 4 && memcmp(e->s + a, "true", 4) == 0) ||
            (n == 5 && memcmp(e->s + a, "false", 5) == 0)) {
            val_t v = {V_BOOL, n == 4 ? 1 : 0, NULL, 0};
            return v;
        }
        if (n == 3 && memcmp(e->s + a, "nil", 3) == 0) return nil();
        return lookup(e, e->s + a, n);
    }
    ev_fail(e, "unexpected character");
    return nil();
}

static val_t unary(ev_t *e, int depth)
{
    if (depth > 32) {
        ev_fail(e, "nested too deeply");
        return nil();
    }
    if (at(e, "-")) return num(-as_num(unary(e, depth + 1)));
    if (at(e, "!")) {
        val_t v = unary(e, depth + 1);
        return num(truth(v) ? 0 : 1);
    }
    return atom(e, depth);
}

static val_t prod(ev_t *e, int depth)
{
    val_t v = unary(e, depth);
    for (;;) {
        if (at(e, "*")) {
            v = num(as_num(v) * as_num(unary(e, depth)));
        } else if (at(e, "/")) {
            double d = as_num(unary(e, depth));
            v = num(d == 0.0 ? 0.0 : as_num(v) / d);
        } else {
            return v;
        }
    }
}

static val_t sum(ev_t *e, int depth)
{
    val_t v = prod(e, depth);
    for (;;) {
        if (at(e, "+")) {
            v = num(as_num(v) + as_num(prod(e, depth)));
        } else if (at(e, "-")) {
            v = num(as_num(v) - as_num(prod(e, depth)));
        } else {
            return v;
        }
    }
}

static int compare(val_t a, val_t b, bool *comparable)
{
    *comparable = true;
    if (a.kind == V_STR && b.kind == V_STR) {
        int c = strcmp(a.str, b.str);
        return c < 0 ? -1 : c > 0;
    }
    if (a.kind == V_STR || b.kind == V_STR) {
        *comparable = false; /* text against a number or nil: only != holds */
        return 1;
    }
    double x = as_num(a), y = as_num(b);
    return x < y ? -1 : x > y;
}

static val_t cmp(ev_t *e, int depth)
{
    val_t a = sum(e, depth);
    static const char *const ops[] = {"<=", ">=", "==", "!=", "<", ">"};
    for (size_t k = 0; k < sizeof(ops) / sizeof(ops[0]); k++) {
        if (!at(e, ops[k])) continue;
        val_t b = sum(e, depth);
        bool ok;
        int c = compare(a, b, &ok);
        bool r;
        switch (k) {
        case 0: r = ok && c <= 0; break;
        case 1: r = ok && c >= 0; break;
        case 2: r = ok && c == 0; break;
        case 3: r = !ok || c != 0; break;
        case 4: r = ok && c < 0; break;
        default: r = ok && c > 0; break;
        }
        return num(r ? 1 : 0);
    }
    return a;
}

static val_t and_(ev_t *e, int depth)
{
    val_t v = cmp(e, depth);
    while (at(e, "&&")) {
        val_t w = cmp(e, depth);
        if (truth(v)) v = w; /* Lua: a and b */
    }
    return v;
}

static val_t ev_or(ev_t *e, int depth)
{
    val_t v = and_(e, depth);
    while (at(e, "||")) {
        val_t w = and_(e, depth);
        if (!truth(v)) v = w; /* Lua: a or b */
    }
    return v;
}

static val_t evaluate(ev_t *e, const char *s, size_t len, const atalaia_tpl_scope_t *scope)
{
    memset(e, 0, sizeof(*e));
    e->s = s;
    e->len = len;
    e->scope = scope;
    val_t v = ev_or(e, 0);
    skip_ws(e);
    if (e->i != e->len) ev_fail(e, "unexpected text after the expression");
    return e->error ? nil() : v;
}

bool atalaia_tpl_expr_ok(const char *expr, size_t len, char *err, size_t err_cap)
{
    ev_t e;
    evaluate(&e, expr, len, NULL);
    if (e.error && err && err_cap) snprintf(err, err_cap, "%s", e.why);
    return !e.error;
}

/* ---- text with {expressions} -------------------------------------------- */

enum { F_NONE = 0, F_CLOCK, F_UPPER, F_INT, F_BAD };

/* Splits "{expr|filter}" contents: returns the expression length and the filter. */
static size_t split_filter(const char *s, size_t n, int *filter)
{
    *filter = F_NONE;
    bool quoted = false;
    for (size_t i = 0; i < n; i++) {
        if (s[i] == '\'') quoted = !quoted;
        if (quoted || s[i] != '|') continue;
        if (i + 1 < n && s[i + 1] == '|') {
            i++;
            continue;
        }
        const char *f = s + i + 1;
        size_t fl = n - i - 1;
        while (fl > 0 && is_space(*f)) f++, fl--;
        while (fl > 0 && is_space(f[fl - 1])) fl--;
        if (fl == 5 && memcmp(f, "clock", 5) == 0) {
            *filter = F_CLOCK;
        } else if (fl == 5 && memcmp(f, "upper", 5) == 0) {
            *filter = F_UPPER;
        } else if (fl == 3 && memcmp(f, "int", 3) == 0) {
            *filter = F_INT;
        } else {
            *filter = F_BAD;
        }
        return i;
    }
    return n;
}

typedef struct {
    char *out;
    size_t cap;
    size_t len;
} sbuf_t;

static void sput(sbuf_t *b, const char *s, size_t n)
{
    if (b->cap == 0) return;
    size_t room = b->cap - 1 - b->len;
    if (n > room) n = room;
    memcpy(b->out + b->len, s, n);
    b->len += n;
    b->out[b->len] = '\0';
}

static void format_number(double d, char *buf, size_t cap)
{
    if (!isfinite(d)) {
        snprintf(buf, cap, "0");
    } else if (d == floor(d) && fabs(d) < 1e15) {
        snprintf(buf, cap, "%lld", (long long)d);
    } else {
        snprintf(buf, cap, "%.2f", d);
        size_t n = strlen(buf);
        while (n > 0 && buf[n - 1] == '0') buf[--n] = '\0';
        if (n > 0 && buf[n - 1] == '.') buf[--n] = '\0';
    }
}

static void put_value(sbuf_t *b, val_t v, int filter)
{
    char buf[40];
    if (filter == F_CLOCK) {
        double d = as_num(v);
        /* Clamped first: a double beyond long long's range cannot be converted
         * (undefined behaviour; x86 and ARM give different answers). 1e15 s is
         * over 31 million years. */
        if (isfinite(d) && d > 1e15) d = 1e15;
        long long s = d > 0 && isfinite(d) ? (long long)ceil(d - 1e-9) : 0;
        if (s >= 3600) {
            snprintf(buf, sizeof(buf), "%lld:%02lld:%02lld", s / 3600, (s / 60) % 60, s % 60);
        } else {
            snprintf(buf, sizeof(buf), "%lld:%02lld", s / 60, s % 60);
        }
        sput(b, buf, strlen(buf));
        return;
    }
    if (filter == F_INT) {
        double d = as_num(v);
        format_number(isfinite(d) ? floor(d) : 0, buf, sizeof(buf));
        sput(b, buf, strlen(buf));
        return;
    }
    size_t start = b->len;
    switch (v.kind) {
    case V_NUM:
        format_number(v.num, buf, sizeof(buf));
        sput(b, buf, strlen(buf));
        break;
    case V_BOOL: sput(b, v.num != 0 ? "true" : "false", v.num != 0 ? 4 : 5); break;
    case V_STR: sput(b, v.str, v.len); break;
    default: break;
    }
    if (filter == F_UPPER) {
        for (size_t i = start; i < b->len; i++) {
            if (b->out[i] >= 'a' && b->out[i] <= 'z') b->out[i] = (char)(b->out[i] - 'a' + 'A');
        }
    }
}

size_t atalaia_tpl_text(const char *text, const atalaia_tpl_scope_t *scope, char *out, size_t cap)
{
    sbuf_t b = {out, cap, 0};
    if (cap == 0) return 0;
    out[0] = '\0';
    if (!text) return 0;
    size_t n = strlen(text);
    for (size_t i = 0; i < n; i++) {
        char c = text[i];
        if ((c == '{' || c == '}') && i + 1 < n && text[i + 1] == c) {
            sput(&b, &c, 1);
            i++;
            continue;
        }
        if (c != '{') {
            sput(&b, &c, 1);
            continue;
        }
        size_t close = i + 1;
        while (close < n && text[close] != '}') close++;
        if (close >= n) break; /* checked at parse time */
        int filter;
        size_t elen = split_filter(text + i + 1, close - i - 1, &filter);
        ev_t e;
        val_t v = evaluate(&e, text + i + 1, elen, scope);
        put_value(&b, v, filter);
        i = close;
    }
    return b.len;
}

/* "{expr}" covering the whole value: its expression. */
static bool whole_expr(const char *v, size_t *a, size_t *len)
{
    size_t n = strlen(v);
    if (n < 2 || v[0] != '{' || v[n - 1] != '}') return false;
    for (size_t i = 1; i + 1 < n; i++) {
        if (v[i] == '{' || v[i] == '}') return false;
    }
    *a = 1;
    *len = n - 2;
    return true;
}

bool atalaia_tpl_truthy(const char *value, const atalaia_tpl_scope_t *scope)
{
    if (!value || strcmp(value, "true") == 0) return true;
    if (strcmp(value, "false") == 0) return false;
    size_t a, len;
    if (!whole_expr(value, &a, &len)) return true;
    ev_t e;
    return truth(evaluate(&e, value + a, len, scope));
}

double atalaia_tpl_fraction(const char *value, const atalaia_tpl_scope_t *scope)
{
    if (!value) return 0.0;
    double d;
    size_t a, len;
    if (whole_expr(value, &a, &len)) {
        ev_t e;
        d = as_num(evaluate(&e, value + a, len, scope));
    } else {
        d = strtod(value, NULL);
    }
    if (!(d > 0.0)) return 0.0; /* also NaN */
    return d > 1.0 ? 1.0 : d;
}

/* ---- colours --------------------------------------------------------------- */

static const struct {
    const char *name;
    uint32_t rgb;
} palette[] = {
    /* Team colours: the same as the Field Box's built-in screens. */
    {"red", 0xE53935},
    {"blue", 0x1E88E5},
    {"green", 0x43A047},
    {"yellow", 0xFDD835},
    {"orange", 0xFB8C00},
    {"purple", 0x8E24AA},
    /* Interface colours. */
    {"white", 0xFFFFFF},
    {"black", 0x000000},
    {"grey", 0x78909C},
    {"muted", 0x9AA5B1},
    {"accent", 0xFFB300},
    {"danger", 0xE53935},
    {"panel", 0x222B35},
    {"background", 0x101418},
};

bool atalaia_tpl_color(const char *name, uint32_t *rgb)
{
    if (!name || !*name) return false;
    if (name[0] == '#') {
        if (strlen(name) != 7) return false;
        uint32_t v = 0;
        for (int i = 1; i < 7; i++) {
            int h = hexval(name[i]);
            if (h < 0) return false;
            v = v << 4 | (uint32_t)h;
        }
        *rgb = v;
        return true;
    }
    for (size_t i = 0; i < sizeof(palette) / sizeof(palette[0]); i++) {
        const char *a = palette[i].name;
        const char *b = name;
        while (*a && (*b | 0x20) == *a) a++, b++;
        if (*a == '\0' && *b == '\0') {
            *rgb = palette[i].rgb;
            return true;
        }
    }
    return false;
}

/* ---- checks on template values ---------------------------------------------- */

/* Every {expression} in a text: balanced, parseable, known filter. */
static bool check_text(conv_t *c, int line, const char *text, bool filters)
{
    size_t n = strlen(text);
    for (size_t i = 0; i < n; i++) {
        char ch = text[i];
        if ((ch == '{' || ch == '}') && i + 1 < n && text[i + 1] == ch) {
            i++;
            continue;
        }
        if (ch == '}') return fail(c->p, line, "a '}' without its '{' (write }} for a brace)");
        if (ch != '{') continue;
        size_t close = i + 1;
        while (close < n && text[close] != '}' && text[close] != '{') close++;
        if (close >= n || text[close] != '}') return fail(c->p, line, "a '{' without its '}'");
        int filter;
        size_t elen = split_filter(text + i + 1, close - i - 1, &filter);
        if (filter == F_BAD) return fail(c->p, line, "unknown filter (clock, upper or int)");
        if (filter != F_NONE && !filters) return fail(c->p, line, "filters are only for text");
        char why[64];
        if (!atalaia_tpl_expr_ok(text + i + 1, elen, why, sizeof(why))) {
            return fail(c->p, line, "{%.*s}: %s", (int)elen, text + i + 1, why);
        }
        i = close;
    }
    return true;
}

static bool check_color(conv_t *c, int line, const char *v)
{
    uint32_t rgb;
    size_t a, len;
    if (strcmp(v, "team") == 0 || strcmp(v, "contrast") == 0 || atalaia_tpl_color(v, &rgb)) {
        return true;
    }
    if (whole_expr(v, &a, &len)) return check_text(c, line, v, false);
    return fail(c->p, line,
                "'%s' is not a colour (team, contrast, a palette name, #RRGGBB or {expression})",
                v);
}

static bool check_whole_expr(conv_t *c, int line, const char *v, const char *what)
{
    size_t a, len;
    if (!whole_expr(v, &a, &len)) return fail(c->p, line, "%s must be {expression}", what);
    return check_text(c, line, v, false);
}

static const char *const icon_names[] = {
    "ok",   "close", "warning", "pause", "play",      "stop",     "bell", "home", "refresh",
    "gps",  "wifi",  "battery", "power", "bluetooth", "settings", "eye",  "plus", "minus",
    "left", "right", "up",      "down",  "audio",     "mute",     "bars", "loop", "charge",
};

static const char *const type_names[] = {
    NULL, "label", "progress_bar", "icon", "qr_code", "spacer", "row", "column",
};

const char *atalaia_tpl_type_name(uint8_t type)
{
    return type >= 1 && type <= ATALAIA_TPL_COLUMN ? type_names[type] : "?";
}

static bool known_icon(const char *name)
{
    for (size_t i = 0; i < sizeof(icon_names) / sizeof(icon_names[0]); i++) {
        if (strcmp(icon_names[i], name) == 0) return true;
    }
    return false;
}

/* A size: pixels (0-1000) or "fill". */
static bool size_value(conv_t *c, int i, int16_t *out, const char *what)
{
    char buf[16];
    long v;
    if (!want_scalar(c, i, what) || !text_of(c, i, buf, sizeof(buf))) return false;
    if (strcmp(buf, "fill") == 0) {
        *out = ATALAIA_TPL_FILL;
        return true;
    }
    if (Y(c, i)->style != S_PLAIN || !parse_int(buf, 0, 1000, &v)) {
        return fail(c->p, Y(c, i)->line, "%s is a number of pixels (0-1000) or fill", what);
    }
    *out = (int16_t)v;
    return true;
}

static bool store_checked(conv_t *c, int i, uint16_t *out, const char *what)
{
    if (!want_scalar(c, i, what)) return false;
    *out = store(c, i);
    return *out != 0;
}

static bool parse_style(conv_t *c, int map, atalaia_tpl_widget_t *w)
{
    if (Y(c, map)->kind != Y_MAP) return fail(c->p, Y(c, map)->line, "style must be a mapping");
    for (int i = Y(c, map)->child; i >= 0; i = Y(c, i)->next) {
        int line = Y(c, i)->line;
        char buf[24];
        long v;
        if (key_is(c, i, "font_size")) {
            if (!want_scalar(c, i, "font_size") || !text_of(c, i, buf, sizeof(buf)) ||
                Y(c, i)->style != S_PLAIN || !parse_int(buf, 6, 200, &v)) {
                return fail(c->p, line, "font_size is a number (6-200)");
            }
            w->font_size = (int16_t)v;
        } else if (key_is(c, i, "align")) {
            if (!want_scalar(c, i, "align") || !text_of(c, i, buf, sizeof(buf))) return false;
            if (strcmp(buf, "left") == 0) {
                w->align = ATALAIA_TPL_ALIGN_LEFT;
            } else if (strcmp(buf, "center") == 0) {
                w->align = ATALAIA_TPL_ALIGN_CENTER;
            } else if (strcmp(buf, "right") == 0) {
                w->align = ATALAIA_TPL_ALIGN_RIGHT;
            } else {
                return fail(c->p, line, "align is left, center or right");
            }
        } else if (key_is(c, i, "color") || key_is(c, i, "background")) {
            bool bg = key_is(c, i, "background");
            uint16_t *slot = bg ? &w->background : &w->color;
            if (!store_checked(c, i, slot, bg ? "background" : "color")) return false;
            if (!check_color(c, line, c->t->pool + *slot)) return false;
        } else if (key_is(c, i, "padding")) {
            if (Y(c, i)->kind == Y_MAP) {
                static const char *const sides[] = {"top", "right", "bottom", "left"};
                for (int s = Y(c, i)->child; s >= 0; s = Y(c, s)->next) {
                    int k = -1;
                    for (int j = 0; j < 4; j++) {
                        if (key_is(c, s, sides[j])) k = j;
                    }
                    if (k < 0 || !text_of(c, s, buf, sizeof(buf)) || Y(c, s)->style != S_PLAIN ||
                        !parse_int(buf, 0, 200, &v)) {
                        return fail(c->p, Y(c, s)->line,
                                    "padding is a number or { top, right, bottom, left } (0-200)");
                    }
                    w->pad[k] = (int16_t)v;
                }
            } else {
                if (!text_of(c, i, buf, sizeof(buf)) || Y(c, i)->style != S_PLAIN ||
                    !parse_int(buf, 0, 200, &v)) {
                    return fail(c->p, line,
                                "padding is a number or { top, right, bottom, left } (0-200)");
                }
                for (int j = 0; j < 4; j++) w->pad[j] = (int16_t)v;
            }
        } else if (key_is(c, i, "width")) {
            if (!size_value(c, i, &w->width, "width")) return false;
        } else if (key_is(c, i, "height")) {
            if (!size_value(c, i, &w->height, "height")) return false;
        } else if (key_is(c, i, "visible")) {
            if (!want_scalar(c, i, "visible") || !text_of(c, i, buf, sizeof(buf))) return false;
            if (strcmp(buf, "true") == 0) {
                w->visible = 0;
            } else {
                if (!store_checked(c, i, &w->visible, "visible")) return false;
                const char *vv = c->t->pool + w->visible;
                if (strcmp(vv, "false") != 0 && !check_whole_expr(c, line, vv, "visible")) {
                    return false;
                }
            }
        } else {
            const atalaia_tpl_yaml_t *y = Y(c, i);
            return fail(c->p, line, "unknown style property '%.*s'", (int)y->key_len,
                        c->p->src + y->key);
        }
    }
    return true;
}

static bool parse_widgets(conv_t *c, int seq, int parent, int depth);

static bool parse_widget(conv_t *c, int map, int parent, int depth)
{
    int line = Y(c, map)->line;
    if (Y(c, map)->kind != Y_MAP) return fail(c->p, line, "each widget is a mapping with a type");
    atalaia_tpl_t *t = c->t;
    if (t->count >= ATALAIA_TPL_WIDGETS_MAX) {
        return fail(c->p, line, "too many widgets (at most %d)", ATALAIA_TPL_WIDGETS_MAX);
    }
    int ti = child(c, map, "type");
    char type[16];
    if (ti < 0 || !text_of(c, ti, type, sizeof(type)))
        return fail(c->p, line, "a widget needs a type");
    uint8_t kind = 0;
    for (uint8_t k = 1; k <= ATALAIA_TPL_COLUMN; k++) {
        if (strcmp(type_names[k], type) == 0) kind = k;
    }
    if (kind == 0) return fail(c->p, Y(c, ti)->line, "unknown widget type '%s'", type);

    int index = t->count++;
    atalaia_tpl_widget_t *w = &t->w[index];
    memset(w, 0, sizeof(*w));
    w->type = kind;
    w->parent = (int8_t)parent;
    w->depth = (uint8_t)depth;
    w->width = ATALAIA_TPL_AUTO;
    w->height = ATALAIA_TPL_AUTO;

    static const char *const content_key[] = {NULL,   "text", "value", "icon",
                                              "data", NULL,   NULL,    NULL};
    int children = -1;
    for (int i = Y(c, map)->child; i >= 0; i = Y(c, i)->next) {
        int l = Y(c, i)->line;
        if (key_is(c, i, "type")) continue;
        if (key_is(c, i, "id")) {
            if (!store_checked(c, i, &w->id, "id")) return false;
        } else if (key_is(c, i, "style")) {
            if (!parse_style(c, i, w)) return false;
        } else if (content_key[kind] && key_is(c, i, content_key[kind])) {
            if (!store_checked(c, i, &w->content, content_key[kind])) return false;
        } else if (kind == ATALAIA_TPL_SPACER && key_is(c, i, "height")) {
            if (!size_value(c, i, &w->height, "height")) return false;
        } else if ((kind == ATALAIA_TPL_ROW || kind == ATALAIA_TPL_COLUMN) &&
                   key_is(c, i, "children")) {
            children = i;
        } else {
            const atalaia_tpl_yaml_t *y = Y(c, i);
            return fail(c->p, l, "a %s has no property '%.*s'", type, (int)y->key_len,
                        c->p->src + y->key);
        }
    }

    const char *content = atalaia_tpl_str(t, w->content);
    switch (kind) {
    case ATALAIA_TPL_LABEL:
        if (!content) return fail(c->p, line, "a label needs text");
        if (!check_text(c, line, content, true)) return false;
        break;
    case ATALAIA_TPL_QR_CODE:
        if (!content) return fail(c->p, line, "a qr_code needs data");
        if (!check_text(c, line, content, true)) return false;
        break;
    case ATALAIA_TPL_PROGRESS_BAR: {
        if (!content) return fail(c->p, line, "a progress_bar needs a value");
        size_t a, len;
        char *end;
        if (whole_expr(content, &a, &len)) {
            if (!check_text(c, line, content, false)) return false;
        } else if (strtod(content, &end) < 0 || *end != '\0' || end == content) {
            return fail(c->p, line, "a progress_bar value is a number (0-1) or {expression}");
        }
        break;
    }
    case ATALAIA_TPL_ICON:
        if (!content) return fail(c->p, line, "an icon needs an icon name");
        if (!known_icon(content)) return fail(c->p, line, "unknown icon '%s'", content);
        break;
    case ATALAIA_TPL_SPACER:
        if (w->height == ATALAIA_TPL_AUTO) return fail(c->p, line, "a spacer needs a height");
        break;
    default:
        if (children < 0) return fail(c->p, line, "a %s needs children", type);
        if (depth + 1 > ATALAIA_TPL_DEPTH_MAX) {
            return fail(c->p, line, "rows and columns nest at most %d deep", ATALAIA_TPL_DEPTH_MAX);
        }
        if (Y(c, children)->kind != Y_SEQ) {
            return fail(c->p, Y(c, children)->line, "children is a list of widgets");
        }
        return parse_widgets(c, children, index, depth + 1);
    }
    return true;
}

static bool parse_widgets(conv_t *c, int seq, int parent, int depth)
{
    for (int i = Y(c, seq)->child; i >= 0; i = Y(c, i)->next) {
        if (!parse_widget(c, i, parent, depth)) return false;
    }
    return true;
}

static bool name_ok(const char *s)
{
    size_t n = strlen(s);
    if (n == 0 || n > ATALAIA_TPL_NAME_MAX) return false;
    for (size_t i = 0; i < n; i++) {
        char ch = s[i];
        if (!((ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') || ch == '_')) return false;
    }
    return true;
}

bool atalaia_tpl_parse(atalaia_tpl_t *t, const char *src, size_t len, char *err, size_t err_cap)
{
    if (err && err_cap) err[0] = '\0';
    memset(t, 0, sizeof(*t));
    t->pool_used = 1; /* offset 0 means "not set" */
    yp_t p = {0};
    p.t = t;
    p.src = src;
    p.len = len;
    p.line_no = 1;
    p.err = err;
    p.err_cap = err_cap;
    if (!src || len == 0) return fail(&p, 1, "the template is empty");
    if (len > ATALAIA_TPL_SOURCE_MAX) {
        return fail(&p, 1, "the template is larger than %d bytes", ATALAIA_TPL_SOURCE_MAX);
    }
    for (size_t i = 0; i < len; i++) {
        if (src[i] == '\0') return fail(&p, 1, "the template contains a NUL byte");
    }

    if (!peek(&p)) return p.failed ? false : fail(&p, 1, "the template is empty");
    if (p.indent != 0) return fail(&p, p.at_line, "the template must start at column 1");
    int root = parse_block(&p, 0);
    if (root < 0 || p.failed) return p.failed ? false : fail(&p, p.line_no, "not a template");
    if (peek(&p)) return fail(&p, p.at_line, "unexpected text after the template");
    if (p.failed) return false;

    conv_t c = {&p, t};
    if (Y(&c, root)->kind != Y_MAP) return fail(&p, 1, "a template is a mapping");
    int layout = -1;
    for (int i = Y(&c, root)->child; i >= 0; i = Y(&c, i)->next) {
        int line = Y(&c, i)->line;
        if (key_is(&c, i, "template")) {
            if (!store_checked(&c, i, &t->name, "template")) return false;
            if (!name_ok(t->pool + t->name)) {
                return fail(&p, line, "template names are 1-%d lower-case letters, digits and _",
                            ATALAIA_TPL_NAME_MAX);
            }
        } else if (key_is(&c, i, "layout")) {
            layout = i;
        } else if (key_is(&c, i, "style")) {
            if (Y(&c, i)->kind != Y_MAP) return fail(&p, line, "style must be a mapping");
            for (int s = Y(&c, i)->child; s >= 0; s = Y(&c, s)->next) {
                if (!key_is(&c, s, "background")) {
                    return fail(&p, Y(&c, s)->line, "a screen's style has only a background");
                }
                if (!store_checked(&c, s, &t->background, "background")) return false;
                if (!check_color(&c, Y(&c, s)->line, t->pool + t->background)) return false;
            }
        } else {
            const atalaia_tpl_yaml_t *y = Y(&c, i);
            return fail(&p, line, "unknown key '%.*s' (template, style, layout)", (int)y->key_len,
                        src + y->key);
        }
    }
    if (t->name == 0) return fail(&p, 1, "the template has no name (template: ...)");
    if (layout < 0 || Y(&c, layout)->kind != Y_SEQ || Y(&c, layout)->child < 0) {
        return fail(&p, layout < 0 ? 1 : Y(&c, layout)->line, "layout must list the widgets");
    }
    return parse_widgets(&c, layout, -1, 0);
}

size_t atalaia_tpl_sizeof(void)
{
    return sizeof(atalaia_tpl_t);
}

const char *atalaia_tpl_str(const atalaia_tpl_t *t, uint16_t off)
{
    return off == 0 || off >= t->pool_used ? NULL : t->pool + off;
}
