/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * CBOR encode/decode for all Skirmesh-RF message payloads except EVENT.
 *
 * The wire format is protocol/schema/messages.yaml, field for field:
 * encoders always write every required field (even when it is 0 or
 * empty), with the schema's CBOR types (array_uint8 is an array, map_*
 * types are maps, CMD params is a map); decoders reject a payload that
 * misses a required field, repeats a key, or holds a value that does not
 * fit its field. Unknown keys are skipped, so newer senders can add
 * optional fields. The same JSON vectors in protocol/vectors/ check this
 * codec and the Python one in the simulator.
 */
#include <limits.h>
#include <string.h>

#include "atalaia/codec.h"
#include "atalaia/msg_codec.h"

#include "cbor_int.h"

#define BIT(k) (1u << (k))

/* ---- Decoding helpers ----------------------------------------------------- */

/* Records key in *seen; false if the payload already had it. */
static bool mark(mc_reader_t *r, uint32_t *seen, uint64_t key)
{
    if (key < 32) {
        if (*seen & BIT(key)) {
            r->ok = false;
            return false;
        }
        *seen |= BIT(key);
    }
    return true;
}

/* An unsigned integer no larger than max. */
static bool read_uint_max(mc_reader_t *r, uint64_t max, uint64_t *out)
{
    uint64_t v;
    if (!mc_read_uint(r, &v) || v > max) {
        r->ok = false;
        return false;
    }
    *out = v;
    return true;
}

static bool done(const mc_reader_t *r, uint32_t seen, uint32_t required)
{
    return r->ok && r->p == r->end && (seen & required) == required;
}

/* ---- HELLO ---------------------------------------------------------------- */

#define HELLO_REQUIRED                                                                             \
    (BIT(ATALAIA_PL_HELLO_NODE_NAME) | BIT(ATALAIA_PL_HELLO_PLATFORM) |                            \
     BIT(ATALAIA_PL_HELLO_FW_VERSION) | BIT(ATALAIA_PL_HELLO_CORE_VERSION) |                       \
     BIT(ATALAIA_PL_HELLO_TIER) | BIT(ATALAIA_PL_HELLO_CAPABILITIES) |                             \
     BIT(ATALAIA_PL_HELLO_TRANSPORTS) | BIT(ATALAIA_PL_HELLO_EPOCH))

size_t atalaia_hello_encode(const atalaia_hello_t *msg, uint8_t *buf, size_t cap)
{
    mc_writer_t w;
    mc_init_writer(&w, buf, cap);
    if (msg->capabilities_count > sizeof(msg->capabilities)) {
        return 0;
    }

    mc_put_map(&w, (uint64_t)8 + (msg->battery_pct != 0xFF) + msg->has_device_id);

    mc_put_uint(&w, ATALAIA_PL_HELLO_NODE_NAME);
    mc_put_text(&w, msg->node_name);
    mc_put_uint(&w, ATALAIA_PL_HELLO_PLATFORM);
    mc_put_uint(&w, msg->platform);
    mc_put_uint(&w, ATALAIA_PL_HELLO_FW_VERSION);
    mc_put_text(&w, msg->fw_version);
    mc_put_uint(&w, ATALAIA_PL_HELLO_CORE_VERSION);
    mc_put_text(&w, msg->core_version);
    mc_put_uint(&w, ATALAIA_PL_HELLO_TIER);
    mc_put_uint(&w, msg->tier);
    mc_put_uint(&w, ATALAIA_PL_HELLO_CAPABILITIES);
    mc_put_array(&w, msg->capabilities_count);
    for (uint8_t i = 0; i < msg->capabilities_count; i++) {
        mc_put_uint(&w, msg->capabilities[i]);
    }
    mc_put_uint(&w, ATALAIA_PL_HELLO_TRANSPORTS);
    mc_put_uint(&w, msg->transports);
    if (msg->battery_pct != 0xFF) {
        mc_put_uint(&w, ATALAIA_PL_HELLO_BATTERY_PCT);
        mc_put_uint(&w, msg->battery_pct);
    }
    mc_put_uint(&w, ATALAIA_PL_HELLO_EPOCH);
    mc_put_uint(&w, msg->epoch);
    if (msg->has_device_id) {
        mc_put_uint(&w, ATALAIA_PL_HELLO_DEVICE_ID);
        mc_put_bytes(&w, msg->device_id, sizeof(msg->device_id));
    }

    return w.ok ? w.pos : 0;
}

