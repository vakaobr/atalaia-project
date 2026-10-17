/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * CBOR encode/decode for all Skirmesh-RF message payloads except EVENT.
 */
#include <limits.h>
#include <string.h>

#include "atalaia/msg_codec.h"

#include "cbor_int.h"

/* ---- HELLO ---------------------------------------------------------------- */

size_t atalaia_hello_encode(const atalaia_hello_t *msg, uint8_t *buf, size_t cap)
{
    mc_writer_t w;
    mc_init_writer(&w, buf, cap);

    uint64_t entries = 5; /* node_name, platform, fw_version, core_version, tier */
    if (msg->capabilities_count > 0) entries++;
    if (msg->transports != 0) entries++;
    if (msg->battery_pct != 0xFF) entries++;
    if (msg->epoch != 0) entries++;

    mc_put_map(&w, entries);

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

    if (msg->capabilities_count > 0) {
        mc_put_uint(&w, ATALAIA_PL_HELLO_CAPABILITIES);
        mc_put_bytes(&w, msg->capabilities, msg->capabilities_count);
    }

    if (msg->transports != 0) {
        mc_put_uint(&w, ATALAIA_PL_HELLO_TRANSPORTS);
        mc_put_uint(&w, msg->transports);
    }

    if (msg->battery_pct != 0xFF) {
        mc_put_uint(&w, ATALAIA_PL_HELLO_BATTERY_PCT);
        mc_put_uint(&w, msg->battery_pct);
    }

    if (msg->epoch != 0) {
        mc_put_uint(&w, ATALAIA_PL_HELLO_EPOCH);
        mc_put_uint(&w, msg->epoch);
    }

    return w.ok ? w.pos : 0;
}

bool atalaia_hello_decode(const uint8_t *buf, size_t len, atalaia_hello_t *msg)
{
    mc_reader_t r;
    mc_init_reader(&r, buf, len);
    memset(msg, 0, sizeof(*msg));
    msg->battery_pct = 0xFF;

    uint64_t count;
    if (!mc_read_map(&r, &count)) return false;

    for (uint64_t i = 0; i < count && r.ok; i++) {
        uint64_t key;
        if (!mc_read_uint(&r, &key)) return false;

        switch (key) {
        case ATALAIA_PL_HELLO_NODE_NAME:
            if (!mc_read_text(&r, msg->node_name, sizeof(msg->node_name), NULL)) return false;
            break;
        case ATALAIA_PL_HELLO_PLATFORM: {
            uint64_t v;
            if (!mc_read_uint(&r, &v)) return false;
            msg->platform = (uint8_t)v;
            break;
        }
        case ATALAIA_PL_HELLO_FW_VERSION:
            if (!mc_read_text(&r, msg->fw_version, sizeof(msg->fw_version), NULL)) return false;
            break;
        case ATALAIA_PL_HELLO_CORE_VERSION:
            if (!mc_read_text(&r, msg->core_version, sizeof(msg->core_version), NULL)) return false;
            break;
        case ATALAIA_PL_HELLO_TIER: {
            uint64_t v;
            if (!mc_read_uint(&r, &v)) return false;
            msg->tier = (uint8_t)v;
            break;
        }
        case ATALAIA_PL_HELLO_CAPABILITIES: {
            size_t blen = 0;
            if (!mc_read_bytes(&r, msg->capabilities, sizeof(msg->capabilities), &blen)) {
                return false;
            }
            msg->capabilities_count = (uint8_t)blen;
            break;
        }
        case ATALAIA_PL_HELLO_TRANSPORTS: {
            uint64_t v;
            if (!mc_read_uint(&r, &v)) return false;
            msg->transports = (uint8_t)v;
            break;
        }
        case ATALAIA_PL_HELLO_BATTERY_PCT: {
            uint64_t v;
            if (!mc_read_uint(&r, &v)) return false;
            msg->battery_pct = (uint8_t)v;
            break;
        }
        case ATALAIA_PL_HELLO_EPOCH: {
            uint64_t v;
            if (!mc_read_uint(&r, &v)) return false;
            msg->epoch = (uint16_t)v;
            break;
        }
        default:
            if (!mc_skip_value(&r)) return false;
            break;
        }
    }
    return r.ok;
}

