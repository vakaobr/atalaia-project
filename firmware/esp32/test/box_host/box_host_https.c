/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The host box's HTTPS (box_host_https.h). It answers as fw_update_esp.c's
 * get_text, open_stream, read_stream, close_stream and post do over
 * esp_http_client: HTTP/1.1, one request per connection, no redirect followed,
 * a 15 s read timeout (10 s for the report), a body read as its Content-Length
 * says (or chunked, length -1), and a body cut short an error. The
 * certificate check is the firmware's own (field_ca_pin.c), with the host name
 * of the address checked by mbedTLS as on the box.
 */
#define _POSIX_C_SOURCE 200809L

#include "box_host_https.h"

#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#include "field_ca_pin.h"
#include "mbedtls/ctr_drbg.h"
#include "mbedtls/entropy.h"
#include "mbedtls/error.h"
#include "mbedtls/net_sockets.h"
#include "mbedtls/ssl.h"

#define HEAD_MAX 2048 /* esp_http_client's buffer_size for these requests */

typedef struct {
    bool open;
    mbedtls_net_context net;
    mbedtls_ssl_context ssl;
    uint8_t head[HEAD_MAX]; /* the answer's headers, then the body bytes read with them */
    size_t have, used;      /* bytes in head; of those, handed out */
    int status;
    bool chunked;
    int64_t length; /* Content-Length, -1 if none */
    int64_t left;   /* body bytes still to come (Content-Length) */
    int64_t chunk;  /* bytes left of the current chunk; -1 before the first */
    bool done;      /* the whole body has been read */
} conn_t;

static field_ca_pin_t pin;
static mbedtls_entropy_context entropy;
static mbedtls_ctr_drbg_context drbg;
static mbedtls_ssl_config conf;
static bool ready;
static conn_t stream;

static void say(const char *fmt, ...) __attribute__((format(printf, 1, 2)));

static void say(const char *fmt, ...)
{
    if (pin.warn == NULL) return;
    char why[256];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(why, sizeof(why), fmt, ap);
    va_end(ap);
    pin.warn(why);
}

static void say_error(const char *what, int ret)
{
    char text[120];
    mbedtls_strerror(ret, text, sizeof(text));
    say("%s: %s (-0x%04x)", what, text, (unsigned)-ret);
}

static bool setup(void)
{
    if (ready) return true;
    mbedtls_entropy_init(&entropy);
    mbedtls_ctr_drbg_init(&drbg);
    mbedtls_ssl_config_init(&conf);
    static const unsigned char who[] = "atalaia box_host";
    int ret = mbedtls_ctr_drbg_seed(&drbg, mbedtls_entropy_func, &entropy, who, sizeof(who) - 1);
    if (ret == 0) {
        ret = mbedtls_ssl_config_defaults(&conf, MBEDTLS_SSL_IS_CLIENT,
                                          MBEDTLS_SSL_TRANSPORT_STREAM, MBEDTLS_SSL_PRESET_DEFAULT);
    }
    if (ret != 0) {
        say_error("TLS setup", ret);
        return false;
    }
    mbedtls_ssl_conf_rng(&conf, mbedtls_ctr_drbg_random, &drbg);
    field_ca_pin_attach(&conf, &pin);
    ready = true;
    return true;
}

/* "https://host[:port]" (host may be "[v6]"): host and port. */
static bool split(const char *base, char *host, size_t host_cap, char port[8])
{
    const char *scheme = "https://";
    if (strncmp(base, scheme, strlen(scheme)) != 0) return false;
    const char *h = base + strlen(scheme);
    const char *end;
    size_t n;
    if (*h == '[') {
        end = strchr(h, ']');
        if (end == NULL) return false;
        n = (size_t)(end - h - 1);
        h++;
        end++;
    } else {
        end = h + strcspn(h, ":/");
        n = (size_t)(end - h);
    }
    if (n == 0 || n >= host_cap) return false;
    memcpy(host, h, n);
    host[n] = '\0';
    if (*end == ':') {
        size_t p = strspn(end + 1, "0123456789");
        if (p == 0 || p > 5) return false;
        memcpy(port, end + 1, p);
        port[p] = '\0';
        end += 1 + p;
    } else {
        strcpy(port, "443");
    }
    return *end == '\0' || (*end == '/' && end[1] == '\0');
}

static void conn_close(conn_t *c)
{
    if (!c->open) return;
    mbedtls_ssl_close_notify(&c->ssl);
    mbedtls_ssl_free(&c->ssl);
    mbedtls_net_free(&c->net);
    c->open = false;
}

static bool write_all(conn_t *c, const char *data, size_t len)
{
    while (len > 0) {
        int n = mbedtls_ssl_write(&c->ssl, (const unsigned char *)data, len);
        if (n == MBEDTLS_ERR_SSL_WANT_READ || n == MBEDTLS_ERR_SSL_WANT_WRITE) continue;
        if (n <= 0) {
            say_error("sending to the controller", n);
            return false;
        }
        data += n;
        len -= (size_t)n;
    }
    return true;
}