bool atalaia_hello_decode(const uint8_t *buf, size_t len, atalaia_hello_t *msg)
{
    mc_reader_t r;
    mc_init_reader(&r, buf, len);
    memset(msg, 0, sizeof(*msg));
    msg->battery_pct = 0xFF;
    uint32_t seen = 0;

    uint64_t count;
    if (!mc_read_map(&r, &count)) return false;

    for (uint64_t i = 0; i < count && r.ok; i++) {
        uint64_t key, v;
        if (!mc_read_uint(&r, &key) || !mark(&r, &seen, key)) return false;

        switch (key) {
        case ATALAIA_PL_HELLO_NODE_NAME:
            if (!mc_read_text(&r, msg->node_name, sizeof(msg->node_name), NULL)) return false;
            break;
        case ATALAIA_PL_HELLO_PLATFORM:
            if (!read_uint_max(&r, UINT8_MAX, &v)) return false;
            msg->platform = (uint8_t)v;
            break;
        case ATALAIA_PL_HELLO_FW_VERSION:
            if (!mc_read_text(&r, msg->fw_version, sizeof(msg->fw_version), NULL)) return false;
            break;
        case ATALAIA_PL_HELLO_CORE_VERSION:
            if (!mc_read_text(&r, msg->core_version, sizeof(msg->core_version), NULL)) return false;
            break;
        case ATALAIA_PL_HELLO_TIER:
            if (!read_uint_max(&r, UINT8_MAX, &v)) return false;
            msg->tier = (uint8_t)v;
            break;
        case ATALAIA_PL_HELLO_CAPABILITIES: {
            uint64_t n;
            if (!mc_read_array(&r, &n) || n > sizeof(msg->capabilities)) return false;
            for (uint64_t c = 0; c < n; c++) {
                if (!read_uint_max(&r, UINT8_MAX, &v)) return false;
                msg->capabilities[c] = (uint8_t)v;
            }
            msg->capabilities_count = (uint8_t)n;
            break;
        }
        case ATALAIA_PL_HELLO_TRANSPORTS:
            if (!read_uint_max(&r, UINT8_MAX, &v)) return false;
            msg->transports = (uint8_t)v;
            break;
        case ATALAIA_PL_HELLO_BATTERY_PCT:
            if (!read_uint_max(&r, 100, &v)) return false;
            msg->battery_pct = (uint8_t)v;
            break;
        case ATALAIA_PL_HELLO_EPOCH:
            if (!read_uint_max(&r, UINT16_MAX, &v)) return false;
            msg->epoch = (uint16_t)v;
            break;
        case ATALAIA_PL_HELLO_DEVICE_ID: {
            size_t n = 0;
            if (!mc_read_bytes(&r, msg->device_id, sizeof(msg->device_id), &n) ||
                n != sizeof(msg->device_id)) {
                return false;
            }
            msg->has_device_id = true;
            break;
        }
        default:
            if (!mc_skip_value(&r)) return false;
            break;
        }
    }
    return done(&r, seen, HELLO_REQUIRED);
}

/* ---- ACK ------------------------------------------------------------------ */

#define ACK_REQUIRED (BIT(ATALAIA_PL_ACK_ACK_NODE) | BIT(ATALAIA_PL_ACK_ACK_SEQ))

