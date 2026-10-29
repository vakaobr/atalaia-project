/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * A Field Box in a field controller's game: the join (ADR-P2-12,
 * protocol/join.md), the radio link (radio/field_link.h) and the game the
 * controller drives with CMD and TIME. Platform-free: the ESP32 shell and
 * the host box (test/box_host) supply storage, screens and the clock.
 *
 * Life of a joined game:
 *   join (NFC card, serial "@join ...") -> tag checked with the field join
 *   key -> payload kept in encrypted NVS -> link up (new epoch, HELLO) ->
 *   "waiting" screen -> CMD start (or a TIME showing the game running) ->
 *   the mode runs with the join's role, teams, params, node id and seed ->
 *   events, STATE, ACKs over the radio -> CMD end -> the key is erased once
 *   the last events are acknowledged (or after a minute).
 *   After a reboot the stored payload brings the box back into the game:
 *   new epoch, HELLO, unacknowledged events resent, node.rebooted.
 *
 * Between games (box_lobby.c, protocol/field-frames.md): a box with no game,
 * or whose game is over, announces itself on its last channel in field frames
 * sealed with a key derived from the field join key, answers a controller's
 * DISCOVER, and takes an INVITE for its device id and current token: the
 * join payload it carries goes through exactly the checks of a card. After
 * BOX_READY_MS the final screen gives way to "Ready" for the next game.
 */
#ifndef ATALAIA_BOX_GAME_H
#define ATALAIA_BOX_GAME_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "atalaia/field_frame.h"
#include "atalaia/join.h"
#include "atalaia/tag.h"
#include "node_runner.h"
#include "preset_store.h"
#include "radio/field_link.h"
#include "radio/radio_region.h"

/* Where the join lives across reboots: encrypted NVS on the ESP32 (ADR-P2-12). */
typedef struct {
    int (*load_join)(void *ctx, uint8_t *buf, size_t cap);               /* length, 0 = none */
    int (*save_join)(void *ctx, const uint8_t *buf, size_t len);         /* 0 = ok */
    int (*erase_join)(void *ctx);                                        /* 0 = ok */
    int (*load_join_key)(void *ctx, uint8_t key[ATALAIA_JOIN_KEY_SIZE]); /* 0 = ok */
    int (*save_join_key)(void *ctx, const uint8_t key[ATALAIA_JOIN_KEY_SIZE]); /* 0 = ok */
    /* The box's device id (field frames, HELLO key 10); NULL: a new one every boot. */
    int (*load_device_id)(void *ctx, uint8_t id[ATALAIA_FF_DEVICE_SIZE]);       /* 0 = ok */
    int (*save_device_id)(void *ctx, const uint8_t id[ATALAIA_FF_DEVICE_SIZE]); /* 0 = ok */
    /* The field frames' boot count (their nonces, decision RJ-15): raised and stored before the
     * first frame of every run. NULL, or a failed save: the box sends no field frame. */
    int (*load_ff_boot)(void *ctx, uint32_t *boot); /* 0 = ok, -1 = none stored yet */
    int (*save_ff_boot)(void *ctx, uint32_t boot);  /* 0 = ok */
    /* Where a free box listens (RFC 0001 Amendment 19): the channel of its last game, or of the
     * last MOVE that moved it, and that MOVE's revision (a box takes only a higher one). Both
     * survive a reboot, so an idle box does not go back to the region's default channel. NULL:
     * not kept. load: 0 = ok, -1 = none stored yet. */
    int (*load_field_move)(void *ctx, uint32_t *channel_hz, uint32_t *rev);
    int (*save_field_move)(void *ctx, uint32_t channel_hz, uint32_t rev); /* 0 = ok */
    /* The box's screen language, the last game's (join key 15; box_text.h): "en", "pt". NULL: not
     * kept (English after a reboot until the next game). */
    int (*load_lang)(void *ctx, char *code, size_t cap); /* 0 = ok */
    int (*save_lang)(void *ctx, const char *code);       /* 0 = ok */
    void *ctx;
} box_store_ops_t;

