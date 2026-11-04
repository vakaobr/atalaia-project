/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Host box: a Field Box's game logic on Linux, for end-to-end tests with
 * the field controller and the host modem (controller/tests/test_box_e2e.py,
 * test_box_mode_fetch_e2e.py).
 *
 * It runs the firmware's own box_game.c, radio/field_link.c,
 * radio_protocol.c, node_runner.c, preset_store.c, state_persist.c and
 * event_log.c with the real core and mbedtls AES-CCM. What differs from
 * the ESP32 shell is only the platform:
 *   - the radio is UDP on 127.0.0.1 ("air"): every datagram received is a
 *     packet heard, every packet sent goes to the air peer port;
 *   - NVS (epoch, game key, join, join key) and LittleFS (presets, saved
 *     state, event log) are files in --state-dir, so killing the process
 *     and starting it again with the same directory is a battery pull;
 *   - the team buttons and the serial console are lines on stdin.
 *
 *   box_host --state-dir DIR --modes DIR [--air-port N] [--air-peer N]
 *            [--join-key HEX] [--state-ms N] [--name NAME]
 *            [--as-box VERSION] [--release-keys HEX] [--admin-pin PIN] [--mac MAC] [--pair]
 *            [--announce-ms N] [--no-wifi] [--mode-keys HEX] [--mode-source DIR|https]
 *            [--region eu868|as923-tw] [--no-lbt]
 *
 * Without --join-key (and no key stored in DIR) the box is unadopted
 * (main/adoption.c, protocol/adoption.md); --admin-pin (1234) and --mac
 * (02:00:00:00:00:01) are what "@adopt" checks and "@adopt-info" reports. --pair: an
 * unadopted box shows a pairing code at once (main/box_pair.c; "LOG pairing: code NNN NNN ..."),
 * on the air like the Field Box; "@pair" shows a new one.
 *
 * --announce-ms N: between games, announce N ms after a game ends and then every N ms
 * (instead of 2-20 s and the duty-cycle-based interval), so the tests need not wait.
 * --region: a box built for that radio region (Kconfig ATALAIA_RADIO_REGION; EU868 by
 * default): it pairs on the region's default channel, tunes only to the region's channels
 * and refuses another region's joins (join key 18).
 * --no-lbt: no listen before talk (the build with Kconfig ATALAIA_LBT off); by default every
 * frame goes through the radio task's transmit stage (radio/radio_lbt.c, RFC 0001 Amendment 14)
 * with a fake channel: free, unless "lbtbusy N" (below) says otherwise.
 * The box's device id is the file device_id in --state-dir (made at the first start).
 *
 * --as-box VERSION: HELLO says a Field Box (esp32s3, full tier) running VERSION, so
 * the controller offers it firmware updates; a CMD update then prints
 * "UPDATE <params> link=<CA yes|no>/<addresses> precheck=<result>": the firmware's
 * own offer checks (fw_update_precheck, with --release-keys), without Wi-Fi or a slot.
 * --mode-keys HEX: the mode keys built into this "firmware" (CONFIG_ATALAIA_MODE_KEYS): a join with
 * key 16 whose mode the box lacks is taken as fetching (protocol/mode-packages.md, "Fetching
 * missing modes") and the box runs the firmware's own fetch (mode_fetch.c) once the join is in:
 * from --mode-source DIR (DIR/<id>/release and DIR/<id>/package stand for the controller's
 * answers, a missing file for its 404), or, without it, with no Wi-Fi (no_wifi). With
 * --mode-source https it fetches from the real controller as the Field Box does: over HTTPS to
 * the join's addresses (key 14), trusting only the join's field CA (key 13) with the firmware's
 * own pin (main/field_ca_pin.c; box_host_https.c stands for esp_http_client), and posts the
 * reports to it ("LOG https: ..." says why a connection or a certificate was refused). It prints
 * "REPORT <the report's lines joined by |>" for each report it posts (from files: taken, as a
 * 200; over HTTPS then "REPORT taken=yes|no", the controller's 200 or not) and
 * "FETCH result=<code> part=<id>", then joins the game, or says why over LoRa
 * (node.modes_failed) and is free again.
 * --simple-out FUNCTION[@GPIO][,disabled] (up to twice; draft RFC "The expansion port",
 * increment 2): a simple output (an RC relay switch on a GPIO, main/simple_out.c) on GPIO 46 (the
 * second: 45) unless @GPIO says another, run by the firmware's own output layer
 * (main/outputs.c). FUNCTION (siren, strobe, smoke, light, horn, out.N) is what its admin set at
 * the box, enabled; ",disabled" leaves it with that function but not enabled (EXPL-13: it is
 * then in node.outputs_disabled, not node.modules); "-" leaves it as a new box has it (disabled,
 * out.N) for "@output" to enable. Settings the box
 * stored (the file outputs in --state-dir) win over it, as after a reboot. The pulse train is
 * printed: "PULSE g<gpio> t=<ms> width=<1000|2000> frames=<n> until=<ms>[ flush]" for each burst
 * the RMT would send (frames of 20 ms; flush: what was queued is dropped), and "PIN g<gpio> low
 * t=<ms>" once the last burst has gone out, so a test can tell when the switch's signal stops.
 * HELLO then lists `output` (capability type 11) while one is enabled, a CMD 12 switches it, the
 * mode's cap(fn) calls reach it, and once the HELLO is acknowledged the box sends node.modules
 * ("g46:servo:siren") and node.outputs_disabled (the ones not enabled: "g45:servo:horn", or "").
 *
 * --module NAME[@ADDR] (up to four; draft RFC "The expansion port", increment 8): a module on
 * the expansion port, simulated on the real module core (firmware/module-core/, through
 * test/module_sim.c) behind a fake I2C bus that the firmware's own port driver (main/expansion.c,
 * main/expansion_box.c) reads and writes as on the box: NAME is target (one hit channel, 0x58 by
 * default) or out4 (four relay outputs, siren, strobe, smoke and a generic one, 0x5C by default),
 * ADDR 58-5f in hex. HELLO then lists `hit` (capability type 10) with a target, node.modules
 * carries the module's entry ("58:target/1.0.0:hit") after the simple outputs', hits reach the
 * mode's script as hit.hit while it has armed the channel and a game runs, a module that stops
 * answering during a game is node.module_lost, and a module's outputs join the output layer
 * (disabled until "@output <n> enable", and in node.outputs_disabled until then: EXPL-20).
 * "MODULE <addr> outputs=<bitmap> t=<ms>" is printed each time the module's outputs change (as
 * its relays would). With a module, Target Windows is stored as a preset too (as one put on a
 * box by hand: the Field Box does not build it in until it is bench-tested), so a join can name
 * it.
 *
 * --module NAME[@ADDR] (up to four; draft RFC "The expansion port", increment 8): a module on
 * the expansion port, simulated on the real module core (firmware/module-core/, through
 * test/module_sim.c) behind a fake I2C bus that the firmware's own port driver (main/expansion.c,
 * main/expansion_box.c) reads and writes as on the box: NAME is target (one hit channel, 0x58 by
 * default) or out4 (four relay outputs, siren, strobe, smoke and a generic one, 0x5C by default),
 * ADDR 58-5f in hex. HELLO then lists `hit` (capability type 10) with a target, node.modules
 * carries the module's entry ("58:target/1.0.0:hit") after the simple outputs', hits reach the
 * mode's script as hit.hit while it has armed the channel and a game runs, a module that stops
 * answering during a game is node.module_lost, and a module's outputs join the output layer
 * (disabled until "@output <n> enable"). "MODULE <addr> outputs=<bitmap> t=<ms>" is printed each
 * time the module's outputs change (as its relays would). With a module, Target Windows is stored
 * as a preset too (as one put on a box by hand: the Field Box does not build it in until it is
 * bench-tested), so a join can name it.
 *
 * --module NAME[@ADDR] (up to four; draft RFC "The expansion port", increment 8): a module on
 * the expansion port, simulated on the real module core (firmware/module-core/, through
 * test/module_sim.c) behind a fake I2C bus that the firmware's own port driver (main/expansion.c,
 * main/expansion_box.c) reads and writes as on the box: NAME is target (one hit channel, 0x58 by
 * default) or out4 (four relay outputs, siren, strobe, smoke and a generic one, 0x5C by default),
 * ADDR 58-5f in hex. HELLO then lists `hit` (capability type 10) with a target, node.modules
 * carries the module's entry ("58:target/1.0.0:hit") after the simple outputs', hits reach the
 * mode's script as hit.hit while it has armed the channel and a game runs, a module that stops
 * answering during a game is node.module_lost, and a module's outputs join the output layer
 * (disabled until "@output <n> enable"). "MODULE <addr> outputs=<bitmap> t=<ms>" is printed each
 * time the module's outputs change (as its relays would). With a module, Target Windows is stored
 * as a preset too (as one put on a box by hand: the Field Box does not build it in until it is
 * bench-tested), so a join can name it.
 *
 * --module NAME[@ADDR] (up to four; draft RFC "The expansion port", increment 8): a module on
 * the expansion port, simulated on the real module core (firmware/module-core/, through
 * test/module_sim.c) behind a fake I2C bus that the firmware's own port driver (main/expansion.c,
 * main/expansion_box.c) reads and writes as on the box: NAME is target (one hit channel, 0x58 by
 * default) or out4 (four relay outputs, siren, strobe, smoke and a generic one, 0x5C by default),
 * ADDR 58-5f in hex. HELLO then lists `hit` (capability type 10) with a target, node.modules
 * carries the module's entry ("58:target/1.0.0:hit") after the simple outputs', hits reach the
 * mode's script as hit.hit while it has armed the channel and a game runs, a module that stops
 * answering during a game is node.module_lost, and a module's outputs join the output layer
 * (disabled until "@output <n> enable"). "MODULE <addr> outputs=<bitmap> t=<ms>" is printed each
 * time the module's outputs change (as its relays would). With a module, Target Windows is stored
 * as a preset too (as one put on a box by hand: the Field Box does not build it in until it is
 * bench-tested), so a join can name it.
 *
 * --no-wifi: an offer that passes them then runs the update (fw_update_run), which stops
 * with no_wifi as on a box whose Wi-Fi did not start, and prints "UPDATE result=<code>";
 * a refusal or that failure reaches the controller over LoRa (node.update_failed), as on
 * the Field Box (decision OT-8).
 *
 * stdin, one command per line:
 *   @join atalaia:join:...      join (as typed on the serial console)
 *   @joinkey <64 hex>           set the field join key (the adoption rules: never another field's)
 *   @adopt-info                 one "ATALAIA-ADOPT {json}" line: name, MAC, adoption state
 *   @adopt <64 hex> [<PIN>|-] [<field name>]  USB adoption; answers "ATALAIA-ADOPT {json}"
 *   card <hex>                  an NFC tag's memory on the reader (a field card adopts the box)
 *   @tag <uid hex> [<tag hex>]  a player tag read (as the NFC reader would, in a game)
 *   hold <button 1-4> <ms>      hold a team button for ms, then release it
 *   keys <0-9*#...>             keypad presses (keypad.key events to the mode)
 *   hit <addr> <0-255> [<channel>]  a hit on a module's plate (its piezo), as its firmware feels it
 *   unplug <addr> / plug <addr> a module's cable pulled out or plugged in again (a restart)
 *   @modules                    one "LOG modules: [...]" line: the port's modules
 *   battery <0-100|-1>          the battery gauge's reading (-1: no gauge); 87 at the start
 *   lbtbusy N                   the next N channel checks answer "busy" (-1: every one, 0: none)
 *   status                      print one STATUS line (JSON): the game, the link, and between
 *                               games the device id and whether the box takes an invite, and
 *                               "outputs": each simple output's id, GPIO, enabled, on, pulsing
 *                               (a module's channel: "gpio": -1 and its "module"), and
 *                               "modules": the expansion port's modules
 *   @outputs                    one "LOG outputs: ..." line: the simple outputs' settings
 *   @output <n> enable|disable|test <PIN>, @output <n> function <name> <PIN>,
 *   @output <n> max <seconds> <PIN>
 *                               the admin's settings at the box (main/outputs_admin.c; the PIN
 *                               is --admin-pin's), between games only
 *   quit
 * stdout: "READY air=<port>", then LOG, SCREEN and STATUS lines (SCREEN: the shell's
 * screens and the mode's, "SCREEN <template> <data JSON>", as the display gets them).
 */
#define _POSIX_C_SOURCE 200809L

#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include "adoption.h"
#include "atalaia/version.h"
#include "box_game.h"
#include "box_host_https.h"
#include "box_text.h"
#include "box_pair.h"
#include "builtin_presets.h"
#include "button_tracker.h"
#include "fw_layout.h"
#include "fw_update.h"
#include "radio/radio_lbt.h"
#include "mode_fetch.h"
#include "mode_store.h"
#include "expansion_box.h"
#include "module_sim.h"
#include "outputs.h"
#include "outputs_admin.h"
#include "simple_out.h"
#include "hal/stub/hal_stub.h"
#include "serial_console.h"
#include "state_persist.h"

static int air_sock = -1;
static struct sockaddr_in air_peer;
static bool have_peer;
static char dir[256];

static uint32_t mono_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint32_t)((uint64_t)ts.tv_sec * 1000u + (uint64_t)ts.tv_nsec / 1000000u);
}

static void out(const char *fmt, ...) __attribute__((format(printf, 1, 2)));

static void out(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vprintf(fmt, ap);
    va_end(ap);
    putchar('\n');
    fflush(stdout);
}

/* ---- Files for NVS --------------------------------------------------------------- */

static void path_of(char *buf, size_t cap, const char *name)
{
    snprintf(buf, cap, "%s/%s", dir, name);
}

static int read_file(const char *name, uint8_t *buf, size_t cap)
{
    char p[300];
    path_of(p, sizeof(p), name);
    FILE *f = fopen(p, "rb");
    if (f == NULL) return 0;
    size_t n = fread(buf, 1, cap, f);
    fclose(f);
    return (int)n;
}

static int write_file(const char *name, const uint8_t *buf, size_t len)
{
    char p[300], tmp[310];
    path_of(p, sizeof(p), name);
    snprintf(tmp, sizeof(tmp), "%s.tmp", p);
    FILE *f = fopen(tmp, "wb");
    if (f == NULL) return -1;
    bool ok = fwrite(buf, 1, len, f) == len;
    ok = fflush(f) == 0 && ok;
    fclose(f);
    if (!ok || rename(tmp, p) != 0) return -1;
    return 0;
}

static int erase_file(const char *name)
{
    char p[300];
    path_of(p, sizeof(p), name);
    remove(p);
    return 0;
}

/* "epoch": the single u16 of the firmware before the per-key store (read only: migration). */
static int nvs_read_legacy_epoch(void *ctx, uint16_t *epoch)
{
    (void)ctx;
    uint8_t b[2];
    if (read_file("epoch", b, 2) != 2) return -1;
    *epoch = (uint16_t)(b[0] << 8 | b[1]);
    return 0;
}

/* "epochs": the per-key epoch store, written aside and renamed (atomic, as NVS's blob). */
static int nvs_read_epochs(void *ctx, uint8_t *buf, size_t cap)
{
    (void)ctx;
    char p[300];
    path_of(p, sizeof(p), "epochs");
    FILE *f = fopen(p, "rb");
    if (f == NULL) return -1;
    size_t n = fread(buf, 1, cap, f);
    fclose(f);
    return (int)n;
}

static int nvs_write_epochs(void *ctx, const uint8_t *buf, size_t len)
{
    (void)ctx;
    return write_file("epochs", buf, len);
}

static int nvs_read_key(void *ctx, uint8_t key[16])
{
    (void)ctx;
    return read_file("game_key", key, 16) == 16 ? 0 : -1;
}

static int nvs_write_key(void *ctx, const uint8_t key[16])
{
    (void)ctx;
    return write_file("game_key", key, 16);
}

static int nvs_erase_key(void *ctx)
{
    (void)ctx;
    return erase_file("game_key");
}

static int nvs_random_bytes(void *ctx, uint8_t *buf, size_t n)
{
    (void)ctx;
    for (size_t i = 0; i < n; i++) buf[i] = (uint8_t)rand();
    return 0;
}

/* "epfloor": the highest epoch ever used with any key (EP-2), a file of its own beside "epochs". */
static int nvs_read_floor(void *ctx, uint16_t *floor)
{
    (void)ctx;
    uint8_t b[2];
    if (read_file("epfloor", b, 2) != 2) return -1;
    *floor = (uint16_t)(b[0] << 8 | b[1]);
    return 0;
}

static int nvs_write_floor(void *ctx, uint16_t floor)
{
    (void)ctx;
    uint8_t b[2] = {(uint8_t)(floor >> 8), (uint8_t)floor};
    return write_file("epfloor", b, 2);
}

static const atalaia_radio_nvs_ops_t nvs_ops = {
    .read_legacy_epoch = nvs_read_legacy_epoch,
    .read_epochs = nvs_read_epochs,
    .write_epochs = nvs_write_epochs,
    .read_key = nvs_read_key,
    .write_key = nvs_write_key,
    .erase_key = nvs_erase_key,
    .random_bytes = nvs_random_bytes,
    .read_floor = nvs_read_floor,
    .write_floor = nvs_write_floor,
    .ctx = NULL,
};

static int store_load_join(void *ctx, uint8_t *buf, size_t cap)
{
    (void)ctx;
    return read_file("join", buf, cap);
}

static int store_save_join(void *ctx, const uint8_t *buf, size_t len)
{
    (void)ctx;
    return write_file("join", buf, len);
}

static int store_erase_join(void *ctx)
{
    (void)ctx;
    return erase_file("join");
}

static int store_load_join_key(void *ctx, uint8_t key[ATALAIA_JOIN_KEY_SIZE])
{
    (void)ctx;
    return read_file("join_key", key, ATALAIA_JOIN_KEY_SIZE) == ATALAIA_JOIN_KEY_SIZE ? 0 : -1;
}

static int store_save_join_key(void *ctx, const uint8_t key[ATALAIA_JOIN_KEY_SIZE])
{
    (void)ctx;
    return write_file("join_key", key, ATALAIA_JOIN_KEY_SIZE);
}

static int store_load_device_id(void *ctx, uint8_t id[ATALAIA_FF_DEVICE_SIZE])
{
    (void)ctx;
    return read_file("device_id", id, ATALAIA_FF_DEVICE_SIZE) == ATALAIA_FF_DEVICE_SIZE ? 0 : -1;
}

static int store_save_device_id(void *ctx, const uint8_t id[ATALAIA_FF_DEVICE_SIZE])
{
    (void)ctx;
    return write_file("device_id", id, ATALAIA_FF_DEVICE_SIZE);
}

static int store_load_ff_boot(void *ctx, uint32_t *boot)
{
    (void)ctx;
    uint8_t b[4];
    int n = read_file("ff_boot", b, 4);
    if (n == 0) return -1; /* none stored yet */
    if (n != 4) return -2; /* damaged */
    *boot = (uint32_t)b[0] << 24 | (uint32_t)b[1] << 16 | (uint32_t)b[2] << 8 | b[3];
    return 0;
}

static int store_save_ff_boot(void *ctx, uint32_t boot)
{
    (void)ctx;
    uint8_t b[4] = {(uint8_t)(boot >> 24), (uint8_t)(boot >> 16), (uint8_t)(boot >> 8),
                    (uint8_t)boot};
    return write_file("ff_boot", b, 4);
}

/* Where a free box listens (RFC 0001 Amendment 19): the file "field_move", 8 bytes. */
static int store_load_field_move(void *ctx, uint32_t *channel_hz, uint32_t *rev)
{
    (void)ctx;
    uint8_t b[8];
    if (read_file("field_move", b, sizeof(b)) != (int)sizeof(b)) return -1;
    *channel_hz = (uint32_t)b[0] << 24 | (uint32_t)b[1] << 16 | (uint32_t)b[2] << 8 | b[3];
    *rev = (uint32_t)b[4] << 24 | (uint32_t)b[5] << 16 | (uint32_t)b[6] << 8 | b[7];
    return 0;
}

static int store_save_field_move(void *ctx, uint32_t channel_hz, uint32_t rev)
{
    (void)ctx;
    uint8_t b[8] = {(uint8_t)(channel_hz >> 24), (uint8_t)(channel_hz >> 16),
                    (uint8_t)(channel_hz >> 8),  (uint8_t)channel_hz,
                    (uint8_t)(rev >> 24),        (uint8_t)(rev >> 16),
                    (uint8_t)(rev >> 8),         (uint8_t)rev};
    return write_file("field_move", b, sizeof(b));
}

/* The screens' language, the last game's (join key 15): the file "lang". */
static int store_load_lang(void *ctx, char *code, size_t cap)
{
    (void)ctx;
    if (cap == 0) return -1;
    char p[300];
    path_of(p, sizeof(p), "lang");
    FILE *f = fopen(p, "rb");
    if (f == NULL) return -1;
    size_t n = fread(code, 1, cap - 1, f);
    fclose(f);
    code[n] = '\0';
    return 0;
}

static int store_save_lang(void *ctx, const char *code)
{
    (void)ctx;
    return write_file("lang", (const uint8_t *)code, strlen(code));
}

/* The platform's random bytes, as the box's seeded generator gives them (never a nonce). */
static void shell_random(void *user, uint8_t *buf, size_t len)
{
    (void)user;
    FILE *f = fopen("/dev/urandom", "rb");
    if (f == NULL || fread(buf, 1, len, f) != len) {
        fprintf(stderr, "box_host: /dev/urandom unreadable\n");
        exit(1);
    }
    fclose(f);
}

/* ---- Radio and shell ------------------------------------------------------------- */

static bool air_send(void *user, const uint8_t *pkt, size_t len)
{
    (void)user;
    if (!have_peer) return false;
    return sendto(air_sock, pkt, len, 0, (const struct sockaddr *)&air_peer, sizeof(air_peer)) ==
           (ssize_t)len;
}

/* ---- Listen before talk: the radio task's transmit stage on a fake channel ---------------- */

#define TXQ_LEN 8
static radio_txs_t txs;
static radio_tx_msg_t txq[TXQ_LEN];
static int txq_head, txq_count;
static int lbt_busy_left; /* "lbtbusy N": the next N checks answer busy; -1: always */
static bool lbt_enabled = true;

static int fake_channel_busy(hal_radio_busy_t *info)
{
    info->why = HAL_BUSY_FREE;
    info->sample_us = 0;
    info->cad_us = 8000; /* a CAD took 8 ms on the bench (SL-25 gate) */
    info->rearm_us = 0;
    if (lbt_busy_left == 0) return 0;
    if (lbt_busy_left > 0) lbt_busy_left--;
    info->why = HAL_BUSY_CAD;
    return 1;
}

static int fake_send(const uint8_t *data, size_t len)
{
    return air_send(NULL, data, len) ? 0 : -1;
}

static uint32_t fake_duty(void)
{
    return 360000;
}

static const hal_radio_ops_t fake_radio = {
    .send = fake_send, .duty_cycle_remaining_ms = fake_duty, .channel_busy = fake_channel_busy};

static uint32_t lbt_rand(void *ctx)
{
    (void)ctx;
    uint32_t v;
    shell_random(NULL, (uint8_t *)&v, sizeof(v));
    return v;
}

/* radio_task_send(): a queue of 8 in front of the stage, as the radio task has. */
static bool lbt_send(void *user, const uint8_t *pkt, size_t len)
{
    (void)user;
    if (len == 0 || len > RADIO_MAX_PKT_LEN || txq_count >= TXQ_LEN) return false;
    radio_tx_msg_t *m = &txq[(txq_head + txq_count) % TXQ_LEN];
    memcpy(m->data, pkt, len);
    m->len = len;
    m->tag = 0;
    txq_count++;
    return true;
}

/* One turn of the radio task's loop (every 10 ms here). */
static void lbt_pump(uint32_t now)
{
    if (!radio_txs_busy(&txs) && txq_count > 0) {
        radio_txs_load(&txs, &txq[txq_head], now);
        txq_head = (txq_head + 1) % TXQ_LEN;
        txq_count--;
    }
    uint32_t tag;
    radio_tx_status_t status;
    radio_txs_step(&txs, now, &tag, &status);
}

static void shell_screen(void *user, const char *tmpl, const char *json)
{
    (void)user;
    out("SCREEN %s %s", tmpl, json);
}

static void shell_log(void *user, const char *line)
{
    (void)user;
    out("LOG %s", line);
}

/* The region this "firmware" is built for (--region). */
static atalaia_region_t host_region = RADIO_REGION;

static bool shell_set_channel(void *user, uint32_t hz)
{
    (void)user;
    /* As the SX1262 HAL: only a channel of the build's region. */
    if (!atalaia_region_channel_ok(host_region, hz)) {
        out("LOG channel %lu Hz refused (not a %s channel)", (unsigned long)hz,
            radio_region_code(host_region));
        return false;
    }
    out("LOG channel %lu Hz", (unsigned long)hz);
    return true;
}

/* The battery gauge's reading: "battery N" on stdin (-1: no gauge). */
static int battery = 87;

static int shell_battery(void *user)
{
    (void)user;
    return battery;
}

/* ---- CMD update: the firmware's offer checks (fw_update.h) --------------------------- */

static box_game_t game;

/* ---- Simple outputs (--simple-out): the firmware's output layer, the RMT as log lines ---- */

static outputs_t outs;
static simple_out_t simple[OUTPUTS_MAX];
static uint32_t host_now;                /* the loop's clock, for the fake RMT's lines */
static uint32_t pin_low_at[OUTPUTS_MAX]; /* when the last burst ends; 0: told already */

static bool fake_rmt_send(void *ctx, uint16_t width_us, uint16_t frames, bool flush)
{
    simple_out_t *so = (simple_out_t *)ctx;
    int i = (int)(so - simple);
    /* What the scheduler will have queued once this is taken (simple_out.c). */
    uint32_t start = flush || !simple_out_pulsing(so, host_now) ? host_now : so->horizon_ms;
    uint32_t until = start + (uint32_t)frames * SO_FRAME_MS;
    out("PULSE g%d t=%lu width=%u frames=%u until=%lu%s", so->gpio, (unsigned long)host_now,
        (unsigned)width_us, (unsigned)frames, (unsigned long)until, flush ? " flush" : "");
    pin_low_at[i] = until;
    return true;
}

/* "PIN g<gpio> low" once the last queued burst has gone out. */
static void pins_low(uint32_t now)
{
    for (int i = 0; i < outs.simple; i++) {
        if (pin_low_at[i] != 0 && (int32_t)(now - pin_low_at[i]) >= 0 &&
            !simple_out_pulsing(&simple[i], now)) {
            out("PIN g%d low t=%lu", simple[i].gpio, (unsigned long)pin_low_at[i]);
            pin_low_at[i] = 0;
        }
    }
}

static void outputs_event(void *ctx, const char *type, const char *data_json)
{
    (void)ctx;
    out("LOG event %s %s", type, data_json);
    box_game_output_event(&game, type, data_json);
}

static void outputs_log(void *ctx, const char *line)
{
    (void)ctx;
    out("LOG %s", line);
}

/* The settings "NVS": the file outputs, a line "<index> <enabled 0|1> <function> <max s>" each. */
static bool outputs_save(void *ctx, int index, const out_settings_t *s)
{
    (void)ctx;
    char text[OUTPUTS_MAX * 48] = "";
    size_t len = 0;
    for (int i = 0; i < outs.simple; i++) {
        const out_settings_t *x = i == index ? s : &outs.ch[i].set;
        len += (size_t)snprintf(text + len, sizeof(text) - len, "%d %d %s %lu\n", i,
                                x->enabled ? 1 : 0, x->function, (unsigned long)x->max_on_s);
    }
    return write_file("outputs", (const uint8_t *)text, len) == 0;
}

static bool outputs_load(int index, out_settings_t *s)
{
    char text[OUTPUTS_MAX * 48 + 1];
    int n = read_file("outputs", (uint8_t *)text, sizeof(text) - 1);
    if (n <= 0) return false;
    text[n] = '\0';
    for (char *line = strtok(text, "\n"); line != NULL; line = strtok(NULL, "\n")) {
        int i = -1, en = 0;
        unsigned long max_s = 0;
        char fn[OUT_ID_MAX + 1];
        if (sscanf(line, "%d %d %23s %lu", &i, &en, fn, &max_s) == 4 && i == index) {
            outputs_default_settings(index, s);
            s->enabled = en != 0;
            snprintf(s->function, sizeof(s->function), "%s", fn);
            s->max_on_s = (uint32_t)max_s;
            return true;
        }
    }
    return false;
}

/* "--simple-out FUNCTION[@GPIO][,disabled]": a simple output, its settings from the state dir or
 * from FUNCTION ("-": a new box's, disabled; ",disabled": that function, not enabled). False for a
 * bad FUNCTION or GPIO. */
static bool add_simple_out(const char *arg, uint32_t now)
{
    int i = outs.simple;
    if (i >= OUTPUTS_MAX) return false;
    char fn[OUT_ID_MAX + 1];
    int gpio = i == 0 ? 46 : 45;
    const char *comma = strchr(arg, ',');
    bool disabled = false;
    if (comma != NULL) {
        if (strcmp(comma, ",disabled") != 0) return false;
        disabled = true;
    }
    const char *at = strchr(arg, '@');
    if (at != NULL && comma != NULL && at > comma) return false;
    const char *end = at ? at : comma ? comma : arg + strlen(arg);
    size_t n = (size_t)(end - arg);
    if (n == 0 || n > OUT_ID_MAX) return false;
    memcpy(fn, arg, n);
    fn[n] = '\0';
    if (at != NULL) gpio = atoi(at + 1);
    if (simple_out_pin_problem(gpio, SO_BOARD_V4_3, -1, NULL, 0) != NULL) return false;
    for (int j = 0; j < i; j++) {
        if (simple[j].gpio == gpio) return false;
    }
    out_settings_t s;
    if (!outputs_load(i, &s)) {
        outputs_default_settings(i, &s);
        if (strcmp(fn, "-") != 0) {
            if (!outputs_function_ok(fn)) return false;
            s.enabled = !disabled;
            snprintf(s.function, sizeof(s.function), "%s", fn);
        }
    }
    simple_out_rmt_t rmt = {.ctx = &simple[i], .send = fake_rmt_send};
    simple_out_init(&simple[i], gpio, &rmt);
    out_backend_t be = {.ctx = &simple[i], .drive = simple_out_backend_drive};
    host_now = now;
    return outputs_add_simple(&outs, gpio, &be, &s) >= 0;
}

static void print_outputs(char *buf, size_t cap)
{
    size_t len = (size_t)snprintf(buf, cap, "[");
    for (int i = 0; i < outs.count && len + 2 < cap; i++) {
        const out_channel_t *c = &outs.ch[i];
        if (c->module) {
            len += (size_t)snprintf(buf + len, cap - len,
                                    "%s{\"id\":\"%s\",\"gpio\":-1,\"module\":\"%02x\","
                                    "\"channel\":%u,\"enabled\":%s,\"on\":%s}",
                                    i ? "," : "", c->id, c->addr, (unsigned)c->mch + 1u,
                                    c->set.enabled ? "true" : "false", c->level ? "true" : "false");
            continue;
        }
        len += (size_t)snprintf(buf + len, cap - len,
                                "%s{\"id\":\"%s\",\"gpio\":%d,\"enabled\":%s,\"on\":%s,"
                                "\"pulsing\":%s,\"bursts\":%lu}",
                                i ? "," : "", c->id, c->gpio, c->set.enabled ? "true" : "false",
                                c->level ? "true" : "false",
                                simple_out_pulsing(&simple[i], host_now) ? "true" : "false",
                                (unsigned long)simple[i].bursts);
    }
    if (len + 2 <= cap) snprintf(buf + len, cap - len, "]");
}

/* ---- Modules on the expansion port (--module): the module core behind a fake I2C bus ---- */

static expansion_box_t port;
static module_sim_t modules[EXP_ADDR_COUNT];
static bool module_present[EXP_ADDR_COUNT]; /* a module at that address (plugged in or not) */
static bool module_plugged[EXP_ADDR_COUNT];
static uint8_t module_shown[EXP_ADDR_COUNT]; /* its outputs as last printed */
static int module_count;

static module_sim_t *module_at(uint8_t addr)
{
    if (addr < EXP_ADDR_FIRST || addr > EXP_ADDR_LAST) return NULL;
    int i = addr - EXP_ADDR_FIRST;
    return module_present[i] && module_plugged[i] ? &modules[i] : NULL;
}

static bool sim_probe(void *ctx, uint8_t addr)
{
    (void)ctx;
    return module_at(addr) != NULL;
}

static int sim_write(void *ctx, uint8_t addr, const uint8_t *data, size_t len)
{
    (void)ctx;
    module_sim_t *m = module_at(addr);
    if (m == NULL) return EXP_BUS_FAIL;
    module_sim_write(m, host_now, data, len);
    return EXP_BUS_OK;
}

static int sim_write_read(void *ctx, uint8_t addr, const uint8_t *o, size_t olen, uint8_t *in,
                          size_t ilen)
{
    (void)ctx;
    module_sim_t *m = module_at(addr);
    if (m == NULL) return EXP_BUS_FAIL;
    module_sim_write(m, host_now, o, olen);
    module_sim_read(m, host_now, in, ilen);
    return EXP_BUS_OK;
}

/* "--module NAME[@ADDR]": false for an unknown NAME, a bad or taken address. */
static bool add_module(const char *arg)
{
    char name[16];
    unsigned addr = 0;
    const char *at = strchr(arg, '@');
    size_t n = at ? (size_t)(at - arg) : strlen(arg);
    if (n == 0 || n >= sizeof(name)) return false;
    memcpy(name, arg, n);
    name[n] = '\0';
    if (at != NULL &&
        (sscanf(at + 1, "%x", &addr) != 1 || addr < EXP_ADDR_FIRST || addr > EXP_ADDR_LAST)) {
        return false;
    }
    module_sim_t probe;
    if (!module_sim_named(&probe, name, (uint8_t)addr, 0)) return false;
    int i = probe.cfg.address - EXP_ADDR_FIRST;
    if (module_present[i]) return false;
    modules[i] = probe;
    /* the core keeps a pointer to the module for its outputs: start it where it stays */
    module_sim_restart(&modules[i], 0);
    module_present[i] = module_plugged[i] = true;
    module_count++;
    return true;
}

/* Every turn: the modules' own timers, and their outputs printed when they change. */
static void modules_tick(uint32_t now)
{
    for (int i = 0; i < EXP_ADDR_COUNT; i++) {
        if (!module_present[i] || !module_plugged[i]) continue;
        uint8_t outputs = 0;
        module_sim_state(&modules[i], now, &outputs, NULL);
        if (outputs != module_shown[i]) {
            module_shown[i] = outputs;
            out("MODULE %02x outputs=0x%02x t=%lu", EXP_ADDR_FIRST + i, (unsigned)outputs,
                (unsigned long)now);
        }
    }
}

/* "hit <addr> <strength> [<channel>]", "unplug <addr>", "plug <addr>". */
static bool module_command(const char *line, uint32_t now)
{
    unsigned addr = 0, value = 0, channel = 0;
    if (sscanf(line, "hit %x %u %u", &addr, &value, &channel) >= 2) {
        module_sim_t *m = module_at((uint8_t)addr);
        bool kept = m != NULL && value <= 255 &&
                    module_sim_hit(m, now, (uint8_t)channel, MC_EVENT_HIT, (uint8_t)value);
        out("LOG module %02x: hit %u %s", addr, value,
            kept ? "felt" : "not kept (no such module, or the channel is not armed)");
        return true;
    }
    bool unplug = sscanf(line, "unplug %x", &addr) == 1;
    if (unplug || sscanf(line, "plug %x", &addr) == 1) {
        if (addr < EXP_ADDR_FIRST || addr > EXP_ADDR_LAST ||
            !module_present[addr - EXP_ADDR_FIRST]) {
            out("LOG module %02x: none at that address", addr);
            return true;
        }
        int i = (int)addr - EXP_ADDR_FIRST;
        if (!unplug && !module_plugged[i]) {
            module_sim_restart(&modules[i], now); /* power again: a fresh start */
            module_shown[i] = 0;
        }
        if (unplug && module_plugged[i] && module_shown[i] != 0) {
            module_shown[i] = 0; /* no power: its relays drop */
            out("MODULE %02x outputs=0x00 t=%lu", addr, (unsigned long)now);
        }
        module_plugged[i] = !unplug;
        out("LOG module %02x: %s", addr, unplug ? "unplugged" : "plugged in");
        return true;
    }
    return false;
}

static node_runner_t runner; /* defined below, with the game */

static void port_input(void *ctx, const char *type, const char *data_json)
{
    (void)ctx;
    out("LOG input %s %s", type, data_json);
    if (runner.running) node_runner_input(&runner, type, data_json);
}

static void port_event(void *ctx, const char *type, const char *data_json)
{
    (void)ctx;
    out("LOG event %s %s", type, data_json);
    box_game_output_event(&game, type, data_json);
}

static void port_log(void *ctx, const char *line)
{
    (void)ctx;
    out("LOG %s", line);
}

/* ---- Adoption (adoption.h): the join key and the field's name in "NVS" ------------ */

static adoption_t adopt;

static bool adopt_busy(void *ctx)
{
    (void)ctx;
    return box_game_active(&game);
}

static bool adopt_store(void *ctx, const uint8_t key[ADOPTION_KEY_SIZE], const char *name)
{
    (void)ctx;
    return box_game_set_join_key(&game, key) &&
           write_file("field_name", (const uint8_t *)name, strlen(name)) == 0;
}

const fw_desc_t atalaia_fw_desc = {.magic = {'A', 'T', 'F', 'W'},
                                   .format = 1,
                                   .layout = FW_LAYOUT_VERSION,
                                   .variant = "box",
                                   .board = "heltec_v4_3"};
static char fw_version[32] = "host"; /* HELLO's fw_version, as esp_app_desc_t's */
static uint8_t release_keys[FW_KEYS_MAX][32];
static int release_key_count;

static bool no_wifi; /* --no-wifi: run the update, which finds no Wi-Fi */

static bool host_net_up(void *ctx)
{
    (void)ctx;
    return false; /* the host box has no field Wi-Fi: no_wifi */
}
static void host_net_down(void *ctx)
{
    (void)ctx;
}

static void shell_update(void *user, const char *params)
{
    (void)user;
    fw_job_t job;
    memset(&job, 0, sizeof(job));
    job.platform = "esp32s3";
    job.running_version = fw_version;
    job.desc = &atalaia_fw_desc;
    job.keys = (const uint8_t(*)[32])release_keys;
    job.key_count = (size_t)release_key_count;
    job.slot_size = 0x400000;
    job.layout = FW_LAYOUT_VERSION;
    job.playing = box_game_playing(&game);
    job.battery_pct = battery;
    job.min_battery_pct = 30;
    job.join = &game.join;
    fw_result_t r =
        fw_offer_parse(params, job.id, job.version) ? fw_update_precheck(&job) : FW_BAD_OFFER;
    out("UPDATE %s link=%s/%u precheck=%s", params, game.join.has_ca ? "yes" : "no",
        (unsigned)game.join.url_count, fw_result_name(r));
    if (!no_wifi) return;
    if (r == FW_INSTALLED) {
        fw_io_t io;
        memset(&io, 0, sizeof(io));
        io.net_up = host_net_up;
        io.net_down = host_net_down;
        r = fw_update_run(&job, &io);
        out("UPDATE result=%s", fw_result_name(r));
    }
    if (r != FW_INSTALLED && !job.reported) {
        box_game_update_failed(&game, job.id, fw_result_name(r), job.running_version);
    }
}

/* ---- Fetching a game's missing modes (mode_fetch.h) ------------------------------------ */

static uint8_t mode_keys[FW_KEYS_MAX][32];
static int mode_key_count;
static const char *mode_source; /* --mode-source: the controller's answers as files, or "https" */
static bool fetch_due;
static atalaia_join_t fetch_for;

static void shell_fetch_modes(void *user, const atalaia_join_t *join)
{
    (void)user;
    fetch_for = *join; /* fetched from the main loop, as the shell's task would */
    fetch_due = true;
}

static bool mf_net_up(void *ctx)
{
    (void)ctx;
    return mode_source != NULL;
}

/* "/api/v1/mode-packages/<id>/<what>" -> DIR/<id>/<what>. */
static FILE *mf_file(const char *path)
{
    const char *prefix = "/api/v1/mode-packages/";
    if (strncmp(path, prefix, strlen(prefix)) != 0 || strstr(path, "..") != NULL) return NULL;
    char p[400];
    snprintf(p, sizeof(p), "%s/%s", mode_source, path + strlen(prefix));
    return fopen(p, "rb");
}

static int mf_get_text(void *ctx, const char *base, const char *path, char *buf, size_t cap)
{
    (void)ctx;
    (void)base;
    FILE *f = mf_file(path);
    if (f == NULL) return -2; /* the controller's 404 */
    size_t n = fread(buf, 1, cap - 1, f);
    bool more = fgetc(f) != EOF;
    fclose(f);
    if (more || n == 0) return -3;
    buf[n] = '\0';
    return (int)n;
}

static FILE *mf_stream;

static bool mf_open(void *ctx, const char *base, const char *path, int64_t *length)
{
    (void)ctx;
    (void)base;
    mf_stream = mf_file(path);
    if (mf_stream == NULL) {
        *length = -2;
        return false;
    }
    fseek(mf_stream, 0, SEEK_END);
    *length = ftell(mf_stream);
    fseek(mf_stream, 0, SEEK_SET);
    return true;
}

static int mf_read(void *ctx, uint8_t *buf, size_t cap)
{
    (void)ctx;
    return mf_stream != NULL ? (int)fread(buf, 1, cap, mf_stream) : -1;
}

static void mf_close(void *ctx)
{
    (void)ctx;
    if (mf_stream != NULL) fclose(mf_stream);
    mf_stream = NULL;
}

/* --mode-source https: the firmware's HTTPS, as box_host_https.c gives it (NULL otherwise). */
static const fw_io_t *mf_https;

static bool mf_post(void *ctx, const char *base, const char *path, const char *body,
                    const char *mac_hex)
{
    char line[MF_REPORT_MAX];
    snprintf(line, sizeof(line), "%s", body);
    for (char *c = line; *c; c++) {
        if (*c == '\n') *c = c[1] ? '|' : '\0';
    }
    out("REPORT %s", line);
    if (mf_https == NULL) return true;
    bool taken = mf_https->post(ctx, base, path, body, mac_hex);
    out("REPORT taken=%s", taken ? "yes" : "no");
    return taken;
}

static bool mf_cancelled(void *ctx)
{
    (void)ctx;
    return game.fetch_cancel;
}

static void https_warn(const char *why)
{
    out("LOG https: %s", why);
}

static void run_fetch(void)
{
    static uint8_t buf[4096];
    static char scratch[PRESET_SOURCE_MAX];
    fw_io_t io;
    memset(&io, 0, sizeof(io));
    if (mode_source != NULL && strcmp(mode_source, "https") == 0) {
        /* As mode_fetch_esp.c: the firmware's HTTPS pinned to the join's field CA (key 13), to
         * the join's addresses (key 14). */
        mf_https = box_host_https_net(fetch_for.ca_sha256, https_warn);
        io = *mf_https;
    } else {
        mf_https = NULL;
        io.net_up = mf_net_up;
        io.net_down = host_net_down;
        io.get_text = mf_get_text;
        io.open = mf_open;
        io.read = mf_read;
        io.close = mf_close;
    }
    io.post = mf_post;
    io.cancelled = mf_cancelled;
    io.ctx = NULL;
    mf_job_t job;
    memset(&job, 0, sizeof(job));
    job.keys = (const uint8_t(*)[32])mode_keys;
    job.key_count = (size_t)mode_key_count;
    job.mem_limit = 256u * 1024u;
    job.builtin = builtin_presets_has;
    job.join = &fetch_for;
    job.buf = buf;
    job.buf_cap = sizeof(buf);
    job.scratch = scratch;
    job.scratch_cap = sizeof(scratch);
    mf_result_t r = mf_run(&job, &io);
    out("FETCH result=%s part=%s", mf_result_name(r), job.part);
    memset(fetch_for.game_key, 0, sizeof(fetch_for.game_key));
    box_game_fetch_done(&game, (int)r, job.part, job.reported);
}

/* ---- Files for the mode sources -------------------------------------------------- */

static char *slurp(const char *path, size_t *len)
{
    FILE *f = fopen(path, "rb");
    if (f == NULL) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *buf = malloc((size_t)n + 1);
    if (buf == NULL || fread(buf, 1, (size_t)n, f) != (size_t)n) {
        fclose(f);
        free(buf);
        return NULL;
    }
    fclose(f);
    buf[n] = '\0';
    *len = (size_t)n;
    return buf;
}

static long arg_value(int argc, char **argv, int *i)
{
    if (*i + 1 >= argc) {
        fprintf(stderr, "box_host: %s needs a value\n", argv[*i]);
        exit(2);
    }
    (*i)++;
    return strtol(argv[*i], NULL, 10);
}

static int bind_udp(uint16_t port)
{
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) return -1;
    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    addr.sin_port = htons(port);
    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        close(fd);
        return -1;
    }
    return fd;
}