size_t atalaia_ack_msg_encode(const atalaia_ack_msg_t *msg, uint8_t *buf, size_t cap)
{
    mc_writer_t w;
    mc_init_writer(&w, buf, cap);
    if (msg->ack_bitmap_len > sizeof(msg->ack_bitmap)) {
        return 0;
    }

    mc_put_map(&w, msg->ack_bitmap_len > 0 ? 3 : 2);
    mc_put_uint(&w, ATALAIA_PL_ACK_ACK_NODE);
    mc_put_uint(&w, msg->ack_node);
    mc_put_uint(&w, ATALAIA_PL_ACK_ACK_SEQ);
    mc_put_uint(&w, msg->ack_seq);
    if (msg->ack_bitmap_len > 0) {
        mc_put_uint(&w, ATALAIA_PL_ACK_ACK_BITMAP);
        mc_put_bytes(&w, msg->ack_bitmap, msg->ack_bitmap_len);
    }

    return w.ok ? w.pos : 0;
}

bool atalaia_ack_msg_decode(const uint8_t *buf, size_t len, atalaia_ack_msg_t *msg)
{
    mc_reader_t r;
    mc_init_reader(&r, buf, len);
    memset(msg, 0, sizeof(*msg));
    uint32_t seen = 0;

    uint64_t count;
    if (!mc_read_map(&r, &count)) return false;

    for (uint64_t i = 0; i < count && r.ok; i++) {
        uint64_t key, v;
        if (!mc_read_uint(&r, &key) || !mark(&r, &seen, key)) return false;

        switch (key) {
        case ATALAIA_PL_ACK_ACK_NODE:
            if (!read_uint_max(&r, UINT16_MAX, &v)) return false;
            msg->ack_node = (uint16_t)v;
            break;
        case ATALAIA_PL_ACK_ACK_SEQ:
            if (!read_uint_max(&r, UINT16_MAX, &v)) return false;
            msg->ack_seq = (uint16_t)v;
            break;
        case ATALAIA_PL_ACK_ACK_BITMAP:
            if (!mc_read_bytes(&r, msg->ack_bitmap, sizeof(msg->ack_bitmap), &msg->ack_bitmap_len))
                return false;
            break;
        default:
            if (!mc_skip_value(&r)) return false;
            break;
        }
    }
    return done(&r, seen, ACK_REQUIRED);
}

/* ---- STATE ---------------------------------------------------------------- */

#define STATE_REQUIRED                                                                             \
    (BIT(ATALAIA_PL_STATE_OWNER_TEAM) | BIT(ATALAIA_PL_STATE_PHASE) |                              \
     BIT(ATALAIA_PL_STATE_GAME_TIME_MS) | BIT(ATALAIA_PL_STATE_COUNTERS) |                         \
     BIT(ATALAIA_PL_STATE_EPOCH))

#define STATE_LOST_MAX                                                                             \
    (sizeof(((atalaia_state_msg_t *)0)->lost) / sizeof(((atalaia_state_msg_t *)0)->lost[0]))

#define STATE_COUNTERS_MAX                                                                         \
    (sizeof(((atalaia_state_msg_t *)0)->counters) / sizeof(((atalaia_state_msg_t *)0)->counters[0]))

