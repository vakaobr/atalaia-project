/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The radio task's transmit stage with listen before talk (RFC 0001 Amendment 14, decision
 * SL-25): one frame in hand, asked of the radio before every send. Plain C, no FreeRTOS and no
 * clock of its own, so the host tests, the host box and the ESP32 radio task all run this code;
 * the rule itself (the tries, the 20-200 ms wait) is the core's, atalaia/lbt.h.
 *
 * The task pops a frame from its queue into the stage (radio_txs_load) and calls radio_txs_step()
 * every turn of its loop. A step with the frame due asks the radio whether the channel is busy
 * (hal_radio_channel_busy: the receiver's own state first, one CAD if nothing is flagged). Busy:
 * the frame stays in the stage and is due again after the core's wait; the task is never blocked
 * for it, it keeps receiving. Free, or busy for the eighth time: the frame goes through the HAL's
 * send() exactly as before, and the duty-cycle rules apply there, after the wait: a CAD is not
 * time on air and spends no budget. With the stage disabled (Kconfig ATALAIA_LBT off) the frame
 * goes at the first step and no HAL call but send() is made.
 *
 * Counters (read by the radio_stats line through radio_task_lbt_stats):
 *   cads       CADs run (a busy flag from the receiver costs none),
 *   deferrals  frames that waited (one per busy answer),
 *   gave_up    frames sent after the eighth busy answer in a row.
 */
#ifndef ATALAIA_RADIO_LBT_H
#define ATALAIA_RADIO_LBT_H

#include <stdbool.h>
#include <stdint.h>

#include "atalaia/lbt.h"
#include "hal/hal_radio.h"
#include "radio_task.h"

typedef struct {
    const hal_radio_ops_t *radio;
    bool enabled;
    atalaia_lbt_t lbt;
    radio_lbt_stats_t stats;
    bool has; /* a frame is in hand */
    radio_tx_msg_t msg;
    uint32_t due_ms;
} radio_txs_t;

typedef enum {
    RADIO_TXS_IDLE,    /* no frame in hand */
    RADIO_TXS_WAITING, /* a frame is held: busy channel, or its wait has not passed */
    RADIO_TXS_DONE,    /* the frame is gone: *tag and *status say how it ended */
} radio_txs_state_t;

void radio_txs_init(radio_txs_t *t, const hal_radio_ops_t *radio, bool enabled,
                    atalaia_lbt_rand_fn rand, void *rand_ctx);

/* A frame is in hand (loaded and not yet sent or refused). */
bool radio_txs_busy(const radio_txs_t *t);

/* Takes a frame, due at once. False if one is already in hand. */
bool radio_txs_load(radio_txs_t *t, const radio_tx_msg_t *msg, uint32_t now_ms);

/*
 * One turn: does what the frame in hand is due for. tag is the frame's (0 = no result wanted) and
 * status its outcome, set when DONE (RADIO_TX_RESULT_OK, _DUTY_CYCLE, _ERROR).
 */
radio_txs_state_t radio_txs_step(radio_txs_t *t, uint32_t now_ms, uint32_t *tag,
                                 radio_tx_status_t *status);

/* Milliseconds until the held frame is due (0 when due now or when none is held). */
uint32_t radio_txs_wait_ms(const radio_txs_t *t, uint32_t now_ms);

#endif /* ATALAIA_RADIO_LBT_H */
