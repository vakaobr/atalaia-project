/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Field link: a box's side of Skirmesh-RF in a joined game (see field_link.h).
 */
#include "field_link.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "atalaia/codec.h"
#include "atalaia/flood.h"

#define ACK_RETRY_MS 3000

static void say(field_link_t *l, const char *fmt, ...) __attribute__((format(printf, 2, 3)));

static void say(field_link_t *l, const char *fmt, ...)
{
    if (l->io.log == NULL) return;
    char line[160];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);
    l->io.log(l->io.user, line);
}

/* ---- Outbox ---------------------------------------------------------------- */

static field_link_pending_t *outbox_slot(field_link_t *l)
{
    for (size_t i = 0; i < FIELD_LINK_OUTBOX; i++) {
        if (!l->outbox[i].used) return &l->outbox[i];
    }
    return NULL;
}

/* Sends (or resends) an outbox entry in a new packet. */
static void transmit(field_link_t *l, field_link_pending_t *p)
{
    uint16_t seq = l->proto.seq;
    uint16_t epoch = l->proto.epoch;
    if (!atalaia_radio_proto_send_payload(&l->proto, p->type, p->prio, true, p->payload, p->len,
                                          NULL)) {
        l->stats.tx_refused++;
    }
    /* A seq that was used (even if the radio queue then refused the packet)
     * is what an ACK will name; a refusal before that (no key, NVS failure)
     * leaves the entry unsent. */
    if (l->proto.seq != seq || l->proto.epoch != epoch) {
        p->pkt_seq = seq;
        p->sent = true;
    }
    p->tries++;
    p->next_ms = l->now_ms + ACK_RETRY_MS;
}

/* The lowest log seq still unacknowledged; everything below may be compacted. */
static void update_log_ack(field_link_t *l)
{
    if (l->log == NULL || l->backlog) return;
    uint16_t lowest = 0;
    for (size_t i = 0; i < FIELD_LINK_OUTBOX; i++) {
        const field_link_pending_t *p = &l->outbox[i];
        if (p->used && p->log_seq != 0 && (lowest == 0 || p->log_seq < lowest)) lowest = p->log_seq;
    }
    uint16_t upto = lowest != 0 ? (uint16_t)(lowest - 1) : (uint16_t)(l->next_log_seq - 1);
    if (upto > l->log->ack_seq) {
        event_log_ack(l->log, upto);
        event_log_compact(l->log);
    }
}

static void done(field_link_t *l, field_link_pending_t *p, bool acked)
{
    if (acked) {
        l->stats.acked++;
        if (p->type == ATALAIA_MSG_HELLO) l->hello_pending = false;
    } else {
        l->stats.expired++;
    }
    p->used = false;
}

typedef struct {
    field_link_t *l;
    int added;
} refill_ctx_t;

static bool in_outbox(const field_link_t *l, uint16_t log_seq)
{
    for (size_t i = 0; i < FIELD_LINK_OUTBOX; i++) {
        if (l->outbox[i].used && l->outbox[i].log_seq == log_seq) return true;
    }
    return false;
}

static void refill_cb(const event_log_entry_t *entry, void *user)
{
    refill_ctx_t *c = (refill_ctx_t *)user;
    field_link_t *l = c->l;
    if (entry->seq >= l->next_log_seq) l->next_log_seq = (uint16_t)(entry->seq + 1);
    if (in_outbox(l, entry->seq) || entry->data_len == 0) return;
    field_link_pending_t *p = outbox_slot(l);
    if (p == NULL) {
        l->backlog = true;
        return;
    }
    memset(p, 0, sizeof(*p));
    p->used = true;
    p->type = ATALAIA_MSG_EVENT;
    p->prio = entry->priority == EVENT_LOG_CRITICAL ? ATALAIA_PRIO_CRITICAL : ATALAIA_PRIO_NORMAL;
    p->log_seq = entry->seq;
    p->len = entry->data_len;
    memcpy(p->payload, entry->data, entry->data_len);
    p->next_ms = l->now_ms; /* send at the next tick */
    c->added++;
}