size_t atalaia_state_encode(const atalaia_state_msg_t *msg, uint8_t *buf, size_t cap)
{
    mc_writer_t w;
    mc_init_writer(&w, buf, cap);
    if (msg->counter_count > STATE_COUNTERS_MAX || msg->lost_count > STATE_LOST_MAX) {
        return 0;
    }

    uint64_t entries = 5; /* owner_team, phase, game_time_ms, counters, epoch */
    if (msg->rssi != INT8_MIN) entries++;
    if (msg->battery_pct != 0xFF) entries++;
    if (msg->flags != 0xFF) entries++;
    if (msg->lost_count > 0) entries++;

    mc_put_map(&w, entries);
    mc_put_uint(&w, ATALAIA_PL_STATE_OWNER_TEAM);
    mc_put_uint(&w, msg->owner_team);
    mc_put_uint(&w, ATALAIA_PL_STATE_PHASE);
    mc_put_uint(&w, msg->phase);
    mc_put_uint(&w, ATALAIA_PL_STATE_GAME_TIME_MS);
    mc_put_uint(&w, msg->game_time_ms);

    /* map_u8_u32: team id -> counter. */
    mc_put_uint(&w, ATALAIA_PL_STATE_COUNTERS);
    mc_put_map(&w, msg->counter_count);
    for (uint8_t c = 0; c < msg->counter_count; c++) {
        mc_put_uint(&w, msg->counters[c].team);
        mc_put_uint(&w, msg->counters[c].score);
    }

    if (msg->rssi != INT8_MIN) {
        mc_put_uint(&w, ATALAIA_PL_STATE_RSSI);
        mc_put_int(&w, msg->rssi);
    }
    if (msg->battery_pct != 0xFF) {
        mc_put_uint(&w, ATALAIA_PL_STATE_BATTERY_PCT);
        mc_put_uint(&w, msg->battery_pct);
    }
    if (msg->flags != 0xFF) {
        mc_put_uint(&w, ATALAIA_PL_STATE_FLAGS);
        mc_put_uint(&w, msg->flags);
    }
    mc_put_uint(&w, ATALAIA_PL_STATE_EPOCH);
    mc_put_uint(&w, msg->epoch);
    if (msg->lost_count > 0) {
        mc_put_uint(&w, ATALAIA_PL_STATE_LOST);
        mc_put_map(&w, msg->lost_count);
        for (uint8_t c = 0; c < msg->lost_count; c++) {
            mc_put_uint(&w, msg->lost[c].team);
            mc_put_uint(&w, msg->lost[c].points);
        }
    }

    return w.ok ? w.pos : 0;
}

bool atalaia_state_decode(const uint8_t *buf, size_t len, atalaia_state_msg_t *msg)
{
    mc_reader_t r;
    mc_init_reader(&r, buf, len);
    memset(msg, 0, sizeof(*msg));
    msg->rssi = INT8_MIN;
    msg->battery_pct = 0xFF;
    msg->flags = 0xFF;
    uint32_t seen = 0;

    uint64_t count;
    if (!mc_read_map(&r, &count)) return false;

    for (uint64_t i = 0; i < count && r.ok; i++) {
        uint64_t key, v;
        if (!mc_read_uint(&r, &key) || !mark(&r, &seen, key)) return false;

        switch (key) {
        case ATALAIA_PL_STATE_OWNER_TEAM:
            if (!read_uint_max(&r, UINT8_MAX, &v)) return false;
            msg->owner_team = (uint8_t)v;
            break;
        case ATALAIA_PL_STATE_PHASE:
            if (!read_uint_max(&r, UINT8_MAX, &v)) return false;
            msg->phase = (uint8_t)v;
            break;
        case ATALAIA_PL_STATE_GAME_TIME_MS:
            if (!read_uint_max(&r, UINT32_MAX, &v)) return false;
            msg->game_time_ms = (uint32_t)v;
            break;
        case ATALAIA_PL_STATE_COUNTERS: {
            uint64_t n;
            if (!mc_read_map(&r, &n) || n > STATE_COUNTERS_MAX) return false;
            for (uint64_t c = 0; c < n; c++) {
                uint64_t team, score;
                if (!read_uint_max(&r, UINT8_MAX, &team) || !read_uint_max(&r, UINT32_MAX, &score))
                    return false;
                for (uint64_t k = 0; k < c; k++) {
                    if (msg->counters[k].team == team) return false; /* duplicate team */
                }
                msg->counters[c].team = (uint8_t)team;
                msg->counters[c].score = (uint32_t)score;
            }
            msg->counter_count = (uint8_t)n;
            break;
        }
        case ATALAIA_PL_STATE_RSSI: {
            int64_t s;
            if (!mc_read_int(&r, &s) || s < INT8_MIN || s > INT8_MAX) return false;
            msg->rssi = (int8_t)s;
            break;
        }
        case ATALAIA_PL_STATE_BATTERY_PCT:
            if (!read_uint_max(&r, 100, &v)) return false;
            msg->battery_pct = (uint8_t)v;
            break;
        case ATALAIA_PL_STATE_FLAGS:
            if (!read_uint_max(&r, UINT8_MAX, &v)) return false;
            msg->flags = (uint8_t)v;
            break;
        case ATALAIA_PL_STATE_EPOCH:
            if (!read_uint_max(&r, UINT16_MAX, &v)) return false;
            msg->epoch = (uint16_t)v;
            break;
        case ATALAIA_PL_STATE_LOST: {
            uint64_t n;
            if (!mc_read_map(&r, &n) || n > STATE_LOST_MAX) return false;
            for (uint64_t c = 0; c < n; c++) {
                uint64_t team, points;
                if (!read_uint_max(&r, UINT8_MAX, &team) || !read_uint_max(&r, UINT32_MAX, &points))
                    return false;
                for (uint64_t k = 0; k < c; k++) {
                    if (msg->lost[k].team == team) return false; /* duplicate team */
                }
                msg->lost[c].team = (uint8_t)team;
                msg->lost[c].points = (uint32_t)points;
            }
            msg->lost_count = (uint8_t)n;
            break;
        }
        default:
            if (!mc_skip_value(&r)) return false;
            break;
        }
    }
    return done(&r, seen, STATE_REQUIRED);
}

