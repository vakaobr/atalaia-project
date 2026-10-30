/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Field link: a box's side of Skirmesh-RF in a joined game (decision D18).
 *
 *   - every game event the node emits goes out as an EVENT packet; normal
 *     and critical ones ask for an ACK and stay in an outbox (and in the
 *     flash event log) until the controller acknowledges them, resent
 *     at 3, 6, 12, 24, then every 30 s (each x0.75-1.25), in a new packet (new seq,
 *     same event; RFC 0001 Amendment 13);
 *   - HELLO after a join or a reboot, until acknowledged;
 *   - STATE (owner, phase, game time, score counters, epoch) every
 *     state_interval_ms and after a change of owner;
 *   - TIME beacons drive the time sync and the leader (highest term);
 *   - CMDs for this node (or every node) go to the shell through on_cmd;
 *   - ACKs (ack_seq + bitmap, D7) clear the outbox;
 *   - authenticated packets from others are relayed at most once with hop_limit
 *     clamped to max_hops and decremented, by the rules of Amendment 13 (core
 *     atalaia_relay_*: a frame that asks for an ACK waits 350-700 ms and is
 *     cancelled if the controller's ACK is heard; the controller's ACK is relayed
 *     only for a box whose frame this box relayed; the rest with probability
 *     min(1, 3 / neighbours) after 20-600 ms; 8 slots), all from the box's own entropy.
 *
 * No FreeRTOS, no ESP-IDF: the shell feeds it received packets and the
 * time, and supplies the TX sink, so the host tests and the host box
 * (test/box_host) run exactly this code.
 */
#ifndef ATALAIA_FIELD_LINK_H
#define ATALAIA_FIELD_LINK_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "atalaia/event.h"
#include "atalaia/flood.h"
#include "atalaia/join.h"
#include "atalaia/msg_codec.h"
#include "event_log.h"
#include "radio_protocol.h"
#include "time_sync.h"

#define FIELD_LINK_OUTBOX      32
#define FIELD_LINK_RELAYS      ATALAIA_RELAY_SLOTS /* 8 (was 4 before Amendment 13) */
#define FIELD_LINK_STATE_MS    15000               /* default STATE interval */
#define FIELD_LINK_AIRTIME_MS  40                  /* rough TIME airtime at SF7/BW125 */
#define FIELD_LINK_MAX_RETRIES 10                  /* normal priority; critical retries until ACK */

/* CMD opcodes (ADR-P2-3; FIELD_CMD_MODE: RFC 0001 Amendment 5; FIELD_CMD_UPDATE:
 * Amendment 6, protocol/firmware-update.md). */
enum {
    FIELD_CMD_START = 0,
    FIELD_CMD_PAUSE = 1,
    FIELD_CMD_RESUME = 2,
    FIELD_CMD_END = 3,
    FIELD_CMD_SET_OWNER = 4,
    FIELD_CMD_MESSAGE = 5,
    FIELD_CMD_RESET = 6,
    FIELD_CMD_REBOOT = 7,
    FIELD_CMD_MODE = 8,   /* a command for the mode script: cmd.mode, its params name it */
    FIELD_CMD_UPDATE = 9, /* a firmware update over Wi-Fi: params {"id", "version"} */
};

/* Game states as TIME carries them. */
enum {
    FIELD_GAME_WAITING = 0,
    FIELD_GAME_RUNNING = 1,
    FIELD_GAME_PAUSED = 2,
    FIELD_GAME_ENDED = 3,
};

typedef struct {
    /* The node's state for STATE packets: owner_team, phase, game_time_ms,
     * counters and battery (0xFF if unknown). The link fills epoch and rssi. */
    void (*get_state)(void *user, atalaia_state_msg_t *st);
    /* A CMD for this node: opcode and its params as compact JSON ("" if none).
     * Also called when a TIME beacon shows the game state moved on without
     * us (a CMD was lost): START, PAUSE, RESUME or END with params "". */
    void (*on_cmd)(void *user, uint8_t cmd, const char *params_json);
    /* The node's current game time in ms (for the time sync). */
    uint32_t (*game_time)(void *user);
    /* A log line (may be NULL). */
    void (*log)(void *user, const char *line);
    /* Random bytes from the box's entropy (the shell's, shell.random: timing spread, never a
     * nonce). NULL: a fixed per-node sequence (host tests that do not care). */
    void (*random)(void *user, uint8_t *buf, size_t len);
    void *user;
    /* Where packets go (proto.tx): NULL = radio_task_send(). */
    bool (*tx)(void *ctx, const uint8_t *pkt, size_t len);
    void *tx_ctx;
} field_link_io_t;

typedef struct {
    bool used;
    uint8_t type;     /* ATALAIA_MSG_EVENT or ATALAIA_MSG_HELLO */
    uint8_t prio;     /* atalaia_prio_t */
    bool sent;        /* pkt_seq is valid */
    uint16_t pkt_seq; /* header seq of the last transmission */
    uint16_t log_seq; /* entry in the flash log; 0 = not logged */
    uint8_t tries;
    uint32_t next_ms;
    uint8_t len;
    uint8_t payload[ATALAIA_RF_PAYLOAD_MAX];
} field_link_pending_t;

typedef struct {
    uint8_t len;
    uint8_t pkt[RADIO_MAX_PKT_LEN];
} field_link_relay_t;