/* Loads unacknowledged events from the flash log into free outbox slots. */
static int refill(field_link_t *l)
{
    if (l->log == NULL) return 0;
    l->backlog = false;
    refill_ctx_t c = {l, 0};
    event_log_replay_from(l->log, 1, refill_cb, &c);
    return c.added;
}

/* ---- Sending ----------------------------------------------------------------- */

static void send_hello(field_link_t *l)
{
    atalaia_hello_t h = l->hello;
    h.epoch = l->proto.epoch;
    uint8_t buf[ATALAIA_RF_PAYLOAD_MAX];
    size_t n = atalaia_hello_encode(&h, buf, sizeof(buf));
    if (n == 0) return;
    /* HELLO waits for its ACK in the outbox like a critical event. */
    for (size_t i = 0; i < FIELD_LINK_OUTBOX; i++) {
        if (l->outbox[i].used && l->outbox[i].type == ATALAIA_MSG_HELLO) l->outbox[i].used = false;
    }
    field_link_pending_t *p = outbox_slot(l);
    if (p == NULL) return;
    memset(p, 0, sizeof(*p));
    p->used = true;
    p->type = ATALAIA_MSG_HELLO;
    p->prio = ATALAIA_PRIO_CRITICAL;
    p->len = (uint8_t)n;
    memcpy(p->payload, buf, n);
    l->hello_pending = true;
    l->stats.hellos_sent++;
    transmit(l, p);
}

static void send_state(field_link_t *l)
{
    atalaia_state_msg_t st;
    memset(&st, 0, sizeof(st));
    st.rssi = INT8_MIN;
    st.battery_pct = 0xFF;
    st.flags = 0xFF;
    if (l->io.get_state != NULL) l->io.get_state(l->io.user, &st);
    st.epoch = l->proto.epoch;
    if (l->last_rssi != 0) st.rssi = l->last_rssi;
    if (atalaia_radio_proto_send_state(&l->proto, &st)) {
        l->stats.states_sent++;
    } else {
        l->stats.tx_refused++;
    }
    l->last_state_ms = l->now_ms;
    l->state_due = false;
}

void field_link_event(field_link_t *l, const atalaia_event_t *ev, const char *data_json)
{
    uint8_t payload[ATALAIA_RF_PAYLOAD_MAX];
    const char *err = NULL;
    size_t n = atalaia_event_encode(ev, data_json, payload, sizeof(payload), &err);
    if (n == 0) {
        say(l, "event %s not sent: %s", ev->type, err ? err : "encode failed");
        return;
    }
    l->stats.events_sent++;
    if (ev->prio == ATALAIA_PRIO_TELEMETRY) {
        if (!atalaia_radio_proto_send_payload(&l->proto, ATALAIA_MSG_EVENT, ATALAIA_PRIO_TELEMETRY,
                                              false, payload, n, NULL)) {
            l->stats.tx_refused++;
        }
        return;
    }

    /* Normal and critical: into the flash log first (power loss), then the outbox. */
    uint16_t log_seq = 0;
    if (l->log != NULL && l->next_log_seq != 0) {
        event_log_entry_t entry;
        memset(&entry, 0, sizeof(entry));
        entry.seq = l->next_log_seq;
        entry.priority = ev->prio == ATALAIA_PRIO_CRITICAL ? EVENT_LOG_CRITICAL : EVENT_LOG_NORMAL;
        entry.data_len = (uint8_t)n;
        memcpy(entry.data, payload, n);
        if (event_log_append(l->log, &entry) == 0) {
            log_seq = l->next_log_seq;
            l->next_log_seq = l->next_log_seq == 0xFFFF ? 0 : (uint16_t)(l->next_log_seq + 1);
        } else {
            say(l, "event log full or failing: %s kept in RAM only", ev->type);
        }
    }

    field_link_pending_t *p = outbox_slot(l);
    if (p == NULL) {
        if (log_seq != 0) {
            l->backlog = true; /* sent from the log once the outbox has room */
        } else {
            say(l, "outbox full: %s dropped", ev->type);
            l->stats.expired++;
        }
        /* Still send it once now: the controller may well hear it. */
        atalaia_radio_proto_send_payload(&l->proto, ATALAIA_MSG_EVENT, (uint8_t)ev->prio, true,
                                         payload, n, NULL);
        return;
    }
    memset(p, 0, sizeof(*p));
    p->used = true;
    p->type = ATALAIA_MSG_EVENT;
    p->prio = (uint8_t)ev->prio;
    p->log_seq = log_seq;
    p->len = (uint8_t)n;
    memcpy(p->payload, payload, n);
    transmit(l, p);

    /* A capture changes what STATE says: tell the controller now. */
    if (strcmp(ev->type, "zone.captured") == 0 || strcmp(ev->type, "zone.neutralized") == 0) {
        l->state_due = true;
    }
}