typedef struct {
    void (*screen)(void *user, const char *template_name, const char *data_json);
    void (*log)(void *user, const char *line);
    void (*reboot)(void *user);                   /* CMD reboot; may be NULL */
    bool (*set_channel)(void *user, uint32_t hz); /* tune the radio; may be NULL */
    int (*battery_pct)(void *user);               /* -1 if unknown; may be NULL */
    /* Puts a packet on air; NULL = the radio task's queue (radio_task_send). */
    bool (*radio_send)(void *user, const uint8_t *pkt, size_t len);
    /* CMD update (protocol/firmware-update.md): the shell checks the offer and runs the update
     * over Wi-Fi (fw_update.h); never called while a game is played. May be NULL. */
    void (*update)(void *user, const char *params_json);
    /* Random bytes (the device id, tokens, timing spread; never a nonce): the ESP32 shell seeds
     * them with entropy collected at boot (decision RJ-15). NULL: no field frames. */
    void (*random)(void *user, uint8_t *buf, size_t len);
    /* A join whose mode the box lacks asks it to fetch the signed packages (join key 16,
     * mode_fetch.h): the shell fetches them for join (on its own task on the ESP32) and then
     * calls box_game_fetch_done on the game's task. NULL: the box answers "no mode" as before. */
    void (*fetch_modes)(void *user, const atalaia_join_t *join);
    /* The field test's radio report (radio/radio_stats.h, decision SL-18): the duty-cycle budget
     * left (ms), and one JSON line for the serial log under the tag RADIO_STATS_TAG. Read-only,
     * both may be NULL (no line is made without radio_stats). */
    uint32_t (*duty_remaining_ms)(void *user);
    void (*radio_stats)(void *user, const char *json_line);
    /* Listen before talk's counters (the radio task's; Amendment 14): CADs run, frames that
     * waited, frames sent after 8 busy answers. May be NULL (the line then carries zeros). */
    void (*lbt_stats)(void *user, uint32_t *cads, uint32_t *deferrals, uint32_t *gave_up);
    void *user;
} box_shell_ops_t;

typedef enum {
    BOX_IDLE = 0, /* no game joined: the stand-alone preset picker */
    BOX_JOINED,   /* joined, waiting for the controller to start */
    BOX_PLAYING,  /* running or paused */
    BOX_ENDED,    /* ended; the key goes once the last events are acknowledged */
    BOX_FETCHING, /* took a join, getting the mode packages it lacks; not on the game's link yet */
} box_phase_t;

typedef enum {
    BOX_JOIN_OK = 0,
    BOX_JOIN_NO_KEY,     /* this box has no field join key yet */
    BOX_JOIN_NOT_A_JOIN, /* not a join text or card */
    BOX_JOIN_REFUSED,    /* bad tag, unknown version or bad content (see the log) */
    BOX_JOIN_CONTROLLER, /* a standby controller's payload */
    BOX_JOIN_NO_MODE,    /* the mode is not installed on this box */
    BOX_JOIN_BUSY,       /* a game is being played */
    BOX_JOIN_STORAGE,    /* the payload could not be stored */
    BOX_JOIN_RADIO,      /* the radio may not transmit (epoch NVS failure) */
    BOX_JOIN_ENDED,      /* a game this box played to its end, or an old game's key (BN-19) */
    BOX_JOIN_REGION,     /* another radio region's game (join key 18): not this firmware's band */
} box_join_result_t;

#define BOX_END_LINGER_MS 60000
/* "Ready" (for the next game) replaces the final screen this long after the end. */
#define BOX_READY_MS 30000

/* Field frames between games (box_lobby.c; the same timings as atalaia_sim/lobby.py). */
#define BOX_ANNOUNCE_FIRST_MIN_MS  2000  /* the first announcement after a game ends: */
#define BOX_ANNOUNCE_FIRST_MAX_MS  20000 /* spread, so a field's boxes do not all talk at once */
#define BOX_ANNOUNCE_MIN_MS        60000 /* never more often than once a minute */
#define BOX_ANNOUNCE_SHARE_PCT     2     /* of the sub-band's hourly duty-cycle budget */
#define BOX_DISCOVER_ANSWER_MAX_MS 3000
#define BOX_INVITE_ANSWER_MIN_MS   100
#define BOX_INVITE_ANSWER_MAX_MS   600
#define BOX_MOVE_ANNOUNCE_MIN_MS                                                                   \
    6000 /* a box that took a MOVE announces itself on the new channel */