typedef struct {
    uint32_t events_sent, retries, acked, expired;
    uint32_t rx_ok, rx_rejected, rx_duplicates, relayed;
    uint32_t rx_replays; /* authentic but 64+ counters below the source's highest (SR-20) */
    uint32_t cmds_stale, times_stale; /* a CMD or TIME older than one already applied (SR-21) */
    uint32_t relay_skipped, relay_cancelled, relay_no_slot; /* Amendment 13's rules at work */
    uint32_t cmds, times, states_sent, hellos_sent, tx_refused;
    /* Listen before talk (RFC 0001 Amendment 14), copied from the radio task's counters when the
     * radio report is made (box_game.c; the link itself never sees the radio): CADs run, frames
     * that waited for a busy channel, frames sent after the eighth busy answer in a row. */
    uint32_t lbt_cads, lbt_deferrals, lbt_gave_up;
} field_link_stats_t;

typedef struct {
    atalaia_join_t join;
    atalaia_radio_proto_t proto;
    atalaia_time_sync_t ts;
    field_link_io_t io;
    atalaia_hello_t hello; /* template; epoch and battery filled at send time */
    event_log_t *log;      /* flash log for unacknowledged events; may be NULL */

    field_link_pending_t outbox[FIELD_LINK_OUTBOX];
    bool backlog;          /* the log holds events the outbox had no room for */
    uint16_t next_log_seq; /* 1.. */
    atalaia_relay_t relay; /* the rules and the slots state */
    field_link_relay_t relays[FIELD_LINK_RELAYS]; /* the packets, by slot */
    uint32_t rand_fallback;                       /* io.random == NULL */

    uint32_t now_ms;
    uint32_t state_interval_ms;
    uint32_t last_state_ms;
    bool state_due;
    bool hello_pending;
    uint32_t next_hello_ms;

    uint16_t leader; /* who we follow: the join's controller, then the highest term's TIME */
    uint32_t term;
    uint8_t game_state; /* FIELD_GAME_*, from TIME and CMD */
    bool have_time;
    uint32_t controller_time_ms; /* game time of the last TIME, plus its airtime */
    /* Freshness of what changes the game's state (RFC 0001 Amendment 23, SR-21): the nonce
     * counter of the last game-state CMD applied and of the last TIME applied, per source (a new
     * leader starts its own). One that is not above is refused: a recording of a CMD or TIME that
     * this box never heard at the time passes the replay window, but not this. */
    uint16_t cmd_source, time_source;
    uint32_t cmd_ctr, time_ctr;
    bool have_cmd_ctr, have_time_ctr;
    int8_t last_rssi;
    int32_t step_ms;  /* time-sync step still to apply (positive: jump ahead) */
    uint32_t hold_ms; /* local clock ahead by this much: hold game time until caught up */

    field_link_stats_t stats;
} field_link_t;

/*
 * Set up the link for a verified join. Runs the boot epoch cycle (ADR-P2-2,
 * per game key since the RFC 0001 amendment of 2026-10-22: this key's epoch
 * + 1, or 1 for a new key, persisted before the first packet; resuming: the
 * stored game after a reboot, see atalaia_radio_proto_boot_epoch), and
 * queues HELLO. Unacknowledged events still in the log (a reboot) are
 * queued again. Returns false if the radio must not transmit (NVS failure:
 * proto.tx_blocked).
 */
bool field_link_init(field_link_t *l, const atalaia_join_t *join,
                     const atalaia_crypto_ops_t *crypto, const atalaia_radio_nvs_ops_t *nvs,
                     event_log_t *log, const atalaia_hello_t *hello, const field_link_io_t *io,
                     uint32_t now_ms, bool resuming);

/* The game event the node just emitted (from the core's event callback). */
void field_link_event(field_link_t *l, const atalaia_event_t *ev, const char *data_json);

/* A packet heard on the radio. */
void field_link_on_packet(field_link_t *l, const uint8_t *pkt, size_t len, int8_t rssi);

/* Time passes: retries, HELLO, STATE, relays. now_ms is the box's monotonic clock. */
void field_link_tick(field_link_t *l, uint32_t now_ms);

/* Ask for a STATE at the next tick (an owner change, a phase change). */
void field_link_state_now(field_link_t *l);

/*
 * The game-time delta to feed the node for raw_delta_ms of local time, with
 * the time sync applied: slewed by at most 5 %, a step ahead applied at once,
 * and a local clock that is ahead held until the controller catches up.
 */
uint32_t field_link_adjust_delta(field_link_t *l, uint32_t raw_delta_ms);

/* The local game time was set (start, resume after reboot): the sync restarts. */
void field_link_reset_sync(field_link_t *l);

/* Number of events still waiting for an ACK (outbox and log backlog). */
size_t field_link_pending(const field_link_t *l);

/* Sends node.rebooted (critical) from the link itself (event seq 0, game time t_ms). */
void field_link_send_rebooted(field_link_t *l, uint32_t t_ms);

/* Sends battery.low with the level in percent (telemetry: one packet, no ACK; event seq 0,
 * game time t_ms). */
void field_link_send_battery_low(field_link_t *l, uint8_t percent, uint32_t t_ms);

/* Sends node.update_failed (critical, retried until acknowledged): a firmware update the box
 * could not report over HTTPS (protocol/firmware-update.md). release: the offer's id (16 hex
 * digits, or "" if the offer had none), reason: the result code, fw: the version it still runs.
 * The event seq is the header seq of the first packet that carries it, so two failures in one
 * game (game time 0 before the start) are two events, not one taken for a copy of the other. */
void field_link_send_update_failed(field_link_t *l, const char *release, const char *reason,
                                   const char *fw, uint32_t t_ms);

/* Sends node.modes_failed (critical, retried until acknowledged): a fetch of the game's mode
 * packages that failed and could not be reported over HTTPS (mode_fetch.h, decision P5E-8).
 * mode: the part it could not get, reason: the fetch's result code. Its seq as above. */
void field_link_send_modes_failed(field_link_t *l, const char *mode, const char *reason,
                                  uint32_t t_ms);

#endif /* ATALAIA_FIELD_LINK_H */