void field_link_send_rebooted(field_link_t *l, uint32_t t_ms)
{
    atalaia_event_t ev;
    if (!atalaia_event_init(&ev, l->join.node_id, 0, t_ms, "node.rebooted", ATALAIA_TEAM_NONE,
                            ATALAIA_SQUAD_NONE, ATALAIA_PRIO_CRITICAL)) {
        return;
    }
    field_link_event(l, &ev, "{\"reason\":\"power\"}");
}

void field_link_send_battery_low(field_link_t *l, uint8_t percent, uint32_t t_ms)
{
    atalaia_event_t ev;
    if (!atalaia_event_init(&ev, l->join.node_id, 0, t_ms, "battery.low", ATALAIA_TEAM_NONE,
                            ATALAIA_SQUAD_NONE, ATALAIA_PRIO_TELEMETRY)) {
        return;
    }
    char data[24];
    snprintf(data, sizeof(data), "{\"percent\":%u}", (unsigned)percent);
    field_link_event(l, &ev, data);
}

/* Copies a short code into out, keeping only what needs no JSON escape ([0-9A-Za-z._+-]). */
static void plain_code(char *out, size_t cap, const char *in)
{
    size_t n = 0;
    for (; in != NULL && *in != '\0' && n + 1 < cap; in++) {
        char c = *in;
        if ((c >= '0' && c <= '9') || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
            c == '.' || c == '_' || c == '+' || c == '-') {
            out[n++] = c;
        }
    }
    out[n] = '\0';
}

void field_link_send_update_failed(field_link_t *l, const char *release, const char *reason,
                                   const char *fw, uint32_t t_ms)
{
    atalaia_event_t ev;
    uint16_t seq = (uint16_t)(l->proto.seq + 1u); /* the header seq of the next packet */
    if (!atalaia_event_init(&ev, l->join.node_id, seq, t_ms, "node.update_failed",
                            ATALAIA_TEAM_NONE, ATALAIA_SQUAD_NONE, ATALAIA_PRIO_CRITICAL)) {
        return;
    }
    char rel[17], why[24], ver[33], data[128];
    plain_code(rel, sizeof(rel), release);
    plain_code(why, sizeof(why), reason);
    plain_code(ver, sizeof(ver), fw);
    snprintf(data, sizeof(data), "{\"release\":\"%s\",\"reason\":\"%s\",\"fw\":\"%s\"}", rel, why,
             ver);
    field_link_event(l, &ev, data);
}

void field_link_send_modes_failed(field_link_t *l, const char *mode, const char *reason,
                                  uint32_t t_ms)
{
    atalaia_event_t ev;
    uint16_t seq = (uint16_t)(l->proto.seq + 1u); /* the header seq of the next packet */
    if (!atalaia_event_init(&ev, l->join.node_id, seq, t_ms, "node.modes_failed", ATALAIA_TEAM_NONE,
                            ATALAIA_SQUAD_NONE, ATALAIA_PRIO_CRITICAL)) {
        return;
    }
    char id[ATALAIA_JOIN_MODE_MAX + 1], why[24], data[128];
    plain_code(id, sizeof(id), mode);
    plain_code(why, sizeof(why), reason);
    snprintf(data, sizeof(data), "{\"mode\":\"%s\",\"reason\":\"%s\"}", id, why);
    field_link_event(l, &ev, data);
}

/* ---- Init -------------------------------------------------------------------- */