#define BOX_MOVE_ANNOUNCE_MAX_MS 15000 /* once the controller's MOVEs are over (Amendment 19) */
#define BOX_TOKEN_ROTATE_MS      600000
#define BOX_ANSWER_REPEAT_MS     10000
#define BOX_ANSWER_IDS           8 /* invites answered lately: one answer each in 10 s */
#define BOX_ANSWERS_PER_MIN      6 /* and at most this many answers a minute in all */
#define BOX_ENDED_GAMES          4

typedef struct {
    bool ready; /* device id and key: field frames can be sent and read */
    uint8_t key[ATALAIA_FF_KEY_SIZE];
    uint8_t nonce_key[32]; /* the nonces' pseudonym key (atalaia_ff_nonce_key) */
    bool boot_ok;          /* this run's boot count is stored and in use */
    uint32_t boot;
    uint32_t ctr; /* frames sent under boot; at 65536 the boot count rises again */
    uint8_t device_id[ATALAIA_FF_DEVICE_SIZE];
    uint8_t token[ATALAIA_FF_TOKEN_SIZE];
    uint8_t prev_token[ATALAIA_FF_TOKEN_SIZE];
    bool have_prev;
    uint32_t rotate_ms;
    bool announce_due;
    uint32_t announce_ms;
    bool announced; /* last_announce_ms is valid */
    uint32_t last_announce_ms;
    bool answer_due;
    uint32_t answer_ms;
    uint16_t answer_invite;
    uint8_t answer_result;
    uint16_t answered_ids[BOX_ANSWER_IDS]; /* 0 = free */
    uint32_t answered_at[BOX_ANSWER_IDS];
    uint32_t answer_times[BOX_ANSWERS_PER_MIN]; /* the last answers sent, a ring */
    uint8_t answer_next;
    bool boot_error_logged; /* the boot count could not be read (not "none yet") */
    atalaia_ff_reasm_t reasm;
    uint16_t last_game; /* the last game played, its role: in announcements */
    char last_role[ATALAIA_JOIN_ROLE_MAX + 1];
    uint16_t ended[BOX_ENDED_GAMES]; /* games played to their end: never joined again */
    uint32_t channel_hz;             /* where it listens: its last game's channel */
    bool ready_screen_due;
    uint32_t ready_screen_ms;
    bool invited; /* the current game came from an invite */
    uint32_t invites_accepted, invites_refused, frames_ignored;
    /* GAME_OVER frames (decision OT-13): one that ended this box's game; ones for its game id
     * under another key (an old game's, recorded and played back), refused. */
    uint32_t games_over_heard, games_over_refused;
    /* MOVE frames (Amendment 19): the revision of the last one taken, how many moved this box
     * or were refused (old revision, a channel of another region, or a box in a game). */
    uint32_t move_rev, moves_taken, moves_refused;
    uint32_t saved_channel_hz; /* what the store holds, so it is written only when it changes */
    bool move_loaded;          /* the stored channel and revision were read (once) */
    bool move_tuned;           /* a free box went to the stored channel (once, at its first tick) */
    /* The timings (box_game_init sets the BOX_ANNOUNCE_* values; the host box shortens them). */
    uint32_t first_min_ms, first_max_ms, interval_min_ms;
    uint32_t interval_fixed_ms; /* the host box's tests: this interval, not the computed one */
} box_lobby_t;
/* battery.low (decision FU1-6): the gauge is read this often in a joined game; below
 * battery_low_pct the box sends one battery.low, and again only after the level has come
 * back BOX_BATTERY_HYSTERESIS points above it. */
#define BOX_BATTERY_CHECK_MS   10000
#define BOX_BATTERY_HYSTERESIS 5
#define BOX_BATTERY_LOW_PCT                                                                        \
    20 /* the default; the ESP32 shell uses CONFIG_ATALAIA_BATTERY_LOW_PCT */