/* ---- ACK ------------------------------------------------------------------ */

size_t atalaia_ack_msg_encode(const atalaia_ack_msg_t *msg, uint8_t *buf, size_t cap)
{
    mc_writer_t w;
    mc_init_writer(&w, buf, cap);

    uint64_t entries = 2;
    if (msg->ack_bitmap_len > 0) entries++;

    mc_put_map(&w, entries);

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

    uint64_t count;
    if (!mc_read_map(&r, &count)) return false;

    for (uint64_t i = 0; i < count && r.ok; i++) {
        uint64_t key;
        if (!mc_read_uint(&r, &key)) return false;

        switch (key) {
        case ATALAIA_PL_ACK_ACK_NODE: {
            uint64_t v;
            if (!mc_read_uint(&r, &v)) return false;
            msg->ack_node = (uint16_t)v;
            break;
        }
        case ATALAIA_PL_ACK_ACK_SEQ: {
            uint64_t v;
            if (!mc_read_uint(&r, &v)) return false;
            msg->ack_seq = (uint16_t)v;
            break;
        }
        case ATALAIA_PL_ACK_ACK_BITMAP:
            if (!mc_read_bytes(&r, msg->ack_bitmap, sizeof(msg->ack_bitmap), &msg->ack_bitmap_len))
                return false;
            break;
        default:
            if (!mc_skip_value(&r)) return false;
            break;
        }
    }
    return r.ok;
}

/* ---- STATE ---------------------------------------------------------------- */