bool field_link_init(field_link_t *l, const atalaia_join_t *join,
                     const atalaia_crypto_ops_t *crypto, const atalaia_radio_nvs_ops_t *nvs,
                     event_log_t *log, const atalaia_hello_t *hello, const field_link_io_t *io,
                     uint32_t now_ms, bool resuming)
{
    memset(l, 0, sizeof(*l));
    l->join = *join;
    l->io = *io;
    l->hello = *hello;
    l->log = log;
    l->now_ms = now_ms;
    l->state_interval_ms = FIELD_LINK_STATE_MS;
    l->last_state_ms = now_ms;
    l->leader = join->controller_id;
    l->next_log_seq = 1;
    atalaia_time_sync_init(&l->ts);

    atalaia_radio_proto_init(&l->proto, join->game_id, join->node_id, crypto, nvs);
    l->proto.max_hops = join->max_hops;
    l->proto.tx = io->tx;
    l->proto.tx_ctx = io->tx_ctx;
    atalaia_radio_proto_set_key(&l->proto, join->game_key);
    if (!atalaia_radio_proto_boot_epoch(&l->proto, resuming)) {
        say(l, "radio halted: the nonce epoch could not be stored");
        return false;
    }
    /* Events from before a reboot that were never acknowledged. */
    int replayed = refill(l);
    if (replayed > 0)
        say(l, "%d unacknowledged event(s) from the flash log queued again", replayed);
    send_hello(l);
    return true;
}

/* ---- Receiving -------------------------------------------------------------------- */

/* True if (source, epoch, seq) was seen in the last 30 s; records it otherwise. */
static bool seen_before(field_link_t *l, uint16_t source, uint16_t epoch, uint16_t seq)
{
    field_link_seen_t *oldest = &l->seen[0];
    field_link_seen_t *free_slot = NULL;
    for (size_t i = 0; i < FIELD_LINK_DEDUPE; i++) {
        field_link_seen_t *s = &l->seen[i];
        bool live = s->seen_ms != 0 && l->now_ms - s->seen_ms < FIELD_LINK_DEDUPE_MS;
        if (live && s->source == source && s->epoch == epoch && s->seq == seq) return true;
        if (!live && free_slot == NULL) free_slot = s;
        if (s->seen_ms < oldest->seen_ms) oldest = s;
    }
    field_link_seen_t *slot = free_slot != NULL ? free_slot : oldest;
    slot->source = source;
    slot->epoch = epoch;
    slot->seq = seq;
    slot->seen_ms = l->now_ms ? l->now_ms : 1;
    return false;
}

static void schedule_relay(field_link_t *l, const uint8_t *pkt, size_t len,
                           const atalaia_header_t *h)
{
    uint8_t hop;
    if (!atalaia_flood_should_relay(h->hop_limit, l->join.max_hops, &hop)) return;
    for (size_t i = 0; i < FIELD_LINK_RELAYS; i++) {
        field_link_relay_t *r = &l->relays[i];
        if (r->used) continue;
        r->used = true;
        r->len = (uint8_t)len;
        memcpy(r->pkt, pkt, len);
        r->pkt[ATALAIA_RF_HOP_LIMIT_OFFSET] = hop; /* not in the AAD: the MIC stays valid */
        r->due_ms = l->now_ms + atalaia_flood_jitter_ms(h->source, h->seq);
        return;
    }
}

static void apply_acks(field_link_t *l, const atalaia_ack_msg_t *ack)
{
    int32_t contig = ack->ack_seq == 0xFFFF ? -1 : (int32_t)ack->ack_seq;
    for (size_t i = 0; i < FIELD_LINK_OUTBOX; i++) {
        field_link_pending_t *p = &l->outbox[i];
        if (!p->used || !p->sent) continue;
        bool acked = (int32_t)p->pkt_seq <= contig;
        int32_t bit = (int32_t)p->pkt_seq - contig - 1;
        if (!acked && bit >= 0 && (size_t)(bit / 8) < ack->ack_bitmap_len) {
            acked = (ack->ack_bitmap[bit / 8] >> (bit % 8)) & 1;
        }
        if (acked) done(l, p, true);
    }
    update_log_ack(l);
}