/* preset_t holds 16 KB of source: static, like on the ESP32. */
static preset_t preset;
static node_runner_t runner;
static hal_t hal;
static event_log_t evlog;

static void print_status(void)
{
    char outputs_json[OUT_CHANNELS_MAX * 130 + 4];
    print_outputs(outputs_json, sizeof(outputs_json));
    char modules_json[600];
    expansion_box_status_json(&port, modules_json, sizeof(modules_json));
    char scores[96] = "";
    size_t o = 0;
    if (runner.node != NULL) {
        const atalaia_score_t *s = atalaia_node_score(runner.node);
        for (uint8_t t = 1; t <= game.join.team_count && o < sizeof(scores) - 16; t++) {
            o += (size_t)snprintf(scores + o, sizeof(scores) - o, "%s%lu", t > 1 ? "," : "",
                                  (unsigned long)s->gained[t]);
        }
    }
    const field_link_stats_t *st = &game.link.stats;
    char device[17];
    box_lobby_device_hex(&game, device);
    out("STATUS {\"phase\":%d,\"paused\":%s,\"game_id\":%u,\"node_id\":%u,\"epoch\":%u,"
        "\"game_time_ms\":%lu,\"owner\":%u,\"scores\":[%s],\"pending\":%u,\"leader\":%u,"
        "\"term\":%lu,\"events_sent\":%lu,\"retries\":%lu,\"acked\":%lu,\"cmds\":%lu,"
        "\"times\":%lu,\"states\":%lu,\"rx_ok\":%lu,\"rx_rejected\":%lu,\"relayed\":%lu,"
        "\"have_key\":%s,\"device_id\":\"%s\",\"available\":%s,\"invites_accepted\":%lu,"
        "\"invites_refused\":%lu,\"last_game\":%u,\"lang\":\"%s\","
        "\"lbt_cads\":%lu,\"lbt_deferrals\":%lu,\"lbt_gave_up\":%lu,\"outputs\":%s,\"modules\":%s}",
        (int)game.phase, game.paused ? "true" : "false", game.join.game_id, game.join.node_id,
        game.link.proto.epoch, (unsigned long)runner.game_time_ms, game.owner_team, scores,
        (unsigned)field_link_pending(&game.link), game.link.leader, (unsigned long)game.link.term,
        (unsigned long)st->events_sent, (unsigned long)st->retries, (unsigned long)st->acked,
        (unsigned long)st->cmds, (unsigned long)st->times, (unsigned long)st->states_sent,
        (unsigned long)st->rx_ok, (unsigned long)st->rx_rejected, (unsigned long)st->relayed,
        game.link.proto.has_key ? "true" : "false", device,
        box_lobby_available(&game) ? "true" : "false", (unsigned long)game.lobby.invites_accepted,
        (unsigned long)game.lobby.invites_refused, game.lobby.last_game,
        box_lang_given() ? box_lang_code(box_lang()) : "", (unsigned long)txs.stats.cads,
        (unsigned long)txs.stats.deferrals, (unsigned long)txs.stats.gave_up, outputs_json,
        modules_json);
}

