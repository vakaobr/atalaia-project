/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The box's output layer (draft RFC "The expansion port", increment 2; decisions EXP-27 to
 * EXP-30, EXP-36; protocol/expansion-port.md, sections 6-9): the `output` capability, whatever
 * path its channels take. Today every channel is a simple output (one GPIO sending an RC-servo
 * signal to an RC relay switch: simple_out.h), or an output channel of a module on the expansion
 * port (expansion.h; draft RFC "The expansion port", increment 8): a module's channels join when
 * the module is found and leave when it is lost, after the simple outputs, and take the desired
 * state whole (on until a time, a pattern) through their back-end's `set`, so the module runs its
 * own timers and patterns.
 *
 * What it holds, per channel:
 *   - the field admin's settings, kept on the box (EXP-28): enabled or not (off until the admin
 *     enables it at the box with the admin PIN), its function (the capability id scripts call:
 *     siren, strobe, smoke, light, horn, else out.<n>; a second channel with the same function
 *     is siren.2) and its max on;
 *   - the desired state: off, on until a time, or a pattern until a time, and who asked;
 *   - the rules: a call never runs longer than the max on; a simple output changes state at most
 *     every OUT_SIMPLE_MIN_MS, so a shorter pulse runs for that long, a pattern faster than it is
 *     refused, and an on within it of the last change is refused (off never is); a module's
 *     channel takes patterns down to its own floor (100 ms on a relay, 10 ms otherwise) and its
 *     max on is never above the module's; a script starts a channel at most OUT_SCRIPT_STARTS
 *     times a second (more are dropped, one script.error);
 *   - the game-state rules (EXP-29): outputs switch on only while a game runs; every output goes
 *     off at boot, pause, script halt and game end, and a resumed game does not turn them back on;
 *     for OUT_GRACE_MS after the end the mode's game.end handler and the field may pulse an output
 *     (an end-of-game horn), never past that grace; the admin's 1 s test only while no game runs.
 *
 * What it tells: output.switched (each start, and an off before its time, with its source) and a
 * box's node.modules text (its simple outputs: "g46:servo:siren"); outputs that the game state
 * turns off send nothing (the game's own state says why).
 *
 * Platform-free: the shell gives the clock (outputs_tick every game-task turn), the events (the
 * field link, or the log in a stand-alone game), the settings store and each channel's back-end.
 * The host tests and the host box (test/box_host) run it as the box does.
 */
#ifndef ATALAIA_OUTPUTS_H
#define ATALAIA_OUTPUTS_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define OUTPUTS_MAX              2 /* simple outputs a box drives (EXP-34) */
#define OUT_MODULE_CHANNELS      8 /* module output channels a box takes (EXPI8-6) */
#define OUT_CHANNELS_MAX         (OUTPUTS_MAX + OUT_MODULE_CHANNELS)
#define OUT_ID_MAX               23     /* a capability id: 1-23 bytes of a-z 0-9 . _ - */
#define OUT_GRACE_MS             10000  /* after a game's end: an end-of-game horn (EXP-29) */
#define OUT_SIMPLE_MIN_MS        500    /* a simple output changes state at most this often */
#define OUT_SCRIPT_STARTS        2      /* starts a second per channel from a script (EXP-30) */
#define OUT_MS_MAX               600000 /* the longest call: 10 minutes (CMD 12) */
#define OUT_PATTERN_MIN_MS       10     /* a pattern's on and off times in CMD 12 ... */
#define OUT_PATTERN_MAX_MS       10000  /* ... (a channel raises the floor: OUT_SIMPLE_MIN_MS) */
#define OUT_RELAY_PATTERN_MIN_MS 100    /* a module's relay channel: its pattern floor */
#define OUT_MODULE_LEAST_MS      100    /* a module's shortest on: its durations are in 100 ms */
#define OUT_MAX_ON_DEFAULT_S     30     /* a channel's max on until its admin sets another */
#define OUT_MAX_ON_MAX_S         600
#define OUT_TEST_MS              1000 /* the admin's test at the box (EXP-27) */
#define OUT_MODULES_MAX          100 /* node.modules' text (protocol/expansion-port.md, section 7) */

typedef enum {
    OUT_SRC_SCRIPT = 0, /* the box's own mode script: cap(fn):pulse(ms) */
    OUT_SRC_FIELD,      /* a field script or a scenario trigger: CMD 12 with src field */
    OUT_SRC_GM,         /* the GM in the console: CMD 12 with src gm */
    OUT_SRC_BOX_ADMIN,  /* the field's admin at the box: the 1 s test */
} out_source_t;

typedef enum { OUT_ACT_ON = 0, OUT_ACT_OFF, OUT_ACT_PULSE, OUT_ACT_PATTERN } out_act_t;

/* The box's game as the output layer sees it (box_game_output_state). */
typedef enum {
    OUT_GAME_NONE = 0, /* no game running: between games, the picker, joined but not started */
    OUT_GAME_RUNNING,
    OUT_GAME_PAUSED,
    OUT_GAME_ENDED,  /* the end's grace, then nothing */
    OUT_GAME_HALTED, /* the sandbox stopped the mode's script */
} out_game_t;

typedef enum {
    OUT_OK = 0,
    OUT_NO_SUCH,  /* no output with that capability id: the call does nothing (EXP-19) */
    OUT_DISABLED, /* its admin has not enabled it (EXP-28) */
    OUT_NOT_NOW,  /* no game running (or the end's grace is over, or the test during a game) */
    OUT_BAD_ARGS, /* a duration or a pattern out of range */
    OUT_TOO_SOON, /* a simple output changed state less than OUT_SIMPLE_MIN_MS ago */
    OUT_RATE,     /* a script's third start within a second (EXP-30) */
    OUT_BUSY,     /* settings change during a game: refused */
} out_result_t;

/* A channel's settings, kept on the box (EXP-28). */
typedef struct {
    bool enabled;
    char function[OUT_ID_MAX + 1]; /* siren, strobe, smoke, light, horn or out.<n> */
    uint32_t max_on_s;             /* 1 to OUT_MAX_ON_MAX_S */
} out_settings_t;

/* A channel's last step: a simple output's burst scheduler (simple_out.h). Called every turn of
 * the game task with what the channel is to show: on (2.0 ms pulses) or off, and live (a game
 * running, or the channel on: keep the pulses coming; otherwise the back-end ends its signal). */
typedef struct {
    bool on;
    bool pattern;
    uint32_t until_ms;      /* when it ends, on the box's clock */
    uint32_t on_ms, off_ms; /* a pattern's */
} out_want_t;

/* A module's channel instead takes the desired state whole when it changes (set: drive is NULL):
 * OUT_OK, or why the module side refuses it now (OUT_TOO_SOON: its min off; OUT_BAD_ARGS). */
typedef struct {
    void *ctx;
    void (*drive)(void *ctx, bool on, bool live, uint32_t now_ms);
    out_result_t (*set)(void *ctx, const out_want_t *want, uint32_t now_ms);
} out_backend_t;

typedef struct {
    int gpio; /* a simple output's GPIO (node.modules); -1 for a module's channel */
    /* A module's channel (expansion.h): its address and channel, relay or not, its max on. */
    bool module;
    uint8_t addr, mch;
    bool relay;
    uint32_t module_max_s;
    out_backend_t be;
    out_settings_t set;
    /* The I/O pod's: left out of its IDENT for want of room, so not lent (pod_port.h, decision
     * EXPI9-27): refused as disabled, and left out of node.modules. A box never sets it. */
    bool withheld;
    char id[OUT_ID_MAX + 1]; /* the capability id: the function, or "<function>.2" */
    /* the desired state */
    bool on;
    bool pattern;
    uint32_t start_ms, until_ms, on_ms, off_ms;
    out_source_t src;
    /* what the channel shows, and since when */
    bool level;
    bool changed; /* change_ms is valid */
    uint32_t change_ms;
    /* a script's last starts (EXP-30) */
    uint32_t starts[OUT_SCRIPT_STARTS];
    uint8_t start_count;
    uint8_t start_next;
    bool rate_told; /* the script.error about it went out (once a game) */
} out_channel_t;

typedef struct {
    void *ctx;
    /* An event for the controller: output.switched, script.error (data as compact JSON). In a
     * field game the shell sends it on the field link; otherwise the log is enough. May be NULL. */
    void (*event)(void *ctx, const char *type, const char *data_json);
    void (*log)(void *ctx, const char *line); /* may be NULL */
    /* Keeps a channel's settings (index from 0); false when they could not be stored. NULL: in
     * RAM only. */
    bool (*save)(void *ctx, int index, const out_settings_t *s);
} outputs_ops_t;

typedef struct {
    out_channel_t ch[OUT_CHANNELS_MAX];
    int count;  /* channels: the simple outputs first, then the modules' */
    int simple; /* simple outputs (the first `simple` channels) */
    outputs_ops_t ops;
    out_game_t game; /* as the shell last said */
    bool grace;      /* a game ended less than OUT_GRACE_MS ago */
    uint32_t grace_until;
    uint32_t now; /* the last outputs_tick's clock (script calls between two turns use it) */
} outputs_t;

void outputs_init(outputs_t *o, const outputs_ops_t *ops);

/* A channel's settings before its admin set any: disabled, "out.<index + 1>", the default max on.
 */
void outputs_default_settings(int index, out_settings_t *s);

/* True for a function an admin may give a channel: siren, strobe, smoke, light, horn, or
 * out.<1-9>. */
bool outputs_function_ok(const char *function);

/* True for a capability id (1-23 bytes of a-z 0-9 . _ -). */
bool outputs_id_ok(const char *id);

/* Adds a simple output on gpio with its back-end and its stored settings (NULL, or invalid
 * ones: the defaults). Returns its index, or -1 when the box has OUTPUTS_MAX already. Every
 * output starts off; the shell then calls outputs_tick, which ends the back-end's signal (the
 * boot's off: 1.0 ms pulses for 0.5 s, then the pin low). */
int outputs_add_simple(outputs_t *o, int gpio, const out_backend_t *be,
                       const out_settings_t *saved);

/* Adds output channel mch of the module at addr (expansion.h), after the simple outputs: its
 * function (the module's hint: siren, ..., else out.<mch + 1>), relay or not, the module's max on
 * in seconds, its back-end (set). Disabled until its admin enables it at the box (EXP-28), at
 * most the module's max on (or OUT_MAX_ON_DEFAULT_S, the lower); its id is its function, or
 * "<function>.2" when a channel before it has that function (a simple output first). Kept in RAM:
 * a box that restarts, or a module plugged in again, starts disabled (EXPI8-7). Returns its
 * index, or -1 when the box has OUT_MODULE_CHANNELS module channels already. */
int outputs_add_module(outputs_t *o, uint8_t addr, uint8_t mch, const char *function, bool relay,
                       uint32_t module_max_s, const out_backend_t *be);

/* The module at addr is gone: its channels leave (they count as off; nothing is told: the module's
 * own loss says why) and the others are named again. Returns how many left. */
int outputs_remove_module(outputs_t *o, uint8_t addr);

/* The admin changes a channel's settings (the admin PIN menu, the serial console): stored with
 * ops.save (a simple output's; a module's channel stays in RAM). A module channel's max on is at
 * most the module's (OUT_BAD_ARGS above it). OUT_BUSY while a game runs (or in the end's grace),
 * OUT_BAD_ARGS for a function or a max on out of range, OUT_NO_SUCH for an index the box does not
 * have. A disabled channel goes off at once. */
out_result_t outputs_configure(outputs_t *o, int index, const out_settings_t *s);

/*
 * Every turn of the game task (10 ms): the game's state (box_game_output_state) and the clock.
 * Applies the game-state rules, ends what has run its time, and drives every back-end.
 */
void outputs_tick(outputs_t *o, out_game_t game, uint32_t now_ms);

/* A game starts now (node_runner_start, before the mode's game.start handlers run, so they may
 * switch outputs): as outputs_tick turning to OUT_GAME_RUNNING. */
void outputs_game_start(outputs_t *o);

/* The game ends now: every output off, then the grace starts. Called before the mode's game.end
 * handlers run (node_runner.c), so what they switch on is the grace's; also from outputs_tick
 * when the state turns to OUT_GAME_ENDED. Does nothing unless a game was running or paused. */
void outputs_game_end(outputs_t *o, uint32_t now_ms);

/*
 * Switches the output with capability id `id` (index order: the first match; "*" with
 * OUT_ACT_OFF: every output). ms: how long (on: 0 = its max on; pulse and pattern: required);
 * on_ms and off_ms: a pattern's times. The rules of the file's header apply.
 */
out_result_t outputs_switch(outputs_t *o, const char *id, out_act_t act, uint32_t ms,
                            uint32_t on_ms, uint32_t off_ms, out_source_t src);

/* The admin's 1 s test of channel index (at the box, only while no game runs). */
out_result_t outputs_test(outputs_t *o, int index);

/*
 * CMD opcode 12 (RFC 0001 Amendment 26; protocol/expansion-port.md, section 8): its params as
 * compact JSON. NULL when a box takes them, else why not, in the words of the shared vectors
 * (protocol/vectors/cmd.json, "output_params"). Unknown keys are ignored.
 */
const char *outputs_cmd_problem(const char *params_json);

/* Runs CMD 12 (checked with outputs_cmd_problem first: OUT_BAD_ARGS when refused, and *why
 * says so; why may be NULL). */
out_result_t outputs_cmd(outputs_t *o, const char *params_json, const char **why);

/* The index of the channel with capability id `id`, or -1. */
int outputs_find(const outputs_t *o, const char *id);

/* How many channels are enabled (HELLO lists `output` when one is). */
int outputs_enabled_count(const outputs_t *o);

/* node.modules' text for the box's enabled simple outputs (not an I/O pod's withheld ones; a
 * module's channels are in its own entry: expansion_modules_text)
 * ("g46:servo:siren;g45:servo:horn", at most OUT_MODULES_MAX bytes); its length, 0 when there is
 * none. */
size_t outputs_modules_text(const outputs_t *o, char *out, size_t cap);

/* What channel index shows now (true: on). */
bool outputs_level(const outputs_t *o, int index);

const char *outputs_result_name(out_result_t r);
const char *outputs_source_name(out_source_t s);
const char *outputs_game_name(out_game_t g);

#endif /* ATALAIA_OUTPUTS_H */