/* A TIME or CMD moved the game on: tell the shell what it missed. */
static void follow_state(field_link_t *l, uint8_t state)
{
    if (state == l->game_state || state > FIELD_GAME_ENDED) return;
    uint8_t was = l->game_state;
    l->game_state = state;
    if (l->io.on_cmd == NULL) return;
    switch (state) {
    case FIELD_GAME_RUNNING:
        l->io.on_cmd(l->io.user, was == FIELD_GAME_PAUSED ? FIELD_CMD_RESUME : FIELD_CMD_START, "");
        break;
    case FIELD_GAME_PAUSED:
        if (was == FIELD_GAME_WAITING) l->io.on_cmd(l->io.user, FIELD_CMD_START, "");
        l->io.on_cmd(l->io.user, FIELD_CMD_PAUSE, "");
        break;
    case FIELD_GAME_ENDED: l->io.on_cmd(l->io.user, FIELD_CMD_END, ""); break;
    default: break;
    }
}

static void on_time(field_link_t *l, const atalaia_header_t *h, const uint8_t *pl, size_t n)
{
    atalaia_time_msg_t t;
    if (!atalaia_time_decode(pl, n, &t)) return;
    if (t.term < l->term) return; /* an old controller that has not stepped down yet */
    if (t.term > l->term || h->source != l->leader) {
        if (h->source != l->leader)
            say(l, "following controller %u (term %lu)", h->source, (unsigned long)t.term);
        l->leader = h->source;
        l->term = t.term;
    }
    l->stats.times++;
    l->have_time = true;
    l->controller_time_ms = t.game_time_ms + FIELD_LINK_AIRTIME_MS;
    follow_state(l, t.game_state);
    if (t.game_state == FIELD_GAME_RUNNING && l->io.game_time != NULL) {
        uint32_t local = l->io.game_time(l->io.user);
        atalaia_time_sync_on_beacon(&l->ts, t.game_time_ms, FIELD_LINK_AIRTIME_MS,
                                    t.tx_time_us == 0xFFFF ? 0 : t.tx_time_us, local);
        if (l->ts.stepped) {
            if (l->ts.offset_ms > 0) {
                l->step_ms += l->ts.offset_ms;
            } else {
                l->hold_ms += (uint32_t)(-l->ts.offset_ms);
            }
            say(l, "game clock stepped by %ld ms", (long)l->ts.offset_ms);
            atalaia_time_sync_init(&l->ts);
        }
    }
}

static void on_cmd(field_link_t *l, const atalaia_header_t *h, const uint8_t *pl, size_t n)
{
    atalaia_cmd_msg_t c;
    if (!atalaia_cmd_decode(pl, n, &c)) return;
    if (c.dest != 0xFFFF && c.dest != l->join.node_id) return;
    /* Commands come from the controller we follow (or anyone before the first TIME). */
    if (h->source != l->leader && l->have_time) return;
    l->stats.cmds++;
    switch (c.cmd) {
    case FIELD_CMD_START: l->game_state = FIELD_GAME_RUNNING; break;
    case FIELD_CMD_PAUSE: l->game_state = FIELD_GAME_PAUSED; break;
    case FIELD_CMD_RESUME: l->game_state = FIELD_GAME_RUNNING; break;
    case FIELD_CMD_END: l->game_state = FIELD_GAME_ENDED; break;
    default: break;
    }
    if (l->io.on_cmd != NULL) l->io.on_cmd(l->io.user, c.cmd, c.params_json);
    if (c.cmd == FIELD_CMD_START || c.cmd == FIELD_CMD_RESUME) field_link_reset_sync(l);
}