/* ---- CMD ------------------------------------------------------------------ */

#define CMD_REQUIRED BIT(ATALAIA_PL_CMD_CMD)

size_t atalaia_cmd_encode(const atalaia_cmd_msg_t *msg, uint8_t *buf, size_t cap)
{
    mc_writer_t w;
    mc_init_writer(&w, buf, cap);

    uint64_t entries = 1; /* cmd */
    if (msg->params_json[0] != '\0') entries++;
    if (msg->dest != 0xFFFF) entries++;

    mc_put_map(&w, entries);
    mc_put_uint(&w, ATALAIA_PL_CMD_CMD);
    mc_put_uint(&w, msg->cmd);

    if (msg->params_json[0] != '\0') {
        /* The params are a CBOR map with text keys; the struct holds them as JSON. */
        mc_put_uint(&w, ATALAIA_PL_CMD_PARAMS);
        if (w.ok) {
            size_t n =
                atalaia_json_map_encode(msg->params_json, w.buf + w.pos, w.cap - w.pos, NULL);
            if (n == 0) {
                w.ok = false;
            } else {
                w.pos += n;
            }
        }
    }

    if (msg->dest != 0xFFFF) {
        mc_put_uint(&w, ATALAIA_PL_CMD_DEST);
        mc_put_uint(&w, msg->dest);
    }

    return w.ok ? w.pos : 0;
}

bool atalaia_cmd_decode(const uint8_t *buf, size_t len, atalaia_cmd_msg_t *msg)
{
    mc_reader_t r;
    mc_init_reader(&r, buf, len);
    memset(msg, 0, sizeof(*msg));
    msg->dest = 0xFFFF;
    uint32_t seen = 0;

    uint64_t count;
    if (!mc_read_map(&r, &count)) return false;

    for (uint64_t i = 0; i < count && r.ok; i++) {
        uint64_t key, v;
        if (!mc_read_uint(&r, &key) || !mark(&r, &seen, key)) return false;

        switch (key) {
        case ATALAIA_PL_CMD_CMD:
            if (!read_uint_max(&r, UINT8_MAX, &v)) return false;
            msg->cmd = (uint8_t)v;
            break;
        case ATALAIA_PL_CMD_PARAMS: {
            size_t used = 0;
            if (!atalaia_json_map_decode(r.p, mc_remaining(&r), &used, msg->params_json,
                                         sizeof(msg->params_json), NULL)) {
                return false;
            }
            r.p += used;
            break;
        }
        case ATALAIA_PL_CMD_DEST:
            if (!read_uint_max(&r, UINT16_MAX, &v)) return false;
            msg->dest = (uint16_t)v;
            break;
        default:
            if (!mc_skip_value(&r)) return false;
            break;
        }
    }
    return done(&r, seen, CMD_REQUIRED);
}

