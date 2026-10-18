/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The node runtime: one sandboxed Lua state running a mode's node script.
 *
 * The host (ESP32 shell, Linux daemon, Android app or the simulator) owns
 * the clock and the hardware. It feeds the node input events and game time,
 * and receives emitted events, hardware commands and log lines through
 * callbacks. Nothing here blocks, sleeps or reads a real clock, so a game
 * can be replayed exactly from its inputs. See "Game runtime and scripting"
 * in the design specification.
 *
 * Typical use:
 *
 *   node = atalaia_node_create(&cfg);
 *   atalaia_node_set_teams(node, names, 2);
 *   atalaia_node_set_params(node, "{\"fuse_s\":300}");
 *   atalaia_node_load(node, source, len, "bomb/node.lua");
 *   atalaia_node_input(node, "game.start", NULL);
 *   ... atalaia_node_input() for each hardware event,
 *       atalaia_node_advance() as game time passes ...
 *   atalaia_node_destroy(node);
 *
 * Callbacks run synchronously and must not call back into the same node.
 */
#ifndef ATALAIA_NODE_H
#define ATALAIA_NODE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "atalaia/event.h"
#include "atalaia/field_ops.h"
#include "atalaia/score.h"

/* Defaults for the Full device tier (section 6 of the design spec). */
#define ATALAIA_NODE_DEFAULT_MEM_LIMIT   (256u * 1024u)
#define ATALAIA_NODE_DEFAULT_INSTR_LIMIT 1000000u

#define ATALAIA_NODE_MAX_TIMERS      32
#define ATALAIA_NODE_MIN_INTERVAL_MS 10u
#define ATALAIA_TEAM_NAME_MAX        24 /* includes the terminating NUL */

typedef struct atalaia_node atalaia_node_t;

typedef enum {
    ATALAIA_NODE_EMPTY = 0, /* created; no script loaded yet */
    ATALAIA_NODE_RUNNING,   /* script loaded; reacts to inputs and timers */
    ATALAIA_NODE_ENDED,     /* game.end seen: scores and displays frozen */
    ATALAIA_NODE_HALTED     /* stopped by the sandbox; shows a paused screen */
} atalaia_node_status_t;

typedef struct {
    /* An event emitted by the script or the runtime, with its data as a JSON
     * object. Hardware events from the host are not echoed back. */
    void (*event)(void *user, const atalaia_event_t *ev, const char *data_json);
    /* A hardware command, e.g. target "ring", method "fill", args ["red"].
     * Targets are capability ids, or "ui" and "audio". */
    void (*command)(void *user, const char *target, const char *method, const char *args_json);
    /* A line from the script's log() or print(). */
    void (*log)(void *user, const char *message);
    /* Field state changed on a controller node (key/value_json). */
    void (*field_state)(void *user, const char *key, const char *value_json);
    void *user;
} atalaia_node_callbacks_t;

/* Same contract as lua_Alloc: free when new_size is 0, otherwise resize. */
typedef void *(*atalaia_alloc_fn)(void *ud, void *ptr, size_t old_size, size_t new_size);

typedef struct {
    uint16_t node_id;     /* short id within the game */
    uint32_t game_seed;   /* seeds rand(); the same seed replays the same game */
    size_t mem_limit;     /* script memory cap in bytes; 0 for the default */
    uint32_t instr_limit; /* instructions per callback; 0 for the default */
    atalaia_node_callbacks_t callbacks;
    atalaia_alloc_fn alloc; /* NULL for realloc/free */
    void *alloc_ud;
    const atalaia_field_ops_t *field_ops; /* NULL for regular nodes */
} atalaia_node_config_t;

/* Returns NULL if memory runs out. */
atalaia_node_t *atalaia_node_create(const atalaia_node_config_t *cfg);
void atalaia_node_destroy(atalaia_node_t *node);

/*
 * Before loading: the game's teams (ids 1..count in this order) and the
 * preset's parameters as a JSON object, exposed to the script as `params`.
 */
bool atalaia_node_set_teams(atalaia_node_t *node, const char *const *names, size_t count);
bool atalaia_node_set_params(atalaia_node_t *node, const char *params_json);

/*
 * Compiles and runs a node script (source text only, never bytecode).
 * Returns false if it fails to compile or its top level fails; the node is
 * then halted and atalaia_node_last_error() says why.
 */
bool atalaia_node_load(atalaia_node_t *node, const char *source, size_t len,
                       const char *chunk_name);

/*
 * Dispatches an event to the script's handlers at the current game time:
 * hardware and semantic events (team_input.hold) or game events from the
 * field (game.start, game.pause, game.end). data_json may be NULL.
 * Returns false if the node is not running, the game is paused and the
 * event is not a game.* event, or data_json is not a JSON object.
 */
bool atalaia_node_input(atalaia_node_t *node, const char *type, const char *data_json);

/*
 * Moves game time forward to now_ms, firing due timers in order. Game time
 * stops while the game is paused, so hosts should not advance then.
 */
void atalaia_node_advance(atalaia_node_t *node, uint32_t now_ms);

atalaia_node_status_t atalaia_node_status(const atalaia_node_t *node);
const char *atalaia_node_status_name(atalaia_node_status_t status);
bool atalaia_node_paused(const atalaia_node_t *node);
uint32_t atalaia_node_time(const atalaia_node_t *node);
const char *atalaia_node_last_error(const atalaia_node_t *node);
size_t atalaia_node_mem_used(const atalaia_node_t *node);
const atalaia_score_t *atalaia_node_score(const atalaia_node_t *node);

/* Team id for a name, or ATALAIA_TEAM_NONE if unknown; and the reverse. */
uint8_t atalaia_node_team_id(const atalaia_node_t *node, const char *name);
const char *atalaia_node_team_name(const atalaia_node_t *node, uint8_t team);

#endif /* ATALAIA_NODE_H */