typedef struct {
    node_runner_t *runner;
    preset_t *preset; /* buffer for the mode source (16 KB: static in the shell) */
    field_link_t link;
    box_store_ops_t store;
    box_shell_ops_t shell;
    const atalaia_crypto_ops_t *crypto;
    const atalaia_radio_nvs_ops_t *nvs;
    event_log_t *log;
    atalaia_hello_t hello;

    uint8_t join_key[ATALAIA_JOIN_KEY_SIZE];
    bool have_join_key;
    /* The radio region the firmware is built for (RADIO_REGION after init; host tests may set
     * another): a join of another region is refused before anything changes (RF-AS923-2). */
    atalaia_region_t region;
    box_phase_t phase;
    atalaia_join_t join;
    const char *teams[ATALAIA_JOIN_TEAMS_MAX];
    int preset_index;
    bool paused;
    uint8_t owner_team;
    uint32_t now_ms;
    uint32_t ended_ms;
    uint32_t state_interval_ms; /* 0 = FIELD_LINK_STATE_MS */
    char last_message[128];
    uint8_t battery_low_pct;  /* battery.low below this level; 0 = never */
    bool battery_low;         /* battery.low sent for this crossing (until the level is back up) */
    uint32_t battery_next_ms; /* next gauge reading */
    bool stats_on;            /* the radio report's clock runs (a game is on this box) */
    uint32_t stats_last_ms;   /* when the last report line was made */
    box_lobby_t lobby;        /* between games: field frames (box_lobby.c) */
    bool has_picker;          /* the shell has the game picker: "ready" says a key brings it */
    /* Fetching mode packages (BOX_FETCHING, mode_fetch.h): the join payload taken, joined once
     * the packages are in; fetch_cancel stops the fetch (the game is over). */
    uint8_t fetch_payload[ATALAIA_JOIN_MAX];
    size_t fetch_len;
    volatile bool fetch_cancel;
    /* The box took part in its game only to say over LoRa that the fetch failed (P5E-8): its
     * link reports "waiting", and it leaves once the event is acknowledged (not an ended game). */
    bool fetch_failed_link;
} box_game_t;

void box_game_init(box_game_t *g, node_runner_t *runner, preset_t *preset_buf,
                   const box_store_ops_t *store, const box_shell_ops_t *shell,
                   const atalaia_crypto_ops_t *crypto, const atalaia_radio_nvs_ops_t *nvs,
                   event_log_t *log, const atalaia_hello_t *hello);

/* The field join key: from the store, or set by the field owner (and stored). */
bool box_game_load_join_key(box_game_t *g);
bool box_game_set_join_key(box_game_t *g, const uint8_t key[ATALAIA_JOIN_KEY_SIZE]);
/* "@joinkey <64 hex digits>" on the console (stored). */
bool box_game_set_join_key_hex(box_game_t *g, const char *hex);
/* A key for this boot only, not stored (CONFIG_ATALAIA_DEV_JOIN_KEY). */
bool box_game_use_join_key_hex(box_game_t *g, const char *hex);

/* A join payload (NFC card, decoded text). */
box_join_result_t box_game_join(box_game_t *g, const uint8_t *payload, size_t len);
/* The text form: "atalaia:join:..." */
box_join_result_t box_game_join_text(box_game_t *g, const char *text);
/* The user memory of an NFC Type 2 tag (from page 4). */
box_join_result_t box_game_join_tag(box_game_t *g, const uint8_t *mem, size_t len);
const char *box_join_result_name(box_join_result_t r);

/*
 * At boot: if a join is stored, rejoin (new epoch, HELLO) and, if the game
 * was being played, resume it from the saved state and send node.rebooted.
 * Returns true if the box is in a joined game.
 */
bool box_game_resume(box_game_t *g, uint32_t now_ms);

/* A packet heard on the radio. */
void box_game_on_packet(box_game_t *g, const uint8_t *pkt, size_t len, int8_t rssi);

/* Advance by raw_delta_ms of local time (now_ms: monotonic clock). */
void box_game_tick(box_game_t *g, uint32_t raw_delta_ms, uint32_t now_ms);

/* True while the box belongs to a field controller's game (buttons go to the node). */
bool box_game_active(const box_game_t *g);

/* True while a joined game is being played (running or paused): no firmware update then. */
bool box_game_playing(const box_game_t *g);

/*
 * A firmware update that failed and could not be reported over HTTPS (no Wi-Fi, the controller
 * unreachable, refused before any network: protocol/firmware-update.md): tells the controller
 * over LoRa with node.update_failed, so its record does not wait for the timeout. Only in a
 * joined game (the link's key); false otherwise. Call it on the game task.
 */