/* ---- TIME ----------------------------------------------------------------- */

#define TIME_REQUIRED                                                                              \
    (BIT(ATALAIA_PL_TIME_GAME_TIME_MS) | BIT(ATALAIA_PL_TIME_GAME_STATE) |                         \
     BIT(ATALAIA_PL_TIME_DURATION_MS) | BIT(ATALAIA_PL_TIME_WALL_S) | BIT(ATALAIA_PL_TIME_TERM))

size_t atalaia_time_encode(const atalaia_time_msg_t *msg, uint8_t *buf, size_t cap)
{
    mc_writer_t w;
    mc_init_writer(&w, buf, cap);

    mc_put_map(&w, msg->tx_time_us != 0xFFFF ? 6 : 5);
    mc_put_uint(&w, ATALAIA_PL_TIME_GAME_TIME_MS);
    mc_put_uint(&w, msg->game_time_ms);
    mc_put_uint(&w, ATALAIA_PL_TIME_GAME_STATE);
    mc_put_uint(&w, msg->game_state);
    mc_put_uint(&w, ATALAIA_PL_TIME_DURATION_MS);
    mc_put_uint(&w, msg->duration_ms);
    mc_put_uint(&w, ATALAIA_PL_TIME_WALL_S);
    mc_put_uint(&w, msg->wall_s);
    mc_put_uint(&w, ATALAIA_PL_TIME_TERM);
    mc_put_uint(&w, msg->term);
    if (msg->tx_time_us != 0xFFFF) {
        mc_put_uint(&w, ATALAIA_PL_TIME_TX_TIME_US);
        mc_put_uint(&w, msg->tx_time_us);
    }

    return w.ok ? w.pos : 0;
}

bool atalaia_time_decode(const uint8_t *buf, size_t len, atalaia_time_msg_t *msg)
{
    mc_reader_t r;
    mc_init_reader(&r, buf, len);
    memset(msg, 0, sizeof(*msg));
    msg->tx_time_us = 0xFFFF;
    uint32_t seen = 0;

    uint64_t count;
    if (!mc_read_map(&r, &count)) return false;

    for (uint64_t i = 0; i < count && r.ok; i++) {
        uint64_t key, v;
        if (!mc_read_uint(&r, &key) || !mark(&r, &seen, key)) return false;

        switch (key) {
        case ATALAIA_PL_TIME_GAME_TIME_MS:
            if (!read_uint_max(&r, UINT32_MAX, &v)) return false;
            msg->game_time_ms = (uint32_t)v;
            break;
        case ATALAIA_PL_TIME_GAME_STATE:
            if (!read_uint_max(&r, UINT8_MAX, &v)) return false;
            msg->game_state = (uint8_t)v;
            break;
        case ATALAIA_PL_TIME_DURATION_MS:
            if (!read_uint_max(&r, UINT32_MAX, &v)) return false;
            msg->duration_ms = (uint32_t)v;
            break;
        case ATALAIA_PL_TIME_WALL_S:
            if (!read_uint_max(&r, UINT32_MAX, &v)) return false;
            msg->wall_s = (uint32_t)v;
            break;
        case ATALAIA_PL_TIME_TERM:
            if (!read_uint_max(&r, UINT32_MAX, &v)) return false;
            msg->term = (uint32_t)v;
            break;
        case ATALAIA_PL_TIME_TX_TIME_US:
            if (!read_uint_max(&r, UINT16_MAX, &v)) return false;
            msg->tx_time_us = (uint16_t)v;
            break;
        default:
            if (!mc_skip_value(&r)) return false;
            break;
        }
    }
    return done(&r, seen, TIME_REQUIRED);
}