size_t atalaia_state_encode(const atalaia_state_msg_t *msg, uint8_t *buf, size_t cap)
{
    mc_writer_t w;
    mc_init_writer(&w, buf, cap);

    uint64_t entries = 3; /* owner_team, phase, game_time */
    if (msg->counter_count > 0) entries++;
    if (msg->rssi != INT8_MIN) entries++;
    if (msg->battery_pct != 0xFF) entries++;
    if (msg->flags != 0xFF) entries++;
    if (msg->epoch != 0) entries++;

    mc_put_map(&w, entries);

    mc_put_uint(&w, ATALAIA_PL_STATE_OWNER_TEAM);
    mc_put_uint(&w, msg->owner_team);

    mc_put_uint(&w, ATALAIA_PL_STATE_PHASE);
    mc_put_uint(&w, msg->phase);

    mc_put_uint(&w, ATALAIA_PL_STATE_GAME_TIME_MS);
    mc_put_uint(&w, msg->game_time_ms);

    if (msg->counter_count > 0) {
        mc_put_uint(&w, ATALAIA_PL_STATE_COUNTERS);
        mc_put_array(&w, msg->counter_count);
        for (uint8_t c = 0; c < msg->counter_count; c++) {
            mc_put_map(&w, 2);
            mc_put_uint(&w, 1); /* team key */
            mc_put_uint(&w, msg->counters[c].team);
            mc_put_uint(&w, 2); /* score key */
            mc_put_uint(&w, msg->counters[c].score);
        }
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

    if (msg->epoch != 0) {
        mc_put_uint(&w, ATALAIA_PL_STATE_EPOCH);
        mc_put_uint(&w, msg->epoch);
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

    uint64_t count;
    if (!mc_read_map(&r, &count)) return false;

    for (uint64_t i = 0; i < count && r.ok; i++) {
        uint64_t key;
        if (!mc_read_uint(&r, &key)) return false;

        switch (key) {
        case ATALAIA_PL_STATE_OWNER_TEAM: {
            uint64_t v;
            if (!mc_read_uint(&r, &v)) return false;
            msg->owner_team = (uint8_t)v;
            break;
        }
        case ATALAIA_PL_STATE_PHASE: {
            uint64_t v;
            if (!mc_read_uint(&r, &v)) return false;
            msg->phase = (uint8_t)v;
            break;
        }
        case ATALAIA_PL_STATE_GAME_TIME_MS: {
            uint64_t v;
            if (!mc_read_uint(&r, &v)) return false;
            msg->game_time_ms = (uint32_t)v;
            break;
        }
        case ATALAIA_PL_STATE_COUNTERS: {
            uint64_t arr_count;
            if (!mc_read_array(&r, &arr_count)) return false;
            if (arr_count > 16) {
                r.ok = false;
                return false;
            }
            msg->counter_count = (uint8_t)arr_count;
            for (uint64_t c = 0; c < arr_count; c++) {
                uint64_t mc2;
                if (!mc_read_map(&r, &mc2)) return false;
                for (uint64_t j = 0; j < mc2; j++) {
                    uint64_t ck;
                    if (!mc_read_uint(&r, &ck)) return false;
                    uint64_t cv;
                    if (!mc_read_uint(&r, &cv)) return false;
                    if (ck == 1)
                        msg->counters[c].team = (uint8_t)cv;
                    else if (ck == 2)
                        msg->counters[c].score = (uint32_t)cv;
                }
            }
            break;
        }
        case ATALAIA_PL_STATE_RSSI: {
            int64_t v;
            if (!mc_read_int(&r, &v)) return false;
            msg->rssi = (int8_t)v;
            break;
        }
        case ATALAIA_PL_STATE_BATTERY_PCT: {
            uint64_t v;
            if (!mc_read_uint(&r, &v)) return false;
            msg->battery_pct = (uint8_t)v;
            break;
        }
        case ATALAIA_PL_STATE_FLAGS: {
            uint64_t v;
            if (!mc_read_uint(&r, &v)) return false;
            msg->flags = (uint8_t)v;
            break;
        }
        case ATALAIA_PL_STATE_EPOCH: {
            uint64_t v;
            if (!mc_read_uint(&r, &v)) return false;
            msg->epoch = (uint16_t)v;
            break;
        }
        default:
            if (!mc_skip_value(&r)) return false;
            break;
        }
    }
    return r.ok;
}

/* ---- CMD ------------------------------------------------------------------ */

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
        mc_put_uint(&w, ATALAIA_PL_CMD_PARAMS);
        mc_put_text(&w, msg->params_json);
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

    uint64_t count;
    if (!mc_read_map(&r, &count)) return false;

    for (uint64_t i = 0; i < count && r.ok; i++) {
        uint64_t key;
        if (!mc_read_uint(&r, &key)) return false;

        switch (key) {
        case ATALAIA_PL_CMD_CMD: {
            uint64_t v;
            if (!mc_read_uint(&r, &v)) return false;
            msg->cmd = (uint8_t)v;
            break;
        }
        case ATALAIA_PL_CMD_PARAMS:
            if (!mc_read_text(&r, msg->params_json, sizeof(msg->params_json), NULL)) return false;
            break;
        case ATALAIA_PL_CMD_DEST: {
            uint64_t v;
            if (!mc_read_uint(&r, &v)) return false;
            msg->dest = (uint16_t)v;
            break;
        }
        default:
            if (!mc_skip_value(&r)) return false;
            break;
        }
    }
    return r.ok;
}

/* ---- TIME ----------------------------------------------------------------- */

size_t atalaia_time_encode(const atalaia_time_msg_t *msg, uint8_t *buf, size_t cap)
{
    mc_writer_t w;
    mc_init_writer(&w, buf, cap);

    uint64_t entries = 3; /* game_time, game_state, duration */
    if (msg->wall_s != 0) entries++;
    if (msg->term != 0) entries++;
    if (msg->tx_time_us != 0xFFFF) entries++;

    mc_put_map(&w, entries);

    mc_put_uint(&w, ATALAIA_PL_TIME_GAME_TIME_MS);
    mc_put_uint(&w, msg->game_time_ms);

    mc_put_uint(&w, ATALAIA_PL_TIME_GAME_STATE);
    mc_put_uint(&w, msg->game_state);

    mc_put_uint(&w, ATALAIA_PL_TIME_DURATION_MS);
    mc_put_uint(&w, msg->duration_ms);

    if (msg->wall_s != 0) {
        mc_put_uint(&w, ATALAIA_PL_TIME_WALL_S);
        mc_put_uint(&w, msg->wall_s);
    }

    if (msg->term != 0) {
        mc_put_uint(&w, ATALAIA_PL_TIME_TERM);
        mc_put_uint(&w, msg->term);
    }

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

    uint64_t count;
    if (!mc_read_map(&r, &count)) return false;

    for (uint64_t i = 0; i < count && r.ok; i++) {
        uint64_t key;
        if (!mc_read_uint(&r, &key)) return false;

        switch (key) {
        case ATALAIA_PL_TIME_GAME_TIME_MS: {
            uint64_t v;
            if (!mc_read_uint(&r, &v)) return false;
            msg->game_time_ms = (uint32_t)v;
            break;
        }
        case ATALAIA_PL_TIME_GAME_STATE: {
            uint64_t v;
            if (!mc_read_uint(&r, &v)) return false;
            msg->game_state = (uint8_t)v;
            break;
        }
        case ATALAIA_PL_TIME_DURATION_MS: {
            uint64_t v;
            if (!mc_read_uint(&r, &v)) return false;
            msg->duration_ms = (uint32_t)v;
            break;
        }
        case ATALAIA_PL_TIME_WALL_S: {
            uint64_t v;
            if (!mc_read_uint(&r, &v)) return false;
            msg->wall_s = (uint32_t)v;
            break;
        }
        case ATALAIA_PL_TIME_TERM: {
            uint64_t v;
            if (!mc_read_uint(&r, &v)) return false;
            msg->term = (uint32_t)v;
            break;
        }
        case ATALAIA_PL_TIME_TX_TIME_US: {
            uint64_t v;
            if (!mc_read_uint(&r, &v)) return false;
            msg->tx_time_us = (uint16_t)v;
            break;
        }
        default:
            if (!mc_skip_value(&r)) return false;
            break;
        }
    }
    return r.ok;
}

/* ---- CONFIG --------------------------------------------------------------- */

size_t atalaia_config_encode(const atalaia_config_msg_t *msg, uint8_t *buf, size_t cap)
{
    mc_writer_t w;
    mc_init_writer(&w, buf, cap);

    uint64_t entries = 1; /* mode_id */
    if (msg->role[0] != '\0') entries++;
    if (msg->params_json[0] != '\0') entries++;
    if (msg->team_count > 0) entries++;
    if (msg->game_seed != 0) entries++;

    mc_put_map(&w, entries);

    mc_put_uint(&w, ATALAIA_PL_CONFIG_MODE_ID);
    mc_put_text(&w, msg->mode_id);

    if (msg->role[0] != '\0') {
        mc_put_uint(&w, ATALAIA_PL_CONFIG_ROLE);
        mc_put_text(&w, msg->role);
    }

    if (msg->params_json[0] != '\0') {
        mc_put_uint(&w, ATALAIA_PL_CONFIG_PARAMS);
        mc_put_text(&w, msg->params_json);
    }

    if (msg->team_count > 0) {
        mc_put_uint(&w, ATALAIA_PL_CONFIG_TEAMS);
        mc_put_array(&w, msg->team_count);
        for (uint8_t t = 0; t < msg->team_count; t++) {
            mc_put_text(&w, msg->teams[t]);
        }
    }

    if (msg->game_seed != 0) {
        mc_put_uint(&w, ATALAIA_PL_CONFIG_GAME_SEED);
        mc_put_uint(&w, msg->game_seed);
    }

    return w.ok ? w.pos : 0;
}

bool atalaia_config_decode(const uint8_t *buf, size_t len, atalaia_config_msg_t *msg)
{
    mc_reader_t r;
    mc_init_reader(&r, buf, len);
    memset(msg, 0, sizeof(*msg));

    uint64_t count;
    if (!mc_read_map(&r, &count)) return false;

    for (uint64_t i = 0; i < count && r.ok; i++) {
        uint64_t key;
        if (!mc_read_uint(&r, &key)) return false;

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
            uint64_t arr_count;
            if (!mc_read_array(&r, &arr_count)) return false;
            if (arr_count > 8) {
                r.ok = false;
                return false;
            }
            msg->team_count = (uint8_t)arr_count;
            for (uint64_t t = 0; t < arr_count; t++) {
                if (!mc_read_text(&r, msg->teams[t], sizeof(msg->teams[t]), NULL)) return false;
            }
            break;
        }
        case ATALAIA_PL_CONFIG_GAME_SEED: {
            uint64_t v;
            if (!mc_read_uint(&r, &v)) return false;
            msg->game_seed = (uint32_t)v;
            break;
        }
        default:
            if (!mc_skip_value(&r)) return false;
            break;
        }
    }
    return r.ok;
}