/* Bytes off the connection: >0, 0 when the controller closed it, <0 an error or the timeout. */
static int raw_recv(conn_t *c, uint8_t *buf, size_t cap)
{
    for (;;) {
        int n = mbedtls_ssl_read(&c->ssl, buf, cap);
        if (n == MBEDTLS_ERR_SSL_WANT_READ || n == MBEDTLS_ERR_SSL_WANT_WRITE) continue;
        if (n == MBEDTLS_ERR_SSL_PEER_CLOSE_NOTIFY) return 0;
        return n;
    }
}

/* Body bytes as they came: first those read with the headers. */
static int raw_read(conn_t *c, uint8_t *buf, size_t cap)
{
    if (c->used < c->have) {
        size_t n = c->have - c->used;
        if (n > cap) n = cap;
        memcpy(buf, c->head + c->used, n);
        c->used += n;
        return (int)n;
    }
    return raw_recv(c, buf, cap);
}

/* A line of a chunked body (a size, the CRLF after a chunk, the trailer): false if cut off. */
static bool raw_line(conn_t *c, char *line, size_t cap)
{
    size_t n = 0;
    for (;;) {
        uint8_t ch;
        if (raw_read(c, &ch, 1) != 1) return false;
        if (ch == '\n') break;
        if (n + 1 < cap) line[n++] = (char)ch;
    }
    if (n > 0 && line[n - 1] == '\r') n--;
    line[n] = '\0';
    return true;
}

/* GET or POST base+path; the status line and headers read. false: no answer (no connection,
 * the handshake refused, the controller silent). */
static bool request(conn_t *c, const char *method, const char *base, const char *path,
                    const char *extra_headers, const char *body, uint32_t timeout_ms)
{
    char host[128], port[8];
    memset(c, 0, sizeof(*c));
    if (!setup()) return false;
    if (!split(base, host, sizeof(host), port)) {
        say("not an address of the controller: %s", base);
        return false;
    }
    mbedtls_net_init(&c->net);
    mbedtls_ssl_init(&c->ssl);
    c->open = true;
    int ret = mbedtls_net_connect(&c->net, host, port, MBEDTLS_NET_PROTO_TCP);
    if (ret != 0) {
        say_error(base, ret);
        conn_close(c);
        return false;
    }
    mbedtls_ssl_conf_read_timeout(&conf, timeout_ms);
    ret = mbedtls_ssl_setup(&c->ssl, &conf);
    if (ret == 0) ret = mbedtls_ssl_set_hostname(&c->ssl, host);
    if (ret != 0) {
        say_error("TLS", ret);
        conn_close(c);
        return false;
    }
    mbedtls_ssl_set_bio(&c->ssl, &c->net, mbedtls_net_send, NULL, mbedtls_net_recv_timeout);
    while ((ret = mbedtls_ssl_handshake(&c->ssl)) != 0) {
        if (ret == MBEDTLS_ERR_SSL_WANT_READ || ret == MBEDTLS_ERR_SSL_WANT_WRITE) continue;
        say_error("the TLS handshake with the controller", ret);
        mbedtls_ssl_free(&c->ssl);
        mbedtls_net_free(&c->net);
        c->open = false;
        return false;
    }
    char req[1024];
    int n = snprintf(req, sizeof(req),
                     "%s %s HTTP/1.1\r\nHost: %s:%s\r\nUser-Agent: atalaia-box-host\r\n"
                     "Connection: close\r\n%s",
                     method, path, host, port, extra_headers);
    if (n < 0 || (size_t)n >= sizeof(req) || !write_all(c, req, (size_t)n) ||
        (body != NULL && !write_all(c, body, strlen(body)))) {
        conn_close(c);
        return false;
    }
    /* The status line and headers, up to the empty line. */
    char *end = NULL;
    while (end == NULL) {
        if (c->have == sizeof(c->head) - 1) {
            say("the controller's headers are longer than %d bytes", HEAD_MAX);
            conn_close(c);
            return false;
        }
        int got = raw_recv(c, c->head + c->have, sizeof(c->head) - 1 - c->have);
        if (got <= 0) {
            if (got < 0) say_error("reading the controller's answer", got);
            conn_close(c);
            return false;
        }
        c->have += (size_t)got;
        c->head[c->have] = '\0';
        end = strstr((char *)c->head, "\r\n\r\n");
    }
    c->used = (size_t)(end + 4 - (char *)c->head);
    *end = '\0';
    char *line = (char *)c->head;
    if (sscanf(line, "HTTP/1.%*d %d", &c->status) != 1) {
        say("not an HTTP answer");
        conn_close(c);
        return false;
    }
    c->length = -1;
    c->chunk = -1;
    for (line = strstr(line, "\r\n"); line != NULL; line = strstr(line, "\r\n")) {
        line += 2;
        if (strncasecmp(line, "Content-Length:", 15) == 0) {
            c->length = strtoll(line + 15, NULL, 10);
        } else if (strncasecmp(line, "Transfer-Encoding:", 18) == 0) {
            c->chunked = strstr(line + 18, "chunked") != NULL;
        }
    }
    if (c->chunked) c->length = -1;
    c->left = c->length;
    c->done = !c->chunked && c->length == 0;
    return true;
}