/* ---- CONFIG --------------------------------------------------------------- */

#define CONFIG_REQUIRED                                                                            \
    (BIT(ATALAIA_PL_CONFIG_MODE_ID) | BIT(ATALAIA_PL_CONFIG_ROLE) |                                \
     BIT(ATALAIA_PL_CONFIG_PARAMS) | BIT(ATALAIA_PL_CONFIG_TEAMS) |                                \
     BIT(ATALAIA_PL_CONFIG_GAME_SEED))

#define CONFIG_TEAMS_MAX                                                                           \
    (sizeof(((atalaia_config_msg_t *)0)->teams) / sizeof(((atalaia_config_msg_t *)0)->teams[0]))

size_t atalaia_config_encode(const atalaia_config_msg_t *msg, uint8_t *buf, size_t cap)
{
    mc_writer_t w;
    mc_init_writer(&w, buf, cap);
    if (msg->team_count > CONFIG_TEAMS_MAX) {
        return 0;
    }

    mc_put_map(&w, 5);
    mc_put_uint(&w, ATALAIA_PL_CONFIG_MODE_ID);
    mc_put_text(&w, msg->mode_id);
    mc_put_uint(&w, ATALAIA_PL_CONFIG_ROLE);
    mc_put_text(&w, msg->role);
    mc_put_uint(&w, ATALAIA_PL_CONFIG_PARAMS);
    mc_put_text(&w, msg->params_json);
    mc_put_uint(&w, ATALAIA_PL_CONFIG_TEAMS);
    mc_put_array(&w, msg->team_count);
    for (uint8_t t = 0; t < msg->team_count; t++) {
        mc_put_text(&w, msg->teams[t]);
    }
    mc_put_uint(&w, ATALAIA_PL_CONFIG_GAME_SEED);
    mc_put_uint(&w, msg->game_seed);

    return w.ok ? w.pos : 0;
}

bool atalaia_config_decode(const uint8_t *buf, size_t len, atalaia_config_msg_t *msg)
{
    mc_reader_t r;
    mc_init_reader(&r, buf, len);
    memset(msg, 0, sizeof(*msg));
    uint32_t seen = 0;

    uint64_t count;
    if (!mc_read_map(&r, &count)) return false;

    for (uint64_t i = 0; i < count && r.ok; i++) {
        uint64_t key, v;
        if (!mc_read_uint(&r, &key) || !mark(&r, &seen, key)) return false;

        switch (key) {
        case ATALAIA_PL_CONFIG_MODE_ID:
            if (!mc_read_text(&r, msg->mode_id, sizeof(msg->mode_id), NULL)) return false;
            break;
        case ATALAIA_PL_CONFIG_ROLE:
            if (!mc_read_text(&r, msg->role, sizeof(msg->role), NULL)) return false;
            break;
        case ATALAIA_PL_CONFIG_PARAMS:
            if (!mc_read_text(&r, msg->params_json, sizeof(msg->params_json), NULL)) return false;
            break;
        case ATALAIA_PL_CONFIG_TEAMS: {
            uint64_t n;
            if (!mc_read_array(&r, &n) || n > CONFIG_TEAMS_MAX) return false;
            for (uint64_t t = 0; t < n; t++) {
                if (!mc_read_text(&r, msg->teams[t], sizeof(msg->teams[t]), NULL)) return false;
            }
            msg->team_count = (uint8_t)n;
            break;
        }
        case ATALAIA_PL_CONFIG_GAME_SEED:
            if (!read_uint_max(&r, UINT32_MAX, &v)) return false;
            msg->game_seed = (uint32_t)v;
            break;
        default:
            if (!mc_skip_value(&r)) return false;
            break;
        }
    }
    return done(&r, seen, CONFIG_REQUIRED);
}