/* ---- CLAIM ---------------------------------------------------------------- */

size_t atalaia_claim_encode(const atalaia_claim_msg_t *msg, uint8_t *buf, size_t cap)
{
    mc_writer_t w;
    mc_init_writer(&w, buf, cap);

    uint64_t entries = 3; /* term, priority, node_id */
    if (msg->last_ack_count > 0) entries++;

    mc_put_map(&w, entries);

    mc_put_uint(&w, ATALAIA_PL_CLAIM_TERM);
    mc_put_uint(&w, msg->term);

    mc_put_uint(&w, ATALAIA_PL_CLAIM_PRIORITY);
    mc_put_uint(&w, msg->priority);

    mc_put_uint(&w, ATALAIA_PL_CLAIM_NODE_ID);
    mc_put_uint(&w, msg->node_id);

    if (msg->last_ack_count > 0) {
        mc_put_uint(&w, ATALAIA_PL_CLAIM_LAST_ACK_SEQ);
        mc_put_array(&w, msg->last_ack_count);
        for (uint8_t a = 0; a < msg->last_ack_count; a++) {
            mc_put_map(&w, 2);
            mc_put_uint(&w, 1); /* node key */
            mc_put_uint(&w, msg->last_ack[a].node);
            mc_put_uint(&w, 2); /* seq key */
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

    uint64_t count;
    if (!mc_read_map(&r, &count)) return false;

    for (uint64_t i = 0; i < count && r.ok; i++) {
        uint64_t key;
        if (!mc_read_uint(&r, &key)) return false;

        switch (key) {
        case ATALAIA_PL_CLAIM_TERM: {
            uint64_t v;
            if (!mc_read_uint(&r, &v)) return false;
            msg->term = (uint32_t)v;
            break;
        }
        case ATALAIA_PL_CLAIM_PRIORITY: {
            uint64_t v;
            if (!mc_read_uint(&r, &v)) return false;
            msg->priority = (uint16_t)v;
            break;
        }
        case ATALAIA_PL_CLAIM_NODE_ID: {
            uint64_t v;
            if (!mc_read_uint(&r, &v)) return false;
            msg->node_id = (uint16_t)v;
            break;
        }
        case ATALAIA_PL_CLAIM_LAST_ACK_SEQ: {
            uint64_t arr_count;
            if (!mc_read_array(&r, &arr_count)) return false;
            if (arr_count > 32) {
                r.ok = false;
                return false;
            }
            msg->last_ack_count = (uint8_t)arr_count;
            for (uint64_t a = 0; a < arr_count; a++) {
                uint64_t mc2;
                if (!mc_read_map(&r, &mc2)) return false;
                for (uint64_t j = 0; j < mc2; j++) {
                    uint64_t ck;
                    if (!mc_read_uint(&r, &ck)) return false;
                    uint64_t cv;
                    if (!mc_read_uint(&r, &cv)) return false;
                    if (ck == 1)
                        msg->last_ack[a].node = (uint16_t)cv;
                    else if (ck == 2)
                        msg->last_ack[a].seq = (uint16_t)cv;
                }
            }
            break;
        }
        default:
            if (!mc_skip_value(&r)) return false;
            break;
        }
    }
    return r.ok;
}