/* The body: >0 bytes, 0 at its end, -1 if it broke off before (esp_http_client_read with
 * esp_http_client_is_complete_data_received). */
static int body_read(conn_t *c, uint8_t *buf, size_t cap)
{
    if (c->done) return 0;
    if (c->chunked) {
        if (c->chunk <= 0) {
            char line[64];
            if (c->chunk == 0 && (!raw_line(c, line, sizeof(line)) || line[0] != '\0')) return -1;
            if (!raw_line(c, line, sizeof(line))) return -1;
            char *after;
            c->chunk = strtoll(line, &after, 16);
            if (after == line || c->chunk < 0) return -1;
            if (c->chunk == 0) {
                do {
                    if (!raw_line(c, line, sizeof(line))) return -1;
                } while (line[0] != '\0');
                c->done = true;
                return 0;
            }
        }
        if ((int64_t)cap > c->chunk) cap = (size_t)c->chunk;
        int n = raw_read(c, buf, cap);
        if (n <= 0) return -1;
        c->chunk -= n;
        return n;
    }
    if (c->length < 0) {
        int n = raw_read(c, buf, cap); /* no length: until the controller closes */
        if (n == 0) c->done = true;
        return n < 0 ? -1 : n;
    }
    if ((int64_t)cap > c->left) cap = (size_t)c->left;
    int n = raw_read(c, buf, cap);
    if (n <= 0) return -1; /* closed or failed before Content-Length bytes */
    c->left -= n;
    if (c->left == 0) c->done = true;
    return n;
}

static bool net_up(void *ctx)
{
    (void)ctx;
    return true; /* the host's own network */
}

static void net_down(void *ctx)
{
    (void)ctx;
}

static int get_text(void *ctx, const char *base, const char *path, char *buf, size_t cap)
{
    (void)ctx;
    conn_t c;
    if (!request(&c, "GET", base, path, "\r\n", NULL, 15000)) return -1;
    int got = -1;
    if (c.status != 200) {
        got = -2; /* the controller answered: not this (404, 409) */
    } else if (c.length <= 0 || (size_t)c.length >= cap) {
        got = -3; /* longer than such a text may be */
    } else {
        got = 0;
        while (got < (int)c.length) {
            int n = body_read(&c, (uint8_t *)buf + got, (size_t)(c.length - got));
            if (n <= 0) break;
            got += n;
        }
        if (got != (int)c.length) got = -1;
    }
    if (got >= 0) buf[got] = '\0';
    conn_close(&c);
    return got;
}

static bool open_stream(void *ctx, const char *base, const char *path, int64_t *length)
{
    (void)ctx;
    if (!request(&stream, "GET", base, path, "\r\n", NULL, 15000)) {
        *length = -1;
        return false;
    }
    if (stream.status != 200) {
        *length = -2; /* an answer other than 200 (the controller does not offer it) */
        conn_close(&stream);
        return false;
    }
    *length = stream.length;
    return true;
}

static int read_stream(void *ctx, uint8_t *buf, size_t cap)
{
    (void)ctx;
    if (!stream.open) return -1;
    return body_read(&stream, buf, cap);
}

static void close_stream(void *ctx)
{
    (void)ctx;
    conn_close(&stream);
}

static bool post(void *ctx, const char *base, const char *path, const char *body,
                 const char *mac_hex)
{
    (void)ctx;
    char headers[256];
    snprintf(headers, sizeof(headers),
             "Content-Type: text/plain\r\nX-Atalaia-Mac: %s\r\nContent-Length: %u\r\n\r\n", mac_hex,
             (unsigned)strlen(body));
    conn_t c;
    if (!request(&c, "POST", base, path, headers, body, 10000)) {
        say("the report did not reach the controller: over LoRa instead");
        return false;
    }
    /* esp_http_client_perform reads the whole answer. */
    uint8_t sink[256];
    while (body_read(&c, sink, sizeof(sink)) > 0) {
    }
    bool ok = c.status == 200;
    if (!ok) say("the controller answered the report with %d: over LoRa instead", c.status);
    conn_close(&c);
    return ok;
}

static const fw_io_t IO = {
    .net_up = net_up,
    .net_down = net_down,
    .get_text = get_text,
    .open = open_stream,
    .read = read_stream,
    .close = close_stream,
    .post = post,
};

const fw_io_t *box_host_https_net(const uint8_t ca_sha256[32], void (*warn)(const char *why))
{
    memcpy(pin.sha256, ca_sha256, sizeof(pin.sha256));
    pin.warn = warn;
    return &IO;
}