/* ---- CLAIM ---------------------------------------------------------------- */

#define CLAIM_REQUIRED                                                                             \
    (BIT(ATALAIA_PL_CLAIM_TERM) | BIT(ATALAIA_PL_CLAIM_PRIORITY) | BIT(ATALAIA_PL_CLAIM_NODE_ID))

#define CLAIM_ACKS_MAX                                                                             \
    (sizeof(((atalaia_claim_msg_t *)0)->last_ack) / sizeof(((atalaia_claim_msg_t *)0)->last_ack[0]))

size_t atalaia_claim_encode(const atalaia_claim_msg_t *msg, uint8_t *buf, size_t cap)
{
    mc_writer_t w;
    mc_init_writer(&w, buf, cap);
    if (msg->last_ack_count > CLAIM_ACKS_MAX) {
        return 0;
    }

    mc_put_map(&w, msg->last_ack_count > 0 ? 4 : 3);
    mc_put_uint(&w, ATALAIA_PL_CLAIM_TERM);
    mc_put_uint(&w, msg->term);
    mc_put_uint(&w, ATALAIA_PL_CLAIM_PRIORITY);
    mc_put_uint(&w, msg->priority);
    mc_put_uint(&w, ATALAIA_PL_CLAIM_NODE_ID);
    mc_put_uint(&w, msg->node_id);

    /* map_u16_u16: node -> last ACK'd seq. */
    if (msg->last_ack_count > 0) {
        mc_put_uint(&w, ATALAIA_PL_CLAIM_LAST_ACK_SEQ);
        mc_put_map(&w, msg->last_ack_count);
        for (uint8_t a = 0; a < msg->last_ack_count; a++) {
            mc_put_uint(&w, msg->last_ack[a].node);
            mc_put_uint(&w, msg->last_ack[a].seq);
        }
    }

    return w.ok ? w.pos : 0;
}

bool atalaia_claim_decode(const uint8_t *buf, size_t len, atalaia_claim_msg_t *msg)
{
    mc_reader_t r;
    mc_init_reader(&r, buf, len);
    memset(msg, 0, sizeof(*msg));
    uint32_t seen = 0;

    uint64_t count;
    if (!mc_read_map(&r, &count)) return false;

    for (uint64_t i = 0; i < count && r.ok; i++) {
        uint64_t key, v;
        if (!mc_read_uint(&r, &key) || !mark(&r, &seen, key)) return false;

        switch (key) {
        case ATALAIA_PL_CLAIM_TERM:
            if (!read_uint_max(&r, UINT32_MAX, &v)) return false;
            msg->term = (uint32_t)v;
            break;
        case ATALAIA_PL_CLAIM_PRIORITY:
            if (!read_uint_max(&r, UINT16_MAX, &v)) return false;
            msg->priority = (uint16_t)v;
            break;
        case ATALAIA_PL_CLAIM_NODE_ID:
            if (!read_uint_max(&r, UINT16_MAX, &v)) return false;
            msg->node_id = (uint16_t)v;
            break;
        case ATALAIA_PL_CLAIM_LAST_ACK_SEQ: {
            uint64_t n;
            if (!mc_read_map(&r, &n) || n > CLAIM_ACKS_MAX) return false;
            for (uint64_t a = 0; a < n; a++) {
                uint64_t node, seq;
                if (!read_uint_max(&r, UINT16_MAX, &node) || !read_uint_max(&r, UINT16_MAX, &seq))
                    return false;
                for (uint64_t k = 0; k < a; k++) {
                    if (msg->last_ack[k].node == node) return false; /* duplicate node */
                }
                msg->last_ack[a].node = (uint16_t)node;
                msg->last_ack[a].seq = (uint16_t)seq;
            }
            msg->last_ack_count = (uint8_t)n;
            break;
        }
        default:
            if (!mc_skip_value(&r)) return false;
            break;
        }
    }
    return done(&r, seen, CLAIM_REQUIRED);
}