void field_link_on_packet(field_link_t *l, const uint8_t *pkt, size_t len, int8_t rssi)
{
    if (len > RADIO_MAX_PKT_LEN) return;
    radio_rx_msg_t rx;
    memcpy(rx.data, pkt, len);
    rx.len = len;
    rx.rssi = rssi;
    rx.timestamp_ms = l->now_ms;

    atalaia_header_t h;
    uint8_t pl[ATALAIA_RF_PAYLOAD_MAX + ATALAIA_RF_MIC_SIZE];
    size_t n = 0;
    uint16_t epoch = 0;
    /* Other games and our own relayed copies are ignored before any crypto. */
    if (len < ATALAIA_RF_HEADER_SIZE || !atalaia_header_decode(pkt, &h) ||
        h.game_id != l->join.game_id || h.source == l->join.node_id) {
        return;
    }
    if (!atalaia_radio_proto_on_recv_window(&l->proto, &rx, 16, &h, pl, &n, &epoch)) {
        l->stats.rx_rejected++;
        return;
    }
    if (seen_before(l, h.source, epoch, h.seq)) {
        l->stats.rx_duplicates++;
        return;
    }
    l->stats.rx_ok++;
    l->last_rssi = rssi;
    schedule_relay(l, pkt, len, &h);

    switch (h.type) {
    case ATALAIA_MSG_TIME: on_time(l, &h, pl, n); break;
    case ATALAIA_MSG_CMD: on_cmd(l, &h, pl, n); break;
    case ATALAIA_MSG_ACK: {
        atalaia_ack_msg_t a;
        if (atalaia_ack_msg_decode(pl, n, &a) && a.ack_node == l->join.node_id) apply_acks(l, &a);
        break;
    }
    default: break; /* other boxes' EVENT, STATE, HELLO, and CLAIM: relayed only */
    }
}

/* ---- Time ---------------------------------------------------------------------- */

void field_link_state_now(field_link_t *l)
{
    l->state_due = true;
}

void field_link_tick(field_link_t *l, uint32_t now_ms)
{
    l->now_ms = now_ms;

    /* Relays whose jitter has passed. */
    for (size_t i = 0; i < FIELD_LINK_RELAYS; i++) {
        field_link_relay_t *r = &l->relays[i];
        if (!r->used || (int32_t)(now_ms - r->due_ms) < 0) continue;
        bool ok = l->proto.tx != NULL ? l->proto.tx(l->proto.tx_ctx, r->pkt, r->len)
                                      : radio_task_send(r->pkt, r->len);
        if (ok) l->stats.relayed++;
        r->used = false;
    }

    /* Retries: a new packet for each, so the controller ACKs it again. */
    for (size_t i = 0; i < FIELD_LINK_OUTBOX; i++) {
        field_link_pending_t *p = &l->outbox[i];
        if (!p->used || (int32_t)(now_ms - p->next_ms) < 0) continue;
        if (p->tries > 0 && p->prio != ATALAIA_PRIO_CRITICAL && p->tries > FIELD_LINK_MAX_RETRIES) {
            done(l, p, false); /* normal priority: STATE sync repairs the rest */
            continue;
        }
        if (p->tries > 0) l->stats.retries++;
        transmit(l, p);
    }
    if (l->backlog) {
        refill(l);
    } else {
        update_log_ack(l);
    }

    if (l->state_due || now_ms - l->last_state_ms >= l->state_interval_ms) send_state(l);
}

uint32_t field_link_adjust_delta(field_link_t *l, uint32_t raw_delta_ms)
{
    if (l->step_ms > 0) {
        uint32_t d = raw_delta_ms + (uint32_t)l->step_ms;
        l->step_ms = 0;
        return d;
    }
    if (l->hold_ms > 0) {
        if (raw_delta_ms >= l->hold_ms) {
            uint32_t d = raw_delta_ms - l->hold_ms;
            l->hold_ms = 0;
            return d;
        }
        l->hold_ms -= raw_delta_ms;
        return 0;
    }
    return atalaia_time_sync_adjust(&l->ts, raw_delta_ms);
}

void field_link_reset_sync(field_link_t *l)
{
    atalaia_time_sync_init(&l->ts);
    l->step_ms = 0;
    l->hold_ms = 0;
}

size_t field_link_pending(const field_link_t *l)
{
    size_t n = 0;
    for (size_t i = 0; i < FIELD_LINK_OUTBOX; i++) {
        if (l->outbox[i].used && l->outbox[i].type == ATALAIA_MSG_EVENT) n++;
    }
    return n + (l->backlog ? 1 : 0);
}