int main(int argc, char **argv)
{
    long air_port = 0, peer_port = 0, state_ms = 0, announce_ms = 0;
    const char *modes = NULL;
    const char *join_key_hex = NULL;
    const char *name = "box-host";
    const char *admin_pin = "1234";
    const char *mac = "02:00:00:00:00:01";
    bool as_box = false;
    bool pair = false;
    const char *simple_outs[OUTPUTS_MAX];
    int simple_out_count = 0;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--pair") == 0) {
            pair = true;
            continue;
        }
        if (strcmp(argv[i], "--region") == 0 && i + 1 < argc) {
            host_region = atalaia_region_from_code(argv[++i]);
            if (host_region == ATALAIA_REGION_COUNT) {
                fprintf(stderr, "box_host: --region eu868 or as923-tw\n");
                return 2;
            }
        } else if (strcmp(argv[i], "--admin-pin") == 0 && i + 1 < argc) {
            admin_pin = argv[++i];
        } else if (strcmp(argv[i], "--mac") == 0 && i + 1 < argc) {
            mac = argv[++i];
        } else if (strcmp(argv[i], "--air-port") == 0) {
            air_port = arg_value(argc, argv, &i);
        } else if (strcmp(argv[i], "--air-peer") == 0) {
            peer_port = arg_value(argc, argv, &i);
        } else if (strcmp(argv[i], "--state-ms") == 0) {
            state_ms = arg_value(argc, argv, &i);
        } else if (strcmp(argv[i], "--announce-ms") == 0) {
            announce_ms = arg_value(argc, argv, &i);
        } else if (strcmp(argv[i], "--state-dir") == 0 && i + 1 < argc) {
            snprintf(dir, sizeof(dir), "%s", argv[++i]);
        } else if (strcmp(argv[i], "--modes") == 0 && i + 1 < argc) {
            modes = argv[++i];
        } else if (strcmp(argv[i], "--join-key") == 0 && i + 1 < argc) {
            join_key_hex = argv[++i];
        } else if (strcmp(argv[i], "--name") == 0 && i + 1 < argc) {
            name = argv[++i];
        } else if (strcmp(argv[i], "--as-box") == 0 && i + 1 < argc &&
                   fw_version_valid(argv[i + 1]) && strlen(argv[i + 1]) < sizeof(fw_version)) {
            snprintf(fw_version, sizeof(fw_version), "%s", argv[++i]);
            as_box = true;
        } else if (strcmp(argv[i], "--mode-keys") == 0 && i + 1 < argc) {
            mode_key_count = fw_keys_parse(argv[++i], mode_keys, FW_KEYS_MAX);
            if (mode_key_count < 0) {
                fprintf(stderr, "box_host: --mode-keys: 64 hex digits each\n");
                return 2;
            }
        } else if (strcmp(argv[i], "--mode-source") == 0 && i + 1 < argc) {
            mode_source = argv[++i];
        } else if (strcmp(argv[i], "--simple-out") == 0 && i + 1 < argc) {
            if (simple_out_count >= OUTPUTS_MAX) {
                fprintf(stderr, "box_host: --simple-out at most %d times\n", OUTPUTS_MAX);
                return 2;
            }
            simple_outs[simple_out_count++] = argv[++i];
        } else if (strcmp(argv[i], "--module") == 0 && i + 1 < argc) {
            if (module_count >= EXP_MODULES_MAX || !add_module(argv[++i])) {
                fprintf(stderr,
                        "box_host: --module NAME[@ADDR]: target or out4, at 58-5f, at most %d\n",
                        EXP_MODULES_MAX);
                return 2;
            }
        } else if (strcmp(argv[i], "--no-wifi") == 0) {
            no_wifi = true;
        } else if (strcmp(argv[i], "--no-lbt") == 0) {
            lbt_enabled = false;
        } else if (strcmp(argv[i], "--release-keys") == 0 && i + 1 < argc) {
            release_key_count = fw_keys_parse(argv[++i], release_keys, FW_KEYS_MAX);
            if (release_key_count < 0) {
                fprintf(stderr, "box_host: --release-keys: 64 hex digits each\n");
                return 2;
            }
        } else {
            fprintf(stderr, "box_host: unknown option %s\n", argv[i]);
            return 2;
        }
    }
    if (!dir[0] || modes == NULL) {
        fprintf(stderr, "box_host: --state-dir and --modes are required\n");
        return 2;
    }
    signal(SIGPIPE, SIG_IGN);
    mkdir(dir, 0700);
    radio_txs_init(&txs, &fake_radio, lbt_enabled, lbt_rand, NULL);

    air_sock = bind_udp((uint16_t)air_port);
    if (air_sock < 0) {
        perror("box_host: bind");
        return 1;
    }
    if (peer_port > 0) {
        memset(&air_peer, 0, sizeof(air_peer));
        air_peer.sin_family = AF_INET;
        air_peer.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        air_peer.sin_port = htons((uint16_t)peer_port);
        have_peer = true;
    }

    /* "Flash": presets, saved state and the event log, as on the box's LittleFS. */
    char sub[300];
    snprintf(sub, sizeof(sub), "%s/presets", dir);
    mkdir(sub, 0700);
    preset_store_init(sub);
    mode_store_init(sub); /* fetched mode packages beside the presets, as on the box */
    mode_store_verify((const uint8_t(*)[32])mode_keys, (size_t)mode_key_count);
    snprintf(sub, sizeof(sub), "%s/state", dir);
    mkdir(sub, 0700);
    state_persist_init(sub);
    snprintf(sub, sizeof(sub), "%s/log", dir);
    mkdir(sub, 0700);
    event_log_init(&evlog, sub);

    /* The built-in modes, as main/CMakeLists.txt puts them in the image. */
    static const char *const builtin_modes[][2] = {
        {"bomb", "org.atalaia.bomb"},
        {"domination", "org.atalaia.domination"},
        {"holdall", "org.atalaia.holdall"},
        {"laststand", "org.atalaia.laststand"},
        {"codes", "org.atalaia.codes"},
        {"kill_confirmed", "org.atalaia.kill_confirmed"},
        {"respawn", "org.atalaia.respawn"},
        {"player_checkin", "org.atalaia.player_checkin"},
        {"medic", "org.atalaia.medic"},
        {"master_satellites", "org.atalaia.master_satellites"},
        {"hacking_terminal", "org.atalaia.hacking_terminal"},
        {"vip_payload", "org.atalaia.vip_payload"},
        {"objectives", "org.atalaia.objectives"},
        {"money_factory", "org.atalaia.money_factory"},
        {"progressive_domination", "org.atalaia.progressive_domination"},
        {"sabotage", "org.atalaia.sabotage"},
    };
    enum { BUILTIN_COUNT = sizeof(builtin_modes) / sizeof(builtin_modes[0]) };
    builtin_source_t sources[BUILTIN_COUNT];
    for (int i = 0; i < BUILTIN_COUNT; i++) {
        char p[300];
        snprintf(p, sizeof(p), "%s/%s/node.lua", modes, builtin_modes[i][0]);
        sources[i].mode_id = builtin_modes[i][1];
        sources[i].source = slurp(p, &sources[i].source_len);
        if (sources[i].source == NULL) {
            fprintf(stderr, "box_host: cannot read %s\n", p);
            return 1;
        }
    }
    builtin_presets_seed(sources, BUILTIN_COUNT);
    /* With a module on the port: Target Windows stored as a preset, as one put on a box by hand
     * (the Field Box builds it in once it is bench-tested: draft RFC "The expansion port", row 8).
     */
    if (module_count > 0 && preset_store_find_mode("org.atalaia.target_windows") < 0) {
        char p[300];
        size_t len = 0;
        snprintf(p, sizeof(p), "%s/target_windows/node.lua", modes);
        char *src = slurp(p, &len);
        int slot = 0;
        preset_summary_t list[PRESET_MAX_SLOTS];
        int used = preset_store_list(list, PRESET_MAX_SLOTS);
        for (int k = 1; k <= PRESET_MAX_SLOTS && slot == 0; k++) {
            bool taken = false;
            for (int j = 0; j < used; j++) taken = taken || list[j].index == k;
            if (!taken) slot = k;
        }
        memset(&preset, 0, sizeof(preset));
        snprintf(preset.mode_id, sizeof(preset.mode_id), "org.atalaia.target_windows");
        snprintf(preset.label, sizeof(preset.label), "Target Windows");
        snprintf(preset.params_json, sizeof(preset.params_json), "{}");
        if (src != NULL && len < sizeof(preset.source)) {
            memcpy(preset.source, src, len);
            preset.source_len = len;
        }
        if (src == NULL || preset.source_len == 0 || slot == 0 ||
            !preset_store_save(slot, &preset)) {
            fprintf(stderr, "box_host: cannot store Target Windows from %s\n", p);
            return 1;
        }
        free(src);
    }

    hal_stub_init(&hal);
    node_runner_init(&runner, &hal, 0);

    atalaia_hello_t hello;
    memset(&hello, 0, sizeof(hello));
    snprintf(hello.node_name, sizeof(hello.node_name), "%s", name);
    hello.platform = as_box ? 1 : 2; /* esp32s3 (--as-box) or linux */
    snprintf(hello.fw_version, sizeof(hello.fw_version), "%s", fw_version);
    snprintf(hello.core_version, sizeof(hello.core_version), "%s", atalaia_version());
    hello.tier = 0;
    /* The team buttons and the keypad stand on stdin ("hold", "keys"); box_game adds `output`
     * (11) while a simple output is enabled. */
    hello.capabilities[0] = ATALAIA_CAP_BUTTON;
    hello.capabilities[1] = ATALAIA_CAP_KEYPAD;
    hello.capabilities_count = 2;
    hello.transports = 1;
    hello.battery_pct = 87;

    box_store_ops_t store = {.load_join = store_load_join,
                             .save_join = store_save_join,
                             .erase_join = store_erase_join,
                             .load_join_key = store_load_join_key,
                             .save_join_key = store_save_join_key,
                             .load_device_id = store_load_device_id,
                             .save_device_id = store_save_device_id,
                             .load_ff_boot = store_load_ff_boot,
                             .save_ff_boot = store_save_ff_boot,
                             .load_field_move = store_load_field_move,
                             .save_field_move = store_save_field_move,
                             .load_lang = store_load_lang,
                             .save_lang = store_save_lang,
                             .ctx = NULL};
    box_shell_ops_t shell = {.screen = shell_screen,
                             .log = shell_log,
                             .reboot = NULL,
                             .set_channel = shell_set_channel,
                             .battery_pct = shell_battery,
                             .radio_send = lbt_send,
                             .update = shell_update,
                             .random = shell_random,
                             .fetch_modes = mode_key_count > 0 ? shell_fetch_modes : NULL,
                             .user = NULL};
    box_game_init(&game, &runner, &preset, &store, &shell, &atalaia_crypto_mbedtls, &nvs_ops,
                  &evlog, &hello);
    game.region = host_region;
    {
        outputs_ops_t oops = {.event = outputs_event, .log = outputs_log, .save = outputs_save};
        outputs_init(&outs, &oops);
        for (int i = 0; i < simple_out_count; i++) {
            if (!add_simple_out(simple_outs[i], mono_ms())) {
                fprintf(stderr,
                        "box_host: --simple-out %s: FUNCTION[@GPIO][,disabled] (siren, strobe, "
                        "smoke, light, horn, out.N or -; a free GPIO)\n",
                        simple_outs[i]);
                return 2;
            }
        }
        box_game_set_outputs(&game, &outs);
        /* The expansion port after the outputs, as on the box: ALL_OFF to every module first. */
        exp_bus_t bus = {
            .ctx = NULL, .probe = sim_probe, .write = sim_write, .write_read = sim_write_read};
        xb_ops_t xops = {.ctx = NULL, .input = port_input, .event = port_event, .log = port_log};
        expansion_box_init(&port, &bus, &outs, &xops);
        host_now = mono_ms();
        expansion_box_start(&port, host_now);
        box_game_set_port(&game, &port);
    }
    if (announce_ms > 0) {
        game.lobby.first_min_ms = game.lobby.first_max_ms = (uint32_t)announce_ms;
        game.lobby.interval_fixed_ms = (uint32_t)announce_ms;
    }
    if (join_key_hex != NULL && !box_game_set_join_key_hex(&game, join_key_hex)) {
        fprintf(stderr, "box_host: --join-key needs 64 hex digits\n");
        return 2;
    }
    adoption_ops_t aops = {adopt_busy, adopt_store, shell_screen, shell_log, NULL};
    adoption_init(&adopt, &aops, admin_pin);
    static admin_pin_t guard; /* "@output ..." wants the admin PIN, as a release build does */
    admin_pin_init(&guard, NULL, admin_pin);
    adoption_identity_t adopt_id = {name, mac, fw_version};
    if (box_game_load_join_key(&game)) {
        char field_name[ADOPTION_NAME_MAX + 1];
        int n = read_file("field_name", (uint8_t *)field_name, ADOPTION_NAME_MAX);
        field_name[n > 0 ? n : 0] = '\0';
        adoption_restore(&adopt, game.join_key, field_name);
    }
    game.state_interval_ms = (uint32_t)state_ms;
    static box_pair_t pairing;
    box_pair_ops_t pops = {lbt_send, shell_random, shell_screen, shell_log, NULL};
    box_pair_init(&pairing, &pops, &adopt, &atalaia_crypto_mbedtls, name, 0,
                  radio_region_default_channel_hz(host_region));

    uint32_t last = mono_ms();
    box_game_set_reset_reason(&game, "power"); /* the host's "battery pull" is a power cut */
    bool resumed = box_game_resume(&game, last);
    if (resumed) out("LOG rejoined the stored game");
    button_tracker_t buttons;
    button_tracker_init(&buttons, game.teams, game.join.team_count);
    uint8_t pressed = 0;
    uint32_t release_at[4] = {0};

    struct sockaddr_in addr;
    socklen_t alen = sizeof(addr);
    getsockname(air_sock, (struct sockaddr *)&addr, &alen);
    out("READY air=%u", ntohs(addr.sin_port));
    /* A free adopted box: ready from boot (decision BN-10), after READY (the first line). */
    if (!resumed && adopt.adopted && game.lobby.ready && !pair) box_lobby_show_ready(&game);
    if (pair) box_pair_start(&pairing, last);

    serial_console_t console;
    serial_console_init(&console);
    char line[1024];
    size_t line_len = 0;

    for (;;) {
        struct pollfd fds[2] = {{air_sock, POLLIN, 0}, {STDIN_FILENO, POLLIN, 0}};
        if (poll(fds, 2, 10) < 0 && errno != EINTR) {
            perror("box_host: poll");
            return 1;
        }
        uint32_t now = mono_ms();
        uint32_t delta = now - last;
        last = now;

        if (fds[0].revents & POLLIN) {
            uint8_t pkt[RADIO_MAX_PKT_LEN + 1];
            ssize_t got = recv(air_sock, pkt, sizeof(pkt), 0);
            if (got > 0 && got <= RADIO_MAX_PKT_LEN &&
                !box_pair_on_packet(&pairing, pkt, (size_t)got, now)) {
                box_game_on_packet(&game, pkt, (size_t)got, -48);
            }
        }
        if (fds[1].revents & (POLLIN | POLLHUP)) {
            char buf[512];
            ssize_t got = read(STDIN_FILENO, buf, sizeof(buf));
            if (got <= 0) return 0; /* stdin closed: the test is done */
            for (ssize_t i = 0; i < got; i++) {
                /* '@' lines go through the console parser, exactly as on the box. */
                char key;
                const char *command = NULL;
                serial_input_t in = serial_console_feed(&console, buf[i], &key, &command);
                if (in == SERIAL_COMMAND) {
                    if (strncmp(command, "join ", 5) == 0) {
                        box_join_result_t r = box_game_join_text(&game, command + 5);
                        out("LOG join: %s", box_join_result_name(r));
                        button_tracker_init(&buttons, game.teams, game.join.team_count);
                    } else if (strcmp(command, "pair") == 0) {
                        if (!box_pair_start(&pairing, now)) out("LOG pair: refused");
                    } else if (strncmp(command, "joinkey ", 8) == 0 ||
                               strncmp(command, "adopt", 5) == 0) {
                        /* "@adopt-info", "@adopt ...", "@joinkey ...": the box's own rules. */
                        static char reply[ADOPTION_REPLY_MAX];
                        if (adoption_command(&adopt, command, &adopt_id, now, reply,
                                             sizeof(reply))) {
                            if (strncmp(reply, ADOPTION_REPLY_PREFIX,
                                        sizeof(ADOPTION_REPLY_PREFIX) - 1) == 0) {
                                out("%s", reply);
                            } else {
                                out("LOG %s", reply);
                            }
                        }
                    } else if (strcmp(command, "modules") == 0) {
                        static char mods[600];
                        expansion_box_status_json(&port, mods, sizeof(mods));
                        out("LOG modules: %s", mods);
                    } else if (strcmp(command, "outputs") == 0 ||
                               outputs_admin_args(command) >= 0) {
                        static char line_out[200], reply_out[240];
                        snprintf(line_out, sizeof(line_out), "%s", command);
                        int args = outputs_admin_args(line_out);
                        if (args < 0 || admin_pin_gate_serial(&guard, false, line_out, args,
                                                              reply_out, sizeof(reply_out))) {
                            bool busy = box_game_active(&game) || runner.running;
                            outputs_admin_command(&outs, line_out, busy, reply_out,
                                                  sizeof(reply_out));
                        }
                        out("LOG %s", reply_out);
                    } else if (strncmp(command, "tag ", 4) == 0) {
                        out("LOG tag %s",
                            box_game_tag_text(&game, command + 4) ? "read" : "not read");
                    }
                    line_len = 0;
                    continue;
                }
                if (console.in_command || buf[i] == '@') continue;
                if (buf[i] == '\n') {
                    line[line_len] = '\0';
                    line_len = 0;
                    int b = 0;
                    unsigned ms = 0;
                    if (sscanf(line, "hold %d %u", &b, &ms) == 2 && b >= 1 && b <= 4) {
                        pressed |= (uint8_t)(1u << (b - 1));
                        release_at[b - 1] = now + ms;
                    } else if (strncmp(line, "keys ", 5) == 0) {
                        /* Keypad presses, as the shell sends them to a running mode. */
                        for (const char *k = line + 5; *k; k++) {
                            /* An admin PIN for another field's card first, as the shell does. */
                            if (box_pair_showing(&pairing) && box_pair_key(&pairing, *k, now)) {
                                continue;
                            }
                            if (adoption_active(&adopt) && adoption_key(&adopt, *k, now)) continue;
                            if (!runner.running) continue;
                            char json[16];
                            snprintf(json, sizeof(json), "{\"key\":\"%c\"}", *k);
                            node_runner_input(&runner, "keypad.key", json);
                        }
                    } else if (strncmp(line, "card ", 5) == 0) {
                        /* An NFC tag's memory (hex, from page 4) on the reader, between games. */
                        static uint8_t mem[888];
                        size_t n = 0;
                        unsigned v;
                        for (const char *h = line + 5; n < sizeof(mem) && sscanf(h, "%2x", &v) == 1;
                             h += 2) {
                            mem[n++] = (uint8_t)v;
                        }
                        adopt_result_t r;
                        if (!adoption_tap(&adopt, mem, n, now, &r)) out("LOG card: no field card");
                    } else if (sscanf(line, "battery %d", &b) == 1) {
                        battery = b < 0 ? -1 : b > 100 ? 100 : b;
                    } else if (sscanf(line, "lbtbusy %d", &b) == 1) {
                        lbt_busy_left = b;
                    } else if (module_command(line, now)) {
                        /* hit, unplug, plug: the modules on the port */
                    } else if (strcmp(line, "status") == 0) {
                        print_status();
                    } else if (strcmp(line, "quit") == 0) {
                        return 0;
                    }
                } else if (line_len + 1 < sizeof(line)) {
                    line[line_len++] = buf[i];
                }
            }
        }

        for (int b = 0; b < 4; b++) {
            if ((pressed & (1u << b)) && (int32_t)(now - release_at[b]) >= 0) {
                pressed &= (uint8_t) ~(1u << b);
            }
        }
        if (game.phase == BOX_PLAYING && !game.paused && runner.running) {
            button_tracker_update(&buttons, pressed, delta, &runner);
        }
        if (fetch_due) {
            fetch_due = false;
            run_fetch();
        }
        box_game_tick(&game, delta, now);
        host_now = now;
        outputs_tick(&outs, box_game_output_state(&game), now);
        expansion_box_tick(&port, box_game_output_state(&game), now);
        modules_tick(now);
        pins_low(now);
        lbt_pump(now);
        adoption_tick(&adopt, now);
        box_pair_tick(&pairing, now);
        for (int i = 0; i < runner.queues.screen_count; i++) {
            const screen_update_t *su = &runner.queues.screens[i];
            out("SCREEN %s %s", su->template_name, su->data_json);
        }
        runner.queues.screen_count = 0;
        runner.queues.audio_count = 0;
    }
}