bool box_game_update_failed(box_game_t *g, const char *release, const char *reason, const char *fw);

/*
 * The shell's fetch of the joined game's mode packages (shell.fetch_modes) is over, on the game
 * task: result is an mf_result_t (mode_fetch.h), part the part it is about, reported whether the
 * controller took the HTTPS report. Installed: the box joins the game (HELLO) as from the join
 * itself. Otherwise it says why on its screen and, when the controller has not heard it over
 * HTTPS, tells it over LoRa (node.modes_failed) in that game's link, which it then leaves.
 */
void box_game_fetch_done(box_game_t *g, int result, const char *part, bool reported);

/* True while the box is fetching mode packages for a join (BOX_FETCHING). */
bool box_game_fetching(const box_game_t *g);

/* ---- Between games (box_lobby.c) ----------------------------------------------- */

/* Sets up field frames once the join key is known (also after "@joinkey"): the device id
 * (stored, or made now), the derived key, a token. False without a random source or key. */
bool box_lobby_init(box_game_t *g);

/* True if this box played game_id to its end (it keeps its last BOX_ENDED_GAMES). */
bool box_lobby_played_to_the_end(const box_game_t *g, uint16_t game_id);

/* True when the box may take an invite: no game joined, or its game over, and no game
 * picked on the box being played. */
bool box_lobby_available(const box_game_t *g);

/* A packet heard on the radio: true if it was a field frame (handled or ignored here). */
bool box_lobby_on_packet(box_game_t *g, const uint8_t *pkt, size_t len);

/* Time passes: answers, announcements, the token, the ready screen. */
void box_lobby_tick(box_game_t *g, uint32_t now_ms);

/* The game ended (box_game.c): remember it, announce soon, the ready screen later. */
void box_lobby_game_over(box_game_t *g, uint32_t now_ms);

/* A join the box took to fetch its modes failed (mode_fetch.h): it is free again, as after a
 * game (a new token, an announcement soon, "ready" later), but the game is not an ended one, so
 * the GM may invite it again. */
void box_lobby_free_again(box_game_t *g);

/* The box joined a game (a card, a QR code, the serial console, an invite): its tokens go,
 * so no invite recorded before can work afterwards (box_game.c). */
void box_lobby_joined(box_game_t *g);

/* Stores the idle channel (and the revision of the MOVE that set it) when it changed: after a
 * game's join and after a MOVE, so a rebooted free box listens where its field is. */
void box_lobby_remember_channel(box_game_t *g);

/* The shell drew something else (the preset picker): no ready screen over it. */
void box_lobby_cancel_ready_screen(box_game_t *g);

/* Shows "ready" now (a free adopted box at boot, decision BN-10): "Ready / next game", and with
 * has_picker, that a key brings the game picker. */
void box_lobby_show_ready(box_game_t *g);

/* The device id as 16 hex digits (NUL-terminated), "" before box_lobby_init. */
void box_lobby_device_hex(const box_game_t *g, char out[17]);

/* Internal to box_game.c and box_lobby.c: take a join payload from an invite. */
box_join_result_t box_game_join_invited(box_game_t *g, const uint8_t *payload, size_t len);

/* Internal to box_game.c and box_lobby.c: the field said this box's game is over (a GAME_OVER
 * field frame for its game id and key tag, decision OT-13): it ends exactly as on CMD end. */
void box_game_end_by_field(box_game_t *g);

/*
 * An NFC tag read while a game runs (joined or stand-alone): the node gets
 * nfc.tag with the tag checked against the joined game's id and key
 * (atalaia_tag_event_json; a stand-alone game has no key: reason no_game).
 * payload is the tag's Atalaia record (atalaia_tag_from_ndef_tag), or NULL
 * when it has none. Returns true if the node took the event.
 */
bool box_game_tag(box_game_t *g, const uint8_t *uid, size_t uid_len, const uint8_t *payload,
                  size_t len);
/* "@tag <uid hex> [<tag payload hex>]" on the console: the same, without a reader. */
bool box_game_tag_text(box_game_t *g, const char *text);

#endif /* ATALAIA_BOX_GAME_H */
